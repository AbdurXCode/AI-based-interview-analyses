"""State machine: user answer → follow-up, next topic, or closing report."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ai_interview_analysis.db.models import (
    InterviewPhase,
    MockInterviewSession,
    MockTurn,
    ResumeProfile,
    utcnow,
)
from ai_interview_analysis.services.interview_input_guard import (
    refusal_assistant_message,
    screen_user_answer,
)
from ai_interview_analysis.services.resume_pipeline import analyze_domain_alignment
from ai_interview_analysis.services.mock_interview import (
    _fallback_question,
    assistant_follow_same_topic,
    assistant_next_question,
    classify_continue_intent,
    closing_message,
    enrich_report_with_post_interview_dimensions,
    ensure_evaluation_semantic_defaults,
    ensure_valid_main_question,
    evaluate_answer,
    finalize_report,
    first_assistant_message,
    format_recent_transcript_excerpt,
    load_jd_bundle,
    load_jd_optional,
    outline_from_resume,
)
from ai_interview_analysis.services.mock_section_scores import public_section_scores

logger = logging.getLogger(__name__)


def _json_sanitize(obj: Any) -> Any:
    """Ensure nested structures are JSON-serializable for SQLAlchemy JSON columns and FastAPI responses."""
    if obj is None:
        return None
    if isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        if obj != obj:  # NaN
            return None
        return float(obj)
    if isinstance(obj, dict):
        return {str(k): _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_sanitize(x) for x in obj]
    return str(obj)


def stamp_session_activity(sess: MockInterviewSession) -> None:
    """Record last interaction time on the JSON session_state (no DB migration)."""
    st = dict(sess.session_state or {})
    st["last_activity_at"] = utcnow().isoformat()
    sess.session_state = st
    flag_modified(sess, "session_state")


def _with_section_scores(db: Session, sess: MockInterviewSession, payload: dict[str, Any]) -> dict[str, Any]:
    db.refresh(sess)
    out = dict(payload)
    out["section_scores"] = public_section_scores(sess)
    return out


def _return_submit(db: Session, sess: MockInterviewSession, t0: float, payload: dict[str, Any]) -> dict[str, Any]:
    logger.info("submit_answer_ms=%.1f session_id=%s", (time.perf_counter() - t0) * 1000.0, sess.id)
    return _with_section_scores(db, sess, payload)


def _policy_coaching(reason: str | None) -> tuple[list[str], list[str]]:
    """Brief coach bullets for screened-out inputs (paired with interviewer refusal)."""
    r = (reason or "policy").lower()
    if r == "profanity":
        return (
            ["Language isn’t usable in a graded mock interview.", "Interviewers expect professional tone even under stress."],
            ["Rephrase politely; then tie your experience directly to the question asked."],
        )
    if r == "policy_injection":
        return (
            ["Request looks like bypassing interviewer rules or tooling — staying on-profile is safer."],
            ["Answer strictly as a candidate: relevance, STAR-style specifics, measurable outcomes."],
        )
    if r == "inappropriate":
        return (
            ["Message crossed professional-boundary norms for recruiting practice."],
            ["Reset to competency-based content: responsibilities, teamwork, conflicts resolved professionally."],
        )
    if r == "off_topic":
        return (
            ["This wasn’t grounded in answering the interviewer’s prompt or your fit for this role."],
            ["Redirect: restate how your experience maps to what they asked."],
        )
    return (
        ["Couldn’t use this reply for structured interview grading."],
        ["Answer the interviewer’s prompt from your résumé and role context.", "Use specifics: context, actions, measurable result."],
    )


def _safe_avg_from_eval(ev: dict[str, Any]) -> float:
    try:
        return float(ev.get("average") or 0)
    except (TypeError, ValueError):
        return 0.0


def _turns(db: Session, session_id: uuid.UUID) -> list[MockTurn]:
    return list(
        db.execute(
            select(MockTurn).where(MockTurn.session_id == session_id).order_by(MockTurn.turn_index),
        ).scalars()
    )


def _next_idx(turns: list[MockTurn]) -> int:
    if not turns:
        return 0
    return max(t.turn_index for t in turns) + 1


def _last_assistant_text(turns: list[MockTurn]) -> str:
    for t in reversed(turns):
        if t.role == "assistant":
            return t.content
    return ""


def _generate_final_report_payload(
    profile_data: dict[str, Any],
    jd_raw: str | None,
    *,
    turns: list[MockTurn],
    topics_es: list[Any],
) -> dict[str, Any]:
    """Build performance report dict from transcript turns (pure; no DB writes)."""
    user_turn_records = [t for t in turns if t.role == "user"]
    tr = [{"role": t.role, "content": t.content} for t in turns]

    if not user_turn_records:
        rep: dict[str, Any] = {
            "overall_percent": 0,
            "strengths": [],
            "weaknesses": ["No graded answers were recorded before the session ended."],
            "coach_note": (
                "Start a mock interview again and reply to the first interviewer question "
                "to receive scored feedback."
            ),
            "missed_opportunities": [],
        }
    else:
        try:
            rep = finalize_report(profile_data, jd_raw, tr)
            if not isinstance(rep, dict):
                rep = {}
        except Exception:
            logger.exception("finalize_report failed; using heuristic fallback scores")
            eval_scores = [
                float(t.evaluation.get("average", 0))
                for t in turns
                if t.role == "user"
                and t.evaluation
                and isinstance(t.evaluation, dict)
            ]
            avg_pct = (sum(eval_scores) / len(eval_scores) * 10) if eval_scores else 50.0
            rep = {
                "overall_percent": int(max(0, min(100, avg_pct))),
                "strengths": [],
                "weaknesses": [],
                "coach_note": "Keep practising to improve your scores.",
            }
        try:
            rep = enrich_report_with_post_interview_dimensions(
                rep, profile_data, jd_raw, tr, topics_es
            )
        except Exception:
            logger.exception("enrich_report_with_post_interview_dimensions skipped")

    if not isinstance(rep, dict):
        rep = {"overall_percent": 0, "strengths": [], "weaknesses": []}
    return _json_sanitize(rep)


def _mark_session_report_complete(
    sess: MockInterviewSession,
    rep: dict[str, Any],
) -> None:
    sess.final_report = rep
    sess.phase = InterviewPhase.ended.value
    sess.ended_at = utcnow()
    st = dict(sess.session_state or {})
    st.pop("report_generation", None)
    st["report_generation"] = "complete"
    sess.session_state = st
    flag_modified(sess, "session_state")


def finalize_pending_session_report(
    db: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """
    After natural interview close: generate and persist final_report, then mark ended.
    Idempotent if already completed.
    """
    sess = db.get(MockInterviewSession, session_id)
    if not sess or sess.user_id != user_id:
        return None

    if (
        sess.phase == InterviewPhase.ended.value
        and sess.ended_at
        and isinstance(sess.final_report, dict)
        and sess.final_report
    ):
        db.refresh(sess)
        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "phase": sess.phase,
                "final_report": sess.final_report,
                "assistant_message": _last_assistant_text(_turns(db, sess.id)),
            },
        )

    if sess.phase != InterviewPhase.closing.value:
        return None

    prof = db.get(ResumeProfile, sess.resume_profile_id) if sess.resume_profile_id else None
    profile_data = dict(prof.profile_data or {}) if prof else {}
    jd_raw = load_jd_optional(db, sess.jd_id, user_id)
    topics_es = (sess.outline or {}).get("topics") if sess.outline else []
    if not topics_es:
        topics_es = [{"id": "t0", "title": "General"}]

    turns = _turns(db, sess.id)
    rep = _generate_final_report_payload(
        profile_data,
        jd_raw,
        turns=turns,
        topics_es=topics_es,
    )
    _mark_session_report_complete(sess, rep)
    try:
        db.commit()
    except Exception:
        logger.exception("finalize_pending_session_report commit failed session_id=%s", session_id)
        db.rollback()
        raise

    return _with_section_scores(
        db,
        sess,
        {
            "done": True,
            "phase": InterviewPhase.ended.value,
            "final_report": rep,
            "assistant_message": _last_assistant_text(turns),
        },
    )


def _update_canonical_question(sess: MockInterviewSession, assistant_text: str) -> None:
    """Store last substantive interview question (not policy refusals)."""
    st = dict(sess.session_state or {})
    st["canonical_question"] = (assistant_text or "").strip()
    sess.session_state = st
    flag_modified(sess, "session_state")


def _canonical_or_last_q(sess: MockInterviewSession, turns: list[MockTurn]) -> str:
    st = sess.session_state if isinstance(sess.session_state, dict) else {}
    cq = (st.get("canonical_question") or "").strip()
    if cq:
        return cq
    return _last_assistant_text(turns)


def _count_substantive_user_answers(turns: list[MockTurn]) -> int:
    """User turns that are not policy-screen blocks (those don't advance interview substance)."""
    c = 0
    for t in turns:
        if t.role != "user":
            continue
        evl = t.evaluation if isinstance(t.evaluation, dict) else {}
        if evl.get("policy_block"):
            continue
        c += 1
    return c


def _domain_gap_probe_message(domain_alignment: dict[str, Any], substantive_user_count: int) -> str:
    """Extra main question when domain mismatch would otherwise close too early."""
    skills_raw = domain_alignment.get("absent_skills_for_jd")
    skills = [str(x).strip() for x in skills_raw if str(x).strip()] if isinstance(skills_raw, list) else []
    jd_track = str(domain_alignment.get("jd_career_track") or "this role").strip()
    if skills:
        sk = skills[(max(0, substantive_user_count - 1)) % len(skills)]
        return (
            f"Before we wrap this section—{jd_track} requires credible depth on **{sk}**. "
            "Walk through one concrete example end-to-end: what you owned, the setup, "
            "how you measured success, and what you would improve next time?"
        )
    return (
        f"Mapping to {jd_track}: what is the most technically deep work you have done that aligns with this role's "
        "core craft, and what gap are you still closing?"
    )


def _prepend_domain_mismatch_warning(opening: str, domain_alignment: dict[str, Any]) -> str:
    """Ensure the first assistant turn names a ladder mismatch (but still asks only one question)."""
    if not isinstance(domain_alignment, dict) or not bool(domain_alignment.get("domain_mismatch")):
        return (opening or "").strip()

    msg = (opening or "").strip()
    if not msg:
        return msg

    # If the model already referenced mismatch, don't double-prefix.
    lower = msg.lower()
    if "domain" in lower and ("mismatch" in lower or "different" in lower):
        return msg

    r = str(domain_alignment.get("resume_career_track") or "").strip()
    j = str(domain_alignment.get("jd_career_track") or "").strip()
    if r and j:
        prefix = (
            f"Quick note: your recent experience reads closest to {r}, while this job is centered on {j} "
            "— so I'll focus questions on closing those JD gaps."
        )
    else:
        prefix = (
            "Quick note: your résumé and this job appear to target different career tracks — "
            "so I'll focus questions on closing the JD gaps."
        )

    # Keep SYSTEM_OPEN_Q's constraint of exactly one question mark in the whole bubble.
    prefix = prefix.replace("?", "")
    return f"{prefix}\n\n{msg}".strip()


def _mismatch_confirm_message(domain_alignment: dict[str, Any]) -> str:
    """Standalone gating message shown BEFORE the first interview question."""
    da = domain_alignment if isinstance(domain_alignment, dict) else {}
    r = str(da.get("resume_career_track") or "").strip()
    j = str(da.get("jd_career_track") or "").strip()
    if r and j:
        return (
            f"Quick note: your recent experience reads closest to {r}, while this job is centered on {j}.\n\n"
            "You can still practise this interview, but I will focus questions on the JD gaps.\n\n"
            "Would you like to continue? (yes/no)"
        )
    return (
        "Quick note: your résumé and this job appear to target different career tracks.\n\n"
        "You can still practise this interview, but I will focus questions on the JD gaps.\n\n"
        "Would you like to continue? (yes/no)"
    )


def _interpret_yes_no(text: str) -> str | None:
    """Return 'yes' / 'no' / None for ambiguous."""
    # Semantic classifier only (LLM). If unclear/unavailable, treat as ambiguous and ask again.
    decision = classify_continue_intent(text)
    if decision in ("yes", "no"):
        return decision
    return None


def start_session(
    db: Session,
    *,
    user_id: uuid.UUID,
    resume_profile_id: uuid.UUID,
    jd_id: uuid.UUID | None,
    role: str,
    level: str,
    interview_type: str,
    max_followups: int,
) -> tuple[MockInterviewSession, dict[str, Any]]:
    prof = db.get(ResumeProfile, resume_profile_id)
    if not prof or prof.user_id != user_id:
        raise ValueError("invalid_resume_profile")
    t0 = time.perf_counter()
    effective_jd_id = jd_id or prof.jd_id
    jd_raw, jd_struct = load_jd_bundle(db, effective_jd_id, user_id)
    profile_data = dict(prof.profile_data or {})
    outline = outline_from_resume(profile_data, jd_raw, interview_type, level)
    topics = outline.get("topics") or [{"id": "t0", "title": role or "General", "anchor": "experience"}]

    da = analyze_domain_alignment(profile_data, jd_raw or "", jd_struct)
    min_before_close = 8 if da.get("domain_mismatch") else 0

    first_q = first_assistant_message(
        outline=outline,
        profile=profile_data,
        interview_type=interview_type,
        level=level,
        domain_alignment=da,
    )
    # If mismatch: gate with an explicit yes/no confirmation BEFORE asking questions.
    awaiting_confirm = bool(da.get("domain_mismatch"))
    msg = _mismatch_confirm_message(da) if awaiting_confirm else first_q

    sess = MockInterviewSession(
        user_id=user_id,
        jd_id=effective_jd_id,
        resume_profile_id=resume_profile_id,
        role=role or "General",
        level=level,
        interview_type=interview_type,
        phase=InterviewPhase.main.value,
        outline={"topics": topics},
        topic_index=0,
        followups_in_topic=0,
        max_followups_per_topic=max_followups,
        session_state={
            "outline": outline,
            # Canonical interview question (used for eval routing / refusals). On mismatch-gate,
            # keep this as the real first question, not the confirmation prompt.
            "canonical_question": first_q,
            # Used for filtering "accidental / no-answer" sessions out of history UI.
            "has_user_answers": False,
            "domain_alignment": da,
            "min_user_answers_before_close": min_before_close,
            "awaiting_mismatch_confirm": awaiting_confirm,
            "pending_first_question": first_q if awaiting_confirm else None,
        },
    )
    stamp_session_activity(sess)
    db.add(sess)
    db.flush()

    db.add(
        MockTurn(
            session_id=sess.id,
            turn_index=0,
            role="assistant",
            content=msg,
            modality=None,
        ),
    )
    db.commit()
    db.refresh(sess)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info("start_session_ms=%.1f session_id=%s", elapsed_ms, sess.id)
    bundle = _with_section_scores(db, sess, {"session_id": str(sess.id), "assistant_message": msg})
    return sess, bundle


def submit_answer(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    answer_text: str,
    modality: str | None,
) -> dict[str, Any]:
    t_submit = time.perf_counter()
    sess = db.get(MockInterviewSession, session_id)
    if not sess or sess.user_id != user_id:
        raise LookupError("session_not_found")
    if sess.ended_at:
        raise RuntimeError("session_already_ended")
    if sess.phase != InterviewPhase.main.value:
        raise RuntimeError("session_not_accepting_answers")

    st = dict(sess.session_state or {})
    # Special gate: if mismatch confirmation is pending, interpret answer as yes/no first.
    if bool(st.get("awaiting_mismatch_confirm")):
        decision = _interpret_yes_no(answer_text or "")
        turns = _turns(db, sess.id)
        next_idx = _next_idx(turns)

        # Record the user message for transcript completeness.
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=next_idx,
                role="user",
                content=answer_text,
                modality=(modality or "text"),
                evaluation=None,
            ),
        )
        db.flush()

        if decision == "no":
            # End immediately without running interview scoring.
            bye = "No problem — I won’t start the interview. Update your JD/resume pairing and start again when ready."
            db.add(
                MockTurn(
                    session_id=sess.id,
                    turn_index=next_idx + 1,
                    role="assistant",
                    content=bye,
                    modality=None,
                ),
            )
            st2 = dict(st)
            st2["ended_without_answers"] = True
            st2["awaiting_mismatch_confirm"] = False
            st2["pending_first_question"] = None
            sess.session_state = st2
            flag_modified(sess, "session_state")
            sess.phase = InterviewPhase.ended.value
            sess.ended_at = utcnow()
            db.commit()
            return _return_submit(
                db,
                sess,
                t_submit,
                {
                    "done": True,
                    "phase": InterviewPhase.ended.value,
                    "final_report": None,
                    "assistant_message": bye,
                    "evaluation": None,
                },
            )

        if decision == "yes":
            q = str(st.get("pending_first_question") or "").strip()
            if not q:
                # Fallback: use canonical_question if pending missing.
                q = str(st.get("canonical_question") or "").strip()
            if not q:
                q = "Great — to start, walk me through your most relevant experience for this job and what you would prioritize learning first?"
            db.add(
                MockTurn(
                    session_id=sess.id,
                    turn_index=next_idx + 1,
                    role="assistant",
                    content=q,
                    modality=None,
                ),
            )
            st3 = dict(st)
            st3["awaiting_mismatch_confirm"] = False
            st3["pending_first_question"] = None
            # Do not mark has_user_answers True yet: this was a confirmation, not a graded answer.
            sess.session_state = st3
            flag_modified(sess, "session_state")
            stamp_session_activity(sess)
            db.commit()
            return _return_submit(
                db,
                sess,
                t_submit,
                {
                    "done": False,
                    "evaluation": None,
                    "assistant_message": q,
                    "phase": sess.phase,
                },
            )

        # Ambiguous: ask again, do not advance topics.
        retry = "Reply 'yes' to continue with the mock interview, or 'no' to stop here."
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=next_idx + 1,
                role="assistant",
                content=retry,
                modality=None,
            ),
        )
        stamp_session_activity(sess)
        db.commit()
        return _return_submit(
            db,
            sess,
            t_submit,
            {
                "done": False,
                "evaluation": None,
                "assistant_message": retry,
                "phase": sess.phase,
            },
        )

    st["has_user_answers"] = True
    sess.session_state = st
    flag_modified(sess, "session_state")
    stamp_session_activity(sess)

    prof = db.get(ResumeProfile, sess.resume_profile_id) if sess.resume_profile_id else None
    profile_data = dict(prof.profile_data or {}) if prof else {}
    jd_raw = load_jd_optional(db, sess.jd_id, user_id)
    da_sess = st.get("domain_alignment") if isinstance(st.get("domain_alignment"), dict) else None

    turns = _turns(db, sess.id)
    next_idx = _next_idx(turns)
    last_q = _last_assistant_text(turns)
    transcript_before_answer = format_recent_transcript_excerpt(turns)

    topics = (sess.outline or {}).get("topics") if sess.outline else []
    if not topics:
        topics = [{"id": "t0", "title": "General"}]
    ti = sess.topic_index
    if ti >= len(topics) and topics:
        ti = max(0, len(topics) - 1)
        sess.topic_index = ti

    topic_now = topics[ti] if 0 <= ti < len(topics) else {}

    allowed, policy_reason = screen_user_answer(answer_text or "")
    if not allowed:
        fbp, sug = _policy_coaching(policy_reason)
        ev = {
            "scores": {"structure": 2, "clarity": 2, "technical": 2},
            "average": 2.0,
            "weak": True,
            "weakness_reason": "Out of scope for mock interview",
            "missed_concepts": [],
            "policy_block": policy_reason,
            "coach_feedback": fbp,
            "coach_suggestions": sug[:4],
            "addresses_question": False,
            "exclude_from_live_scores": True,
        }
        ensure_evaluation_semantic_defaults(ev)
        ev.setdefault("coach_strengths", [])
    else:
        tp_phase = topic_now.get("phase") if isinstance(topic_now, dict) else None
        jd_clip = (jd_raw or "").strip()
        ev = evaluate_answer(
            last_q,
            answer_text or "",
            sess.interview_type,
            topic_phase=str(tp_phase) if tp_phase else None,
            recent_transcript=transcript_before_answer or None,
            jd_snippet=jd_clip[:6000] if jd_clip else None,
            domain_alignment=da_sess,
        )

    ev["answered_topic_index"] = ti

    db.add(
        MockTurn(
            session_id=sess.id,
            turn_index=next_idx,
            role="user",
            content=answer_text,
            modality=(modality or "text"),
            evaluation=ev,
        ),
    )
    db.flush()
    transcript_after_answer = format_recent_transcript_excerpt(_turns(db, sess.id))

    # Policy block: one assistant refusal, do not advance topic or call more LLMs
    if not allowed:
        canon = _canonical_or_last_q(sess, turns)
        amsg = refusal_assistant_message(policy_reason or "policy", canon)
        ai_idx = next_idx + 1
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=ai_idx,
                role="assistant",
                content=amsg,
                modality=None,
            ),
        )
        db.commit()
        return _return_submit(
            db,
            sess,
            t_submit,
            {
                "done": False,
                "evaluation": ev,
                "assistant_message": amsg,
                "phase": sess.phase,
                "policy_blocked": True,
            },
        )

    # Follow-up branch (ask only when the evaluation says "weak"/off-target)
    weak = bool(ev.get("weak"))
    skip_weak_follow = (
        bool(ev.get("advance_to_next_topic_recommended"))
        or bool(ev.get("candidate_requests_skip"))
        or bool(ev.get("candidate_explicitly_disengaging"))
    )
    max_fups = (
        int(topic_now.get("max_followups"))
        if isinstance(topic_now, dict) and isinstance(topic_now.get("max_followups"), int)
        else int(sess.max_followups_per_topic)
    )
    if weak and not skip_weak_follow and sess.followups_in_topic < max_fups:
        sess.followups_in_topic += 1
        try:
            amsg, fe = assistant_follow_same_topic(
                last_q,
                answer_text,
                topic_now,
                profile_data,
                sess.followups_in_topic - 1,
                recent_transcript=transcript_after_answer or None,
                evaluation_context=ev,
            )
        except Exception:
            ttl = topic_now.get("title") if isinstance(topic_now, dict) else "this topic"
            amsg = (
                f"What is one concrete metric or outcome from your work on {ttl} that best shows impact—how did you measure it?"
            )
            fe = {}

        if isinstance(fe, dict) and fe.get("kind") == "followup_limit_reached":
            sess.followups_in_topic = 0
            if ti + 1 < len(topics):
                sess.topic_index = ti + 1
                new_idx = sess.topic_index
                tp = topics[new_idx]
                try:
                    amsg, _aux = assistant_next_question(
                        jd_raw=jd_raw,
                        profile=profile_data,
                        outline_topics=topics,
                        topic_idx=new_idx,
                        previous_q=last_q or "",
                        previous_answer=answer_text or "",
                        previous_eval=ev,
                        interview_type=sess.interview_type,
                        level=sess.level,
                        recent_transcript=transcript_after_answer or None,
                    )
                    if not amsg.strip():
                        raise ValueError("empty message")
                    amsg = ensure_valid_main_question(amsg, tp, profile_data)
                except Exception:
                    td = tp if isinstance(tp, dict) else {}
                    amsg = ensure_valid_main_question(
                        _fallback_question(td, profile_data),
                        td,
                        profile_data,
                    )

                _update_canonical_question(sess, amsg)
                ai_idx = next_idx + 1
                db.add(
                    MockTurn(
                        session_id=sess.id,
                        turn_index=ai_idx,
                        role="assistant",
                        content=amsg,
                        modality=None,
                    ),
                )
                db.commit()
                return _return_submit(
                    db,
                    sess,
                    t_submit,
                    {
                        "done": False,
                        "evaluation": ev,
                        "assistant_message": amsg,
                        "phase": sess.phase,
                    },
                )
            # Follow-up cap hit on last topic: fall through to closing (no hollow transition turn)
        else:
            _update_canonical_question(sess, amsg)
            ai_idx = next_idx + 1
            db.add(
                MockTurn(
                    session_id=sess.id,
                    turn_index=ai_idx,
                    role="assistant",
                    content=amsg,
                    modality=None,
                ),
            )
            db.commit()
            return _return_submit(
                db,
                sess,
                t_submit,
                {
                    "done": False,
                    "evaluation": ev,
                    "assistant_message": amsg,
                    "phase": sess.phase,
                },
            )

    # Advance topic — reset follow-ups unless we exhausted all topics below
    sess.followups_in_topic = 0

    if ti + 1 < len(topics):
        sess.topic_index = ti + 1
        new_idx = sess.topic_index
        tp = topics[new_idx]

        try:
            amsg, _aux = assistant_next_question(
                jd_raw=jd_raw,
                profile=profile_data,
                outline_topics=topics,
                topic_idx=new_idx,
                previous_q=last_q or "",
                previous_answer=answer_text or "",
                previous_eval=ev,
                interview_type=sess.interview_type,
                level=sess.level,
                recent_transcript=transcript_after_answer or None,
            )
            if not amsg.strip():
                raise ValueError("empty message")
            amsg = ensure_valid_main_question(amsg, tp, profile_data)
        except Exception:
            topic_dict = tp if isinstance(tp, dict) else {}
            amsg = ensure_valid_main_question(
                _fallback_question(topic_dict, profile_data),
                topic_dict,
                profile_data,
            )

        _update_canonical_question(sess, amsg)
        ai_idx = next_idx + 1
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=ai_idx,
                role="assistant",
                content=amsg,
                modality=None,
            ),
        )
        db.commit()
        return _return_submit(
            db,
            sess,
            t_submit,
            {
                "done": False,
                "evaluation": ev,
                "assistant_message": amsg,
                "phase": sess.phase,
            },
        )

    # Domain mismatch: require minimum substantive user answers before closing.
    fresh_turns = _turns(db, sess.id)
    st_close = dict(sess.session_state or {})
    min_need = int(st_close.get("min_user_answers_before_close") or 0)
    da_close = st_close.get("domain_alignment") if isinstance(st_close.get("domain_alignment"), dict) else {}
    user_ans_n = _count_substantive_user_answers(fresh_turns)

    if min_need > 0 and bool(da_close.get("domain_mismatch")) and user_ans_n < min_need:
        amsg = _domain_gap_probe_message(da_close, user_ans_n)
        _update_canonical_question(sess, amsg)
        ai_idx = next_idx + 1
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=ai_idx,
                role="assistant",
                content=amsg,
                modality=None,
            ),
        )
        db.commit()
        return _return_submit(
            db,
            sess,
            t_submit,
            {
                "done": False,
                "evaluation": ev,
                "assistant_message": amsg,
                "phase": sess.phase,
            },
        )

    # Closing message first; report generation runs in a follow-up call so this request stays fast/reliable.
    sess.phase = InterviewPhase.closing.value
    try:
        bye = closing_message(profile_data)
    except Exception:
        bye = "Thanks for your time today—review the feedback report and iterate on your resume bullets."

    ai_idx = next_idx + 1
    db.add(
        MockTurn(
            session_id=sess.id,
            turn_index=ai_idx,
            role="assistant",
            content=bye,
            modality=None,
        ),
    )
    st_rep = dict(sess.session_state or {})
    st_rep["report_generation"] = "pending"
    sess.session_state = st_rep
    flag_modified(sess, "session_state")
    stamp_session_activity(sess)

    sess.final_report = None
    sess.ended_at = None

    db.commit()
    return _return_submit(
        db,
        sess,
        t_submit,
        {
            "done": True,
            "report_pending": True,
            "evaluation": ev,
            "assistant_message": bye,
            "final_report": None,
            "phase": InterviewPhase.closing.value,
        },
    )


def get_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> MockInterviewSession | None:
    s = db.get(MockInterviewSession, session_id)
    if not s or s.user_id != user_id:
        return None
    return s


def get_active_session(db: Session, user_id: uuid.UUID) -> MockInterviewSession | None:
    """Return most recent active (non-ended, non-cancelled) session for user."""
    rows = list(
        db.execute(
            select(MockInterviewSession)
            .where(MockInterviewSession.user_id == user_id)
            .order_by(MockInterviewSession.created_at.desc())
            .limit(10)
        ).scalars()
    )
    for s in rows:
        if s.ended_at:
            continue
        st = s.session_state if isinstance(s.session_state, dict) else {}
        if st.get("cancelled") is True:
            continue
        return s
    return None


def heartbeat_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Update last_activity_at without adding turns (no LLM)."""
    sess = db.get(MockInterviewSession, session_id)
    if not sess or sess.user_id != user_id:
        return False
    if sess.ended_at:
        return True
    stamp_session_activity(sess)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


def end_session(
    db: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Force-end a session and generate the final report immediately.

    Safe to call even if the session is already ended — in that case it
    just returns the existing report.
    """
    sess = db.get(MockInterviewSession, session_id)
    if not sess or sess.user_id != user_id:
        return None

    # Already ended — return what we have
    if sess.ended_at:
        turns = _turns(db, sess.id)
        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "phase": sess.phase,
                "final_report": sess.final_report,
                "assistant_message": _last_assistant_text(turns),
            },
        )

    prof = db.get(ResumeProfile, sess.resume_profile_id) if sess.resume_profile_id else None
    profile_data = dict(prof.profile_data or {}) if prof else {}
    jd_raw = load_jd_optional(db, sess.jd_id, user_id)

    topics_es = (sess.outline or {}).get("topics") if sess.outline else []
    if not topics_es:
        topics_es = [{"id": "t0", "title": "General"}]

    skip_goodbye = sess.phase == InterviewPhase.closing.value
    bye = ""

    try:
        turns = _turns(db, sess.id)
        user_turn_records = [t for t in turns if t.role == "user"]

        if not skip_goodbye:
            if user_turn_records:
                try:
                    bye = closing_message(profile_data)
                except Exception:
                    bye = "Thank you for completing your mock interview! Your performance report is now ready."
            else:
                bye = (
                    "We're closing this mock interview. "
                    "You didn't submit any answers yet, but you can restart anytime from setup."
                )
            next_idx = _next_idx(turns)
            db.add(
                MockTurn(
                    session_id=sess.id,
                    turn_index=next_idx,
                    role="assistant",
                    content=bye,
                    modality=None,
                ),
            )
            db.flush()
            turns = _turns(db, sess.id)
            user_turn_records = [t for t in turns if t.role == "user"]

        rep = _generate_final_report_payload(
            profile_data,
            jd_raw,
            turns=turns,
            topics_es=topics_es,
        )

        if not user_turn_records:
            st_nf = dict(sess.session_state or {})
            st_nf["has_user_answers"] = False
            st_nf["ended_without_answers"] = True
            sess.session_state = st_nf
            flag_modified(sess, "session_state")

        _mark_session_report_complete(sess, rep)

        db.commit()

        assistant_out = _last_assistant_text(turns) if skip_goodbye else bye

        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "phase": InterviewPhase.ended.value,
                "final_report": rep,
                "assistant_message": assistant_out,
            },
        )
    except Exception:
        logger.exception("end_session failed session_id=%s", sess.id)
        db.rollback()
        raise


def request_end_session(
    db: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Request an interview to end, without generating the report in this request.

    This moves the session into the `closing` phase and marks report generation as pending.
    The client should follow-up with the `/report` endpoint (or poll) to finalize.

    Safe to call multiple times.
    """
    sess = db.get(MockInterviewSession, session_id)
    if not sess or sess.user_id != user_id:
        return None

    turns = _turns(db, sess.id)

    # Already ended — return what we have
    if sess.ended_at:
        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "phase": sess.phase,
                "final_report": sess.final_report,
                "assistant_message": _last_assistant_text(turns),
            },
        )

    # Already closing — keep it fast and idempotent
    if sess.phase == InterviewPhase.closing.value:
        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "report_pending": True,
                "phase": sess.phase,
                "final_report": sess.final_report,
                "assistant_message": _last_assistant_text(turns),
            },
        )

    prof = db.get(ResumeProfile, sess.resume_profile_id) if sess.resume_profile_id else None
    profile_data = dict(prof.profile_data or {}) if prof else {}

    user_turn_records = [t for t in turns if t.role == "user"]
    if user_turn_records:
        try:
            bye = closing_message(profile_data)
        except Exception:
            bye = "Thanks for your time today — we are generating your performance report now."
    else:
        bye = (
            "We're closing this mock interview. "
            "You didn't submit any answers yet, but you can restart anytime from setup."
        )

    next_idx = _next_idx(turns)
    try:
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=next_idx,
                role="assistant",
                content=bye,
                modality=None,
            ),
        )
        sess.phase = InterviewPhase.closing.value
        st = dict(sess.session_state or {})
        st["report_generation"] = "pending"
        sess.session_state = st
        flag_modified(sess, "session_state")
        stamp_session_activity(sess)

        # Report is not generated here; keep these empty until `/report` finalizes.
        sess.final_report = None
        sess.ended_at = None

        db.commit()
        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "report_pending": True,
                "phase": sess.phase,
                "final_report": None,
                "assistant_message": bye,
            },
        )
    except Exception:
        logger.exception("request_end_session failed session_id=%s", sess.id)
        db.rollback()
        raise


def cancel_session(
    db: Session,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Fast stop: end a session without generating any report (no LLM calls).

    Intended for "retry immediately" UX.
    """
    sess = db.get(MockInterviewSession, session_id)
    if not sess or sess.user_id != user_id:
        return None

    # Idempotent: if already ended, just return current state
    if sess.ended_at:
        turns = _turns(db, sess.id)
        return _with_section_scores(
            db,
            sess,
            {
                "done": True,
                "phase": sess.phase,
                "final_report": sess.final_report,
                "assistant_message": _last_assistant_text(turns),
                "cancelled": True,
            },
        )

    turns = _turns(db, sess.id)
    next_idx = _next_idx(turns)

    try:
        db.add(
            MockTurn(
                session_id=sess.id,
                turn_index=next_idx,
                role="assistant",
                content="Okay — cancelling this attempt. You can restart a new mock interview anytime from setup.",
                modality=None,
            )
        )
        sess.phase = InterviewPhase.ended.value
        sess.ended_at = utcnow()
        st = dict(sess.session_state or {})
        st["cancelled"] = True
        st["cancelled_at"] = sess.ended_at.isoformat()
        sess.session_state = st
        flag_modified(sess, "session_state")
        stamp_session_activity(sess)
        db.commit()
    except Exception:
        logger.exception("cancel_session failed session_id=%s", sess.id)
        db.rollback()
        raise

    return _with_section_scores(
        db,
        sess,
        {
            "done": True,
            "phase": InterviewPhase.ended.value,
            "final_report": sess.final_report,
            "assistant_message": "Okay — cancelling this attempt. You can restart a new mock interview anytime from setup.",
            "cancelled": True,
        },
    )

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
from ai_interview_analysis.services.mock_interview import (
    _fallback_question,
    assistant_follow_same_topic,
    assistant_next_question,
    closing_message,
    enrich_report_with_post_interview_dimensions,
    ensure_evaluation_semantic_defaults,
    ensure_valid_main_question,
    evaluate_answer,
    finalize_report,
    first_assistant_message,
    format_recent_transcript_excerpt,
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
    jd_raw = load_jd_optional(db, jd_id, user_id)
    profile_data = dict(prof.profile_data or {})
    outline = outline_from_resume(profile_data, jd_raw, interview_type, level)
    topics = outline.get("topics") or [{"id": "t0", "title": role or "General", "anchor": "experience"}]

    msg = first_assistant_message(
        outline={"topics": topics},
        profile=profile_data,
        interview_type=interview_type,
        level=level,
    )

    sess = MockInterviewSession(
        user_id=user_id,
        jd_id=jd_id,
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
            "canonical_question": msg,
            # Used for filtering "accidental / no-answer" sessions out of history UI.
            "has_user_answers": False,
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
    st["has_user_answers"] = True
    sess.session_state = st
    flag_modified(sess, "session_state")
    stamp_session_activity(sess)

    prof = db.get(ResumeProfile, sess.resume_profile_id) if sess.resume_profile_id else None
    profile_data = dict(prof.profile_data or {}) if prof else {}
    jd_raw = load_jd_optional(db, sess.jd_id, user_id)

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

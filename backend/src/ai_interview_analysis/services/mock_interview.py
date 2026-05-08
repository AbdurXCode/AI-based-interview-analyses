"""Turn-based adaptive mock interviewer (Gemini)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ai_interview_analysis.db.models import (
    InterviewPhase,
    JobDescription,
    MockInterviewSession,
    MockTurn,
    ResumeProfile,
)
from ai_interview_analysis.prompts.loader import load_mock_interview_system_prompts
from ai_interview_analysis.services import gemini_client

_PROMPTS = load_mock_interview_system_prompts()
SYSTEM_OUTLINE = _PROMPTS["SYSTEM_OUTLINE"]
SYSTEM_OPEN_Q = _PROMPTS["SYSTEM_OPEN_Q"]
SYSTEM_EVALUATE = _PROMPTS["SYSTEM_EVALUATE"]
SYSTEM_FOLLOW = _PROMPTS["SYSTEM_FOLLOW"]
SYSTEM_NEXT_TOPIC = _PROMPTS["SYSTEM_NEXT_TOPIC"]
SYSTEM_CLOSE = _PROMPTS["SYSTEM_CLOSE"]
SYSTEM_REPORT = _PROMPTS["SYSTEM_REPORT"]
SYSTEM_POST_LIVE_METRICS = _PROMPTS["SYSTEM_POST_LIVE_METRICS"]
SYSTEM_CONFIRM_CONTINUE = _PROMPTS["SYSTEM_CONFIRM_CONTINUE"]

# ════════════════════════════════════════════════════════
# GUARDRAIL CONSTANTS
# ════════════════════════════════════════════════════════

MAX_FOLLOWUPS_PER_TOPIC = 2
MIN_ANSWER_WORDS = 10
# Phase quotas for the interview roadmap (main questions == topic count per phase).
# Keep SYSTEM_OUTLINE (prompts/mock_interview/outline.txt) and the UI roadmap in sync.
PHASE_MAIN_QUOTAS: dict[str, int] = {
    "warmup": 1,
    "jd_core": 3,
    "project": 3,
    "problem_solving": 6,
    "behavioral": 1,
}
# Follow-up caps by phase (only used to clamp per-topic max_followups)
PHASE_FOLLOWUP_CAPS: dict[str, int] = {
    # One warmup MAIN only (opening); no scripted follow-ups on warmup.
    "warmup": 0,
    "jd_core": 1,
    "project": 1,
    "problem_solving": 2,
    "behavioral": 1,
}

# Exact capacity for one full pass through PHASE_MAIN_QUOTAS (no extra “+1” slot)
MAX_TOPICS = sum(PHASE_MAIN_QUOTAS.values())
MIN_TOPICS = 4
MAX_TURNS_PER_SESSION = 30

_STOP_TOPIC_TOKENS = frozenset({
    "your", "that", "this", "with", "from", "into", "their", "were", "been",
    "have", "most", "some", "based", "using", "related", "model", "models",
    "data", "system", "project", "experience", "skills", "technical",
})


def _topic_sig_words(topic: dict[str, Any]) -> set[str]:
    blob = f"{topic.get('title', '')} {topic.get('anchor', '')}".lower()
    return {
        w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", blob)
        if w not in _STOP_TOPIC_TOKENS
    }


def _project_topics_overlap_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    sa, sb = _topic_sig_words(a), _topic_sig_words(b)
    if not sa or not sb:
        return False
    inter = len(sa & sb)
    denom = min(len(sa), len(sb))
    return inter >= 2 and (inter / max(denom, 1)) >= 0.4


def classify_continue_intent(user_text: str) -> str | None:
    """Semantic YES/NO/UNCLEAR for mismatch confirmation gate."""
    s = (user_text or "").strip()
    if not s:
        return None
    try:
        blob = gemini_client.generate_json(
            SYSTEM_CONFIRM_CONTINUE,
            s[:2000],
            temperature=0.0,
            max_output_tokens=64,
        )
        if not isinstance(blob, dict):
            return None
        d = str(blob.get("decision") or "").strip().lower()
        if d in ("yes", "no"):
            return d
        if d == "unclear":
            return None
        return None
    except Exception:
        return None


def _pick_project_topics_diverse(pool: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    """Prefer distinct resume projects/systems over similar duplicate rows."""
    take: list[dict[str, Any]] = []
    for t in pool:
        if len(take) >= quota:
            break
        if any(_project_topics_overlap_similar(t, x) for x in take):
            continue
        take.append(t)
    if len(take) < quota:
        for t in pool:
            if len(take) >= quota:
                break
            if t not in take:
                take.append(t)
    return take[:quota]


def format_recent_transcript_excerpt(
    turns: list[Any],
    *,
    max_turns: int = 16,
    max_content_chars: int = 2800,
) -> str:
    """Plain-text recap for interviewer LLM prompts (semantic memory, no pattern matching)."""
    if not turns:
        return ""
    chunk = turns[-max_turns:] if len(turns) > max_turns else turns
    lines: list[str] = []
    for t in chunk:
        role_raw: str | None
        txt_raw: Any
        if isinstance(t, dict):
            role_raw = str(t.get("role") or "")
            txt_raw = t.get("content")
        else:
            role_raw = getattr(t, "role", None)
            txt_raw = getattr(t, "content", None)
        txt = str(txt_raw or "").strip()
        if not txt:
            continue
        if len(txt) > max_content_chars:
            txt = txt[: max_content_chars - 1].rstrip() + "…"
        label = "Interviewer" if role_raw == "assistant" else "Candidate"
        lines.append(f"{label}: {txt}")
    return "\n".join(lines)


_SEMANTIC_EVAL_BOOL_KEYS: tuple[str, ...] = (
    "honest_capability_boundary",
    "meta_answer_not_substantive",
    "candidate_requests_skip",
    "candidate_explicitly_disengaging",
    "explicit_knowledge_gap",
    "numeric_claim_without_measurement_story",
    "star_scaffold_without_technical_substance",
    "advance_to_next_topic_recommended",
    "off_topic_answer",
)


def ensure_evaluation_semantic_defaults(ev: dict[str, Any]) -> None:
    for k in _SEMANTIC_EVAL_BOOL_KEYS:
        ev.setdefault(k, False)
    ev.setdefault("follow_up_priority_hint", "")
    ev.setdefault("coach_strengths", [])


def _merge_evaluator_semantic_flags(
    out: dict[str, Any],
    blob: dict[str, Any],
    topic_phase: str | None,
) -> None:
    """Attach structured signals from SYSTEM_EVALUATE for routing + follow-up hints (LLM-classified)."""
    for k in _SEMANTIC_EVAL_BOOL_KEYS:
        v = blob.get(k)
        out[k] = bool(v) if isinstance(v, bool) else False

    hint = blob.get("follow_up_priority_hint")
    if isinstance(hint, str) and hint.strip():
        out["follow_up_priority_hint"] = hint.strip()[:900]

    ph = str(topic_phase or "").strip().lower()
    if out.get("off_topic_answer") or out.get("meta_answer_not_substantive"):
        out["addresses_question"] = False
        out["weak"] = True

    tech_phases = frozenset({"jd_core", "project", "problem_solving"})
    if ph in tech_phases and out.get("numeric_claim_without_measurement_story"):
        out["weak"] = True
        mc = list(out.get("missed_concepts") or []) if isinstance(out.get("missed_concepts"), list) else []
        needle = "Numeric impact claim needs measurement grounding"
        if needle not in " ".join(str(x) for x in mc):
            mc.append(f"{needle} (baseline / definition / environment).")
            out["missed_concepts"] = mc[:12]

    if ph in tech_phases and out.get("star_scaffold_without_technical_substance"):
        out["weak"] = True

    if out.get("honest_capability_boundary"):
        wf = blob.get("weak")
        if isinstance(wf, bool) and wf is False:
            out["weak"] = False

    if out.get("candidate_requests_skip"):
        out["addresses_question"] = False
        out["weak"] = True


def _evaluator_follow_context(ev: dict[str, Any], topic_phase: str) -> dict[str, Any]:
    hint = ""
    eh = ev.get("follow_up_priority_hint")
    if isinstance(eh, str) and eh.strip():
        hint = eh.strip()
    return {
        "evaluator_follow_hint": hint,
        "honest_capability_boundary": bool(ev.get("honest_capability_boundary")),
        "explicit_knowledge_gap": bool(ev.get("explicit_knowledge_gap")),
        "candidate_requests_skip": bool(ev.get("candidate_requests_skip")),
        "candidate_explicitly_disengaging": bool(ev.get("candidate_explicitly_disengaging")),
    }


# ════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ════════════════════════════════════════════════════════

def outline_from_resume(
    profile: dict[str, Any],
    jd_raw: str | None,
    interview_type: str,
    level: str,
) -> dict[str, Any]:
    """
    Generate structured interview outline anchored to resume + JD.
    Enforces JD alignment and phase structure guardrails.
    """
    jd = (jd_raw or "").strip()[:24000]
    ctx = {
        "profile_summary": profile,
        "jd_snippet": jd,
        "level": level,
        "type": interview_type,
    }
    payload = json.dumps(ctx)[:40000]

    outline = gemini_client.generate_json(
        SYSTEM_OUTLINE,
        payload,
        temperature=0.4,
    )

    # ── Guardrail: validate topic count ──
    topics = outline.get("topics") or []
    if len(topics) < MIN_TOPICS:
        outline["topics"] = _inject_fallback_topics(topics, jd, profile)
    if len(topics) > MAX_TOPICS:
        outline["topics"] = topics[:MAX_TOPICS]

    # ── Guardrail: ensure at least one JD core topic ──
    phases = [t.get("phase") for t in outline.get("topics", [])]
    if "jd_core" not in phases:
        outline["topics"].insert(
            1,
            {
                "id": "topic_jd_fallback",
                "title": "Core JD Skills",
                "anchor": "JD must-have skills",
                "phase": "jd_core",
                "jd_skill": (outline.get("jd_must_have_skills") or ["ML"])[0],
                "max_followups": 1,
            },
        )

    # ── Guardrail: enforce per-phase quotas + follow-up caps ──
    def _phase_of(t: dict[str, Any]) -> str:
        p = t.get("phase")
        return p if isinstance(p, str) and p.strip() else "jd_core"

    # Normalize phases and max_followups first
    norm: list[dict[str, Any]] = []
    for t in outline.get("topics", []):
        if not isinstance(t, dict):
            continue
        rp = t.get("phase")
        if isinstance(rp, str) and rp.strip().lower() == "behavioural":
            t["phase"] = "behavioral"
        p = _phase_of(t)
        t["phase"] = p
        mf = t.get("max_followups")
        if not isinstance(mf, int):
            mf = MAX_FOLLOWUPS_PER_TOPIC
        cap = PHASE_FOLLOWUP_CAPS.get(p, MAX_FOLLOWUPS_PER_TOPIC)
        t["max_followups"] = max(0, min(int(mf), int(cap)))
        norm.append(t)

    order = ["warmup", "jd_core", "project", "problem_solving", "behavioral"]
    chosen: list[dict[str, Any]] = []
    project_chosen: list[dict[str, Any]] = []
    for p in order:
        quota = PHASE_MAIN_QUOTAS.get(p, 0)
        picked = [t for t in norm if _phase_of(t) == p]
        if p == "project":
            take = _pick_project_topics_diverse(picked, quota)
            chosen.extend(take)
            project_chosen.extend(take)
        else:
            chosen.extend(picked[:quota])

    # If we still don't have the warmup topic, inject a fallback at front
    if not any(_phase_of(t) == "warmup" for t in chosen):
        chosen.insert(
            0,
            {
                "id": "fallback_warmup",
                "title": "Background & Motivation",
                "anchor": "overall experience and career path",
                "phase": "warmup",
                "jd_skill": None,
                "max_followups": PHASE_FOLLOWUP_CAPS["warmup"],
            },
        )

    # Ensure one behavioral main question (roadmap label matches STAR-style prompts)
    if not any(_phase_of(t) == "behavioral" for t in chosen):
        chosen.append(
            {
                "id": "fallback_behavioral",
                "title": "Collaboration & Communication",
                "anchor": "working with stakeholders, conflict, or remote collaboration",
                "phase": "behavioral",
                "jd_skill": None,
                "max_followups": PHASE_FOLLOWUP_CAPS["behavioral"],
            },
        )

    # Fill remaining capacity (if any) with other topics (but keep total capped)
    remaining = [t for t in norm if t not in chosen]
    if len(chosen) < MAX_TOPICS:
        for t in remaining:
            if len(chosen) >= MAX_TOPICS:
                break
            if (
                _phase_of(t) == "project"
                and any(_project_topics_overlap_similar(t, x) for x in project_chosen)
            ):
                continue
            chosen.append(t)
            if _phase_of(t) == "project":
                project_chosen.append(t)

    outline["topics"] = chosen[:MAX_TOPICS]

    return outline


def first_assistant_message(
    outline: dict[str, Any],
    profile: dict[str, Any],
    interview_type: str,
    level: str,
    domain_alignment: dict[str, Any] | None = None,
) -> str:
    """Generate warm opening + first warmup question."""
    blob = gemini_client.generate_json(
        SYSTEM_OPEN_Q,
        json.dumps({
            "outline": outline,
            "resume": profile,
            "jd_must_have_skills": outline.get("jd_must_have_skills"),
            "type": interview_type,
            "level": level,
            "domain_alignment": domain_alignment or {},
        })[:40000],
        temperature=0.45,
    )
    msg = blob.get("message") or blob.get("assistant_message") or ""

    # ── Guardrail: prevent empty opening ──
    if not str(msg).strip():
        name = _get_candidate_name(profile)
        greet = f"Hi{', ' + name if name else ' there'}"
        msg = (
            f"{greet} — in about two minutes, walk me through your ML engineering background with emphasis on "
            "taking models from development toward production—and call out whichever JD-aligned tools or stack "
            "you used most?"
        )
    return str(msg).strip()


def _normalize_coach_bullets(v: Any, max_n: int = 4) -> list[str]:
    if isinstance(v, str) and v.strip():
        return [v.strip()[:420]]
    if isinstance(v, list):
        out = [str(x).strip()[:420] for x in v if str(x).strip()]
        return out[:max_n]
    return []


def _merge_evaluation_coaching(
    out: dict[str, Any],
    blob: dict[str, Any],
) -> None:
    """Attach coaching from evaluator JSON (semantic). Fallbacks respect skip/disengage vs thin-substance."""
    b = blob if isinstance(blob, dict) else {}
    skip = bool(out.get("candidate_requests_skip"))
    disengage = bool(out.get("candidate_explicitly_disengaging"))

    focus = b.get("coach_focus_label")
    if isinstance(focus, str) and focus.strip():
        out["weakness_reason"] = focus.strip()[:220]
    elif isinstance(b.get("weakness_reason"), str) and str(b.get("weakness_reason")).strip():
        out["weakness_reason"] = str(b.get("weakness_reason")).strip()[:220]
    elif skip or disengage:
        out["weakness_reason"] = "Intentional skip — no competency answer"
    elif not str(out.get("weakness_reason") or "").strip():
        if not bool(out.get("addresses_question", True)):
            out["weakness_reason"] = "Did not engage with the interview question"
        else:
            out["weakness_reason"] = "Needs clearer depth, mechanics, or evidence"

    out["coach_strengths"] = _normalize_coach_bullets(b.get("coach_strengths"), max_n=3)

    fb = _normalize_coach_bullets(b.get("coach_feedback"), max_n=5)
    sug = _normalize_coach_bullets(b.get("coach_suggestions"), max_n=5)

    if not fb:
        if skip or disengage:
            fb = [
                "You chose not to answer this competency prompt — that reads as a visible gap on the topic being tested.",
                "A real interviewer may note the skip when calibrating depth for senior ML/production questions.",
            ]
        elif not bool(out.get("addresses_question", True)):
            fb = ["The reply did not engage with what the interviewer asked."]
        else:
            wr = str(out.get("weakness_reason") or "").strip()
            if wr:
                fb = [wr[:420]]

    mc = out.get("missed_concepts")
    if not sug:
        if isinstance(mc, list) and mc and not skip:
            sug = [
                f"Develop this angle next: {str(c).strip()}"[:420]
                for c in mc[:3]
                if str(c).strip()
            ]
    if not sug:
        if skip or disengage:
            sug = [
                "Re-read the interviewer question and list the 4–6 bullet topics a complete answer would cover.",
                "Draft one short spoken outline: trade-off → metric → failure mode → how you'd validate.",
            ]
        else:
            sug = [
                "For each technique you cite, add one concrete lever: data path, model call site, eval set, or rollback.",
                "Tie claims to how you would measure success against a baseline in a production-like setting.",
            ]

    out["coach_feedback"] = fb or (
        ["Add specifics so your answer maps clearly to the question."]
        if not skip
        else ["Skipping leaves the competency untested — use post-session prep to close the gap."]
    )
    out["coach_suggestions"] = sug[:4]


def _eval_addresses_question(blob: dict[str, Any]) -> bool:
    """True if the model says the user engaged with the question (default True if absent)."""
    v = blob.get("addresses_question")
    if v is None:
        v = blob.get("addresses_interview_question")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("false", "no", "0"):
            return False
        if s in ("true", "yes", "1"):
            return True
    return True


def routing_evaluation_stub(
    question: str,
    answer: str,
    interview_type: str,
) -> dict[str, Any]:
    """Routing-only heuristic during chat: no Gemini. Full scoring runs after interview ends."""
    _ = (question, interview_type)
    answer_words = len((answer or "").strip().split())
    if answer_words < MIN_ANSWER_WORDS:
        out: dict[str, Any] = {
            "scores": {"structure": 1, "clarity": 1, "technical": 1},
            "average": 1.0,
            "weak": True,
            "weakness_reason": "Answer too short — candidate needs to elaborate",
            "missed_concepts": [],
            "addresses_question": True,
            "coach_feedback": [
                "Scoring appears when you End & Get Report.",
                "Try a longer, more specific reply on similar questions later.",
            ],
            "coach_suggestions": [
                "Use multiple sentences grounded in what was asked.",
                "Include one measurable outcome where possible.",
            ],
        }
        ensure_evaluation_semantic_defaults(out)
        out.setdefault("coach_strengths", [])
        _merge_evaluation_coaching(out, {})
        return out

    heuristic_weak = answer_words < 42
    out2 = {
        "scores": {"structure": 7, "clarity": 7, "technical": 7},
        "average": 7.0,
        "weak": heuristic_weak,
        "weakness_reason": "",
        "missed_concepts": [],
        "addresses_question": True,
        "coach_feedback": [],
        "coach_suggestions": [],
    }
    ensure_evaluation_semantic_defaults(out2)
    out2.setdefault("coach_strengths", [])
    _merge_evaluation_coaching(out2, {})
    return out2


def evaluate_answer(
    question: str,
    answer: str,
    interview_type: str,
    topic_phase: str | None = None,
    recent_transcript: str | None = None,
    jd_snippet: str | None = None,
    domain_alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Evaluate candidate answer quality.
    Returns scores, weak flag, and coaching fields (semantic via SYSTEM_EVALUATE).
    Very short answers still go through the model so skips and intent are not mislabeled as "too short".
    """
    ans = (answer or "").strip()
    if not ans:
        empty_ev: dict[str, Any] = {
            "scores": {"structure": 1, "clarity": 1, "technical": 1},
            "average": 1.0,
            "weak": True,
            "weakness_reason": "No answer provided",
            "missed_concepts": [],
            "addresses_question": False,
            "coach_feedback": ["Submit a substantive reply when you are ready to continue."],
            "coach_suggestions": [
                "Restate the question in one line, then answer with context → action → outcome.",
            ],
        }
        ensure_evaluation_semantic_defaults(empty_ev)
        empty_ev["coach_strengths"] = []
        return empty_ev

    try:
        user_payload = (
            f"interview_type={interview_type}\n"
            f"topic_phase={(topic_phase or '')}\n"
            f"interview_question={question[:8000]}\n"
            f"candidate_answer={answer[:12000]}\n"
        )
        jd = (jd_snippet or "").strip()
        if jd:
            user_payload += f"jd_snippet=\n{jd[:6000]}\n"
        rtx = (recent_transcript or "").strip()
        if rtx:
            user_payload += f"recent_conversation_transcript=\n{rtx[:32000]}\n"

        da = domain_alignment if isinstance(domain_alignment, dict) else {}
        if da.get("domain_mismatch"):
            rsum = str(da.get("resume_career_track") or "").strip()
            jsum = str(da.get("jd_career_track") or "").strip()
            absent = da.get("absent_skills_for_jd") if isinstance(da.get("absent_skills_for_jd"), list) else []
            off = da.get("resume_strengths_off_track") if isinstance(da.get("resume_strengths_off_track"), list) else []
            absent_s = ", ".join(str(x).strip() for x in absent[:8] if str(x).strip())
            off_s = ", ".join(str(x).strip() for x in off[:6] if str(x).strip())
            user_payload += "domain_alignment_context=\n"
            user_payload += (
                f"CAREER_DOMAIN_MISMATCH: The candidate's résumé emphasizes ({rsum or 'see profile'}) "
                f"while this role centers on ({jsum or 'see JD'}). "
                "Penalize answers that only showcase off-track strengths when the question probes JD craft. "
                "In coach_feedback, call out **wrong-track / domain misalignment** when relevant (not only 'vague').\n"
            )
            if absent_s:
                user_payload += f"Priority gaps to probe or credit if demonstrated: {absent_s}.\n"
            if off_s:
                user_payload += (
                    "Résumé comfort topics that should NOT substitute for JD depth unless tied to the question: "
                    f"{off_s}.\n"
                )

        blob = gemini_client.generate_json(
            SYSTEM_EVALUATE,
            user_payload[:40000],
            temperature=0.05,
            max_output_tokens=2048,
        )
    except Exception:
        busy_ev: dict[str, Any] = {
            "scores": {"structure": 5, "clarity": 5, "technical": 5},
            "average": 5.0,
            "weak": True,
            "weakness_reason": "Evaluation service busy — answered as neutral; continue the interview",
            "missed_concepts": [],
            "addresses_question": True,
            "coach_feedback": ["Couldn't generate detailed coaching — try sharpening your examples on the next turn."],
            "coach_suggestions": [
                "Add one clear example aligned with the interviewer’s wording.",
                "End with impact: metric, stakeholder outcome, or trade-off.",
            ],
        }
        ensure_evaluation_semantic_defaults(busy_ev)
        busy_ev.setdefault("coach_strengths", [])
        return busy_ev

    scores = blob.get("scores") or {}
    if not isinstance(scores, dict):
        scores = {}

    raw_avg = blob.get("avg")
    try:
        avg = float(raw_avg) if raw_avg is not None else None
    except (TypeError, ValueError):
        avg = None

    if avg is None:
        vals: list[float] = []
        for v in scores.values():
            try:
                if isinstance(v, (int, float)):
                    vals.append(float(v))
                elif isinstance(v, str) and v.strip():
                    vals.append(float(v))
            except (TypeError, ValueError):
                continue
        avg = sum(vals) / max(len(vals), 1) if vals else 0.0

    weak_flag = blob.get("weak")
    if isinstance(weak_flag, str):
        weak_flag = weak_flag.lower() in ("true", "1", "yes")
    weak = bool(weak_flag) if weak_flag is not None else float(avg or 0) < 6.0

    addresses = _eval_addresses_question(blob)
    if not addresses:
        weak = True

    out: dict[str, Any] = {
        "scores": scores,
        "average": float(avg or 0),
        "weak": weak,
        "weakness_reason": "",
        "missed_concepts": blob.get("missed_concepts") or [],
        "addresses_question": addresses,
    }
    # Irrelevant / non-answers must not inflate the live skill bars (same as policy blocks)
    if not addresses:
        out["exclude_from_live_scores"] = True
    _merge_evaluator_semantic_flags(out, blob if isinstance(blob, dict) else {}, topic_phase)
    ensure_evaluation_semantic_defaults(out)
    _merge_evaluation_coaching(out, blob if isinstance(blob, dict) else {})
    return out


def assistant_follow_same_topic(
    question: str,
    answer: str,
    topic: dict[str, Any],
    profile: dict[str, Any],
    followup_count: int,
    *,
    recent_transcript: str | None = None,
    evaluation_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Generate follow-up question on same topic.
    Enforces max followup guardrail.
    """
    # ── Guardrail: enforce max followups per topic ──
    max_allowed = topic.get("max_followups", MAX_FOLLOWUPS_PER_TOPIC)
    if followup_count >= max_allowed:
        return _topic_exhausted_message(topic), {
            "scores": {},
            "kind": "followup_limit_reached",
        }

    phase_str = str(topic.get("phase") or "").strip().lower()
    evc = evaluation_context or {}
    follow_payload = {
        "question": question,
        "answer": answer,
        "topic": topic,
        "topic_phase": topic.get("phase"),
        "phase_instructions": _phase_instructions_next_topic(phase_str),
        "resume": profile,
        "followup_number": followup_count + 1,
        "max_followups": max_allowed,
        "recent_conversation_transcript": (recent_transcript or "").strip()[:32000],
        **_evaluator_follow_context(evc, phase_str),
    }

    blob = gemini_client.generate_json(
        SYSTEM_FOLLOW,
        json.dumps(follow_payload)[:40000],
        temperature=0.35,
    )

    evaluation = blob.get("evaluation")
    msg = str(blob.get("message", "")).strip()

    # ── Guardrail: prevent empty follow-up ──
    if not msg:
        if phase_str == "behavioral":
            msg = (
                "Can you add one concrete detail — your personal actions and "
                "a clear outcome or stakeholder response?"
            )
        elif evc.get("explicit_knowledge_gap"):
            msg = (
                "No problem — what single concept or missing piece would most unblock you "
                "on answering that design question cleanly?"
            )
        elif evc.get("honest_capability_boundary"):
            msg = (
                "Given that boundary in production—what was the hardest prompt-engineering or "
                "evaluation trade-off you navigated without fine-tuning, and how did you validate it?"
            )
        elif evc.get("numeric_claim_without_measurement_story"):
            msg = (
                "You quoted a sizable improvement — how exactly did you measure that, "
                "what was the baseline before your change, and was this offline evaluation or production?"
            )
        elif evc.get("star_scaffold_without_technical_substance"):
            msg = (
                "Strip the STAR labels — walk through concrete implementation: versions, configs, "
                "worker/process counts, thresholds, APIs, plus one failure mode you hit."
            )
        elif evc.get("meta_answer_not_substantive") or evc.get("off_topic_answer"):
            msg = (
                "Take the question literally—give one resume-grounded example: your goal, constraint, "
                "what you built or changed, and one measurable outcome."
            )
        else:
            msg = (
                "Could you elaborate further on that? Specifically, walk through the technical "
                "implementation in enough detail that someone could reproduce your reasoning."
            )
    else:
        msg = polish_followup_message(msg, phase_str)

    return msg, {
        "scores": evaluation if isinstance(evaluation, dict) else {},
        "kind": "followup",
    }


def assistant_next_question(
    *,
    jd_raw: str | None,
    profile: dict[str, Any],
    outline_topics: list[dict[str, Any]],
    topic_idx: int,
    previous_q: str,
    previous_answer: str,
    previous_eval: dict[str, Any],
    interview_type: str,
    level: str,
    recent_transcript: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Generate next main question for new topic.
    Enforces JD alignment and topic sequencing guardrails.
    """
    # ── Guardrail: prevent topic index overflow ──
    if topic_idx >= len(outline_topics):
        return _closing_transition_message(), {}

    topic_obj = outline_topics[topic_idx]

    # ── Guardrail: skip non-JD topics if JD provided ──
    jd_skill = topic_obj.get("jd_skill")
    phase = topic_obj.get("phase", "")
    if jd_raw and phase == "project" and not jd_skill:
        topic_obj["jd_skill"] = "general ML skills"

    tp = str(topic_obj.get("phase") or "").strip()
    prior_topics = [
        {
            "idx": idx,
            "title": t.get("title"),
            "phase": t.get("phase"),
            "anchor": t.get("anchor"),
        }
        for idx, t in enumerate(outline_topics)
        if isinstance(t, dict) and idx < topic_idx
    ]
    ctx = json.dumps({
        "resume": profile,
        "jd": (jd_raw or "")[:14000],
        "topic_idx": topic_idx,
        "topic": topic_obj,
        "topic_phase": topic_obj.get("phase"),
        "phase_instructions": _phase_instructions_next_topic(tp),
        "prior_completed_topics": prior_topics,
        "sequencing_note": (
            "Topics listed in prior_completed_topics were already interviewed. "
            "Do NOT ask about the same resume project/system/product AGAIN unless THIS topic explicitly "
            "requires it (problem_solving may use hypothetical variants). Anchor the ONLY current ask to THIS topic rows title/anchor/jd_skill."
        ),
        "prior_q": previous_q[:8000],
        "prior_answer": previous_answer[:12000],
        "prior_evaluation": previous_eval,
        "recent_conversation_transcript": (recent_transcript or "").strip()[:32000],
        "outline": outline_topics,
        "level": level,
        "interview_type": interview_type,
    })

    blob = gemini_client.generate_json(
        SYSTEM_NEXT_TOPIC,
        ctx[:40000],
        temperature=0.4,
    )

    evaluation = blob.get("evaluation") or {}
    msg = str(blob.get("message", "")).strip()

    # ── Guardrail: prevent empty next question ──
    if not msg:
        msg = _fallback_question(topic_obj, profile)
    else:
        msg = ensure_valid_main_question(msg, topic_obj, profile)

    return msg, (
        evaluation
        if isinstance(evaluation, dict)
        else {"combined": blob.get("evaluation")}
    )


def closing_message(profile: dict[str, Any]) -> str:
    """Return a neutral, always-true interview closing.

    Important: avoid unconditional praise (can be inaccurate) and avoid an LLM call
    (closing should be reliable even when the report generation is struggling).
    """
    name = _get_candidate_name(profile)
    return (
        f"Thank you{', ' + name if name else ''} for your time today. "
        "We’re preparing your performance report now — it will be available shortly."
    )


def finalize_report(
    profile: dict[str, Any],
    jd_raw: str | None,
    transcript: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Generate comprehensive post-interview performance report.
    Includes JD alignment scoring and actionable next steps.
    """
    # ── Guardrail: limit transcript length ──
    truncated = transcript[-MAX_TURNS_PER_SESSION:]
    jd_clip = (
        jd_raw[:20000]
        if isinstance(jd_raw, str) and jd_raw.strip()
        else None
    )

    payload = {
        "resume": profile,
        "jd_snippet": jd_clip,
        "full_transcript": truncated,
    }

    report = gemini_client.generate_json(
        SYSTEM_REPORT,
        json.dumps(payload)[:40000],
        temperature=0.25,
    )

    # ── Guardrail: ensure all required fields present ──
    report.setdefault("overall_percent", 0)
    report.setdefault("strengths", ["Participated in full interview"])
    report.setdefault("weaknesses", [])
    report.setdefault("missed_opportunities", [])
    report.setdefault("resume_bullet_refs", [])
    report.setdefault("jd_alignment", [])
    report.setdefault("recommended_next_steps", [])

    # ── Guardrail: clamp score to valid range ──
    report["overall_percent"] = max(
        0, min(100, int(report["overall_percent"]))
    )

    return report


def enrich_report_with_post_interview_dimensions(
    report: dict[str, Any],
    profile: dict[str, Any],
    jd_raw: str | None,
    transcript: list[dict[str, Any]],
    outline_topics: list[dict[str, Any]],
) -> dict[str, Any]:
    """After SYSTEM_REPORT: add dimension % and JD/technical rationale bullets (one Gemini call)."""
    truncated = transcript[-MAX_TURNS_PER_SESSION:]
    payload = json.dumps({
        "resume": profile,
        "jd_snippet": ((jd_raw or "").strip())[:16000],
        "full_transcript": truncated,
        "outline_topics": outline_topics[:MAX_TOPICS],
        "overall_percent_from_report": report.get("overall_percent"),
        "jd_alignment_from_report": report.get("jd_alignment"),
    })[:40000]

    try:
        blob = gemini_client.generate_json(
            SYSTEM_POST_LIVE_METRICS,
            payload,
            temperature=0.12,
            max_output_tokens=2048,
        )
    except Exception:
        return report

    dims = blob.get("dimension_scores_pct") or blob.get("dimensions")
    if isinstance(dims, dict):
        pct: dict[str, int] = {}
        fb = max(0, min(100, int(report.get("overall_percent") or 60)))
        for k in ("technical", "structure", "communication", "depth"):
            raw = dims.get(k)
            try:
                v = int(float(raw))
            except (TypeError, ValueError):
                v = fb
            pct[k] = max(0, min(100, v))
        if len(pct) == 4:
            report["dimension_scores_pct"] = pct

    rationale = blob.get("technical_jd_score_rationale")
    bullets: list[str] = []
    if isinstance(rationale, list):
        bullets = [str(x).strip()[:500] for x in rationale if str(x).strip()]
    elif isinstance(rationale, str) and rationale.strip():
        bullets = [rationale.strip()[:500]]
    if bullets:
        report["technical_jd_score_rationale"] = bullets[:10]

    return report


# ════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════

def _get_candidate_name(profile: dict[str, Any]) -> str:
    """Extract candidate first name from profile safely."""
    name = profile.get("name") or profile.get("full_name") or ""
    return str(name).split()[0] if name else ""


def _phase_instructions_next_topic(phase: str) -> str:
    """Short rules passed to SYSTEM_NEXT_TOPIC so the question style matches the roadmap phase."""
    p = (phase or "").strip().lower()
    if p == "behavioral":
        return (
            "PHASE behavioral: Ask ONE behavioral interview question (workplace situations). "
            "Use STAR implicitly (situation, your actions, outcome). "
            "Do NOT ask for code, APIs, algorithms, system design, or JD tool details."
        )
    if p == "warmup":
        return (
            "PHASE warmup: ONE concise overview anchored to JD-relevant ML/engineering experience "
            "(models from development toward production/trade-offs). Prefer tools and scope from jd_must_have_skills when provided; "
            "do NOT double as a specialization deep-dive unrelated to JD."
        )
    if p == "jd_core":
        return (
            "PHASE jd_core: Test a specific must-have skill from the JD — depth on tools, "
            "methods, and trade-offs tied to the topic anchor."
        )
    if p == "project":
        return (
            "PHASE project: Deep-dive ONE resume project tied to the anchor — implementation, "
            "decisions, and measurable outcome."
        )
    if p == "problem_solving":
        return (
            "PHASE problem_solving: FORWARD hypothetical ONLY — phrase as if the situation is NEW to them "
            '(e.g., "Suppose you\'re given…", "Imagine…", constraint + trade-off ask). '
            "Do NOT ask them to recount a past bullet from resume as the ONLY thread; forbid pure backward "
            "\"how did you previously\" wording unless anchored as a hypothetical parallel. "
            "Ask for steps, pitfalls, metrics to monitor, rollback — one question."
        )
    return "Match the topic phase and anchor; one clear interview question."


def _profile_snippet(profile: dict[str, Any]) -> str:
    return json.dumps(profile)[:36000]


def repair_non_answer_message(canonical_question: str) -> str:
    """User-visible repair when evaluator marks addresses_question=false (once before advancing)."""
    q = (canonical_question or "").strip()
    if len(q) > 420:
        q = q[:417] + "…"
    if not q:
        return (
            "Sticking with this topic—I still need an on-topic reply. "
            "In two or three sentences, answer using your own experience or the role context."
        )
    return (
        "Sticking with this topic—I don't have a substantive answer to this yet. "
        "Reply directly in a few sentences. Question: " + q
    )


def advance_after_non_engagement_prefix() -> str:
    """Prepended to the next main question after two consecutive non-substantive turns."""
    return "We'll move on—please answer each prompt directly with relevant substance.\n\n"


def _topic_exhausted_message(topic: dict[str, Any]) -> str:
    """Return transition message when follow-up limit reached (rarely user-visible)."""
    return "Moving to the next segment—stand by for the next question."


def _closing_transition_message() -> str:
    """Return message when all topics are exhausted."""
    return (
        "We've covered all the topics I had planned for today. "
        "Let me wrap up our session."
    )


def _fallback_question(
    topic: dict[str, Any],
    profile: dict[str, Any],
) -> str:
    """Generate safe fallback question if LLM returns empty."""
    _ = profile
    anchor = topic.get("anchor", "your experience")
    title = topic.get("title", "this topic")
    phase = str(topic.get("phase") or "").strip().lower()
    if phase == "behavioral":
        return (
            f"Let's discuss {title}. "
            f"Can you describe a specific situation where {anchor} came up — "
            f"what was at stake, what actions you took, and what changed as a result?"
        )
    if phase == "problem_solving":
        return (
            f"Suppose you inherit {title}: {anchor} — constraints are messy data, tight latency, "
            f"and limited labeling budget. How would you approach it end-to-end, and what metric would convince you "
            f"it's safe to ship?"
        )
    return (
        f"Let's talk about {title}. "
        f"Could you walk me through {anchor} "
        f"in detail — specifically what you built, "
        f"the technologies you used, and the outcome?"
    )


def _clamp_reply(text: str, max_chars: int = 1600) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _main_question_is_valid(msg: str) -> bool:
    """Reject empty, transition-only, or non-question main prompts."""
    text = (msg or "").strip()
    if len(text) < 40 or "?" not in text:
        return False
    low = text.lower()
    interrogatives = (
        "how ", "what ", "why ", "which ", "walk me", "describe ", "tell me",
        "could you", "can you", "suppose ", "imagine ", "you're given",
    )
    if any(i in low for i in interrogatives):
        return True
    # Transition-only stubs (short, no real ask)
    if ("move on" in low or "next topic" in low) and len(text) < 260:
        return False
    # Long messages with ? are usually substantive even without keyword at start
    if len(text) >= 120:
        return True
    return False


def ensure_valid_main_question(
    msg: str,
    topic: dict[str, Any],
    profile: dict[str, Any],
) -> str:
    """Ensure the next-topic message always contains a real question."""
    text = (msg or "").strip()
    if _main_question_is_valid(text):
        return _clamp_reply(text)
    merged = _fallback_question(topic, profile)
    return _clamp_reply(merged)


def polish_followup_message(msg: str, phase: str | None = None) -> str:
    """Keep follow-ups readable; ensure a question mark exists."""
    text = (msg or "").strip()
    if not text:
        return text
    if "?" not in text:
        p = str(phase or "").strip().lower()
        if p == "behavioral":
            text += " What was your role and the clearest outcome?"
        else:
            text += " Can you give one concrete example with a metric?"
    return _clamp_reply(text, max_chars=1200)


def _inject_fallback_topics(
    existing: list[dict[str, Any]],
    jd: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Inject minimum required topics if outline is too short."""
    fallbacks = [
        {
            "id": "fallback_warmup",
            "title": "Background & Motivation",
            "anchor": "overall ML experience",
            "phase": "warmup",
            "jd_skill": None,
            "max_followups": PHASE_FOLLOWUP_CAPS["warmup"],
        },
        {
            "id": "fallback_jd_core",
            "title": "Core ML Skills",
            "anchor": "TensorFlow/Scikit-Learn experience",
            "phase": "jd_core",
            "jd_skill": "TensorFlow",
            "max_followups": PHASE_FOLLOWUP_CAPS["jd_core"],
        },
        {
            "id": "fallback_project",
            "title": "Key Project Deep Dive",
            "anchor": "most relevant ML project",
            "phase": "project",
            "jd_skill": "model development",
            "max_followups": PHASE_FOLLOWUP_CAPS["project"],
        },
        {
            "id": "fallback_problem",
            "title": "Problem Solving",
            "anchor": "hypothetical ML scenario",
            "phase": "problem_solving",
            "jd_skill": "data preprocessing",
            "max_followups": PHASE_FOLLOWUP_CAPS["problem_solving"],
        },
        {
            "id": "fallback_behavioral",
            "title": "Remote Work & Collaboration",
            "anchor": "independent project management",
            "phase": "behavioral",
            "jd_skill": None,
            "max_followups": PHASE_FOLLOWUP_CAPS["behavioral"],
        },
    ]
    existing_phases = {t.get("phase") for t in existing}
    for fb in fallbacks:
        if fb["phase"] not in existing_phases:
            existing.append(fb)
    return existing


# ════════════════════════════════════════════════════════
# DB HELPERS (unchanged)
# ════════════════════════════════════════════════════════

def load_profile(
    db_session,
    pid: uuid.UUID,
    user_id: uuid.UUID,
) -> ResumeProfile | None:
    row = db_session.get(ResumeProfile, pid)
    if not row or row.user_id != user_id:
        return None
    return row


def load_jd_optional(
    db_session,
    jd_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> str | None:
    if not jd_id:
        return None
    jd = db_session.get(JobDescription, jd_id)
    if jd and jd.user_id == user_id:
        return jd.raw_text
    return None


def load_jd_bundle(
    db_session,
    jd_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> tuple[str | None, dict[str, Any]]:
    """JD raw text + structured keywords (same shape as resume analyze route)."""
    if not jd_id:
        return None, {}
    jd = db_session.get(JobDescription, jd_id)
    if not jd or jd.user_id != user_id:
        return None, {}
    raw = jd.raw_text or ""
    st = jd.extracted_keywords if isinstance(jd.extracted_keywords, dict) else {}
    st = dict(st)
    st.setdefault("keywords", st.get("keywords") or [])
    return raw, st


def session_transcript_turns(
    session: MockInterviewSession,
) -> list[dict[str, str]]:
    turns = sorted(session.turns, key=lambda t: t.turn_index)
    return [
        {
            "role": t.role,
            "content": t.content,
            "modality": t.modality or "",
            "evaluation": json.dumps(t.evaluation)
            if t.evaluation is not None
            else "",
        }
        for t in turns
    ]
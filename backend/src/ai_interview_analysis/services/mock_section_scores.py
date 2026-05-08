"""Per-topic segment scores aligned with frontend/lib/mockInterviewEval.ts rules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ai_interview_analysis.db.models import MockInterviewSession, MockTurn


def _percent_from_raw(n: float) -> float:
    if not isinstance(n, (int, float)) or n != n:
        return 0.0
    f = float(n)
    if f <= 10:
        return min(100.0, max(0.0, f * 10.0))
    return min(100.0, max(0.0, f))


def _metrics_from_evaluation(ev: dict[str, Any]) -> dict[str, float] | None:
    if ev.get("policy_block"):
        return None
    if ev.get("exclude_from_live_scores"):
        return None
    scores = ev.get("scores")
    if isinstance(scores, dict):
        raw_t = scores.get("technical")
        raw_s = scores.get("structure")
        raw_c = scores.get("clarity")
        if isinstance(raw_t, (int, float)) and isinstance(raw_s, (int, float)):
            technical = _percent_from_raw(float(raw_t))
            structure = _percent_from_raw(float(raw_s))
            communication = (
                _percent_from_raw(float(raw_c))
                if isinstance(raw_c, (int, float))
                else (technical + structure) / 2.0
            )
            depth = (technical + communication) / 2.0
            return {
                "technical": technical,
                "structure": structure,
                "communication": communication,
                "depth": depth,
            }
    ta = ev.get("technical_accuracy")
    st = ev.get("answer_structure")
    co = ev.get("communication")
    de = ev.get("depth_and_detail")
    if isinstance(ta, (int, float)) and isinstance(st, (int, float)):
        technical = _percent_from_raw(float(ta))
        structure = _percent_from_raw(float(st))
        communication = _percent_from_raw(float(co)) if isinstance(co, (int, float)) else (technical + structure) / 2.0
        depth = _percent_from_raw(float(de)) if isinstance(de, (int, float)) else (technical + communication) / 2.0
        return {
            "technical": technical,
            "structure": structure,
            "communication": communication,
            "depth": depth,
        }
    return None


def aggregate_section_metrics(turns: list[MockTurn], topic_index: int) -> dict[str, float] | None:
    """Average metrics for user turns tagged with answered_topic_index == topic_index."""
    rows: list[dict[str, float]] = []
    for t in turns:
        if t.role != "user" or not t.evaluation:
            continue
        ev = t.evaluation if isinstance(t.evaluation, dict) else {}
        if ev.get("answered_topic_index") != topic_index:
            continue
        m = _metrics_from_evaluation(ev)
        if m:
            rows.append(m)
    if not rows:
        return None
    n = len(rows)
    return {
        "technical": sum(r["technical"] for r in rows) / n,
        "structure": sum(r["structure"] for r in rows) / n,
        "communication": sum(r["communication"] for r in rows) / n,
        "depth": sum(r["depth"] for r in rows) / n,
    }


def finalize_section_for_topic(
    db: Session,
    sess: MockInterviewSession,
    *,
    completed_topic_idx: int,
) -> None:
    """Persist aggregate scores for a completed roadmap segment under session_state.section_scores."""
    turns = list(
        db.execute(
            select(MockTurn).where(MockTurn.session_id == sess.id).order_by(MockTurn.turn_index),
        ).scalars(),
    )
    metrics = aggregate_section_metrics(turns, completed_topic_idx)
    st = dict(sess.session_state or {})
    sec: dict[str, Any] = dict(st.get("section_scores") or {})
    key = str(int(completed_topic_idx))
    if metrics is not None:
        sec[key] = metrics
    elif key not in sec:
        sec[key] = {
            "technical": 0.0,
            "structure": 0.0,
            "communication": 0.0,
            "depth": 0.0,
        }
    st["section_scores"] = sec
    sess.session_state = st
    flag_modified(sess, "session_state")


def public_section_scores(sess: MockInterviewSession) -> dict[str, Any]:
    st = sess.session_state if isinstance(sess.session_state, dict) else {}
    raw = st.get("section_scores")
    return dict(raw) if isinstance(raw, dict) else {}

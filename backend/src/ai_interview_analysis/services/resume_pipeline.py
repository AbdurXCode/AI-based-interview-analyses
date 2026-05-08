"""
Resume structuring, JD profiling, and Gemini-driven analysis.

Resume-vs-JD **analyze** uses a unified LLM pass (`unified_resume_analysis`) for scores
and copy, plus a focused **domain alignment** pass. If alignment detects a career-track
mismatch, the overall match percent is capped at 45% and a warning is prepended to the coach summary.

`compute_match` / `structured_feedback` remain for any legacy or manual use but are
not used by POST .../resume-profiles/{id}/analyze.
"""

from __future__ import annotations

import re
from typing import Any

from ai_interview_analysis.services import gemini_client
from ai_interview_analysis.prompts.loader import load_resume_system_prompts

_RP = load_resume_system_prompts()
SYSTEM_PARSE = _RP["SYSTEM_PARSE"]
SYSTEM_JD = _RP["SYSTEM_JD"]
SYSTEM_UNIFIED_ANALYSIS = _RP["SYSTEM_UNIFIED_ANALYSIS"]
SYSTEM_FULL_ANALYSIS = _RP["SYSTEM_FULL_ANALYSIS"]
SYSTEM_REWRITE = _RP["SYSTEM_REWRITE"]
SYSTEM_DOMAIN_ALIGNMENT = _RP["SYSTEM_DOMAIN_ALIGNMENT"]

DOMAIN_MISMATCH_MATCH_CAP = 45.0



def flatten_skills(profile: dict[str, Any]) -> set[str]:
    raw = profile.get("skills") or []
    out: set[str] = set()
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str):
                out.add(_norm_skill(x))
    return out


def flatten_text(profile: dict[str, Any]) -> str:
    parts: list[str] = []

    parts.append(profile.get("summary") or "")
    for ex in profile.get("experience") or []:
        if isinstance(ex, dict):
            for b in ex.get("bullets") or []:
                if isinstance(b, dict):
                    parts.append(str(b.get("text", "")))
                else:
                    parts.append(str(b))
    for pj in profile.get("projects") or []:
        if isinstance(pj, dict):
            for b in pj.get("bullets") or []:
                if isinstance(b, dict):
                    parts.append(str(b.get("text", "")))
                else:
                    parts.append(str(b))
    return "\n".join(parts).lower()


def _norm_skill(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _as_str_list(val: Any, max_n: int) -> list[str]:
    if not isinstance(val, list):
        return []
    out: list[str] = []
    for x in val:
        s = str(x).strip() if x is not None else ""
        if s:
            out.append(s[:120])
        if len(out) >= max_n:
            break
    return out


def _fallback_domain_alignment_blob() -> dict[str, Any]:
    return {
        "domain_mismatch": False,
        "severity": "none",
        "resume_career_track": "",
        "jd_career_track": "",
        "absent_skills_for_jd": [],
        "resume_strengths_off_track": [],
        "warning_for_candidate": "",
    }


def _merge_domain_alignment_heuristics(
    blob: dict[str, Any],
    profile: dict[str, Any],
    jd_struct: dict[str, Any],
) -> dict[str, Any]:
    """Normalize model output. Do not override domain_mismatch with string heuristics — LLM is sole source for ladder fit."""
    out: dict[str, Any] = {**_fallback_domain_alignment_blob(), **(blob if isinstance(blob, dict) else {})}
    out["domain_mismatch"] = bool(out.get("domain_mismatch"))
    sev = str(out.get("severity") or "none").strip().lower()
    if sev not in ("none", "moderate", "severe"):
        sev = "none"
    out["severity"] = sev
    out["resume_career_track"] = str(out.get("resume_career_track") or "").strip()
    out["jd_career_track"] = str(out.get("jd_career_track") or "").strip()
    out["absent_skills_for_jd"] = _as_str_list(out.get("absent_skills_for_jd"), 12)
    out["resume_strengths_off_track"] = _as_str_list(out.get("resume_strengths_off_track"), 8)
    out["warning_for_candidate"] = str(out.get("warning_for_candidate") or "").strip()

    if not out["domain_mismatch"]:
        out["severity"] = "none"
        out["resume_strengths_off_track"] = []
        out["warning_for_candidate"] = ""
    elif out["severity"] == "none":
        out["severity"] = "moderate"

    # Optional: enrich gap list when model left it empty — use full résumé text (soft substring), not skills array only.
    must_list = [x for x in (jd_struct.get("must_have_skills") or []) if isinstance(x, str) and x.strip()]
    if not out["absent_skills_for_jd"] and must_list:
        blob_txt = flatten_text(profile)
        deduced: list[str] = []
        for phrase in must_list:
            key = _norm_skill(phrase).lower()
            if len(key) < 4:
                continue
            if key not in blob_txt:
                deduced.append(phrase)
            if len(deduced) >= 8:
                break
        if deduced:
            out["absent_skills_for_jd"] = deduced[:8]

    return out


def analyze_domain_alignment(
    profile: dict[str, Any],
    jd_raw: str,
    jd_struct: dict[str, Any],
    resume_plain: str | None = None,
) -> dict[str, Any]:
    """Semantic LLM pass for ladder fit; merge step only normalizes and may enrich gap skills from résumé text."""
    import json as _json

    jd_clip = jd_raw.strip()[:24000]
    resume_xt = (resume_plain or "").strip()
    excerpt = ""
    if resume_xt:
        excerpt = (
            "\n=== RESUME (extracted plain text excerpt; use with structured JSON) ===\n"
            f"{resume_xt[:14000]}\n"
        )
    user = (
        "=== JOB DESCRIPTION (full text) ===\n"
        f"{jd_clip}\n\n"
        "=== STRUCTURED JD (JSON) ===\n"
        f"{_json.dumps(jd_struct, ensure_ascii=False)[:14000]}\n\n"
        "=== RESUME PROFILE (structured JSON — skills, experience bullets, projects) ===\n"
        f"{_json.dumps({'resume_profile': profile}, ensure_ascii=False)[:20000]}\n"
        f"{excerpt}"
    )
    try:
        blob = gemini_client.generate_json(
            SYSTEM_DOMAIN_ALIGNMENT,
            user,
            temperature=0.15,
            max_output_tokens=2048,
        )
        if not isinstance(blob, dict):
            raise ValueError("domain alignment: non-object")
    except Exception:
        blob = _fallback_domain_alignment_blob()
    return _merge_domain_alignment_heuristics(blob, profile, jd_struct)


def _domain_mismatch_summary_lead(da: dict[str, Any]) -> str:
    """First paragraph for coach summary when model warning is missing."""
    r = str(da.get("resume_career_track") or "").strip()
    j = str(da.get("jd_career_track") or "").strip()
    cap = int(DOMAIN_MISMATCH_MATCH_CAP)
    if r and j:
        return (
            f"Domain note: your experience reads closest to «{r}», while this role emphasizes «{j}»—different career ladders, "
            f"not just missing keywords. Overall JD match is capped at {cap}% for this comparison; details follow."
        )
    return (
        f"Domain note: résumé and role target materially different crafts. JD match is capped at {cap}% here; specifics below."
    )


def keyword_tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9+#.]+", text.lower())
    junk = {"the", "and", "or", "a", "an", "to", "with", "of", "in", "for", "yr", "yrs"}
    return set(t for t in tokens if len(t) >= 2 and t not in junk)


def parse_resume_structure(extracted_text: str) -> dict[str, Any]:
    payload = extracted_text.strip()[:48000]
    return gemini_client.generate_json(SYSTEM_PARSE, f"Resume text:\n\n{payload}")


def extract_jd_profile(raw_jd: str) -> dict[str, Any]:
    jd = raw_jd.strip()[:48000]
    return gemini_client.generate_json(SYSTEM_JD, f"Job Description:\n\n{jd}")


def compute_match(
    profile: dict[str, Any],
    jd_struct: dict[str, Any],
    jd_raw: str,
) -> dict[str, Any]:
    """
    Deterministic match using keyword coverage, skill overlaps, semantic similarity (optional embed).
    """
    jd_keywords = {_norm_skill(k) for k in (jd_struct.get("keywords") or [])}
    must_raw = jd_struct.get("must_have_skills") or []
    nice_raw = jd_struct.get("nice_to_have_skills") or []
    must = {_norm_skill(x) for x in must_raw if isinstance(x, str)}
    nice = {_norm_skill(x) for x in nice_raw if isinstance(x, str)}

    skills_prof = flatten_skills(profile)
    jd_blob = jd_raw.lower()
    txt = flatten_text(profile)

    # Merge keywords from jd text heuristic
    extra_kw = keyword_tokenize(jd_raw)
    jd_keywords |= {k for k in extra_kw if len(k) > 3}  # widen net slightly

    covered_kw = len(jd_keywords & keyword_tokenize(txt)) if jd_keywords else 0
    keyword_cov = covered_kw / max(len(jd_keywords), 1)

    must_score = (
        len(must & skills_prof) / max(len(must), 1)
        if must
        else 1.0
    )

    nice_score = (
        len(nice & skills_prof) / max(len(nice), 1) if nice else 1.0
    )

    embed_sim = 0.72  # fallback when embeddings fail
    try:
        vp = flatten_text(profile)[:8000]
        jd_short = jd_raw[:8000]
        if vp.strip() and jd_short.strip():
            vecs = gemini_client.embed_texts([vp, jd_short])
            embed_sim = max(
                0.0,
                min(
                    1.0,
                    (gemini_client.cosine_sim(vecs[0], vecs[1]) + 1) / 2,
                ),
            )
    except Exception:
        pass

    missing_must = sorted(must - skills_prof)
    missing_keywords = sorted(
        jd_keywords - keyword_tokenize(txt),
        key=len,
        reverse=True,
    )[:50]

    kw_pct = round(min(1.0, keyword_cov) * 100, 2)
    exp_pct = round(embed_sim * 100, 2)
    if must:
        skills_pct = round(100 * (0.7 * min(1.0, must_score) + 0.3 * min(1.0, nice_score)), 2)
    else:
        skills_pct = round(100 * min(1.0, nice_score if nice else must_score), 2)

    w_kw, w_exp, w_sk = 0.30, 0.40, 0.30
    composite = round(w_kw * kw_pct + w_exp * exp_pct + w_sk * skills_pct, 1)
    formula = (
        f"overall = {int(w_kw * 100)}%×KeywordCoverage + {int(w_exp * 100)}%×ExperienceRelevance + "
        f"{int(w_sk * 100)}%×SkillsAlignment = {composite}% "
        f"({kw_pct:.0f}×{w_kw} + {exp_pct:.0f}×{w_exp} + {skills_pct:.0f}×{w_sk})"
    )

    return {
        "match_percent": composite,
        "dimensions": {
            "keyword_coverage": kw_pct,
            "experience_relevance": exp_pct,
            "skills_alignment": skills_pct,
        },
        "missing_must_have_skills": missing_must[:30],
        "missing_keywords_sample": missing_keywords[:24],
        "formula": formula,
    }


SECTION_ORDER = (
    "Summary / Objective",
    "Work Experience",
    "Skills",
    "Projects",
    "Education",
)


def _dim_score_read(dimensions: dict[str, Any], key: str) -> float:
    v = dimensions.get(key)
    if isinstance(v, dict):
        try:
            return float(v.get("score", 0))
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _build_bullet_text_index(profile: dict[str, Any]) -> dict[str, str]:
    """Map every bullet_id in the structured resume to its raw text.

    The LLM is supposed to set ``original_text`` to the verbatim resume bullet,
    but it sometimes returns it empty. We index the structured profile so the
    mapper can backfill the text by ``bullet_id``.
    """
    out: dict[str, str] = {}
    for ex in profile.get("experience") or []:
        if not isinstance(ex, dict):
            continue
        for b in ex.get("bullets") or []:
            if isinstance(b, dict):
                bid = str(b.get("id") or "").strip()
                txt = str(b.get("text") or "").strip()
                if bid and txt:
                    out[bid] = txt
    for pj in profile.get("projects") or []:
        if not isinstance(pj, dict):
            continue
        for b in pj.get("bullets") or []:
            if isinstance(b, dict):
                bid = str(b.get("id") or "").strip()
                txt = str(b.get("text") or "").strip()
                if bid and txt:
                    out[bid] = txt
    return out


def _build_bullet_topic_index(profile: dict[str, Any]) -> dict[str, str]:
    """Map every bullet_id to its parent's display name.

    For experience bullets we use ``"Role @ Company"`` (or whichever side
    is populated). For project bullets we use the project name. This is
    the source of truth the UI uses as the bullet's heading so the user
    knows WHICH resume item the feedback is about.
    """
    out: dict[str, str] = {}
    for ex in profile.get("experience") or []:
        if not isinstance(ex, dict):
            continue
        role = str(ex.get("title") or ex.get("role") or "").strip()
        company = str(ex.get("company") or ex.get("employer") or "").strip()
        if role and company:
            heading = f"{role} @ {company}"
        else:
            heading = role or company or "Experience"
        for b in ex.get("bullets") or []:
            if isinstance(b, dict):
                bid = str(b.get("id") or "").strip()
                if bid:
                    out[bid] = heading
    for pj in profile.get("projects") or []:
        if not isinstance(pj, dict):
            continue
        name = str(pj.get("name") or pj.get("title") or "Project").strip()
        for b in pj.get("bullets") or []:
            if isinstance(b, dict):
                bid = str(b.get("id") or "").strip()
                if bid:
                    out[bid] = name
    return out


def _normalize_match_result_from_llm(match_flat: dict[str, Any]) -> dict[str, Any]:
    """Flatten dimension scores and match_percent from the model; no recomputation."""
    dims_in = match_flat.get("dimensions")
    if not isinstance(dims_in, dict):
        dims_in = {}
    kw = round(_dim_score_read(dims_in, "keyword_coverage"), 1)
    exp = round(_dim_score_read(dims_in, "experience_relevance"), 1)
    sk = round(_dim_score_read(dims_in, "skills_alignment"), 1)
    out = dict(match_flat)
    out["dimensions"] = {
        "keyword_coverage": kw,
        "experience_relevance": exp,
        "skills_alignment": sk,
    }
    try:
        overall = float(out.get("match_percent", out.get("overall_score", 0)))
    except (TypeError, ValueError):
        overall = 0.0
    out["match_percent"] = round(overall, 1)
    out.pop("overall_score", None)
    return out


def _map_unified_to_legacy_shapes(raw: dict[str, Any], profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map the exact prompt JSON schema → legacy match_result + feedback dicts.

    The prompt returns:
      match_result.overall_score, match_result.formula, match_result.dimensions
      keywords (matched / partial / missing)
      section_scores  (five section rows)
      bullets  (bullet_id / original_text / quality / issue_label / why / suggested_rewrite)
      ats, smart_insights, coach_summary
    """
    mr_in = raw.get("match_result")
    if not isinstance(mr_in, dict):
        raise ValueError("unified response missing match_result")

    dims_src = mr_in.get("dimensions")
    if not isinstance(dims_src, dict):
        dims_src = {}
    kw = round(_dim_score_read(dims_src, "keyword_coverage"), 1)
    exp = round(_dim_score_read(dims_src, "experience_relevance"), 1)
    sk = round(_dim_score_read(dims_src, "skills_alignment"), 1)

    raw_overall = mr_in.get("overall_score", mr_in.get("match_percent"))
    if raw_overall is None:
        raise ValueError("unified response: match_result.overall_score is required")
    try:
        overall = round(float(raw_overall), 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("unified response: match_result.overall_score must be a number") from exc

    match_result: dict[str, Any] = {
        "match_percent": overall,
        "dimensions": {"keyword_coverage": kw, "experience_relevance": exp, "skills_alignment": sk},
        "formula": str(mr_in.get("formula") or ""),
        "missing_must_have_skills": [],
        "missing_keywords_sample": [],
    }

    # Build missing_keywords_sample from keywords.missing.
    # The prompt caps this at 5 most-impactful entries with no priority field;
    # we enforce the cap defensively here in case the model emits more, and we
    # strip any legacy "priority" field so the UI receives a flat shape.
    kw_block = raw.get("keywords")
    if not isinstance(kw_block, dict):
        kw_block = {"matched": [], "partial": [], "missing": []}
    raw_missing = kw_block.get("missing") if isinstance(kw_block.get("missing"), list) else []
    cleaned_missing: list[dict[str, Any]] = []
    for x in raw_missing:
        if isinstance(x, dict):
            kw_str = str(x.get("keyword") or "").strip()
            reason = str(x.get("reason") or "").strip()
        else:
            kw_str = str(x).strip()
            reason = ""
        if kw_str:
            cleaned_missing.append({"keyword": kw_str, "reason": reason})
        if len(cleaned_missing) >= 5:
            break
    kw_block["missing"] = cleaned_missing
    match_result["missing_keywords_sample"] = [m["keyword"] for m in cleaned_missing]

    # section_scores (prompt key); fall back to "sections" if model uses that key
    sections_raw = raw.get("section_scores")
    if not isinstance(sections_raw, list):
        sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list):
        sections_raw = []
    fixed_sections: list[dict[str, Any]] = []
    for i, name in enumerate(SECTION_ORDER):
        row = next(
            (s for s in sections_raw if isinstance(s, dict) and str(s.get("name", "")).strip() == name),
            None,
        )
        if row is None and i < len(sections_raw) and isinstance(sections_raw[i], dict):
            row = {**sections_raw[i], "name": name}
        if isinstance(row, dict):
            ent = dict(row)
            ent.setdefault("name", name)
            fixed_sections.append(ent)
        else:
            fixed_sections.append({"name": name, "score_1_to_10": 1, "reason": "Section absent.", "improvement": "", "issues": []})

    # bullets: prompt uses bullet_id, issue_label, suggested_rewrite, topic.
    # Build id→text and id→topic indexes from the structured resume profile so
    # we can backfill the verbatim text and the parent project/role name
    # whenever the LLM omits them (the UI relies on both to show the user
    # "this is the bullet, in this part of the resume, that has a problem").
    bullet_text_by_id = _build_bullet_text_index(profile)
    bullet_topic_by_id = _build_bullet_topic_index(profile)

    raw_bullets = raw.get("bullets") if isinstance(raw.get("bullets"), list) else []
    mapped_bullets: list[dict[str, Any]] = []
    for b in (x for x in raw_bullets if isinstance(x, dict)):
        path = str(b.get("bullet_id") or b.get("path") or "").strip()
        sug = str(b.get("suggested_rewrite") or b.get("suggestion") or "")
        issue = str(b.get("issue_label") or b.get("issue") or "Review")
        original = str(b.get("original_text") or "").strip()
        if not original and path:
            original = bullet_text_by_id.get(path, "")
        topic = str(b.get("topic") or b.get("section") or "").strip()
        if not topic and path:
            topic = bullet_topic_by_id.get(path, "")
        mapped_bullets.append(
            {
                "path": path,
                "topic": topic,
                "original_text": original,
                "quality": str(b.get("quality", "Acceptable")),
                "issue": issue,
                "why": str(b.get("why", "")),
                "suggestion": sug,
                "suggested_rewrite": sug,
            },
        )

    ats = raw.get("ats") if isinstance(raw.get("ats"), dict) else {"overall": "pass", "checks": []}
    insights = (
        raw.get("smart_insights")
        if isinstance(raw.get("smart_insights"), dict)
        else {"role_fit_titles": [], "skills_to_learn_next": [], "strategic_tip": ""}
    )

    feedback: dict[str, Any] = {
        "overall_score_explanation": "",
        "keywords": kw_block,
        "sections": fixed_sections,
        "bullets": mapped_bullets,
        "ats": ats,
        "smart_insights": insights,
        "summary": str(raw.get("coach_summary") or ""),
    }
    return match_result, _normalize_full_feedback(feedback, profile)



def unified_resume_analysis(
    profile: dict[str, Any],
    jd_raw: str,
    jd_struct: dict[str, Any],
    resume_plain: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One Gemini JSON response → match_result + feedback (prompt is sole source of truth).

    The user message gives the model exactly what the prompt says it will receive:
    the resume as extracted text and the full JD as raw text.  The structured
    profile JSON is appended as supplementary context for accurate bullet-id
    assignment.
    """
    import json as _json

    # Resume text: prefer raw extraction; fall back to flattening the profile JSON
    resume_text = (resume_plain or "").strip()
    if not resume_text:
        resume_text = flatten_text(profile)
    resume_clip = resume_text[:32000]

    jd_clip = jd_raw.strip()[:32000]

    # Structured profile appended so the model can assign accurate bullet ids
    structured_note = (
        "NOTE: The structured resume JSON below matches the extracted text. "
        "Use the 'id' fields from experience/projects bullets as bullet_id values.\n"
        + _json.dumps({"resume_profile": profile}, ensure_ascii=False)[:20000]
    )

    user = (
        "=== RESUME (extracted text) ===\n"
        f"{resume_clip}\n\n"
        "=== JOB DESCRIPTION ===\n"
        f"{jd_clip}\n\n"
        "=== STRUCTURED CONTEXT (bullet ids) ===\n"
        f"{structured_note}\n"
    )

    blob = gemini_client.generate_json(
        SYSTEM_UNIFIED_ANALYSIS,
        user,
        temperature=1.0,
        # top_p=0.9,
        # top_k=40,
        # Pass None: Gemini's JSON-mode constrained decoding consumes ~7-8k
        # internal tokens before emitting the visible JSON. Capping at 8192
        # caused the model to hit MAX_TOKENS mid-output, producing truncated
        # (un-parseable) JSON. Letting the SDK use its model-max default
        # gives the full window for actual content.
        max_output_tokens=None,
    )
    if not isinstance(blob, dict):
        raise ValueError("unified analysis: non-object response")
    match_result, feedback = _map_unified_to_legacy_shapes(blob, profile)

    da = analyze_domain_alignment(profile, jd_clip, jd_struct, resume_plain=resume_plain)
    feedback["domain_alignment"] = da
    feedback["domain_fit"] = {
        "mismatch": bool(da.get("domain_mismatch")),
        "severity": da.get("severity"),
        "resume_track": da.get("resume_career_track"),
        "jd_track": da.get("jd_career_track"),
        "absent_jd_skills": list(da.get("absent_skills_for_jd") or []) if isinstance(da.get("absent_skills_for_jd"), list) else [],
    }

    mismatch = bool(da.get("domain_mismatch"))
    match_result["domain_mismatch"] = mismatch
    if mismatch:
        try:
            cur = float(match_result.get("match_percent", 0))
        except (TypeError, ValueError):
            cur = 0.0
        match_result["match_percent"] = round(min(cur, DOMAIN_MISMATCH_MATCH_CAP), 1)
        match_result["jd_match_percent_capped_at"] = float(DOMAIN_MISMATCH_MATCH_CAP)
        warn = (da.get("warning_for_candidate") or "").strip()
        if not warn:
            warn = _domain_mismatch_summary_lead(da)
        summ = str(feedback.get("summary") or "").strip()
        feedback["summary"] = f"{warn}\n\n{summ}".strip() if summ else warn
    else:
        match_result.pop("jd_match_percent_capped_at", None)

    return match_result, feedback




def _fallback_feedback(profile: dict[str, Any], match_bundle: dict[str, Any]) -> dict[str, Any]:
    """Minimal structure when LLM fails."""
    missing = match_bundle.get("missing_must_have_skills") or []
    miss_kw = match_bundle.get("missing_keywords_sample") or []
    return {
        "overall_score_explanation": str(match_bundle.get("formula", "")),
        "keywords": {
            "matched": [],
            "partial": [],
            "missing": [
                {"keyword": str(k), "reason": "Gap vs JD"}
                for k in (list(missing) + list(miss_kw))[:5]
            ],
        },
        "sections": [],
        "bullets": [],
        "ats": {"overall": "warning", "checks": []},
        "smart_insights": {
            "role_fit_titles": [],
            "skills_to_learn_next": [str(x) for x in missing[:5]],
            "strategic_tip": "Run analysis again when the AI service is available.",
        },
        "summary": "Automated analysis was limited. Re-run when the model is available.",
    }


def _normalize_full_feedback(blob: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Ensure backwards-compatible keys + bullet suggestion alias."""
    out = dict(blob) if isinstance(blob, dict) else {}
    sections = out.get("sections") if isinstance(out.get("sections"), list) else []
    fixed_sections: list[dict[str, Any]] = []
    for s in sections:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "Section"))
        score = s.get("score_1_to_10")
        try:
            sc = float(score) if score is not None else 0.0
        except (TypeError, ValueError):
            sc = 0.0
        reason = s.get("reason")
        improvement = s.get("improvement")
        issues = s.get("issues") if isinstance(s.get("issues"), list) else []
        if not reason and issues:
            reason = str(issues[0]) if issues else ""
        if not improvement and len(issues) > 1:
            improvement = str(issues[1])
        fixed_sections.append(
            {
                "name": name,
                "score_1_to_10": sc,
                "reason": reason or "",
                "improvement": improvement or "",
                "issues": issues if issues else ([reason] if reason else []),
            },
        )
    out["sections"] = fixed_sections

    raw_bullets = out.get("bullets") if isinstance(out.get("bullets"), list) else []
    fixed_bullets: list[dict[str, Any]] = []
    for b in raw_bullets:
        if not isinstance(b, dict):
            continue
        path = str(b.get("path", ""))
        sug = b.get("suggested_rewrite") or b.get("suggestion") or ""
        fixed_bullets.append(
            {
                "path": path,
                "quality": str(b.get("quality", "Acceptable")),
                "issue": str(b.get("issue", "Review")),
                "why": str(b.get("why", b.get("why_weak", ""))),
                "suggestion": str(sug),
                "suggested_rewrite": str(sug),
            },
        )
    out["bullets"] = fixed_bullets

    if "keywords" not in out or not isinstance(out["keywords"], dict):
        out["keywords"] = {"matched": [], "partial": [], "missing": []}
    if "ats" not in out or not isinstance(out["ats"], dict):
        out["ats"] = {"overall": "pass", "checks": []}
    if "smart_insights" not in out or not isinstance(out["smart_insights"], dict):
        out["smart_insights"] = {"role_fit_titles": [], "skills_to_learn_next": [], "strategic_tip": ""}
    return out


def structured_feedback(
    profile: dict[str, Any],
    match_bundle: dict[str, Any],
    jd_struct: dict[str, Any],
    jd_raw: str,
) -> dict[str, Any]:
    import json as _json

    payload = {
        "resume_profile": profile,
        "jd_struct": jd_struct,
        "deterministic_match": match_bundle,
    }
    user = (
        "Job description (full text):\n"
        f"{jd_raw.strip()[:32000]}\n\n"
        "Structured context (JSON):\n"
        f"{_json.dumps(payload)[:42000]}\n"
    )
    try:
        blob = gemini_client.generate_json(SYSTEM_FULL_ANALYSIS, user, temperature=0.25)
        if not isinstance(blob, dict):
            raise ValueError("non-object")
        return _normalize_full_feedback(blob, profile)
    except Exception:
        return _normalize_full_feedback(_fallback_feedback(profile, match_bundle), profile)




def rewrite_bullet(existing: str, extra_instruction: str | None = None) -> dict[str, str]:
    hints = existing.strip()[:6000]
    user = (
        "Bullet:\n"
        + hints
        + ("\n\nExtra instruction: " + extra_instruction if extra_instruction else "")
    )
    return gemini_client.generate_json(SYSTEM_REWRITE, user, temperature=0.35)

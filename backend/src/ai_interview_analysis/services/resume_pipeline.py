"""
Resume structuring, JD profiling, and Gemini-driven analysis.

Resume-vs-JD **analyze** uses a single unified LLM pass (`unified_resume_analysis`):
scores and copy come straight from the model JSON — no server-side score repair
and no deterministic match fallback on that path.

`compute_match` / `structured_feedback` remain for any legacy or manual use but are
not used by POST .../resume-profiles/{id}/analyze.
"""

from __future__ import annotations

import re
from typing import Any

from ai_interview_analysis.services import gemini_client


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


def keyword_tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9+#.]+", text.lower())
    junk = {"the", "and", "or", "a", "an", "to", "with", "of", "in", "for", "yr", "yrs"}
    return set(t for t in tokens if len(t) >= 2 and t not in junk)


SYSTEM_PARSE = """You extract structured resume data. Respond ONLY JSON with schema:
{
  "summary": string,
  "skills": string[],
  "experience": [{
    "company": string,
    "title": string,
    "dates": string|null,
    "bullets": [{"id": string, "text": string}]
  }],
  "projects": [{"name": string, "stack": string[]|[], "bullets": [{"id": string, "text": string}]}],
  "education": [{"school": string, "degree": string|null, "dates": string|null}]
}

Rules:
- Invent stable bullet ids like "exp0b0", "exp0b1", "proj0b0".
- Normalize common skill names (Javascript -> JavaScript).
"""


def parse_resume_structure(extracted_text: str) -> dict[str, Any]:
    payload = extracted_text.strip()[:48000]
    return gemini_client.generate_json(SYSTEM_PARSE, f"Resume text:\n\n{payload}")


SYSTEM_JD = """Extract job-description signals as JSON ONLY:
{"must_have_skills": string[], "nice_to_have_skills": string[], "keywords": string[], "title_guess": string|null}
"""


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

SYSTEM_UNIFIED_ANALYSIS = """You are an expert resume analyzer AI. Your job is to deeply analyze a candidate's \
resume against a provided job description (JD) and return a single, complete JSON \
object with all analysis results.

You will receive:
- A resume (as extracted text or PDF content)
- A job description (as raw text)

════════════════════════════════════════════════════════
SECTION 1 — SCORING METHODOLOGY (MUST FOLLOW EXACTLY)
════════════════════════════════════════════════════════

Compute THREE sub-scores (each 0–100):

1. keyword_coverage (weight: 30%)
   - Extract all meaningful technical terms, tools, skills, and role-specific \
phrases from the JD
   - Check how many of those appear in the resume (exact or near-exact match)
   - Score = (matched JD terms / total JD terms) × 100
   - Ignore filler words: "the", "and", "with", "a", "an", "to", "for", "of"

2. experience_relevance (weight: 40%)
   - Judge how well the candidate's past roles, seniority, and domain match \
what the JD requires
   - Consider: years of experience, industry domain, role titles, \
responsibilities described
   - Score semantically — a "ML Engineer" resume for an "AI Engineer" JD \
should score high even without exact title match
   - If experience section has NO bullet points (only job titles + dates), \
cap this score at 45 out of 100 maximum

3. skills_alignment (weight: 30%)
   - Extract must-have skills and nice-to-have skills from JD separately
   - must_have contributes 70% of this sub-score
   - nice_to_have contributes 30% of this sub-score
   - Score = (matched_must/total_must × 0.7 + matched_nice/total_nice × 0.3) × 100
   - If no nice-to-have skills found, use must-have skills for full score
   - If neither must-have nor nice-to-have skills can be identified, \
set skills_alignment to 50.0 (neutral) — never return 100 by default

Overall Score = (keyword_coverage × 0.30) + (experience_relevance × 0.40) \
                + (skills_alignment × 0.30)

Round all scores to 1 decimal place.
Include the formula string: \
"overall = 30%×keyword_coverage + 40%×experience_relevance + 30%×skills_alignment \
= {overall}% ({kw}×0.3 + {exp}×0.4 + {sk}×0.3)"

════════════════════════════════════════════════════════
SECTION 2 — KEYWORDS ANALYSIS
════════════════════════════════════════════════════════

Identify THREE groups:

matched:
- Keywords/skills/tools present in BOTH the JD and the resume
- Include exact matches and clear equivalents (e.g. "sklearn" = "scikit-learn")
- Return as array of strings

partial:
- Terms that are related but not a direct match
- Example: JD says "Kubernetes" and resume says "container orchestration"
- Example: JD says "data preprocessing" and resume only implies it via project work
- Return as: [{"term": string, "note": "why it's partial"}]

missing:
- JD terms completely absent from resume
- Return AT MOST 5 entries — only the most highly-impactful keywords
  for THIS specific JD. Be ruthless: if a term is mentioned only once
  in the JD or is a nice-to-have, exclude it.
- Selection criteria (most important first):
  1. Listed under Requirements / Must-Have / Qualifications in the JD
  2. Repeated multiple times across the JD body
  3. Core to the role's day-to-day responsibilities
- Do NOT include priority levels (high/medium/low). Every emitted
  keyword is implicitly high-impact because we cap the list at 5.
- Return as: [{"keyword": string, "reason": "one-line explanation \
of why it matters for this JD"}]
- Order from MOST critical → least critical within the top 5.

════════════════════════════════════════════════════════
SECTION 3 — SECTION SCORES
════════════════════════════════════════════════════════

Score EXACTLY these 5 resume sections (in this order):
1. Summary / Objective
2. Work Experience
3. Skills
4. Projects
5. Education

For each section:
- score_1_to_10: integer 1–10
- reason: ONE sentence explaining the score
- improvement: ONE specific, actionable suggestion for this exact role

Scoring rules:
- Summary: penalize if generic, not tailored to JD, or missing entirely (score ≤ 3)
- Work Experience:
  * No bullet points at all → score ≤ 4, improvement MUST say to add achievement \
bullets with metrics and JD-relevant keywords per role
  * Has bullets but no metrics/numbers → score ≤ 6
  * Has bullets with metrics and JD-relevant keywords → score 7–10
- Skills: reward explicit listing of JD-required tools; penalize if skills section \
is just a comma-dump with no context
- Projects: reward quantified outcomes, named datasets, tech stack clarity; \
penalize vague one-liners
- Education: score based on relevance to role; advanced degrees in relevant \
field = higher score

════════════════════════════════════════════════════════
SECTION 4 — BULLET-LEVEL FEEDBACK
════════════════════════════════════════════════════════

Analyze EVERY bullet point from both Experience and Projects sections.

For each bullet assign:
- bullet_id: stable ID you generate (e.g. "exp0b0", "exp0b1", "proj2b0")
- topic: REQUIRED — the human-readable name of the resume item this bullet
  belongs to, so the user immediately knows WHERE in the resume to look.
    * For an Experience bullet: use the role + company, e.g.
      "Software Engineer @ Acme Corp"
    * For a Project bullet: use the project's title, e.g.
      "Brain Tumor Segmentation" or "Voice Agent for Collecting Debts"
    * If the resume groups bullets under a research / education entry,
      use that entry's heading.
    * Never invent a topic name — copy it from the resume.
- original_text: VERBATIM copy of the bullet text from the resume — REQUIRED
- quality: "Weak" | "Acceptable" | "Strong"
- issue_label: short label shown in UI (MUST be unique per bullet)
- why: specific critique referencing the ACTUAL words in original_text (empty if Strong)
- suggested_rewrite: rewritten bullet (empty string if Strong)

════════════════════════════════════
HARD RULES FOR original_text — DO NOT VIOLATE
════════════════════════════════════

1. original_text MUST be a verbatim copy of the resume bullet, character-for-character.
   - Keep all the original wording, punctuation, em-dashes, capitalization, typos.
   - Do NOT paraphrase, summarize, shorten, or "clean up" the bullet.
   - Do NOT translate to a different style.
   - This is the text the user will see highlighted as "what is wrong" in the UI.

2. original_text MUST NEVER be empty for ANY bullet. If you cannot find a matching
   bullet in the resume, do NOT emit that bullet entry at all.

3. why MUST NOT repeat the bullet text. why is the CRITIQUE only — explain in
   your own words what is missing or wrong. Reference specific phrases from
   original_text using single quotes, e.g. why = "Outcome is vague ('get profit'). \
No dataset or RMSE shown."

FORBIDDEN PATTERNS in why (will be rejected):
   ✗ "This bullet describes a general capability..."  (meta-description)
   ✗ "The bullet says X about Y..."                   (re-narration)
   ✗ Restating the original_text in different words

REQUIRED PATTERNS in why:
   ✓ Cite missing items: dataset, metric, tech stack, deployment, scale.
   ✓ Quote the vague phrase from original in single quotes.
   ✓ Connect the gap to a specific JD requirement when possible.

════════════════════════════════════
QUALITY DEFINITIONS WITH EXAMPLES
════════════════════════════════════

── WEAK ──
A bullet is Weak when it is a vague one-liner, reads like a topic
title instead of an achievement, has no action verb, no metric,
no dataset, and no tech stack.

EXAMPLE 1 — Weak:
  original:      'Research on "Brain Tumor segmentation using deep Neural Network."'
  issue_label:   "Weak — no impact metric"
  why:           "Reads as a topic title, not an achievement. No method, no \
outcome, no dataset or accuracy score mentioned."
  suggested_rewrite: "Developed U-Net CNN for brain tumor segmentation achieving \
94% dice coefficient, reducing radiologist annotation time by ~40%."

EXAMPLE 2 — Weak:
  original:      "Lung cancer detection using deep learning."
  issue_label:   "Weak — vague, no tech stack or metrics"
  why:           "Single line with no model name, dataset, accuracy, or business \
impact. Fails JD requirement for demonstrated production experience."
  suggested_rewrite: "Built CNN lung cancer classifier on CT scan data (LIDC-IDRI \
dataset), achieving 91% accuracy; deployed via Flask REST API using TensorFlow."

EXAMPLE 3 — Weak:
  original:      "Smartly predict Stock market prices using LSTM — helps investor \
to get profit by investing money in stock."
  issue_label:   "Weak — no metrics, low JD relevance"
  why:           "Outcome is vague ('get profit'). No dataset, RMSE, or feature \
engineering detail. Doesn't connect to JD requirements."
  suggested_rewrite: "Built LSTM time-series model on Kaggle OHLCV data (5 yrs); \
applied feature engineering (RSI, MACD, Bollinger Bands) achieving RMSE of 2.4%."

── ACCEPTABLE ──
A bullet is Acceptable when it has real context and purpose but is
missing at least one of: quantified metric, tech stack name, dataset
reference, deployment detail, or JD-relevant keyword.

EXAMPLE — Acceptable:
  original:      "AI-Based Blood Glucose Prediction System using LSTM models \
to guide insulin intake."
  issue_label:   "Acceptable — missing deployment + metric"
  why:           "Good context and goal but lacks MAE/RMSE score, dataset size, \
and production deployment detail required by JD."
  suggested_rewrite: "Engineered LSTM blood glucose predictor (30-min horizon) \
via QTinker desktop app; achieved MAE of 8.3 mg/dL on GlucoRx patient \
dataset of 12K records."

── STRONG ──
A bullet is Strong when it has a strong action verb + named tech stack
+ real-world purpose + at least one quantified or clearly scoped outcome.
Strong bullets do NOT need a suggested rewrite.

EXAMPLE — Strong:
  original:      "Voice Agent for Collecting Debts — Real-Time Voice Interaction \
using LiveKit pipeline (SST-LLM-TTS) with Twilio API."
  issue_label:   "Strong — clear scope and tech stack"
  why:           ""
  suggested_rewrite: ""
  reasoning:     "Clear purpose, named tech stack, real-world domain. Qualifies \
as Strong even without a number because the pipeline and \
use case are clearly defined."

════════════════════════════════════
ISSUE LABEL RULES
════════════════════════════════════

1. EVERY issue_label must be UNIQUE across all bullets in the response.
   Never use the same label for two different bullets.

2. The label must describe what is SPECIFICALLY wrong with THAT bullet.
   Pattern: "[Quality] — [specific problem unique to this bullet]"

   Good labels:
   ✓ "Weak — reads as topic title, not achievement"
   ✓ "Weak — no action verb, no dataset, no accuracy"
   ✓ "Weak — outcome is vague, no feature engineering detail"
   ✓ "Weak — no model name or evaluation metric mentioned"
   ✓ "Weak — JD requires production deployment, none shown"
   ✓ "Acceptable — good scope but missing tech stack name"
   ✓ "Acceptable — has context but no measurable outcome"
   ✓ "Acceptable — missing dataset reference and model accuracy"
   ✓ "Acceptable — JD keyword data preprocessing absent"
   ✓ "Acceptable — no deployment or production detail"
   ✓ "Acceptable — missing quantified business impact"
   ✓ "Acceptable — strong use case but no performance metric"
   ✓ "Strong — quantified impact with JD-aligned tech stack"
   ✓ "Strong — clear scope, named pipeline, real-world domain"

   Bad labels (never use):
   ✗ "Acceptable — missing quantified outcome" for EVERY bullet
   ✗ "Review — [project name]"
   ✗ "Weak — needs improvement"
   ✗ Any label you have already used for a previous bullet

════════════════════════════════════
WHY FIELD RULES
════════════════════════════════════

The "why" must reference the ACTUAL content of the specific bullet.
Never write a generic statement that could apply to any bullet.

Bad (rejected):
  "The bullet describes the capability but lacks metrics or the \
degree of proficiency involved."
  ← Could apply to any bullet. Too generic.

Good:
  "Mentions LSTM and stock market prediction but gives no RMSE score, \
dataset name, or time horizon — the JD explicitly requires model \
evaluation metrics experience."
  ← Specific to this bullet AND references the JD gap.

Good:
  "Single line with no model name, dataset, accuracy, or business \
impact. Fails JD requirement for demonstrated production experience."
  ← References both the bullet content AND the JD requirement.

════════════════════════════════════
SUGGESTED REWRITE RULES
════════════════════════════════════

1. First word MUST always be a strong action verb:
   Developed / Built / Engineered / Designed / Implemented /
   Deployed / Trained / Optimized / Automated / Architected

2. Must include ALL of these where possible:
   - Named tech stack (TensorFlow, U-Net CNN, LSTM, Flask, etc.)
   - Quantified metric (accuracy %, MAE, RMSE, latency, records, etc.)
   - Dataset reference if known or inferable (Kaggle, internal, etc.)
   - At least one JD keyword embedded naturally

3. Only append "(estimated)" when you are genuinely estimating a
   number the candidate never implied anywhere. Do NOT add
   "(estimated)" to every single rewrite.

4. Vary sentence structure — never use the same template twice:
   ✓ Lead with scale:   "Processed 50K+ patient records using..."
   ✓ Lead with outcome: "Reduced API latency by 38% by implementing..."
   ✓ Lead with tool:    "Engineered U-Net CNN model achieving..."
   ✓ Lead with impact:  "Automated debt collection calls for 500+ \
accounts using LiveKit pipeline..."

5. Never invent achievements the candidate did not imply anywhere
   in their resume text.

════════════════════════════════════
QUALITY DISTRIBUTION RULE
════════════════════════════════════

After scoring all bullets, verify your distribution:

  Weak:       20–40% of total bullets
  Acceptable: 40–60% of total bullets
  Strong:     10–30% of total bullets

If ALL bullets are the same quality → re-evaluate every bullet.
If ZERO bullets are Strong → re-evaluate; a bullet with a clearly
  named tech stack + real-world use case qualifies as Strong
  even without a number.
If MORE THAN 60% are Weak → re-evaluate; you are being too harsh.
If MORE THAN 70% are Acceptable → re-evaluate; some should be
  Weak (vague one-liners) and some should be Strong (clear scope).

════════════════════════════════════════════════════════
SECTION 5 — ATS FORMATTING CHECK
════════════════════════════════════════════════════════

Check and return status for each of these 5 keys:

1. key: "headings"
   label: "Standard section headings used"
   Pass if: resume uses standard names (Experience, Education, Skills, Projects)
   Fail if: uses creative names that ATS may not recognize
   Warning if: some standard, some non-standard

2. key: "tables"
   label: "No tables or columns detected"
   Pass if: resume appears to be single-column plain text
   Warning if: multi-column layout suspected (skills in two columns, etc.)
   Fail if: table structure detected

3. key: "font"
   label: "Machine-readable font"
   Pass if: no evidence of image-based or decorative font
   Warning if: cannot confirm from text extraction

4. key: "special_chars"
   label: "Special characters detected"
   Pass if: no pipes, em-dashes, smart quotes, or unusual symbols
   Warning if: pipes (|) used as separators in contact line or skills
   Fail if: heavy use of symbols that break ATS parsing
   detail: list exactly which characters and where they appear

5. key: "extractable"
   label: "Text extractable (not image-based)"
   Pass if: text was provided (implies extractable)
   Warning if: content seems incomplete (may be partial extraction)

Overall ATS status:
- "pass"    if all checks are pass
- "warning" if any check is warning and none are fail
- "fail"    if any check is fail

════════════════════════════════════════════════════════
SECTION 6 — SMART INSIGHTS  (STRICT RULES — NO EXCEPTIONS)
════════════════════════════════════════════════════════

Provide GENUINELY NEW insights — do NOT repeat keywords or section scores.

────────────────────────────────────────────────────────
role_fit_titles  (2–3 items, REAL job titles only)
────────────────────────────────────────────────────────
HARD RULES:

1. Each title MUST be a real, searchable job title that exists on
   LinkedIn / Indeed / job boards. Apply this self-test before emitting:
   "Can a candidate paste this exact title into a LinkedIn job search
    and find live postings?" If the answer is NO, replace it.

2. Titles MUST be grounded in the resume's ACTUAL content, not just
   the JD's wording. Look at the candidate's projects, technologies,
   and demonstrated work — pick titles that match what they have built.

3. NEVER suggest "Researcher" or "Scientist" titles unless the resume
   explicitly lists published papers, conference talks, or citations.
   A "research" line item or thesis is NOT enough — production
   research roles require publication evidence.

4. NEVER invent titles like "AI/ML Model Deployment Specialist" or
   "Cognitive Solutions Architect" — these read as buzzwords and
   no recruiter searches for them. Stick to canonical titles
   (Machine Learning Engineer, Computer Vision Engineer, MLOps
   Engineer, NLP Engineer, Data Scientist, AI Application Developer,
   Backend Engineer (ML), etc.) — narrowed by domain when the resume
   supports it.

GOOD examples (for an ML candidate with CV/NLP/LLM projects):
  ✓ "Mid-level Machine Learning Engineer"
  ✓ "Computer Vision / Deep Learning Engineer"
  ✓ "AI Application Developer (LLMs + NLP)"
BAD examples:
  ✗ "AI/ML Model Deployment Specialist"   (made-up title)
  ✗ "Deep Learning Researcher"            (no publications in resume)
  ✗ "Engineer"                            (too generic)

────────────────────────────────────────────────────────
skills_to_learn_next  (up to 5 items, REAL skills only)
────────────────────────────────────────────────────────
HARD RULES:

1. Use EXACT JD keyword terms — do NOT paraphrase. If the JD says
   "Data Preprocessing", use "Data Preprocessing"; do not turn it
   into "Data Cleaning Techniques".

2. Before emitting any skill, VERIFY it is NOT already present in
   the resume (Skills section, Projects, or Experience bullets).
   If the skill IS present (even in a "(Basics)" form), SKIP it
   and pick the next gap.

3. Each entry must be a concrete, learnable, searchable skill —
   a tool, technique, framework, or named methodology. NEVER
   generic process descriptions or soft responsibilities:
   ✗ "Collaborative Development (Git/Agile)"   (and Git is in resume)
   ✗ "Technical Documentation"                 (soft skill, not technical)
   ✗ "Data Cleaning Techniques"                (paraphrase of JD term)
   ✗ "Advanced Cloud Deployment (AWS/GCP/Azure)" (too vague + AWS in resume)

4. Prefer specific tool/framework names over umbrella terms:
   ✓ "MLflow"  rather than "Experiment Tracking"
   ✓ "TorchServe" / "TF Serving" / "SageMaker" rather than "Model Serving"
   ✓ "Hyperparameter Tuning (Optuna / Ray Tune)" rather than "Tuning"

5. Order by impact on THIS specific JD (most critical first).

GOOD examples (for the gap between an ML candidate and an MLE JD):
  ✓ "Data Preprocessing (scikit-learn pipelines, missing-value handling)"
  ✓ "Model Evaluation Metrics (F1, ROC-AUC, confusion matrix)"
  ✓ "Algorithm Selection & Hyperparameter Tuning"
  ✓ "Production ML Systems (model serving, monitoring, retraining)"
  ✓ "MLflow or Weights & Biases (experiment tracking)"

────────────────────────────────────────────────────────
strategic_tip  (1 sentence, must be NEW)
────────────────────────────────────────────────────────
HARD RULES:

1. Must be COMPLETELY DIFFERENT from anything already said in any
   section_scores[].improvement field. Before writing the tip,
   review every improvement you have already produced; if your
   tip overlaps with any of them, find a different angle.

2. Must reference a specific resume artifact AND a specific JD
   requirement, in one tight sentence.

3. NOT generic ("tailor your resume", "add metrics") — the tip
   must address a gap that NO other section has flagged.

Example: "Your Experience section lists 3 companies with zero bullets — \
adding 2–3 quantified achievement bullets per role could raise your \
match score by ~15–20 points for this JD"

════════════════════════════════════════════════════════
SECTION 7 — COACH SUMMARY
════════════════════════════════════════════════════════

Write a 3–5 sentence coach overview:
- Start with the overall match score and what it means
- Identify the single biggest strength in the resume for this JD
- Identify the single most critical gap
- End with one encouraging, specific next step
- Do NOT repeat verbatim sentences from any other section
- Write in second person ("Your resume...", "You have...")

════════════════════════════════════════════════════════
STRICT OUTPUT RULES
════════════════════════════════════════════════════════

1.  Return ONLY a single JSON object — no markdown, no backticks, \
    no preamble, no explanation outside JSON
2.  Every score must have a reason — never a number without explanation
3.  Every weakness must have a fix — never flag a problem without a solution
4.  Do not repeat the same sentence across multiple sections
5.  If a resume section is completely missing, score it 1–2 and note \
    it as absent in reason
6.  suggested_rewrite must use a strong action verb as the FIRST word
7.  keywords.missing must contain AT MOST 5 items — ordered most-critical first; never include a "priority" field
8.  strategic_tip must reference specific resume content — not generic advice
9.  All numeric scores are rounded to 1 decimal place
10. If you cannot determine something confidently, say so in the \
    relevant "detail" or "reason" field — never hallucinate facts
11. issue_label must be unique for every bullet — never reuse the \
    same label across two bullets
12. why field must reference the actual content of that specific \
    bullet — never write a generic statement
13. Do not append "(estimated)" to every rewrite — only when \
    genuinely estimating a number the candidate never implied
14. skills_alignment must never return 100 by default — if JD skills \
    cannot be identified, return 50.0 as neutral fallback

════════════════════════════════════════════════════════
EXACT JSON SCHEMA TO RETURN
════════════════════════════════════════════════════════

{
  "match_result": {
    "overall_score": number,
    "formula": "string — full formula with substituted values",
    "dimensions": {
      "keyword_coverage":      { "score": number, "weight": 0.30 },
      "experience_relevance":  { "score": number, "weight": 0.40 },
      "skills_alignment":      { "score": number, "weight": 0.30 }
    }
  },

  "keywords": {
    "matched": ["string"],
    "partial": [
      { "term": "string", "note": "string" }
    ],
    "missing": [
      { "keyword": "string", "reason": "one-line: why this matters for THIS JD" }
    ]
    /* keywords.missing: max 5 entries, ordered most-critical first; no priority field */
  },

  "section_scores": [
    {
      "name": "Summary / Objective"|"Work Experience"|"Skills"|"Projects"|"Education",
      "score_1_to_10": number,
      "reason": "string",
      "improvement": "string"
    }
  ],

  "bullets": [
    {
      "bullet_id": "string",
      "topic": "REQUIRED: name of the resume item — project title or 'Role @ Company' — copied verbatim from the resume",
      "original_text": "REQUIRED: verbatim resume bullet text — never empty",
      "quality": "Weak"|"Acceptable"|"Strong",
      "issue_label": "string — unique per bullet, e.g. 'Weak — no metrics, low JD relevance'",
      "why": "REQUIRED for Weak/Acceptable: specific critique citing missing items; quote vague phrases from original_text in single quotes; never empty for Weak; empty string only for Strong",
      "suggested_rewrite": "concrete rewrite with named tech stack + dataset + metric; empty string for Strong"
    }
  ],

  "ats": {
    "overall": "pass"|"warning"|"fail",
    "checks": [
      {
        "key": "string",
        "label": "string",
        "status": "pass"|"fail"|"warning",
        "detail": "string|null"
      }
    ]
  },

  "smart_insights": {
    "role_fit_titles": ["string"],
    "skills_to_learn_next": ["string"],
    "strategic_tip": "string"
  },

  "coach_summary": "string"
}
"""


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
    return _map_unified_to_legacy_shapes(blob, profile)


SYSTEM_FULL_ANALYSIS = """You are an expert resume analyzer AI. Analyze the candidate's resume against the job description.

Return ONE JSON object ONLY (no markdown). Use this exact schema:

{
  "overall_score_explanation": "string — 2–4 sentences: state the same overall % as match_bundle.match_percent and explain how the three dimension percentages (keyword_coverage, experience_relevance, skills_alignment) combine using weights 30% / 40% / 30%. Do not invent a different overall %.",
  "keywords": {
    "matched": ["string", "..."],
    "partial": [{"term": "string", "note": "string"}],
    "missing": [{"keyword": "string", "reason": "one line"}]   /* max 5 entries, ordered most-critical first */
  },
  "sections": [
    {
      "name": "Summary / Objective" | "Work Experience" | "Skills" | "Projects" | "Education",
      "score_1_to_10": number,
      "reason": "one line",
      "improvement": "one specific suggestion"
    }
  ],
  "bullets": [
    {
      "path": "bullet id from resume JSON (e.g. exp0b0)",
      "quality": "Weak" | "Acceptable" | "Strong",
      "issue": "short label e.g. Weak — no impact metric",
      "why": "specific explanation; empty string if Strong",
      "suggested_rewrite": "rewritten bullet with strong verb + metrics; use '(estimated)' if you infer numbers; empty if Strong"
    }
  ],
  "ats": {
    "overall": "pass" | "warning" | "fail",
    "checks": [
      {"key": "headings", "label": "Standard section headings used", "status": "pass"|"fail"|"warning", "detail": "string or null"},
      {"key": "tables", "label": "No tables or columns detected", "status": "pass"|"fail"|"warning", "detail": "string or null"},
      {"key": "font", "label": "Machine-readable font", "status": "pass"|"fail"|"warning", "detail": "string or null"},
      {"key": "special_chars", "label": "Special characters", "status": "pass"|"fail"|"warning", "detail": "list problematic chars/locations or null"},
      {"key": "extractable", "label": "Text extractable (not image-based)", "status": "pass"|"fail"|"warning", "detail": "string or null"}
    ]
  },
  "smart_insights": {
    "role_fit_titles": ["2–3 job titles this resume fits NOW"],
    "skills_to_learn_next": ["up to 5 skills from JD gap"],
    "strategic_tip": "one high-value tip for THIS role only"
  },
  "summary": "coach overview; must NOT repeat verbatim text from other fields"
}

RULES:
1. Do not repeat the same sentence in two sections.
2. Every score needs a reason; every weakness needs a fix in improvement or suggested_rewrite.
3. Cover exactly 5 sections in order: Summary / Objective, Work Experience, Skills, Projects, Education (infer scores from content; if a section is empty, score low and explain).
4. For bullets: include every experience/project bullet from the resume JSON (same path ids). Mark Strong only when clearly quantified and JD-aligned.
5. keywords.missing must align with JD and be capped at 5 most-impactful entries, ordered most-critical first; never include a "priority" field.
6. Use match_bundle only for overall % alignment and baseline gaps — expand with your own analysis; you may add matched terms not listed in match_bundle but present in both texts.
"""


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


SYSTEM_REWRITE = """Rewrite resume bullet WITHOUT inventing achievements or metrics user did not imply.
Respond JSON only: {"revised_text": string, "rationale": string}
"""


def rewrite_bullet(existing: str, extra_instruction: str | None = None) -> dict[str, str]:
    hints = existing.strip()[:6000]
    user = (
        "Bullet:\n"
        + hints
        + ("\n\nExtra instruction: " + extra_instruction if extra_instruction else "")
    )
    return gemini_client.generate_json(SYSTEM_REWRITE, user, temperature=0.35)

"""Load packaged UTF-8 prompt files for Mock Interview and Resume Analyzer."""

from __future__ import annotations

from importlib import resources

_PKG_MOCK = "ai_interview_analysis.prompts.mock_interview"
_PKG_RESUME = "ai_interview_analysis.prompts.resume"

_MOCK_PROMPT_FILES: dict[str, str] = {
    "SYSTEM_OUTLINE": "outline.txt",
    "SYSTEM_OPEN_Q": "open_q.txt",
    "SYSTEM_EVALUATE": "evaluate.txt",
    "SYSTEM_FOLLOW": "follow.txt",
    "SYSTEM_NEXT_TOPIC": "next_topic.txt",
    "SYSTEM_CLOSE": "close.txt",
    "SYSTEM_REPORT": "report.txt",
    "SYSTEM_POST_LIVE_METRICS": "post_live_metrics.txt",
    "SYSTEM_CONFIRM_CONTINUE": "confirm_continue.txt",
}

_RESUME_PROMPT_FILES: dict[str, str] = {
    "SYSTEM_PARSE": "parse.txt",
    "SYSTEM_JD": "jd.txt",
    "SYSTEM_UNIFIED_ANALYSIS": "unified_analysis.txt",
    "SYSTEM_FULL_ANALYSIS": "full_analysis.txt",
    "SYSTEM_REWRITE": "rewrite.txt",
    "SYSTEM_DOMAIN_ALIGNMENT": "domain_alignment.txt",
}


def load_mock_interview_system_prompts() -> dict[str, str]:
    """Load all Mock Interview prompts; raise if any file is missing."""
    root = resources.files(_PKG_MOCK)
    out: dict[str, str] = {}
    for key, filename in _MOCK_PROMPT_FILES.items():
        path = root / filename
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Mock interview prompt missing: {_PKG_MOCK}/{filename}") from exc
        out[key] = raw.strip()
    return out


def load_resume_system_prompts() -> dict[str, str]:
    """Load all Resume Analyzer prompts; raise if any file is missing."""
    root = resources.files(_PKG_RESUME)
    out: dict[str, str] = {}
    for key, filename in _RESUME_PROMPT_FILES.items():
        path = root / filename
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Resume analyzer prompt missing: {_PKG_RESUME}/{filename}") from exc
        out[key] = raw.strip()
    return out

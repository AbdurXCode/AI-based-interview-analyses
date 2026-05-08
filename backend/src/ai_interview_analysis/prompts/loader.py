"""Load mock-interview system prompts from UTF-8 package data (once at import)."""

from __future__ import annotations

from importlib import resources

_PACKAGE = "ai_interview_analysis.prompts"

_PROMPT_FILES: dict[str, str] = {
    "SYSTEM_OUTLINE": "outline.txt",
    "SYSTEM_OPEN_Q": "open_q.txt",
    "SYSTEM_EVALUATE": "evaluate.txt",
    "SYSTEM_FOLLOW": "follow.txt",
    "SYSTEM_NEXT_TOPIC": "next_topic.txt",
    "SYSTEM_CLOSE": "close.txt",
    "SYSTEM_REPORT": "report.txt",
    "SYSTEM_POST_LIVE_METRICS": "post_live_metrics.txt",
}


def load_mock_interview_system_prompts() -> dict[str, str]:
    """Load all system prompts; raise if any file is missing."""
    root = resources.files(_PACKAGE)
    out: dict[str, str] = {}
    for key, filename in _PROMPT_FILES.items():
        path = root / filename
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Mock interview prompt file missing: {_PACKAGE}/{filename}",
            ) from exc
        out[key] = raw.strip()
    return out

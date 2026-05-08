"""Mock-interview user input: policy screen for abuse, jailbreaks, and off-topic asks."""

from __future__ import annotations

import re
from typing import Final

# Word-boundary profanity (lowercase tokens). Keep compact; extend as needed.
_PROFANITY: Final[set[str]] = {
    "fuck",
    "fucking",
    "shit",
    "bitch",
    "bastard",
    "cunt",
    "dick",
    "cock",
    "pussy",
    "whore",
    "slut",
    "nigger",
    "nigga",
    "fag",
    "retard",
}

# NOTE: Candidates legitimately describe API keys / secrets in ML interview answers —
# matching those phrases here caused false positives. Off-topic / manipulation is handled
# by the evaluator prompts instead of keyword triggers for those topics.
_INJECTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bignore (all )?(prior|previous|above) (instructions|rules|prompts)\b", re.I),
    re.compile(r"\b(system prompt|developer message|you are now)\b", re.I),
    re.compile(r"\b(delete|drop|truncate|wipe) (the |all )?(database|db|tables)\b", re.I),
    re.compile(r"\bdrop table\b", re.I),
    re.compile(r"\b(change|modify|edit|overwrite) (the |my )?(code|source|repo|repository)\b", re.I),
    re.compile(r"\b(rm\s+-rf|format c:|sudo rm)\b", re.I),
    re.compile(r"\bbypass safet(y|ies)\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\b(disable|turn off) (filters?|guardrails?|moderation)\b", re.I),
    re.compile(r"\bshow (me )?(your )?(prompt|instructions|rules)\b", re.I),
)

# Romantic / personal boundary violations (not exhaustive).
_HARASSMENT_OR_INAPPROPRIATE: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"\b(i want to|let me) (kiss|hug) you\b", re.I), "inappropriate"),
    (re.compile(r"\bkiss (you|me)\b", re.I), "inappropriate"),
    (re.compile(r"\bhug (you|me)\b", re.I), "inappropriate"),
    (re.compile(r"\b(how )?do you feel (when |)(i |)(kiss|hug)\b", re.I), "inappropriate"),
    (re.compile(r"\b(sext(ing)?|nudes?|send nudes)\b", re.I), "inappropriate"),
)

def screen_user_answer(text: str) -> tuple[bool, str | None]:
    """
    Returns (allowed, refusal_template_or_none).

    When not allowed, the second element is a short reason code for logging; the API layer
    maps this to a candidate-facing message (see orchestration).
    """
    raw = (text or "").strip()
    if not raw:
        return True, None

    lower = raw.lower()
    # Profanity: tokenize loosely on non-letters
    tokens = re.findall(r"[a-z]+", lower)
    if any(t in _PROFANITY for t in tokens):
        return False, "profanity"

    for pat in _INJECTION_PATTERNS:
        if pat.search(raw):
            return False, "policy_injection"

    for pat, reason in _HARASSMENT_OR_INAPPROPRIATE:
        if pat.search(raw):
            return False, reason

    # Off-topic / consumer-chatter screening is delegated to Gemini evaluation prompts so
    # legitimate technical answers mentioning products, startups, purchases, etc. are not brittle-blocked here.

    return True, None


def refusal_assistant_message(
    reason: str,
    last_question_excerpt: str,
) -> str:
    """Standard reply when candidate message is out of scope."""
    q = (last_question_excerpt or "").strip()
    if len(q) > 280:
        q = q[:277] + "…"

    base = (
        "I'm only able to help with this mock interview about your background and the role — "
        "not with unrelated topics or system requests."
    )
    if reason == "profanity":
        base = (
            "Please keep the conversation professional and free of abusive language so we can "
            "continue your mock interview."
        )
    elif reason == "policy_injection":
        base = (
            "I can't change code, access databases, or override system behavior. "
            "Let's stay with the interview questions."
        )
    elif reason == "off_topic":
        base = (
            "That topic isn't part of this interview. Let's stay focused on your experience and the role."
        )
    elif reason == "inappropriate":
        base = (
            "Let's keep our conversation professional and appropriate for a job interview."
        )

    if q:
        return f"{base} Here was my question: {q}"
    return base

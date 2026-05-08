"""Gemini helpers: JSON generation and embeddings.

Retry strategy (using tenacity):
  - 429 / 503 / 504 / RESOURCE_EXHAUSTED  →  retry up to 3 times
  - Waits: 12s between attempts
  - Per-call hard timeout: 150 s for JSON (long structured output up to
    8192 tokens), 30 s for embeddings. The previous 28 s ceiling caused
    every long resume-analysis call to die with DeadlineExceeded before
    `gemini-2.0-flash` could finish generating.
"""

import json
import re
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from ai_interview_analysis.core.settings import get_settings


def _ensure_configured() -> None:
    """Require developer API key (used for embeddings and legacy JSON/text paths)."""
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set — add it to backend/.env. "
            "(Vertex ADK JSON/text does not require this key, but embeddings still do.)"
        )
    import google.generativeai as genai
    genai.configure(api_key=s.gemini_api_key)


# ── error classification ──────────────────────────────────────────────────────

def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc)
    return any(kw in msg for kw in (
        "429", "RESOURCE_EXHAUSTED", "Resource exhausted",   # rate limit
        "503", "Service Unavailable", "overloaded",           # congestion
        "504", "deadline exceeded", "DeadlineExceeded",       # timeout
    ))


def _friendly_error(exc: BaseException) -> str:
    msg = str(exc)
    if any(kw in msg for kw in ("429", "RESOURCE_EXHAUSTED", "Resource exhausted")):
        return (
            "Gemini API rate limit hit (429 — Too Many Requests). "
            "The free tier allows only 15 requests/minute. "
            "Please wait about 60 seconds and try again. "
            "You can also upgrade at https://aistudio.google.com/app/apikey"
        )
    if "503" in msg or "Service Unavailable" in msg or "overloaded" in msg.lower():
        return (
            "Gemini API is temporarily overloaded (503 — Service Unavailable). "
            "This is common on the free tier. Please try again in a few seconds."
        )
    if "504" in msg or "deadline exceeded" in msg.lower() or "DeadlineExceeded" in msg:
        return (
            "Gemini API timed out (504 — Gateway Timeout). "
            "The model took too long to respond. Please try again."
        )
    if "API_KEY" in msg or "API key" in msg or "INVALID_ARGUMENT" in msg:
        return f"Gemini API key error — check GEMINI_API_KEY in backend/.env: {msg[:200]}"
    return f"Gemini API error: {msg[:300]}"


# ── retry decorator ───────────────────────────────────────────────────────────

def _make_retry(attempts: int = 3, wait_seconds: int = 12):
    """tenacity decorator: retry on rate-limit / server errors."""
    def decorator(fn):
        return retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(attempts),
            wait=wait_fixed(wait_seconds),
            reraise=True,
        )(fn)
    return decorator


# ── request helpers ───────────────────────────────────────────────────────────

def _call_generate(model: Any, prompt: str, *, timeout: int = 150) -> Any:
    """Single generate_content call with hard timeout, wrapped for tenacity.

    `timeout` is the per-attempt deadline (seconds) passed to the gRPC client.
    Default 150 s accommodates large JSON completions (up to 8192 tokens)
    that gemini-2.0-flash needs ~60–120 s to produce.
    """
    @_make_retry(attempts=3, wait_seconds=12)
    def _inner():
        try:
            return model.generate_content(
                prompt,
                request_options={"timeout": timeout},
            )
        except Exception as exc:
            if _is_retryable(exc):
                raise   # let tenacity retry it
            raise RuntimeError(_friendly_error(exc)) from exc
    try:
        return _inner()
    except Exception as exc:
        # After all retries exhausted — convert to RuntimeError
        raise RuntimeError(_friendly_error(exc)) from exc


def _call_embed(model_name: str, content: str) -> list[float]:
    """Single embed_content call with retry."""
    import google.generativeai as genai

    @_make_retry(attempts=3, wait_seconds=12)
    def _inner():
        try:
            r = genai.embed_content(
                model=model_name,
                content=content,
                request_options={"timeout": 20},
            )
            emb = getattr(r, "embedding", None) or (r["embedding"] if isinstance(r, dict) else None)
            if emb is None:
                raise RuntimeError("Embedding missing in Gemini response")
            return list(emb)
        except RuntimeError:
            raise
        except Exception as exc:
            if _is_retryable(exc):
                raise
            raise RuntimeError(_friendly_error(exc)) from exc
    try:
        return _inner()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(_friendly_error(exc)) from exc


# ── public API ────────────────────────────────────────────────────────────────

def _friendly_adk_error(exc: BaseException) -> str:
    msg = str(exc)
    if len(msg) > 400:
        msg = msg[:400] + "…"
    return (
        "Vertex AI ADK error — ensure GCP_PROJECT_ID, VERTEX_AI_LOCATION, "
        "and Application Default Credentials (or a service account), and that "
        "Vertex AI is enabled. Detail: "
        + msg
    )


def generate_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    top_p: float | None = 0.92,
    top_k: int | None = 40,
    max_output_tokens: int | None = 8192,
) -> dict[str, Any]:
    """JSON-mode Gemini call with explicit sampling parameters.

    When ``GCP_PROJECT_ID`` and ``VERTEX_AI_LOCATION`` are set, uses the Agent
    Development Kit (``AdkApp`` + ``google.adk.agents.Agent``) on Vertex AI.
    Otherwise uses the Gemini API with ``GEMINI_API_KEY`` (``google.generativeai``).

    - **temperature** (typ. 0.15–0.35 for structured JSON): lower = more stable scores
      and phrasing; higher = more variation.
    - **top_p** (typ. 0.9–0.95): nucleus sampling — limits probability mass of tail tokens.
    - **top_k** (typ. 20–64): restricts candidate tokens per step; helps keep JSON valid.
    - **max_output_tokens**: hard cap on completion length for long analyses.

    Pass ``None`` for ``top_p``, ``top_k``, or ``max_output_tokens`` to omit that field
    from ``GenerationConfig`` (SDK default applies).
    """
    from ai_interview_analysis.services.vertex_adk_json import (
        generate_json_via_vertex_adk,
        vertex_adk_configured,
    )

    if vertex_adk_configured():
        try:
            return generate_json_via_vertex_adk(
                system,
                user,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_output_tokens=max_output_tokens,
            )
        except Exception as exc:
            raise RuntimeError(_friendly_adk_error(exc)) from exc

    _ensure_configured()
    import google.generativeai as genai

    s = get_settings()
    gc_kwargs: dict[str, Any] = {
        "temperature": temperature,
        "response_mime_type": "application/json",
    }
    if top_p is not None:
        gc_kwargs["top_p"] = top_p
    if top_k is not None:
        gc_kwargs["top_k"] = top_k
    if max_output_tokens is not None:
        gc_kwargs["max_output_tokens"] = max_output_tokens

    model = genai.GenerativeModel(
        s.gemini_model,
        system_instruction=system,
        generation_config=genai.types.GenerationConfig(**gc_kwargs),
    )
    resp = _call_generate(model, user)

    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError(
            "Gemini returned an empty response — the prompt may have been blocked by safety filters."
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"Gemini returned non-JSON text: {text[:300]}")


def generate_text(system: str, user: str, temperature: float = 0.4) -> str:
    from ai_interview_analysis.services.vertex_adk_json import vertex_adk_configured

    if vertex_adk_configured():
        from ai_interview_analysis.services.vertex_adk_json import generate_text_via_vertex_adk

        try:
            return generate_text_via_vertex_adk(system, user, temperature=temperature)
        except Exception as exc:
            raise RuntimeError(_friendly_adk_error(exc)) from exc

    _ensure_configured()
    import google.generativeai as genai

    s = get_settings()
    model = genai.GenerativeModel(
        s.gemini_model,
        system_instruction=system,
        generation_config=genai.types.GenerationConfig(temperature=temperature),
    )
    resp = _call_generate(model, user)

    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    return text


def embed_texts(chunks: list[str]) -> list[list[float]]:
    _ensure_configured()
    s = get_settings()
    return [_call_embed(s.embedding_model, chunk) for chunk in chunks]


def cosine_sim(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

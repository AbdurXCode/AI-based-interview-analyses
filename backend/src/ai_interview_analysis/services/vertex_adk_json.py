"""JSON generation via Vertex AI Agent Development Kit (AdkApp + ADK Agent).

Uses ``google.adk.agents.Agent`` and ``vertexai.agent_engines.AdkApp`` as described in:
https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent

Requires Application Default Credentials (or service account) and:
``GCP_PROJECT_ID`` + ``VERTEX_AI_LOCATION``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import warnings
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from ai_interview_analysis.core.settings import get_settings

logger = logging.getLogger(__name__)

_vertex_init_lock = threading.Lock()
_vertex_initialized = False


def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        kw in msg
        for kw in (
            "429",
            "resource exhausted",
            "503",
            "unavailable",
            "504",
            "deadline",
            "timeout",
        )
    )


def _make_retry():
    def decorator(fn):
        return retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(3),
            wait=wait_fixed(12),
            reraise=True,
        )(fn)

    return decorator


def _ensure_vertex() -> None:
    global _vertex_initialized
    with _vertex_init_lock:
        if _vertex_initialized:
            return
        s = get_settings()
        project = (s.gcp_project_id or "").strip()
        location = (s.vertex_ai_location or "").strip()
        if not project or not location:
            raise RuntimeError(
                "Vertex ADK requires gcp_project_id and vertex_ai_location in settings / .env",
            )
        import vertexai

        vertexai.init(project=project, location=location)
        _vertex_initialized = True
        logger.info("vertex_ai initialized for ADK (project=%s, location=%s)", project, location)


def _events_last_model_text(events: list[dict[str, Any]]) -> str:
    """Collect the latest non-empty model text from ADK stream events."""
    last = ""
    for ev in events:
        if not isinstance(ev, dict):
            continue
        content = ev.get("content")
        if not isinstance(content, dict):
            continue
        role = content.get("role")
        if role == "user":
            continue
        for p in content.get("parts") or []:
            if not isinstance(p, dict):
                continue
            # Skip tool / function payloads — want final natural-language or JSON text
            if p.get("function_call") or p.get("function_response"):
                continue
            t = p.get("text")
            if isinstance(t, str) and t.strip():
                last = t.strip()
    return last


@_make_retry()
def _stream_once(
    *,
    system_instruction: str,
    user_payload: str,
    model_name: str,
    temperature: float,
    top_p: float | None,
    top_k: int | None,
    max_output_tokens: int | None,
    response_mime_type: str | None = "application/json",
) -> str:
    _ensure_vertex()
    from google.adk.agents import Agent
    from google.genai import types
    from vertexai.agent_engines import AdkApp

    cfg_kwargs: dict[str, Any] = {"temperature": temperature}
    if response_mime_type:
        cfg_kwargs["response_mime_type"] = response_mime_type
    if top_p is not None:
        cfg_kwargs["top_p"] = top_p
    if top_k is not None:
        cfg_kwargs["top_k"] = top_k
    if max_output_tokens is not None:
        cfg_kwargs["max_output_tokens"] = max_output_tokens

    generate_content_config = types.GenerateContentConfig(**cfg_kwargs)

    agent = Agent(
        model=model_name,
        name="structured_json_turn",
        instruction=system_instruction,
        generate_content_config=generate_content_config,
    )
    app = AdkApp(agent=agent)
    app.set_up()

    events: list[dict[str, Any]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for event in app.stream_query(
            user_id="mock-interview-json",
            message=user_payload,
        ):
            if isinstance(event, dict):
                events.append(event)

    text = _events_last_model_text(events)
    if not text:
        raise RuntimeError(
            "ADK returned no model text — response may have been blocked or contained only tool calls.",
        )
    return text


def generate_json_via_vertex_adk(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    # top_p: float | None = 0.92,  # (reserved) will re-enable later
    # top_k: int | None = 40,      # (reserved) will re-enable later
    max_output_tokens: int | None = 8192,
) -> dict[str, Any]:
    """Run one-shot ADK agent; parse JSON from the final model message."""
    s = get_settings()
    model_name = (s.gemini_model or "gemini-2.0-flash").strip()

    raw = _stream_once(
        system_instruction=system,
        user_payload=user,
        model_name=model_name,
        temperature=temperature,
        # top_p=top_p,  # (reserved) will re-enable later
        # top_k=top_k,  # (reserved) will re-enable later
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"ADK returned non-JSON text: {raw[:300]}") from None


def vertex_adk_configured() -> bool:
    s = get_settings()
    return bool((s.gcp_project_id or "").strip() and (s.vertex_ai_location or "").strip())


def generate_text_via_vertex_adk(
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    max_output_tokens: int | None = 8192,
) -> str:
    """Plain-text completion via ADK (no JSON MIME type)."""
    s = get_settings()
    model_name = (s.gemini_model or "gemini-2.0-flash").strip()

    return _stream_once(
        system_instruction=system,
        user_payload=user,
        model_name=model_name,
        temperature=temperature,
        # top_p=0.95,  # (reserved) will re-enable later
        # top_k=40,    # (reserved) will re-enable later
        max_output_tokens=max_output_tokens,
        response_mime_type=None,
    )

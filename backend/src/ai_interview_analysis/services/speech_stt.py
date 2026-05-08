"""
Speech → text.

Primary path: Gemini multimodal transcription (GEMINI_API_KEY only).
Alternative: google-cloud-speech for teams using Application Default Credentials.
"""

from ai_interview_analysis.core.settings import get_settings


def transcribe_audio_bytes(audio: bytes, mime_type: str = "audio/wav") -> str:
    settings = get_settings()
    if settings.gemini_api_key:
        return _transcribe_gemini(audio, mime_type)
    return _transcribe_google_speech(audio, mime_type)


def _transcribe_gemini(audio: bytes, mime_type: str) -> str:
    import google.generativeai as genai

    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)
    resp = model.generate_content(
        [
            (
                "Transcribe this audio to plain text only. Preserve meaning. "
                "If silent, reply with empty string."
            ),
            {"mime_type": mime_type, "data": audio},
        ]
    )
    return (resp.text or "").strip()


def _transcribe_google_speech(audio: bytes, mime_type: str) -> str:
    try:
        from google.cloud import speech
    except ImportError as e:
        raise RuntimeError(
            "GEMINI_API_KEY missing and google-cloud-speech not usable; configure GEMINI_API_KEY "
            "for audio answers."
        ) from e

    settings = get_settings()
    client = speech.SpeechClient()

    mime = mime_type.lower()
    encoding = speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED
    rate = None
    if "linear" in mime or "wav" in mime:
        encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
        rate = 16000
    cfg_kwargs: dict = {
        "language_code": settings.speech_language_code,
        "enable_automatic_punctuation": True,
    }
    if encoding != speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED:
        cfg_kwargs["encoding"] = encoding
    if rate:
        cfg_kwargs["sample_rate_hertz"] = rate

    cfg = speech.RecognitionConfig(**cfg_kwargs)
    resp = client.recognize(config=cfg, audio=speech.RecognitionAudio(content=audio))
    return "\n".join(
        alt.transcript for r in resp.results for alt in r.alternatives
    ).strip()

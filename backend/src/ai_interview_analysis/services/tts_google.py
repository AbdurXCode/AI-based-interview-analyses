"""Text-to-speech via Google Cloud Text-to-Speech."""

from ai_interview_analysis.core.settings import get_settings


def synthesize_to_mp3(text: str) -> bytes:
    from google.cloud import texttospeech

    settings = get_settings()
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=settings.tts_language_code,
        name=settings.tts_voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )
    resp = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return resp.audio_content

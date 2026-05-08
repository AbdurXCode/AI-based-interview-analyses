"""Video / vision analysis: gaze, body language, speaking (used when ``feature_video_analysis`` is on).

Submodules import heavy optional deps (OpenCV, Mediapipe, etc.). Use lazy exports so
``import ai_interview_analysis.api.app`` does not load them unless something asks for
``track_gaze_module`` / friends.

HTTP entry: :mod:`ai_interview_analysis.api.routes.interview`.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "body_language_analysis_module",
    "speaking_skills_analysis_module",
    "track_gaze_module",
]


def __getattr__(name: str) -> Any:
    if name == "track_gaze_module":
        from ai_interview_analysis.video.gaze_driver import track_gaze_module as _m

        return _m
    if name == "body_language_analysis_module":
        from ai_interview_analysis.video.body_language_driver import body_language_analysis_module as _m

        return _m
    if name == "speaking_skills_analysis_module":
        from ai_interview_analysis.video.speaking_driver import speaking_skills_analysis_module as _m

        return _m
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*__all__, *globals().keys()])

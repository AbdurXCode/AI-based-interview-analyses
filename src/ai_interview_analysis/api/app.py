from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_interview_analysis.core.config import load_env

load_env()

from ai_interview_analysis.api.routes.interview import router as interview_router
from ai_interview_analysis.api.routes.answer_suggestions import router as answer_router


def create_app() -> FastAPI:
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(interview_router)
    app.include_router(answer_router)

    return app


app = create_app()


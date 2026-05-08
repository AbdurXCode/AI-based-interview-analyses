from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ai_interview_analysis.api.middlewares.request_id import RequestIdMiddleware

from ai_interview_analysis.core.config import load_env
from ai_interview_analysis.core.settings import clear_settings_cache, get_settings

load_env()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        yield
    finally:
        clear_settings_cache()


def create_app() -> FastAPI:
    settings = get_settings()
    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])

    app = FastAPI(title="Interview Prep Platform", version="1.0.0", lifespan=_lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(RequestIdMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    api_v1 = APIRouter(prefix="/api/v1")

    from ai_interview_analysis.api.routes import auth, health, interview_product, privacy, resume_products

    api_v1.include_router(auth.router)
    api_v1.include_router(resume_products.router)
    api_v1.include_router(interview_product.router)
    api_v1.include_router(privacy.router)

    app.include_router(health.router)
    app.include_router(api_v1)

    if settings.use_openai_legacy_answer_suggestions:
        from ai_interview_analysis.api.routes import answer_suggestions

        app.include_router(answer_suggestions.router)

    if settings.feature_video_analysis:
        from ai_interview_analysis.api.routes import interview as video_router

        app.include_router(video_router.router)

    return app


app = create_app()


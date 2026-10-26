from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from starlette.middleware.cors import CORSMiddleware

from app.agent.agent import close_model_client
from app.agent.session import close_session_engine
from app.agent.worker import recover_interrupted_runs, stop_runs
from app.api.main import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_agent_config()
    # The in-process MVP has one executor. Refuse a second instance before recovery
    # can accidentally mark another live instance's turns as interrupted.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as guard:
        if not guard.execute(
            text("SELECT pg_try_advisory_lock(826725104)")
        ).scalar_one():
            raise RuntimeError("Agent MVP supports one backend process per database")
        try:
            await recover_interrupted_runs()
            yield
        finally:
            await stop_runs()
            await close_model_client()
            await close_session_engine()
            await close_redis()
            guard.execute(text("SELECT pg_advisory_unlock(826725104)"))


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    lifespan=lifespan,
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

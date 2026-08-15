from __future__ import annotations

import conclave.winloop  # noqa: F401 — must precede loop creation (psycopg async on Windows)

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from conclave.api import conversations, experts, provider_keys
from conclave.config import settings
from conclave.db.session import init_db
from conclave.services.turn_runner import runner_loop


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await init_db()
    runner_task: asyncio.Task | None = None
    if settings.embed_runner:
        # Dev convenience: one process runs both roles. In prod set
        # CONCLAVE_EMBED_RUNNER=0 and scale `python -m conclave.runner` separately.
        runner_task = asyncio.create_task(runner_loop())
    yield
    if runner_task is not None:
        runner_task.cancel()
        try:
            await runner_task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="Conclave API", version="0.2.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(experts.router, prefix="/api")
    app.include_router(provider_keys.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "conclave", "embedded_runner": settings.embed_runner}

    return app


app = create_app()

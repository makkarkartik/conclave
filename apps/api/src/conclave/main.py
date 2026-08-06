from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from conclave.api import conversations, events, experts
from conclave.db.session import init_db


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Conclave API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(experts.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(events.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "conclave"}

    return app


app = create_app()

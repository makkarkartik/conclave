from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[5]  # Conclave/
DATA_DIR = Path(os.environ.get("CONCLAVE_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "conclave.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from sqlalchemy import inspect, text

    from conclave.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    (DATA_DIR / "conversations").mkdir(parents=True, exist_ok=True)

    # Lightweight SQLite column add for existing DBs (no Alembic yet).
    insp = inspect(engine)
    if "messages" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("messages")}
        if "doc_diff" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages ADD COLUMN doc_diff TEXT DEFAULT ''"))

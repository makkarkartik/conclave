from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from conclave.config import settings

DATA_DIR = Path(settings.data)
DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as db:
        yield db


# Additive columns on tables that already exist. create_all() only creates missing
# tables, never alters existing ones, and there is no Alembic yet — when this list
# outgrows a handful, that is the signal to adopt real migrations.
_ADDITIVE_COLUMNS = (
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS extracted_chars INTEGER DEFAULT 0",
    "ALTER TABLE attachments ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(20) DEFAULT ''",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS web_search BOOLEAN DEFAULT FALSE",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS citations_json TEXT DEFAULT '[]'",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS consult_until_lap INTEGER",
    "ALTER TABLE messages ADD COLUMN IF NOT EXISTS objection_json TEXT DEFAULT ''",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS sealed_start BOOLEAN DEFAULT FALSE",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS floor_queue_json TEXT DEFAULT '[]'",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS plan_phase VARCHAR(20) DEFAULT 'deliberate'",
)


async def init_db() -> None:
    from sqlalchemy import select, text

    from conclave.db import models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for ddl in _ADDITIVE_COLUMNS:
            await conn.execute(text(ddl))
    (DATA_DIR / "conversations").mkdir(parents=True, exist_ok=True)

    async with SessionLocal() as db:
        existing = await db.scalar(
            select(models.Tenant).where(models.Tenant.id == models.DEFAULT_TENANT_ID)
        )
        if existing is None:
            db.add(models.Tenant(id=models.DEFAULT_TENANT_ID, name="default"))
            await db.commit()

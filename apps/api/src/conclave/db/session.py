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


async def init_db() -> None:
    from sqlalchemy import select

    from conclave.db import models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    (DATA_DIR / "conversations").mkdir(parents=True, exist_ok=True)

    async with SessionLocal() as db:
        existing = await db.scalar(
            select(models.Tenant).where(models.Tenant.id == models.DEFAULT_TENANT_ID)
        )
        if existing is None:
            db.add(models.Tenant(id=models.DEFAULT_TENANT_ID, name="default"))
            await db.commit()

"""One-shot: migrate experts from the prototype SQLite DB into Postgres.

Keys are read from data/conclave.db, Fernet-encrypted with CONCLAVE_SECRET_KEY,
and inserted via the app's own models. Nothing secret is printed. Idempotent:
experts whose (name, provider) already exist in Postgres are skipped.

Run from apps/api:  python ../../scripts/migrate_sqlite_experts.py
"""

from __future__ import annotations

import conclave.winloop  # noqa: F401 — selector loop policy for psycopg async on Windows

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy import select

from conclave.config import ROOT
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Expert
from conclave.db.session import SessionLocal, init_db
from conclave.domain.crypto import encrypt_secret
from conclave.domain.mask import mask_key

SQLITE_PATH = Path(ROOT) / "data" / "conclave.db"


async def main() -> None:
    if not SQLITE_PATH.exists():
        print(f"no sqlite db at {SQLITE_PATH}")
        return
    con = sqlite3.connect(SQLITE_PATH)
    rows = con.execute(
        "select name, persona, provider, model, api_key, accent from experts"
    ).fetchall()
    con.close()

    await init_db()
    async with SessionLocal() as db:
        existing = {
            (e.name, e.provider)
            for e in (await db.scalars(select(Expert))).all()
        }
        migrated, skipped = [], []
        for name, persona, provider, model, api_key, accent in rows:
            if (name, provider) in existing:
                skipped.append(name)
                continue
            db.add(
                Expert(
                    id=new_id(),
                    tenant_id=DEFAULT_TENANT_ID,
                    name=name,
                    persona=persona or "",
                    provider=provider,
                    model=model,
                    api_key_encrypted=encrypt_secret(api_key or ""),
                    api_key_hint=mask_key(api_key or ""),
                    accent=accent or "#6BA3FF",
                )
            )
            migrated.append(f"{name} ({provider} · {model})")
        await db.commit()

    print("migrated:", ", ".join(migrated) or "none")
    print("skipped (already present):", ", ".join(skipped) or "none")


if __name__ == "__main__":
    asyncio.run(main())

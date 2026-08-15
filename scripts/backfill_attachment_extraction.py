"""One-shot: record extraction stats for attachments uploaded before the
parse-at-upload change. Prints filenames and sizes only, never content.

Run from apps/api:  python ../../scripts/backfill_attachment_extraction.py
"""

from __future__ import annotations

import conclave.winloop  # noqa: F401

import asyncio

from sqlalchemy import select

from conclave.db.models import Attachment
from conclave.db.session import SessionLocal, init_db
from conclave.domain.files import extract_attachment


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        rows = (
            await db.scalars(select(Attachment).where(Attachment.extraction_method == ""))
        ).all()
        if not rows:
            print("nothing to backfill")
            return
        for a in rows:
            e = await asyncio.to_thread(extract_attachment, a.path)
            a.extracted_chars, a.extraction_method = e.chars, e.method
            print(f"{a.filename}: chars={e.chars} method={e.method}")
        await db.commit()
        print(f"backfilled {len(rows)} attachment(s)")


asyncio.run(main())

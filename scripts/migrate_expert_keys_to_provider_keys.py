"""One-shot: promote per-expert BYOK keys to shared provider keys.

Per (tenant, provider): the most common decrypted key among experts becomes the
shared provider key; experts holding that key lose their private copy (they fall
back to the shared one); experts with a different key keep it as an override.
Idempotent; prints only hints and counts, never key material.

Run from apps/api:  python ../../scripts/migrate_expert_keys_to_provider_keys.py
"""

from __future__ import annotations

import conclave.winloop  # noqa: F401

import asyncio
from collections import Counter, defaultdict

from sqlalchemy import select

from conclave.db.models import Expert
from conclave.db.session import SessionLocal, init_db
from conclave.domain.crypto import decrypt_secret
from conclave.services.keys import get_provider_key, set_provider_key


async def main() -> None:
    await init_db()
    async with SessionLocal() as db:
        experts = (await db.scalars(select(Expert))).all()
        groups: dict[tuple[str, str], list[Expert]] = defaultdict(list)
        for e in experts:
            groups[(e.tenant_id, e.provider)].append(e)

        for (tenant_id, provider), members in groups.items():
            keyed = [e for e in members if e.api_key_encrypted]
            shared = await get_provider_key(db, tenant_id, provider)
            if shared is None:
                if not keyed:
                    print(f"{provider}: no keys anywhere — skipped")
                    continue
                counts = Counter(decrypt_secret(e.api_key_encrypted) for e in keyed)
                chosen, _ = counts.most_common(1)[0]
                shared = await set_provider_key(db, tenant_id, provider, chosen)
            shared_plain = decrypt_secret(shared.key_encrypted)
            cleared = 0
            for e in keyed:
                if decrypt_secret(e.api_key_encrypted) == shared_plain:
                    e.api_key_encrypted = ""
                    e.api_key_hint = ""
                    cleared += 1
            overrides = len(keyed) - cleared
            print(
                f"{provider}: shared key {shared.key_hint} | "
                f"{cleared} expert(s) now use it | {overrides} override(s) kept"
            )
        await db.commit()


asyncio.run(main())

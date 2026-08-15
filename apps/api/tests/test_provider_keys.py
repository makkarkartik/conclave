"""Shared provider keys: first key becomes the tenant key, later experts reuse it,
explicit different keys become overrides, and rotation follows intent.
Runs against the dev Postgres; skips if unreachable."""

from __future__ import annotations

import httpx
import pytest

from conclave.db.models import Expert
from conclave.db.session import SessionLocal, engine, init_db
from conclave.main import app
from conclave.services.keys import resolve_api_key


@pytest.fixture
async def client():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    transport = httpx.ASGITransport(app=app)  # no lifespan: no embedded runner
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


# The "fake" provider is E2E-only, so these tests can never collide with (or
# destroy) a real tenant key the way "openai"/"anthropic" could.
def _expert(name: str, key: str = "", provider: str = "fake") -> dict:
    return {"name": name, "persona": "", "provider": provider, "model": "m1", "api_key": key}


async def _resolved(expert_id: str) -> str:
    async with SessionLocal() as db:
        e = await db.get(Expert, expert_id)
        return await resolve_api_key(db, e)


async def test_shared_key_lifecycle(client):
    created: list[str] = []
    await client.delete("/api/provider-keys/fake")  # clean slate from any failed run
    try:
        # First key for the provider becomes the shared tenant key
        a = (await client.post("/api/experts", json=_expert("PK-A", "sk-first-123456789"))).json()
        created.append(a["id"])
        assert a["key_source"] == "provider"

        # Second expert, no key: reuses the shared one
        b = (await client.post("/api/experts", json=_expert("PK-B"))).json()
        created.append(b["id"])
        assert b["key_source"] == "provider"
        assert await _resolved(b["id"]) == "sk-first-123456789"

        # Third expert with an explicitly different key: private override
        c = (await client.post("/api/experts", json=_expert("PK-C", "sk-other-987654321"))).json()
        created.append(c["id"])
        assert c["key_source"] == "own"

        # Same key pasted again is recognized as reuse, not an override
        d = (await client.post("/api/experts", json=_expert("PK-D", "sk-first-123456789"))).json()
        created.append(d["id"])
        assert d["key_source"] == "provider"

        # No key + no stored provider key = clear 400 (only assertable while the
        # tenant genuinely has no key for that provider)
        stored = {k["provider"] for k in (await client.get("/api/provider-keys")).json()}
        if "google" not in stored:
            r = await client.post("/api/experts", json=_expert("PK-E", provider="google"))
            assert r.status_code == 400

        # Rotation intent: a new key on a shared-key expert rotates the shared key…
        await client.patch(f"/api/experts/{a['id']}", json={"api_key": "sk-rotated-42424242"})
        keys = {k["provider"]: k for k in (await client.get("/api/provider-keys")).json()}
        assert keys["fake"]["key_hint"].endswith("4242")
        assert await _resolved(b["id"]) == "sk-rotated-42424242"
        # …while the override expert is untouched
        assert await _resolved(c["id"]) == "sk-other-987654321"

        # Dropping an override falls back to the shared key
        await client.patch(f"/api/experts/{c['id']}", json={"use_provider_key": True})
        assert await _resolved(c["id"]) == "sk-rotated-42424242"
    finally:
        for eid in created:
            await client.delete(f"/api/experts/{eid}")
        await client.delete("/api/provider-keys/fake")


async def test_provider_keys_listing_counts(client):
    created: list[str] = []
    await client.delete("/api/provider-keys/fake")
    try:
        a = (await client.post("/api/experts", json=_expert("PK-L1", "sk-list-111222333"))).json()
        b = (await client.post("/api/experts", json=_expert("PK-L2"))).json()
        created += [a["id"], b["id"]]
        keys = (await client.get("/api/provider-keys")).json()
        fake = next(k for k in keys if k["provider"] == "fake")
        assert fake["expert_count"] >= 2
        assert fake["key_hint"]
    finally:
        for eid in created:
            await client.delete(f"/api/experts/{eid}")
        await client.delete("/api/provider-keys/fake")

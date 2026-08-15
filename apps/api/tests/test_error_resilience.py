"""A room with a failing provider must not race the lap counter: error turns get
a claim backoff, and persistent errors pause the room instead of burning laps to
the safety ceiling. Runs against the dev Postgres; skips if unreachable."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import conclave.services.turn_runner as turn_runner
from conclave.config import settings
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Conversation, Expert
from conclave.db.session import SessionLocal, engine, init_db


@pytest.fixture
async def db_or_skip():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    yield
    await engine.dispose()


async def _always_fails(**kwargs):
    raise RuntimeError("provider down")


async def _make_room(tag: str) -> tuple[str, list[str]]:
    async with SessionLocal() as db:
        experts = [
            Expert(
                id=new_id(),
                tenant_id=DEFAULT_TENANT_ID,
                name=f"{name} {tag}",
                provider="openai",
                model="fake",
                api_key_encrypted="",
                api_key_hint="",
            )
            for name in ("Err-Ada", "Err-Bo")
        ]
        conv = Conversation(
            id=new_id(),
            tenant_id=DEFAULT_TENANT_ID,
            title=f"err-{tag}",
            topic="error resilience",
            status="running",
        )
        conv.chair_ids = [e.id for e in experts]
        db.add_all([*experts, conv])
        await db.commit()
        return conv.id, [e.id for e in experts]


async def _cleanup(cid: str, expert_ids: list[str]) -> None:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if conv is not None:
            await db.delete(conv)
        for eid in expert_ids:
            e = await db.get(Expert, eid)
            if e is not None:
                await db.delete(e)
        await db.commit()


async def test_persistent_errors_pause_room_instead_of_burning_laps(
    db_or_skip, monkeypatch
):
    monkeypatch.setattr(turn_runner, "run_expert_turn", _always_fails)
    monkeypatch.setattr(settings, "error_backoff_seconds", 0)
    monkeypatch.setattr(settings, "max_consecutive_error_turns", 4)

    cid, eids = await _make_room("pause")
    try:
        for _ in range(10):
            async with SessionLocal() as db:
                claimed = await turn_runner.claim_next(db, "err-worker")
            if claimed is None:
                break
            await turn_runner.run_one_turn(cid, "err-worker")

        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            assert conv.status == "error_pause"
            # 4 error turns over 2 chairs = 2 laps, nowhere near the ceiling of 40
            assert conv.lap <= 2
    finally:
        await _cleanup(cid, eids)


async def test_error_turn_defers_next_claim(db_or_skip, monkeypatch):
    monkeypatch.setattr(turn_runner, "run_expert_turn", _always_fails)
    monkeypatch.setattr(settings, "error_backoff_seconds", 60)
    monkeypatch.setattr(settings, "max_consecutive_error_turns", 99)

    cid, eids = await _make_room("backoff")
    try:
        async with SessionLocal() as db:
            assert await turn_runner.claim_next(db, "err-worker") == cid
        await turn_runner.run_one_turn(cid, "err-worker")

        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            assert conv.status == "running"
            assert conv.claimed_until is not None
            assert conv.claimed_until > datetime.now(timezone.utc)
            # Backoff lease blocks the next claim
            assert await turn_runner.claim_next(db, "err-worker") is None
    finally:
        await _cleanup(cid, eids)

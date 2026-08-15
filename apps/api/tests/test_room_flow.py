"""Integration: a full room runs to convergence through the real claim/lease/lap
machinery against Postgres. The LLM is replaced by a scripted expert; everything
else — claim_next, run_one_turn, idempotent slots, lap folding, convergence — is real.

Requires the dev database (docker compose up -d db); skips if unreachable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import conclave.services.turn_runner as turn_runner
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Conversation, Expert, Message
from conclave.db.session import SessionLocal, engine, init_db
from conclave.domain.schemas import TurnAct
from conclave.runtime.turn import TurnOutcome

PROPOSAL = "# Plan\n\nShip the canary with **two experts**."


@pytest.fixture
async def db_or_skip():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    yield
    await engine.dispose()


async def _scripted_turn(**kwargs) -> TurnOutcome:
    return TurnOutcome(
        act=TurnAct(
            action="write_proposal",
            message="I stress-tested it; the tradeoffs hold.",
            thought="scripted",
            gist=f"{kwargs['name']} endorsed the plan",
            proposal=PROPOSAL,
            agree=True,
        )
    )


async def test_room_converges_via_real_machinery(db_or_skip, monkeypatch):
    monkeypatch.setattr(turn_runner, "run_expert_turn", _scripted_turn)

    async with SessionLocal() as db:
        experts = [
            Expert(
                id=new_id(),
                tenant_id=DEFAULT_TENANT_ID,
                name=name,
                provider="openai",
                model="fake",
                api_key_encrypted="",
                api_key_hint="",
            )
            for name in ("Ada", "Bo")
        ]
        conv = Conversation(
            id=new_id(),
            tenant_id=DEFAULT_TENANT_ID,
            title="itest",
            topic="Ship the canary?",
            status="running",
        )
        conv.chair_ids = [e.id for e in experts]
        db.add_all([*experts, conv])
        await db.commit()
        cid = conv.id

    try:
        worker = "itest-worker"
        for _ in range(20):  # 2 experts x 3 laps = 6 turns; generous bound
            async with SessionLocal() as db:
                claimed = await turn_runner.claim_next(db, worker)
            if claimed is None:
                break
            assert claimed == cid
            await turn_runner.run_one_turn(cid, worker)

        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            msgs = (
                await db.scalars(select(Message).where(Message.conversation_id == cid))
            ).all()

            assert conv.status == "converged"
            assert conv.lap == 3
            assert conv.converged_solution == PROPOSAL
            assert len(msgs) == 6
            # Idempotency: every (lap, chair) slot is unique
            slots = {(m.lap, m.chair_index) for m in msgs}
            assert len(slots) == 6
            # Ledger + summary populated
            assert all(m.gist for m in msgs)
            assert "Lap 0:" in conv.rolling_summary and "Lap 2:" in conv.rolling_summary
            # Lease released
            assert conv.claimed_until is None and conv.claimed_by is None
    finally:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            if conv is not None:
                await db.delete(conv)
            for eid in [e.id for e in experts]:
                exp = await db.get(Expert, eid)
                if exp is not None:
                    await db.delete(exp)
            await db.commit()

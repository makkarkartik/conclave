"""Integration: a sealed-start room drafts blind in parallel, union-seeds the
document, reconciles, and settles — through the real claim/lease machinery.

Requires the dev database (docker compose up -d db); skips if unreachable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import conclave.services.turn_runner as turn_runner
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Conversation, DocOp, Expert, Message
from conclave.db.session import SessionLocal, engine, init_db
from conclave.domain.schemas import PollAct, TurnAct
from conclave.runtime.turn import DraftOutcome, TurnOutcome
from conclave.runtime.providers import model_tier

DRAFTS = {
    "Ada": "## Plan\nAda's approach\n\n## Recall check\nonly Ada thought of this\n",
    "Bo": "## Plan\nBo's approach\n\n## Costs\nBo's numbers\n",
}


@pytest.fixture
async def db_or_skip():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    yield
    await engine.dispose()


async def _sealed_draft(**kwargs) -> DraftOutcome:
    name = kwargs["name"].split(" ")[0]
    return DraftOutcome(text=DRAFTS[name])


async def _quiet_turn(**kwargs) -> TurnOutcome:
    return TurnOutcome(
        act=TurnAct(
            action="speak",
            message="The union covers it; no blocking defect.",
            gist=f"{kwargs['name']} consented",
        )
    )


async def _consenting_poll(**kwargs) -> PollAct:
    return PollAct(stance="consent", note="the union stands")


def test_model_tier_orders_strongest_first():
    seats = ["gpt-5.6-sol", "claude-sonnet-5", "claude-opus-5", "fake"]
    ranked = sorted(seats, key=model_tier)
    assert ranked[0] == "claude-opus-5"
    assert ranked[-1] == "fake"


async def test_sealed_room_drafts_seeds_and_settles(db_or_skip, monkeypatch):
    monkeypatch.setattr(turn_runner, "run_sealed_draft", _sealed_draft)
    monkeypatch.setattr(turn_runner, "run_expert_turn", _quiet_turn)
    monkeypatch.setattr(turn_runner, "run_settlement_poll", _consenting_poll)

    async with SessionLocal() as db:
        experts = [
            Expert(
                id=new_id(),
                tenant_id=DEFAULT_TENANT_ID,
                name=f"{n} sealed",
                provider="fake",
                model="fake",
                api_key_encrypted="",
                api_key_hint="",
            )
            for n in ("Ada", "Bo")
        ]
        conv = Conversation(
            id=new_id(),
            tenant_id=DEFAULT_TENANT_ID,
            title="sealed-itest",
            topic="Union seeding",
            status="drafting",
            sealed_start=True,
        )
        conv.chair_ids = [e.id for e in experts]
        db.add_all([*experts, conv])
        await db.commit()
        cid = conv.id

    try:
        worker = "sealed-worker"
        for _ in range(20):
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
            ops = (
                await db.scalars(select(DocOp).where(DocOp.conversation_id == cid))
            ).all()

            drafts = [m for m in msgs if m.action == "draft"]
            assert len(drafts) == 2  # both seats drafted, lap 0
            assert all(m.lap == 0 for m in drafts)
            assert all("Sealed draft" in m.chips for m in drafts)

            # Union seed: both Plans coexist (collision suffixed), the orphan survives.
            headings = {op.anchor for op in ops}
            assert "Plan" in headings and "Plan (Bo sealed)" in headings
            assert "Recall check" in headings
            assert "only Ada thought of this" in conv.shared_proposal
            assert "Bo's numbers" in conv.shared_proposal

            # Ops trace to their draft messages; blame is per author.
            by_msg = {m.id for m in drafts}
            assert all(op.message_id in by_msg for op in ops)

            # Fast convergence: one parallel all-consent poll at lap 1 settles a
            # sealed room (floor 2) — consent rows fill the lap, no serial turns.
            consents = [m for m in msgs if m.action == "consent"]
            assert len(consents) == 2 and all(m.lap == 1 for m in consents)
            assert conv.status == "converged"
            assert conv.lap == 2
            assert conv.converged_solution == conv.shared_proposal
    finally:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            if conv is not None:
                await db.delete(conv)
            for e in experts:
                row = await db.get(Expert, e.id)
                if row is not None:
                    await db.delete(row)
            await db.commit()

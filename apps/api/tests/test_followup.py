"""A converged room must carry forward: the chair can ask a follow-up, the
experts answer for one lap, and the solution survives untouched — or the chair
can reopen deliberation and make convergence be earned again."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import conclave.services.turn_runner as turn_runner
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Conversation, Expert, Message
from conclave.db.session import SessionLocal, engine, init_db
from conclave.domain.schemas import Objection, TurnAct
from conclave.runtime.turn import TurnOutcome

SOLUTION = "# Agreed plan\n\nShip the canary."


@pytest.fixture
async def db_or_skip():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    yield
    await engine.dispose()


async def _answering_turn(**kwargs) -> TurnOutcome:
    """An expert consulted after convergence answers rather than re-proposing."""
    assert kwargs["consulting"] is True
    return TurnOutcome(
        act=TurnAct(
            action="speak",
            message="The plan already covers that: see the rollout section.",
            gist=f"{kwargs['name']} answered the chair's follow-up",
        )
    )


async def _converged_room(tag: str) -> tuple[str, list[str]]:
    async with SessionLocal() as db:
        experts = [
            Expert(
                id=new_id(),
                tenant_id=DEFAULT_TENANT_ID,
                name=f"{n} {tag}",
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
            title=f"followup-{tag}",
            topic="carry forward",
            status="converged",
            shared_proposal=SOLUTION,
            converged_solution=SOLUTION,
            lap=4,
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


async def test_follow_up_answers_for_one_lap_and_preserves_the_solution(
    db_or_skip, monkeypatch
):
    monkeypatch.setattr(turn_runner, "run_expert_turn", _answering_turn)
    cid, eids = await _converged_room("ask")
    try:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            db.add(
                Message(
                    id=new_id(),
                    tenant_id=conv.tenant_id,
                    conversation_id=cid,
                    expert_name="You",
                    lap=conv.lap,
                    chair_index=-1,
                    content="Does this cover the rollback path?",
                    action="ask",
                )
            )
            conv.status = "consulting"
            conv.consult_until_lap = conv.lap + 1
            conv.chair_index = 0
            await db.commit()

        # A converged room is inert; a consulting one must be claimable again.
        async with SessionLocal() as db:
            assert await turn_runner.claim_next(db, "w") == cid

        for _ in range(6):
            await turn_runner.run_one_turn(cid, "w")
            async with SessionLocal() as db:
                if (await db.get(Conversation, cid)).status != "consulting":
                    break

        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            answers = (
                await db.scalars(
                    select(Message).where(
                        Message.conversation_id == cid, Message.action == "speak"
                    )
                )
            ).all()

            assert conv.status == "converged"  # back to rest
            assert conv.consult_until_lap is None
            assert conv.converged_solution == SOLUTION  # untouched
            assert len(answers) == 2  # exactly one lap: both experts answered once

        # The room is inert again, so a stray worker cannot keep it running.
        async with SessionLocal() as db:
            assert await turn_runner.claim_next(db, "w") != cid
    finally:
        await _cleanup(cid, eids)


async def test_reopening_requires_convergence_to_be_earned_again(db_or_skip, monkeypatch):
    async def _objecting_turn(**kwargs) -> TurnOutcome:
        assert kwargs["consulting"] is False
        # v2: keeping the room open costs a staked objection, not a free "no".
        return TurnOutcome(
            act=TurnAct(
                action="speak",
                message="That changes things.",
                gist=f"{kwargs['name']} staked an objection after the new question",
                blocking_objection=Objection(
                    text="The rollout section does not survive the chair's new constraint",
                    confidence=0.8,
                ),
            )
        )

    monkeypatch.setattr(turn_runner, "run_expert_turn", _objecting_turn)
    cid, eids = await _converged_room("reopen")
    try:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            conv.status = "running"
            conv.chair_index = 0
            await db.commit()

        for _ in range(4):
            await turn_runner.run_one_turn(cid, "w")

        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            # Staked objections hold the room open rather than letting it snap
            # back to converged on the strength of its earlier agreement.
            assert conv.status == "running"
            assert conv.converged_solution == SOLUTION
            objections = (
                await db.scalars(
                    select(Message).where(
                        Message.conversation_id == cid, Message.objection_json != ""
                    )
                )
            ).all()
            assert objections, "the staked objection must be on the permanent record"
            assert all(not m.agree for m in objections)
    finally:
        await _cleanup(cid, eids)

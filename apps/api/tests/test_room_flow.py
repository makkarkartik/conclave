"""Integration: a full room runs to convergence through the real claim/lease/lap
machinery against Postgres — protocol v3: propose → vote → settle → execute →
confirm → converge. The LLM is replaced by a scripted expert; everything else —
claim_next, run_one_turn, idempotent slots, the proposal ledger, the executor,
the confirmation poll — is real.

Requires the dev database (docker compose up -d db); skips if unreachable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import conclave.services.turn_runner as turn_runner
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Conversation, DocOp, Expert, Message, Proposal
from conclave.db.session import SessionLocal, engine, init_db
from conclave.domain.schemas import PollAct, TurnAct, Vote
from conclave.runtime.turn import ProposalTools, TurnOutcome

PLAN_BODY = "Ship the canary with **two experts**."
PROPOSAL = f"## Plan\n\n{PLAN_BODY}\n"  # the fold of the one executed proposal


@pytest.fixture
async def db_or_skip():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    yield
    await engine.dispose()


async def _scripted_turn(**kwargs) -> TurnOutcome:
    """v3 shape: the first seat PROPOSES the plan (the document stays frozen);
    every later seat votes agree on whatever it still owes and stakes nothing."""
    ctx = kwargs["context"]
    tools = ProposalTools(
        doc_text=ctx.shared_doc,
        existing=ctx.proposals,
        expert_name=kwargs["name"],
        lap=kwargs["lap"],
    )
    open_nums = [p.num for p in ctx.proposals if p.status == "open"]
    plan_proposed = any("Plan" in str(p.payload.get("heading", "")) for p in ctx.proposals)
    if PLAN_BODY not in ctx.shared_doc and not plan_proposed:
        res = await tools.execute(
            "propose_add_section",
            {"heading": "Plan", "text": PLAN_BODY, "reason": "seed the plan"},
        )
        assert res and res.startswith("Staged as P1"), res
    votes = [
        Vote(proposal=n, stance="agree")
        for n in open_nums
        if not any(p.num == n and p.expert_name == kwargs["name"] for p in ctx.proposals)
    ]
    return TurnOutcome(
        act=TurnAct(
            action="speak",
            message="I stress-tested it; the tradeoffs hold.",
            thought="scripted",
            gist=f"{kwargs['name']} endorsed the plan",
            votes=votes,
        ),
        staged_proposals=list(tools.staged),
    )


async def _consenting_poll(**kwargs) -> PollAct:
    """The confirmation poll after execution: the plan is in the document, consent."""
    assert PLAN_BODY in kwargs["context"].shared_doc
    return PollAct(stance="consent", note="the executed document stands")


async def test_room_plans_executes_and_converges(db_or_skip, monkeypatch):
    monkeypatch.setattr(turn_runner, "run_expert_turn", _scripted_turn)
    monkeypatch.setattr(turn_runner, "run_settlement_poll", _consenting_poll)

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
        for _ in range(30):
            async with SessionLocal() as db:
                claimed = await turn_runner.claim_next(db, worker)
            if claimed is None:
                break
            assert claimed == cid
            await turn_runner.run_one_turn(cid, worker)

        async with SessionLocal() as db:
            conv = await db.get(Conversation, cid)
            msgs = (
                await db.scalars(
                    select(Message)
                    .where(Message.conversation_id == cid)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
            props = (await db.scalars(select(Proposal).where(Proposal.conversation_id == cid))).all()
            ops = (await db.scalars(select(DocOp).where(DocOp.conversation_id == cid))).all()

            assert conv.status == "converged", [(m.lap, m.action, m.expert_name) for m in msgs]
            assert conv.converged_solution == PROPOSAL
            # The document was frozen through deliberation: not one op landed
            # until the executor ran, and that op is attributed to the PROPOSER.
            assert len(ops) == 1 and ops[0].kind == "add_section"
            assert ops[0].expert_name == "Ada"
            exec_msgs = [m for m in msgs if m.action == "execute"]
            assert len(exec_msgs) == 1 and exec_msgs[0].chair_index == -2
            assert exec_msgs[0].doc_diff and "Plan" in exec_msgs[0].doc_diff
            # The ledger: one proposal, executed
            assert [p.status for p in props] == ["executed"]
            # Deliberation converged before execution (floor 3 laps), then one
            # parallel confirmation poll ratified — consent rows, no serial turns.
            consents = [m for m in msgs if m.action == "consent"]
            assert len(consents) == 2 and all(m.lap == exec_msgs[0].lap for m in consents)
            # Idempotency: every occupied (lap, chair) slot is unique
            slots = [(m.lap, m.chair_index) for m in msgs if m.chair_index >= 0]
            assert len(slots) == len(set(slots))
            assert all(m.gist for m in msgs)
            assert conv.claimed_until is None and conv.claimed_by is None
            assert conv.plan_phase == "deliberate"
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

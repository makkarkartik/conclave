from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.config import settings
from conclave.db.ids import new_id
from conclave.db.models import (
    Attachment,
    Conversation,
    DocOp,
    Expert,
    Message,
    Proposal,
    ProposalVote,
)
from conclave.db.session import SessionLocal
from conclave.domain.converge import lap_settled, min_laps
from conclave.domain.diff import format_doc_change
from conclave.domain.docops import available_anchors, fold, seed_ops_from_drafts, slugify
from conclave.domain.files import write_shared_doc
from conclave.domain.proposals import compile_plan, duplicate_topics, open_nums, settle
from conclave.domain.schemas import PollAct
from conclave.runtime.turn import (
    DraftOutcome,
    TurnOutcome,
    run_expert_turn,
    run_sealed_draft,
    run_settlement_poll,
)
from conclave.runtime.providers import model_tier
from conclave.services.context import (
    build_turn_context,
    fold_lap_into_summary,
    load_doc_ops,
    load_proposals,
    seat_names,
)
from conclave.services.keys import resolve_api_key

log = logging.getLogger("conclave.runner")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


async def claim_next(db: AsyncSession, worker_id: str) -> str | None:
    """Claim one runnable room: status='running' with a free or expired lease.
    SKIP LOCKED makes this safe across any number of runner processes."""
    conv = await db.scalar(
        select(Conversation)
        .where(
            Conversation.status.in_(("running", "consulting", "drafting")),
            or_(Conversation.claimed_until.is_(None), Conversation.claimed_until < _now()),
        )
        .order_by(Conversation.updated_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if conv is None:
        return None
    conv.claimed_until = _now() + timedelta(seconds=settings.lease_seconds)
    conv.claimed_by = worker_id
    await db.commit()
    return conv.id


async def _release(conversation_id: str, worker_id: str, defer_seconds: int = 0) -> None:
    """Release the claim. With defer_seconds, leave a short future lease instead:
    the room stays unclaimable for that long (error backoff)."""
    until = _now() + timedelta(seconds=defer_seconds) if defer_seconds > 0 else None
    try:
        async with SessionLocal() as db:
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.claimed_by == worker_id)
                .values(claimed_until=until, claimed_by=None)
            )
            await db.commit()
    except Exception:  # noqa: BLE001 — releasing a deleted room is fine
        log.debug("release failed for %s", conversation_id, exc_info=True)


async def _heartbeat(conversation_id: str, worker_id: str) -> None:
    """Extend the lease while a turn runs — agentic turns can outlive a fixed lease."""
    interval = max(5, settings.lease_seconds // 3)
    while True:
        await asyncio.sleep(interval)
        async with SessionLocal() as db:
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.claimed_by == worker_id)
                .values(claimed_until=_now() + timedelta(seconds=settings.lease_seconds))
            )
            await db.commit()


def _error_outcome(exc: Exception) -> TurnOutcome:
    from conclave.domain.schemas import TurnAct

    return TurnOutcome(
        act=TurnAct(
            action="forfeit",
            thought=f"Error during turn: {exc}",
            message="I hit an error and must pass.",
            gist="hit an error and passed",
        ),
        tool_chips=["Error"],
    )


async def _run_drafting(db, conv: Conversation) -> None:
    """The sealed-divergence prefix (v2 §7c), executed under the room's claim:
    every seat drafts concurrently and blind, then the union of their sections
    seeds the document and the dialectic begins. Idempotent — a retried run
    skips seats whose lap-0 draft already landed."""
    chairs = conv.chair_ids
    existing = {
        m.chair_index
        for m in (
            await db.scalars(
                select(Message).where(Message.conversation_id == conv.id, Message.lap == 0)
            )
        ).all()
    }
    attachments = list(
        (await db.scalars(select(Attachment).where(Attachment.conversation_id == conv.id))).all()
    )
    # Resolve keys up front, serially — the AsyncSession must not be shared by
    # the concurrent draft tasks below.
    seats: list[tuple[int, Expert, str]] = []
    for idx, chair_id in enumerate(chairs):
        if idx in existing:
            continue
        expert = await db.get(Expert, chair_id)
        if expert is not None:
            seats.append((idx, expert, await resolve_api_key(db, expert)))

    async def one(expert: Expert, api_key: str) -> DraftOutcome:
        try:
            return await run_sealed_draft(
                name=expert.name,
                persona=expert.persona,
                provider=expert.provider,
                model=expert.model,
                api_key=api_key,
                topic=conv.topic,
                user_direction=conv.user_direction,
                attachments=attachments,
                web_search=conv.web_search,
            )
        except Exception as exc:  # noqa: BLE001 — one dead seat must not kill the phase
            log.warning("sealed draft failed in %s (%s): %s", conv.id, expert.name, exc)
            return DraftOutcome(text="", tool_chips=["Error"])

    results = await asyncio.gather(*(one(e, k) for _, e, k in seats)) if seats else []

    # Seed: all drafts' sections as attributed ops, collisions suffixed by author.
    prior_ops, _ = await load_doc_ops(db, conv)
    used = set(available_anchors(fold(prior_ops).text)) if prior_ops else set()
    next_seq = max((o.seq for o in prior_ops), default=0) + 1
    all_ops = list(prior_ops)
    for (idx, expert, _key), outcome in zip(seats, results):
        msg_id = new_id()
        sections = seed_ops_from_drafts(
            [(expert.name, outcome.text)], used_anchors=used, start_seq=next_seq
        )
        next_seq += len(sections)
        # seed_ops_from_drafts copies the set; carry this seat's anchors forward
        # so the next seat's collisions are suffixed.
        used.update(slugify(op.payload["heading"]) for op in sections)
        drafted = bool(sections)
        msg = Message(
            id=msg_id,
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            expert_id=expert.id,
            expert_name=expert.name,
            provider=expert.provider,
            model=expert.model,
            lap=0,
            chair_index=idx,
            content=(
                f"Drafted independently — {len(sections)} section(s): "
                + ", ".join(op.payload["heading"] for op in sections)
                if drafted
                else "(draft failed — joining at deliberation)"
            ),
            gist=f"{expert.name} drafted independently, sealed"
            if drafted
            else f"{expert.name}'s sealed draft failed",
            action="draft",
            agree=False,
        )
        msg.chips = ["Sealed draft", *outcome.tool_chips] if drafted else outcome.tool_chips
        msg.citations = outcome.citations
        db.add(msg)
        for op in sections:
            row = DocOp(
                id=new_id(),
                tenant_id=conv.tenant_id,
                conversation_id=conv.id,
                message_id=msg_id,
                expert_id=expert.id,
                expert_name=op.expert_name,
                seq=op.seq,
                lap=0,
                kind=op.kind,
                anchor=str(op.payload.get("heading", ""))[:200],
                reason=op.reason,
            )
            row.payload = op.payload
            db.add(row)
            all_ops.append(op)

    # A pause that landed mid-drafting wins: drafts and ops persist, the flip waits.
    await db.refresh(conv, attribute_names=["status"])
    if conv.status == "drafting":
        folded = fold(all_ops).text
        conv.shared_proposal = folded
        write_shared_doc(conv.id, folded)
        conv.doc_rev += 1
        conv.lap = 1
        conv.chair_index = 0
        conv.status = "running"
    try:
        await db.commit()
    except IntegrityError:
        # Another worker completed drafting for this room (expired lease + retry).
        await db.rollback()
        log.info("drafting collision in %s", conv.id)


async def _wrap_lap(db, conv: Conversation, chairs: list[str], *, consulting: bool) -> None:
    """A lap's slots are all filled: fold it, then decide the room's fate.

    Protocol v3: a deliberating room converges when the ledger is settled (every
    proposal approved or rejected) and the lap added no new proposal — then it
    moves to the execute phase. A confirm-phase lap that raised nothing new after
    execution converges outright. Consulting rooms return to converged."""
    completed_lap = conv.lap
    conv.lap = completed_lap + 1
    conv.floor_queue = []
    await db.flush()
    lap_msgs = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.lap == completed_lap)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()
    fold_lap_into_summary(conv, completed_lap, list(lap_msgs))
    turns = [
        {
            "forfeit": m.action == "forfeit",
            # Consent (agree) is exactly "staked nothing" for non-forfeits.
            "staked": m.action != "forfeit" and not m.agree,
        }
        for m in lap_msgs
        if m.chair_index >= 0  # chair questions never occupy a turn slot
    ]
    if consulting:
        # A follow-up is answered, not re-deliberated: the experts respond for
        # one lap and the room returns to converged with its solution untouched.
        if conv.consult_until_lap is None or conv.lap >= conv.consult_until_lap:
            conv.status = "converged"
            conv.consult_until_lap = None
            # The question was binding direction while it was live; a stale one
            # must not command every future turn.
            conv.user_direction = ""
        return

    props, votes = await load_proposals(db, conv)
    st = settle(props, votes, voters=await seat_names(db, conv))
    quiet = lap_settled(
        laps_done=conv.lap,
        chair_count=len(chairs),
        turns=turns,
        floor=min_laps(sealed=conv.sealed_start),
    )
    if conv.plan_phase == "confirm":
        # The executed document was put to the room; a quiet lap ratifies it.
        if quiet:
            conv.status = "converged"
            conv.converged_solution = conv.shared_proposal
            conv.user_direction = ""
            conv.plan_phase = "deliberate"
        elif conv.lap >= settings.safety_lap_ceiling:
            conv.status = "safety_pause"
        return
    if quiet and st.settled:
        if st.approved:
            conv.plan_phase = "execute"
        else:
            # Nothing approved and nothing left open: the frozen document *is*
            # the answer.
            conv.status = "converged"
            conv.converged_solution = conv.shared_proposal
            conv.user_direction = ""
    elif conv.lap >= settings.safety_lap_ceiling:
        conv.status = "safety_pause"


async def _run_execute(db, conv: Conversation, chairs: list[str]) -> None:
    """Execution is a job, not a debate (v3 §9b): compile the approved plan into
    ops against the frozen document, in proposal order, each op attributed to its
    proposer. The executor seat is the highest-tier model — its discretion is
    zero here (a mechanical fold); it merely lends its slot and name to the act.
    Then the room enters the confirm phase: one lap over the executed document."""
    props, votes = await load_proposals(db, conv)
    voters = await seat_names(db, conv)
    st = settle(props, votes, voters=voters)
    ops_before, _ = await load_doc_ops(db, conv)
    doc_before = fold(ops_before).text if ops_before else ""
    next_seq = max((o.seq for o in ops_before), default=0) + 1
    ops, doc_after, skipped = compile_plan(
        st.approved, doc_text=doc_before, start_seq=next_seq, lap=conv.lap
    )

    # Executor seat: highest tier, first in chair order on ties.
    seats: list[tuple[int, Expert]] = []
    for idx, cid in enumerate(chairs):
        e = await db.get(Expert, cid)
        if e is not None:
            seats.append((idx, e))
    if not seats:
        conv.status = "paused"
        return
    idx, executor = min(seats, key=lambda t: (model_tier(t[1].model), t[0]))

    msg_id = new_id()
    for rec in ops:
        row = DocOp(
            id=new_id(),
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            message_id=msg_id,
            expert_id=None,
            expert_name=rec.expert_name,
            seq=rec.seq,
            lap=rec.lap,
            kind=rec.kind,
            anchor=str(rec.payload.get("anchor") or rec.payload.get("heading") or "")[:200],
            reason=rec.reason,
        )
        row.payload = rec.payload
        db.add(row)
    for r in (
        await db.scalars(select(Proposal).where(Proposal.conversation_id == conv.id))
    ).all():
        if any(p.num == r.num for p in st.approved):
            r.status = "executed" if not any(sp.num == r.num for sp, _ in skipped) else "skipped"
    if ops:
        conv.shared_proposal = doc_after
        write_shared_doc(conv.id, doc_after)
        conv.doc_rev += 1
    applied = len(st.approved) - len(skipped)
    lines = [f"Executed the approved plan: {applied} proposal(s) applied as {len(ops)} operation(s)."]
    if skipped:
        lines.append(
            "Skipped (no longer applicable after earlier changes): "
            + "; ".join(f"P{sp.num} — {why}" for sp, why in skipped)
        )
    # Surface what the plan left unreconciled, so the confirmation lap sees it
    # at once instead of discovering it a lap later.
    leftovers = duplicate_topics(available_anchors(doc_after if ops else doc_before))
    if leftovers:
        lines.append(
            "Note for the confirmation lap — sections that still look like duplicated topics: "
            + "; ".join("§" + " / §".join(g) for g in leftovers)
        )
    msg = Message(
        id=msg_id,
        tenant_id=conv.tenant_id,
        conversation_id=conv.id,
        expert_id=executor.id,
        expert_name=executor.name,
        provider=executor.provider,
        model=executor.model,
        lap=conv.lap,
        chair_index=-2,  # execution is not a turn slot
        content="\n".join(lines),
        gist=f"{executor.name} executed the approved plan ({applied} changes)",
        action="execute",
        agree=True,
        doc_diff=format_doc_change(doc_before, doc_after) if ops else "",
    )
    msg.chips = ["Executed plan"] + [f"P{p.num}" for p in st.approved]
    db.add(msg)
    conv.plan_phase = "confirm"
    conv.chair_index = 0
    conv.floor_queue = []
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        log.info("execute collision in %s", conv.id)


async def _run_poll(db, conv: Conversation, chairs: list[str]) -> bool:
    """The settlement poll (fast convergence): every seat is asked, in parallel,
    to consent or claim the floor. Consent fills the seat's lap slot immediately;
    claimants keep their slots empty and take real serial turns next. A lap where
    everyone consents wraps — and settles, past the floor — right here, for the
    cost of one parallel round. Returns True when every poll errored (backoff)."""
    context = await build_turn_context(db, conv)
    seats: list[tuple[int, Expert, str]] = []
    vacant: list[int] = []
    for idx, chair_id in enumerate(chairs):
        expert = await db.get(Expert, chair_id)
        if expert is None:
            vacant.append(idx)
        else:
            seats.append((idx, expert, await resolve_api_key(db, expert)))

    async def one(expert: Expert, api_key: str):
        try:
            act = await run_settlement_poll(
                name=expert.name,
                persona=expert.persona,
                provider=expert.provider,
                model=expert.model,
                api_key=api_key,
                topic=conv.topic,
                user_direction=conv.user_direction,
                lap=conv.lap,
                context=context,
            )
            return act, False
        except Exception as exc:  # noqa: BLE001 — a dead seat claims the floor instead
            log.warning("poll failed in %s (%s): %s", conv.id, expert.name, exc)
            return PollAct(stance="floor", note="(poll errored — will take a real turn)"), True

    results = await asyncio.gather(*(one(e, k) for _, e, k in seats)) if seats else []

    claimants: list[int] = []
    for (idx, expert, _key), (act, _err) in zip(seats, results):
        if act.stance == "consent":
            msg = Message(
                id=new_id(),
                tenant_id=conv.tenant_id,
                conversation_id=conv.id,
                expert_id=expert.id,
                expert_name=expert.name,
                provider=expert.provider,
                model=expert.model,
                lap=conv.lap,
                chair_index=idx,
                content=act.note or "Consents — nothing to stake.",
                gist=f"{expert.name} consented without staking a change",
                action="consent",
                agree=True,
            )
            db.add(msg)
        else:
            claimants.append(idx)
    for idx in vacant:
        db.add(
            Message(
                id=new_id(),
                tenant_id=conv.tenant_id,
                conversation_id=conv.id,
                expert_id=None,
                expert_name="Vacant seat",
                lap=conv.lap,
                chair_index=idx,
                content="(seat vacant — expert deleted)",
                gist="seat vacant",
                action="forfeit",
                agree=False,
            )
        )

    if claimants:
        # Floor goes to claimants in seat order — seats are already ranked
        # strongest-first at room start. Persisted with the consent rows so a
        # retried claim resumes the queue instead of re-polling. A claim after
        # execution reopens deliberation: proposals again, then execute again.
        conv.floor_queue = sorted(claimants)
        conv.chair_index = min(claimants)
        conv.plan_phase = "deliberate"
    else:
        await _wrap_lap(db, conv, chairs, consulting=False)
    try:
        await db.commit()
    except IntegrityError:
        # Another worker polled this lap (expired lease + retry). Its rows stand.
        await db.rollback()
        log.info("poll collision in %s lap=%s", conv.id, conv.lap)
    return bool(results) and all(err for _act, err in results)


async def run_one_turn(conversation_id: str, worker_id: str) -> None:
    heartbeat = asyncio.create_task(_heartbeat(conversation_id, worker_id))
    errored = False
    try:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, conversation_id)
            if conv is None or conv.status not in ("running", "consulting", "drafting"):
                return
            if conv.status == "drafting":
                await _run_drafting(db, conv)
                return
            consulting = conv.status == "consulting"

            chairs = conv.chair_ids
            if not chairs:
                conv.status = "paused"
                await db.commit()
                return
            if conv.plan_phase == "execute" and not consulting:
                await _run_execute(db, conv, chairs)
                return

            # Slot-based scheduling: a lap is complete when every seat has a
            # message. A fresh lap opens with a parallel settlement poll (running
            # rooms only — consulting rooms answer serially); claimants and
            # mid-lap seats take serial turns in seat order.
            have = set(
                (
                    await db.scalars(
                        select(Message.chair_index).where(
                            Message.conversation_id == conv.id,
                            Message.lap == conv.lap,
                            Message.chair_index >= 0,
                        )
                    )
                ).all()
            )
            missing = [i for i in range(len(chairs)) if i not in have]
            if not missing:
                # Crash landed between the last slot and the wrap: finish it.
                await _wrap_lap(db, conv, chairs, consulting=consulting)
                await db.commit()
                return
            queue = [i for i in conv.floor_queue if i in missing]
            if (
                not consulting
                and conv.plan_phase == "confirm"
                and not queue
                and len(missing) == len(chairs)
            ):
                # Confirm phase: the executed document goes to the room as one
                # parallel poll — consent ratifies, a floor claim opens one
                # correction lap of proposals.
                errored = await _run_poll(db, conv, chairs)
                return

            idx = queue[0] if queue else missing[0]
            expert = await db.get(Expert, chairs[idx])
            if expert is None:
                db.add(
                    Message(
                        id=new_id(),
                        tenant_id=conv.tenant_id,
                        conversation_id=conv.id,
                        expert_id=None,
                        expert_name="Vacant seat",
                        lap=conv.lap,
                        chair_index=idx,
                        content="(seat vacant — expert deleted)",
                        gist="seat vacant",
                        action="forfeit",
                        agree=False,
                    )
                )
                conv.floor_queue = [i for i in queue if i != idx]
                remaining = [i for i in missing if i != idx]
                conv.chair_index = remaining[0] if remaining else 0
                if not remaining:
                    await _wrap_lap(db, conv, chairs, consulting=consulting)
                await db.commit()
                return

            context = (await build_turn_context(db, conv)).ledger_for(expert.name)
            try:
                outcome = await run_expert_turn(
                    name=expert.name,
                    persona=expert.persona,
                    provider=expert.provider,
                    model=expert.model,
                    api_key=await resolve_api_key(db, expert),
                    topic=conv.topic,
                    user_direction=conv.user_direction,
                    lap=conv.lap,
                    context=context,
                    web_search=conv.web_search,
                    consulting=consulting,
                )
            except Exception as exc:  # noqa: BLE001 — provider/tool errors become a pass
                log.warning("turn failed in %s: %s", conversation_id, exc)
                errored = True
                outcome = _error_outcome(exc)

            act = outcome.act
            chips = list(outcome.tool_chips)
            content = act.message or ""

            if act.action == "forfeit":
                content = content or "Passed — listening."
                chips.append("Passed")

            msg_id = new_id()
            # Protocol v3: the document is frozen; the turn persists proposals and
            # votes atomically with the message. Nothing touches doc_ops here.
            staged = list(outcome.staged_proposals)
            existing_props, existing_votes = context.proposals, context.votes
            live_nums = open_nums(existing_props, existing_votes, voters=context.voters) | {
                p.num for p in staged
            }
            for rec in staged:
                row = Proposal(
                    id=new_id(),
                    tenant_id=conv.tenant_id,
                    conversation_id=conv.id,
                    message_id=msg_id,
                    expert_id=expert.id,
                    expert_name=rec.expert_name,
                    num=rec.num,
                    lap=rec.lap,
                    kind=rec.kind,
                    reason=rec.reason,
                    status="open",
                    supersedes=rec.supersedes,
                )
                row.payload = rec.payload
                db.add(row)
                if rec.supersedes is not None:
                    prev = await db.scalar(
                        select(Proposal).where(
                            Proposal.conversation_id == conv.id, Proposal.num == rec.supersedes
                        )
                    )
                    if prev is not None and prev.status == "open":
                        prev.status = "superseded"
                        prev.superseded_by = rec.num
            already = {(v.proposal_num, v.expert_name) for v in existing_votes}
            own = {p.num for p in existing_props + staged if p.expert_name == expert.name}
            rejected_any = False
            for v in act.votes:
                if v.proposal not in live_nums or v.proposal in own:
                    continue  # unknown, settled, or one's own proposal
                if (v.proposal, expert.name) in already:
                    continue
                stance = v.stance if v.stance in ("agree", "reject") else "agree"
                if stance == "reject":
                    rejected_any = True
                db.add(
                    ProposalVote(
                        id=new_id(),
                        tenant_id=conv.tenant_id,
                        conversation_id=conv.id,
                        message_id=msg_id,
                        proposal_num=v.proposal,
                        expert_name=expert.name,
                        stance=stance,
                        reason=(v.reason or "")[:500],
                        lap=conv.lap,
                    )
                )
                already.add((v.proposal, expert.name))
            # Sync stored statuses to the ledger's view — a rejected amendment
            # revives its original (superseded -> open), and stays that way.
            await db.flush()
            _props, _votes = await load_proposals(db, conv)
            _st = settle(_props, _votes, voters=context.voters)
            _status = {p.num: "open" for p in _st.open}
            _status.update({p.num: "approved" for p in _st.approved})
            _status.update({p.num: "rejected" for p in _st.rejected})
            _status.update({p.num: "superseded" for p in _st.superseded})
            for r in (
                await db.scalars(select(Proposal).where(Proposal.conversation_id == conv.id))
            ).all():
                if r.num in _status and r.status not in ("executed", "skipped"):
                    r.status = _status[r.num]
            if act.votes:
                agrees = sum(1 for v in act.votes if v.stance == "agree")
                rejects = sum(1 for v in act.votes if v.stance == "reject")
                chips.append(
                    "Voted: " + ", ".join(
                        s for s in (f"{agrees} agree" if agrees else "", f"{rejects} reject" if rejects else "") if s
                    )
                )

            forfeit = act.action == "forfeit"
            objection = act.blocking_objection
            if objection is not None:
                target = f" §{objection.anchor}" if objection.anchor else ""
                chips.append(f"Blocking objection{target}")
            # v3: a turn that stakes nothing — no proposal, no reject, no objection
            # — consents to the plan as it stands.
            staked = bool(staged) or rejected_any or objection is not None
            msg = Message(
                id=msg_id,
                tenant_id=conv.tenant_id,
                conversation_id=conv.id,
                expert_id=expert.id,
                expert_name=expert.name,
                provider=expert.provider,
                model=expert.model,
                lap=conv.lap,
                chair_index=idx,
                thought=act.thought or "",
                content=content,
                gist=(act.gist or "")[:300],
                action=act.action,
                agree=not forfeit and not staked,
                doc_diff="",
            )
            msg.objection = objection.model_dump() if objection is not None else None
            msg.chips = chips
            msg.citations = outcome.citations
            db.add(msg)
            conv.floor_queue = [i for i in queue if i != idx]
            remaining = [i for i in missing if i != idx]
            conv.chair_index = remaining[0] if remaining else 0
            if not remaining:
                await _wrap_lap(db, conv, chairs, consulting=consulting)

            if errored and conv.status in ("running", "consulting"):
                # A persistently failing room (dead key, provider outage) must not
                # burn laps to the safety ceiling: pause it after N straight errors.
                await db.flush()
                recent = (
                    await db.scalars(
                        select(Message.thought)
                        .where(Message.conversation_id == conv.id)
                        .order_by(Message.created_at.desc(), Message.id.desc())
                        .limit(settings.max_consecutive_error_turns)
                    )
                ).all()
                if len(recent) >= settings.max_consecutive_error_turns and all(
                    t.startswith("Error during turn:") for t in recent
                ):
                    conv.status = "error_pause"
                    log.warning(
                        "pausing %s after %s consecutive error turns",
                        conv.id,
                        settings.max_consecutive_error_turns,
                    )

            try:
                await db.commit()
            except IntegrityError:
                # Turn slot already filled: another worker ran this turn (expired lease
                # + retry). Its result stands; ours is discarded.
                await db.rollback()
                log.info("turn slot collision in %s lap=%s chair=%s", conv.id, conv.lap, idx)
    finally:
        heartbeat.cancel()
        await _release(
            conversation_id,
            worker_id,
            defer_seconds=settings.error_backoff_seconds if errored else 0,
        )


async def runner_loop(worker_id: str | None = None) -> None:
    """The turn-runner role: claim rooms, run one turn each, repeat. Run any number
    of these (embedded in the API process or as separate processes) — Postgres
    arbitrates via SKIP LOCKED."""
    worker_id = worker_id or default_worker_id()
    sem = asyncio.Semaphore(settings.runner_concurrency)
    log.info("runner %s starting (concurrency=%s)", worker_id, settings.runner_concurrency)

    async def _guarded(cid: str) -> None:
        try:
            await run_one_turn(cid, worker_id)
        except Exception:  # noqa: BLE001 — a broken room must not kill the loop
            log.exception("unhandled error running turn for %s", cid)
        finally:
            sem.release()

    while True:
        await sem.acquire()
        claimed: str | None = None
        try:
            async with SessionLocal() as db:
                claimed = await claim_next(db, worker_id)
        except Exception:  # noqa: BLE001 — e.g. DB briefly down; retry after idle
            log.exception("claim failed; retrying")
        if claimed is None:
            sem.release()
            await asyncio.sleep(1.0)
            continue
        asyncio.create_task(_guarded(claimed))

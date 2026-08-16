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
from conclave.db.models import Attachment, Conversation, DocOp, Expert, Message
from conclave.db.session import SessionLocal
from conclave.domain.converge import lap_settled
from conclave.domain.diff import format_doc_change
from conclave.domain.docops import available_anchors, fold, seed_ops_from_drafts, slugify
from conclave.domain.files import write_shared_doc
from conclave.runtime.turn import DraftOutcome, TurnOutcome, run_expert_turn, run_sealed_draft
from conclave.services.context import build_turn_context, fold_lap_into_summary, load_doc_ops
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

            idx = conv.chair_index % len(chairs)
            expert = await db.get(Expert, chairs[idx])
            if expert is None:
                conv.chair_index = (idx + 1) % len(chairs)
                await db.commit()
                return

            context = await build_turn_context(db, conv)
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
            doc_diff = ""

            if act.action == "forfeit":
                content = content or "Passed — listening."
                chips.append("Passed")

            msg_id = new_id()
            staged = list(outcome.staged_ops)
            if staged and outcome.doc_after is not None:
                # Persist the turn's document operations atomically with the message.
                # For a pre-op-log room the synthesized baseline is the first row,
                # so the fold reproduces the v1 text before the new ops apply.
                if context.baseline_synthesized:
                    staged = context.doc_ops + staged
                before_doc = context.shared_doc
                for rec in staged:
                    row = DocOp(
                        id=new_id(),
                        tenant_id=conv.tenant_id,
                        conversation_id=conv.id,
                        message_id=None if rec.kind == "baseline" else msg_id,
                        expert_id=None if rec.kind == "baseline" else expert.id,
                        expert_name=rec.expert_name,
                        seq=rec.seq,
                        lap=rec.lap,
                        kind=rec.kind,
                        anchor=str(
                            rec.payload.get("anchor") or rec.payload.get("heading") or ""
                        )[:200],
                        reason=rec.reason,
                    )
                    row.payload = rec.payload
                    db.add(row)
                conv.shared_proposal = outcome.doc_after
                write_shared_doc(conv.id, outcome.doc_after)
                doc_diff = format_doc_change(before_doc, outcome.doc_after)
                conv.doc_rev += 1
                content = content or "Updated the shared document."

            forfeit = act.action == "forfeit"
            objection = act.blocking_objection
            if objection is not None:
                target = f" §{objection.anchor}" if objection.anchor else ""
                chips.append(f"Blocking objection{target}")
            # v2: a turn that stakes nothing — no op, no objection — consents.
            staked = bool(staged) or objection is not None
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
                doc_diff=doc_diff,
            )
            msg.objection = objection.model_dump() if objection is not None else None
            msg.chips = chips
            msg.citations = outcome.citations
            db.add(msg)
            conv.chair_index = (idx + 1) % len(chairs)

            if conv.chair_index == 0:
                completed_lap = conv.lap
                conv.lap = completed_lap + 1
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
                    # A follow-up is answered, not re-deliberated: the experts
                    # respond for one lap and the room returns to converged with
                    # its solution untouched.
                    if conv.consult_until_lap is None or conv.lap >= conv.consult_until_lap:
                        conv.status = "converged"
                        conv.consult_until_lap = None
                        # The question was binding direction while it was live; a
                        # stale one must not command every future turn.
                        conv.user_direction = ""
                elif lap_settled(laps_done=conv.lap, chair_count=len(chairs), turns=turns):
                    conv.status = "converged"
                    conv.converged_solution = conv.shared_proposal
                    conv.user_direction = ""
                elif conv.lap >= settings.safety_lap_ceiling:
                    conv.status = "safety_pause"

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

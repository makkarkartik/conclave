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
from conclave.db.models import Conversation, Expert, Message
from conclave.db.session import SessionLocal
from conclave.domain.converge import lap_converged, proposal_fingerprint
from conclave.domain.diff import format_doc_change
from conclave.domain.files import edit_shared_doc, read_shared_doc, write_shared_doc
from conclave.runtime.turn import TurnOutcome, run_expert_turn
from conclave.services.context import build_turn_context, fold_lap_into_summary
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
            Conversation.status == "running",
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


async def run_one_turn(conversation_id: str, worker_id: str) -> None:
    heartbeat = asyncio.create_task(_heartbeat(conversation_id, worker_id))
    errored = False
    try:
        async with SessionLocal() as db:
            conv = await db.get(Conversation, conversation_id)
            if conv is None or conv.status != "running":
                return

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
            if act.action == "write_proposal" and act.proposal:
                before_doc = read_shared_doc(conv.id)
                conv.shared_proposal = act.proposal
                write_shared_doc(conv.id, act.proposal)
                doc_diff = format_doc_change(before_doc, act.proposal, mode="replace")
                conv.doc_rev += 1
                chips.extend(["Updated proposal", "Updated shared doc"])
                content = content or "Updated the shared proposal and document."
            if act.action == "edit_shared_doc":
                doc_body = (act.doc_edit_content or act.proposal or act.message or "").strip()
                if doc_body:
                    mode = act.doc_edit_mode or "append"
                    before_doc = read_shared_doc(conv.id)
                    edit_shared_doc(conv.id, mode, doc_body)
                    after_doc = read_shared_doc(conv.id)
                    doc_diff = format_doc_change(before_doc, after_doc, mode=mode)
                    conv.doc_rev += 1
                    chips.append("Updated shared doc")
                    content = content or (
                        "Appended to the shared document."
                        if mode == "append"
                        else "Replaced the shared document."
                    )

            forfeit = act.action == "forfeit"
            vote_proposal = act.proposal or conv.shared_proposal
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
                thought=act.thought or "",
                content=content,
                gist=(act.gist or "")[:300],
                action=act.action,
                agree=bool(act.agree) and not forfeit,
                proposal_hash="" if forfeit else proposal_fingerprint(vote_proposal),
                doc_diff=doc_diff,
            )
            msg.chips = chips
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
                        "agree": m.agree,
                        "forfeit": m.action == "forfeit",
                        "proposal_hash": m.proposal_hash,
                    }
                    for m in lap_msgs
                ]
                if lap_converged(laps_done=conv.lap, chair_count=len(chairs), turns=turns):
                    conv.status = "converged"
                    conv.converged_solution = conv.shared_proposal
                elif conv.lap >= settings.safety_lap_ceiling:
                    conv.status = "safety_pause"

            if errored and conv.status == "running":
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

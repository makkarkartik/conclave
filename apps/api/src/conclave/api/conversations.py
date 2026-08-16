from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from conclave.api.serializers import conversation_out, message_out, speaking_expert_id
from conclave.db.ids import new_id
from conclave.db.models import (  # noqa: F401
    DEFAULT_TENANT_ID,
    Attachment,
    Conversation,
    DocOp,
    Message,
)
from conclave.db.session import get_db
from conclave.domain.docops import fold, parse_sections, suppressed_seqs
from conclave.domain.files import (
    ALLOWED_SUFFIXES,
    conversation_dir,
    extract_attachment,
    read_shared_doc,
    remove_conversation_dir,
    write_shared_doc,
)
from conclave.services.context import load_doc_ops, load_proposals
from conclave.domain.schemas import (
    AskBody,
    ProposalOut,
    ProposalVoteOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    ConversationUpdates,
    PauseBody,
    SharedDocBody,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])
log = logging.getLogger("conclave.api")

_FULL = (selectinload(Conversation.messages), selectinload(Conversation.attachments))


async def _get_conv(
    db: AsyncSession, conversation_id: str, *, full: bool = False
) -> Conversation:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.tenant_id == DEFAULT_TENANT_ID
    )
    stmt = stmt.options(*_FULL) if full else stmt.options(selectinload(Conversation.attachments))
    conv = await db.scalar(stmt)
    if not conv:
        raise HTTPException(404, "Not found")
    return conv


@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == DEFAULT_TENANT_ID)
        .options(selectinload(Conversation.attachments))
        .order_by(Conversation.updated_at.desc())
    )
    return [conversation_out(c, include_messages=False) for c in rows]


@router.post("", response_model=ConversationOut)
async def create_conversation(body: ConversationCreate, db: AsyncSession = Depends(get_db)):
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(400, "Topic required")
    cid = new_id()
    conv = Conversation(
        id=cid,
        tenant_id=DEFAULT_TENANT_ID,
        title=(body.title or topic[:80]).strip(),
        topic=topic,
        chair_ids_json="[]",
        sealed_start=body.sealed_start,
    )
    conv.chair_ids = body.chair_ids
    db.add(conv)
    await db.commit()
    conversation_dir(cid)
    write_shared_doc(cid, "# Shared document\n\n")
    conv = await _get_conv(db, cid, full=True)
    return conversation_out(conv)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await _get_conv(db, conversation_id, full=True)
    return conversation_out(conv)


@router.get("/{conversation_id}/updates", response_model=ConversationUpdates)
async def get_updates(
    conversation_id: str, after: str | None = None, db: AsyncSession = Depends(get_db)
):
    """The polling feed: room state plus messages newer than the client's cursor."""
    conv = await _get_conv(db, conversation_id)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if after:
        ref = await db.get(Message, after)
        if ref is not None:
            stmt = stmt.where(
                tuple_(Message.created_at, Message.id) > tuple_(ref.created_at, ref.id)
            )
    rows = await db.scalars(stmt.order_by(Message.created_at.asc(), Message.id.asc()).limit(200))
    return ConversationUpdates(
        status=conv.status,
        lap=conv.lap,
        chair_index=conv.chair_index,
        doc_rev=conv.doc_rev,
        plan_phase=conv.plan_phase or "deliberate",
        speaking_expert_id=speaking_expert_id(conv),
        messages=[message_out(m) for m in rows],
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: str, body: ConversationUpdate, db: AsyncSession = Depends(get_db)
):
    conv = await _get_conv(db, conversation_id, full=True)
    data = body.model_dump(exclude_unset=True)
    # Title rename is always allowed; structural edits need a pause.
    structural = {k for k in ("topic", "chair_ids", "user_direction") if k in data}
    if conv.status == "running" and structural:
        raise HTTPException(400, "Pause the room before editing topic or seats")

    # Redaction protects what enters a prompt; a search query leaves the machine
    # entirely, so a room holding documents must opt in with eyes open.
    confirmed = bool(data.pop("confirm_egress", False))
    if data.get("web_search") and conv.attachments and not confirmed:
        raise HTTPException(
            400,
            f"This room has {len(conv.attachments)} attached document(s). Enabling web search "
            "lets experts send queries derived from them to a search provider. "
            "Confirm to proceed.",
        )
    if "title" in data and data["title"] is not None:
        title = data["title"].strip()
        if not title:
            raise HTTPException(400, "Title required")
        data["title"] = title
    if "chair_ids" in data and data["chair_ids"] is not None:
        conv.chair_ids = data.pop("chair_ids")
    for k, v in data.items():
        setattr(conv, k, v)
    await db.commit()
    return conversation_out(conv)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await _get_conv(db, conversation_id)
    await db.delete(conv)
    await db.commit()
    remove_conversation_dir(conversation_id)
    return {"ok": True}


def _activate(conv: Conversation) -> None:
    """Waking a room: a sealed room that has not yet seeded its document goes
    (back) to drafting; everything else deliberates."""
    fresh = conv.sealed_start and conv.lap == 0 and not conv.converged_solution
    conv.status = "drafting" if fresh else "running"
    conv.claimed_until = None
    conv.claimed_by = None


async def _order_chairs(db: AsyncSession, conv: Conversation) -> None:
    """Smartest model goes first. On a room's first start, seats are ordered by
    model capability (stable — the chair's seating order breaks ties): the
    strongest model frames the opening proposal, or leads reconciliation after a
    sealed start. Rotation order is then fixed for the room's life."""
    from conclave.db.models import Expert
    from conclave.runtime.providers import model_tier

    chairs = conv.chair_ids
    tiers: list[tuple[int, int, str]] = []
    for i, chair_id in enumerate(chairs):
        expert = await db.get(Expert, chair_id)
        tiers.append((model_tier(expert.model) if expert else 99, i, chair_id))
    conv.chair_ids = [cid for _, _, cid in sorted(tiers)]


@router.post("/{conversation_id}/start", response_model=ConversationOut)
async def start(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await _get_conv(db, conversation_id, full=True)
    if len(conv.chair_ids) < 2:
        raise HTTPException(400, "Seat at least two experts")
    if conv.status not in ("running", "drafting"):
        if conv.lap == 0 and not conv.messages:
            await _order_chairs(db, conv)
        conv.chair_index = 0
        _activate(conv)
        await db.commit()
    return conversation_out(conv)


@router.post("/{conversation_id}/pause", response_model=ConversationOut)
async def pause(conversation_id: str, body: PauseBody, db: AsyncSession = Depends(get_db)):
    conv = await _get_conv(db, conversation_id, full=True)
    if body.direction:
        conv.user_direction = body.direction
    conv.status = "paused"
    await db.commit()
    return conversation_out(conv)


@router.post("/{conversation_id}/resume", response_model=ConversationOut)
async def resume(conversation_id: str, body: PauseBody, db: AsyncSession = Depends(get_db)):
    conv = await _get_conv(db, conversation_id, full=True)
    if len(conv.chair_ids) < 2:
        raise HTTPException(400, "Seat at least two experts")
    if body.direction:
        conv.user_direction = body.direction
    # Clears any leftover lease (incl. error backoff) so resume takes effect now.
    _activate(conv)
    await db.commit()
    return conversation_out(conv)


@router.post("/{conversation_id}/ask", response_model=ConversationOut)
async def ask(conversation_id: str, body: AskBody, db: AsyncSession = Depends(get_db)):
    """Put a follow-up question to a room that has already concluded.

    A converged room is otherwise inert — the runner only claims rooms that are
    running — so this is what carries a finished deliberation forward.
    """
    conv = await _get_conv(db, conversation_id, full=True)
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Question required")
    if conv.status not in ("converged", "paused", "safety_pause", "error_pause"):
        raise HTTPException(400, "Ask a follow-up once the room has stopped")
    if conv.consult_until_lap is not None:
        raise HTTPException(400, "The room is still answering the previous question")

    db.add(
        Message(
            id=new_id(),
            tenant_id=conv.tenant_id,
            conversation_id=conv.id,
            expert_id=None,
            expert_name="You",
            lap=conv.lap,
            chair_index=-1,  # outside the rotation, so it never takes a turn slot
            content=question,
            gist=f"Chair asked: {question[:140]}",
            action="ask",
        )
    )

    conv.user_direction = question
    conv.chair_index = 0
    conv.floor_queue = []
    conv.claimed_until = None
    conv.claimed_by = None
    if body.reopen:
        # Full deliberation: convergence must be re-earned. No floor reset is
        # needed — re-convergence still requires identical proposals across a lap.
        conv.status = "running"
        conv.consult_until_lap = None
    else:
        conv.status = "consulting"
        conv.consult_until_lap = conv.lap + 1
    await db.commit()
    return conversation_out(conv)


@router.post("/{conversation_id}/files")
async def upload_file(
    conversation_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    conv = await _get_conv(db, conversation_id)
    name = file.filename or "upload.txt"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported type {suffix}")
    # Re-attaching the same file wastes a room's context on a duplicate copy —
    # and is what impatient re-clicks during a slow OCR upload produce.
    if any(a.filename == name for a in conv.attachments):
        raise HTTPException(400, f"'{name}' is already attached to this room.")

    dest_dir = conversation_dir(conversation_id) / "files"
    dest = dest_dir / f"{new_id()}_{name}"
    data = await file.read()
    dest.write_bytes(data)

    # Parse now, not at turn time: an unreadable file must fail here, loudly,
    # instead of surfacing mid-deliberation inside a model's context.
    extraction = await asyncio.to_thread(extract_attachment, str(dest))
    log.info(
        "attachment %s: chars=%s method=%s", name, extraction.chars, extraction.method
    )
    if not extraction.usable:
        dest.unlink(missing_ok=True)
        reasons = {
            "empty": "no readable text could be extracted (a scanned image with no OCR result, or an empty file)",
            "failed": "the file could not be parsed — it may be corrupt, encrypted, or not really a "
            f"{suffix} file",
            "missing": "the upload could not be read back from disk",
        }
        raise HTTPException(
            400, f"'{name}' was not attached: {reasons.get(extraction.method, 'unreadable')}."
        )

    att = Attachment(
        id=new_id(),
        tenant_id=conv.tenant_id,
        conversation_id=conversation_id,
        filename=name,
        path=str(dest),
        extracted_chars=extraction.chars,
        extraction_method=extraction.method,
    )
    db.add(att)
    await db.commit()
    return {
        "id": att.id,
        "filename": att.filename,
        "extracted_chars": att.extracted_chars,
        "extraction_method": att.extraction_method,
    }


@router.delete("/{conversation_id}/files/{attachment_id}")
async def delete_attachment(
    conversation_id: str, attachment_id: str, db: AsyncSession = Depends(get_db)
):
    conv = await _get_conv(db, conversation_id)
    att = next((a for a in conv.attachments if a.id == attachment_id), None)
    if att is None:
        raise HTTPException(404, "Attachment not found")
    Path(att.path).unlink(missing_ok=True)
    await db.delete(att)
    await db.commit()
    return {"ok": True}


@router.get("/{conversation_id}/shared-doc")
async def get_shared_doc(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """The document plus its structured history: per-section attribution in
    document order, and the full operation log with revert status — the client
    renders these, it never parses strings."""
    conv = await _get_conv(db, conversation_id)
    ops_records, _ = await load_doc_ops(db, conv)
    if not ops_records:
        return {"content": read_shared_doc(conversation_id), "sections": [], "ops": []}
    folded = fold(ops_records)
    dead = suppressed_seqs(ops_records)
    doc_sections = [s for s in parse_sections(folded.text) if s.heading]
    headings = {s.anchor: s.heading.lstrip("#").strip() for s in doc_sections}
    order = {s.anchor: i for i, s in enumerate(doc_sections)}
    sections = sorted(
        (
            {
                "anchor": anchor,
                "heading": headings.get(anchor, anchor),
                "expert": b.expert_name,
                "lap": b.lap,
                "seq": b.seq,
                "reason": b.reason,
            }
            for anchor, b in folded.blame.items()
        ),
        key=lambda s: order.get(s["anchor"], 999),
    )
    ops = [
        {
            "seq": o.seq,
            "lap": o.lap,
            "expert": o.expert_name,
            "kind": o.kind,
            "target": str(
                o.payload.get("anchor")
                or o.payload.get("heading")
                or (f"op {o.payload.get('target_seq')}" if o.kind == "revert" else "")
            ),
            "reason": o.reason,
            "reverted": o.seq in dead,
        }
        for o in sorted(ops_records, key=lambda o: o.seq)
    ]
    return {"content": folded.text, "sections": sections, "ops": ops}


@router.get("/{conversation_id}/proposals", response_model=list[ProposalOut])
async def get_proposals(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """The proposal ledger (protocol v3): every proposed change, its votes, and its
    fate — the plan the room deliberates over before touching the document."""
    conv = await _get_conv(db, conversation_id)
    props, votes = await load_proposals(db, conv)
    by_num: dict[int, list] = {}
    for v in votes:
        by_num.setdefault(v.proposal_num, []).append(v)
    out: list[ProposalOut] = []
    for p in props:
        pl = p.payload
        if p.kind == "add_section":
            target = str(pl.get("heading", ""))
            text = str(pl.get("text", ""))
        elif p.kind == "merge_sections":
            target = "§" + ", §".join(pl.get("anchors") or []) + f' → "{pl.get("heading", "")}"'
            text = str(pl.get("text", ""))
        else:
            target = "§" + str(pl.get("anchor", ""))
            text = str(pl.get("new_text", ""))
        out.append(
            ProposalOut(
                num=p.num,
                lap=p.lap,
                expert=p.expert_name,
                kind=p.kind,
                target=target,
                reason=p.reason,
                status=p.status,
                supersedes=p.supersedes,
                superseded_by=p.superseded_by,
                votes=[
                    ProposalVoteOut(expert=v.expert_name, stance=v.stance, reason=v.reason, lap=v.lap)
                    for v in by_num.get(p.num, [])
                ],
                text=text,
            )
        )
    return out


@router.put("/{conversation_id}/shared-doc")
async def put_shared_doc(
    conversation_id: str, body: SharedDocBody, db: AsyncSession = Depends(get_db)
):
    """A chair edit is an operation like any other: a baseline the chair signs.
    It supersedes prior ops in the fold, so history stays intact behind it."""
    conv = await _get_conv(db, conversation_id)
    if conv.status in ("running", "drafting", "consulting"):
        raise HTTPException(400, "Pause before editing the shared doc")
    max_seq = await db.scalar(
        select(func.max(DocOp.seq)).where(DocOp.conversation_id == conversation_id)
    )
    op = DocOp(
        id=new_id(),
        tenant_id=conv.tenant_id,
        conversation_id=conversation_id,
        expert_name="Chair",
        seq=(max_seq or 0) + 1,
        lap=conv.lap,
        kind="baseline",
        reason="Chair edited the document directly",
    )
    op.payload = {"text": body.content}
    db.add(op)
    content = write_shared_doc(conversation_id, body.content)
    conv.shared_proposal = body.content
    conv.doc_rev += 1
    await db.commit()
    return {"content": content}

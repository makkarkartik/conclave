from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from conclave.api.serializers import conversation_out, message_out, speaking_expert_id
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Attachment, Conversation, Message
from conclave.db.session import get_db
from conclave.domain.files import (
    ALLOWED_SUFFIXES,
    conversation_dir,
    extract_attachment,
    read_shared_doc,
    remove_conversation_dir,
    write_shared_doc,
)
from conclave.domain.schemas import (
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


@router.post("/{conversation_id}/start", response_model=ConversationOut)
async def start(conversation_id: str, db: AsyncSession = Depends(get_db)):
    conv = await _get_conv(db, conversation_id, full=True)
    if len(conv.chair_ids) < 2:
        raise HTTPException(400, "Seat at least two experts")
    if conv.status != "running":
        conv.status = "running"
        conv.chair_index = 0
        conv.claimed_until = None
        conv.claimed_by = None
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
    conv.status = "running"
    # Clear any leftover lease (incl. error backoff) so resume takes effect now
    conv.claimed_until = None
    conv.claimed_by = None
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
    await _get_conv(db, conversation_id)
    return {"content": read_shared_doc(conversation_id)}


@router.put("/{conversation_id}/shared-doc")
async def put_shared_doc(
    conversation_id: str, body: SharedDocBody, db: AsyncSession = Depends(get_db)
):
    conv = await _get_conv(db, conversation_id)
    if conv.status == "running":
        raise HTTPException(400, "Pause before editing the shared doc")
    content = write_shared_doc(conversation_id, body.content)
    conv.doc_rev += 1
    await db.commit()
    return {"content": content}

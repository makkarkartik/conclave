from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from conclave.api.serializers import conversation_out
from conclave.db.models import Attachment, Conversation
from conclave.db.session import get_db
from conclave.domain.files import (
    ALLOWED_SUFFIXES,
    conversation_dir,
    read_shared_doc,
    remove_conversation_dir,
    write_shared_doc,
)
from conclave.domain.schemas import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    PauseBody,
    SharedDocBody,
)
from conclave.services import room_runner
from conclave.services.events import bus

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    rows = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
    return [conversation_out(c, include_messages=False) for c in rows]


@router.post("", response_model=ConversationOut)
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(400, "Topic required")
    cid = str(uuid.uuid4())
    conv = Conversation(
        id=cid,
        title=(body.title or topic[:80]).strip(),
        topic=topic,
        chair_ids_json="[]",
    )
    conv.chair_ids = body.chair_ids
    db.add(conv)
    db.commit()
    conversation_dir(cid)
    write_shared_doc(cid, "# Shared document\n\n")
    db.refresh(conv)
    return conversation_out(conv)


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Not found")
    return conversation_out(conv)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(conversation_id: str, body: ConversationUpdate, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Not found")
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
    db.commit()
    db.refresh(conv)
    return conversation_out(conv)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Not found")
    room_runner.stop_room(conversation_id)
    db.delete(conv)
    db.commit()
    remove_conversation_dir(conversation_id)
    await bus.publish(conversation_id, "status", {"status": "deleted"})
    return {"ok": True}


@router.post("/{conversation_id}/start", response_model=ConversationOut)
async def start(conversation_id: str, db: Session = Depends(get_db)):
    try:
        conv = room_runner.start_room(conversation_id, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await bus.publish(conversation_id, "status", {"status": "running"})
    return conversation_out(conv)


@router.post("/{conversation_id}/pause", response_model=ConversationOut)
async def pause(conversation_id: str, body: PauseBody, db: Session = Depends(get_db)):
    try:
        conv = room_runner.pause_room(conversation_id, db, body.direction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await bus.publish(conversation_id, "paused", {"reason": "user"})
    return conversation_out(conv)


@router.post("/{conversation_id}/resume", response_model=ConversationOut)
async def resume(conversation_id: str, body: PauseBody, db: Session = Depends(get_db)):
    try:
        conv = room_runner.resume_room(conversation_id, db, body.direction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await bus.publish(conversation_id, "status", {"status": "running"})
    return conversation_out(conv)


@router.post("/{conversation_id}/files")
async def upload_file(
    conversation_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Not found")
    name = file.filename or "upload.txt"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported type {suffix}")
    dest_dir = conversation_dir(conversation_id) / "files"
    dest = dest_dir / f"{uuid.uuid4().hex}_{name}"
    data = await file.read()
    dest.write_bytes(data)
    att = Attachment(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        filename=name,
        path=str(dest),
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return {"id": att.id, "filename": att.filename}


@router.get("/{conversation_id}/shared-doc")
def get_shared_doc(conversation_id: str, db: Session = Depends(get_db)):
    if not db.get(Conversation, conversation_id):
        raise HTTPException(404, "Not found")
    return {"content": read_shared_doc(conversation_id)}


@router.put("/{conversation_id}/shared-doc")
def put_shared_doc(conversation_id: str, body: SharedDocBody, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Not found")
    if conv.status == "running":
        raise HTTPException(400, "Pause before editing the shared doc")
    content = write_shared_doc(conversation_id, body.content)
    return {"content": content}

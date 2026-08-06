from __future__ import annotations

from conclave.db.models import Attachment, Conversation, Expert, Message
from conclave.domain.files import read_shared_doc
from conclave.domain.mask import mask_key
from conclave.domain.schemas import AttachmentOut, ConversationOut, ExpertOut, MessageOut
from conclave.services import room_runner


def expert_out(e: Expert) -> ExpertOut:
    return ExpertOut(
        id=e.id,
        name=e.name,
        persona=e.persona,
        provider=e.provider,
        model=e.model,
        accent=e.accent,
        api_key_masked=mask_key(e.api_key),
        created_at=e.created_at,
    )


def message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        expert_id=m.expert_id,
        expert_name=m.expert_name,
        provider=m.provider,
        model=m.model,
        thought=m.thought,
        content=m.content,
        action=m.action,
        chips=m.chips,
        doc_diff=getattr(m, "doc_diff", "") or "",
        created_at=m.created_at,
    )


def attachment_out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(id=a.id, filename=a.filename, created_at=a.created_at)


def conversation_out(c: Conversation, include_messages: bool = True) -> ConversationOut:
    speaking = None
    if c.status == "running" and c.chair_ids:
        idx = c.chair_index % len(c.chair_ids)
        speaking = c.chair_ids[idx]
    return ConversationOut(
        id=c.id,
        title=c.title,
        topic=c.topic,
        user_direction=c.user_direction,
        chair_ids=c.chair_ids,
        status=c.status,
        shared_proposal=c.shared_proposal,
        converged_solution=c.converged_solution,
        lap=c.lap,
        chair_index=c.chair_index,
        created_at=c.created_at,
        updated_at=c.updated_at,
        messages=[message_out(m) for m in c.messages] if include_messages else [],
        attachments=[attachment_out(a) for a in c.attachments],
        shared_doc=read_shared_doc(c.id),
        speaking_expert_id=speaking if room_runner.is_running(c.id) or c.status == "running" else None,
    )

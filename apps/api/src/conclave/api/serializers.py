from __future__ import annotations

from conclave.db.models import Attachment, Conversation, Expert, Message
from conclave.domain.files import read_shared_doc
from conclave.domain.schemas import AttachmentOut, ConversationOut, ExpertOut, MessageOut


def expert_out(e: Expert) -> ExpertOut:
    return ExpertOut(
        id=e.id,
        name=e.name,
        persona=e.persona,
        provider=e.provider,
        model=e.model,
        accent=e.accent,
        api_key_masked=e.api_key_hint,
        created_at=e.created_at,
    )


def message_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id,
        expert_id=m.expert_id,
        expert_name=m.expert_name,
        provider=m.provider,
        model=m.model,
        lap=m.lap,
        thought=m.thought,
        content=m.content,
        gist=m.gist,
        action=m.action,
        chips=m.chips,
        doc_diff=m.doc_diff or "",
        created_at=m.created_at,
    )


def attachment_out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(id=a.id, filename=a.filename, created_at=a.created_at)


def speaking_expert_id(c: Conversation) -> str | None:
    chairs = c.chair_ids
    if c.status == "running" and chairs:
        return chairs[c.chair_index % len(chairs)]
    return None


def conversation_out(c: Conversation, include_messages: bool = True) -> ConversationOut:
    """Callers must eager-load messages/attachments (async session: no lazy loads)."""
    return ConversationOut(
        id=c.id,
        title=c.title,
        topic=c.topic,
        user_direction=c.user_direction,
        chair_ids=c.chair_ids,
        status=c.status,
        shared_proposal=c.shared_proposal,
        converged_solution=c.converged_solution,
        rolling_summary=c.rolling_summary,
        lap=c.lap,
        chair_index=c.chair_index,
        doc_rev=c.doc_rev,
        created_at=c.created_at,
        updated_at=c.updated_at,
        messages=[message_out(m) for m in c.messages] if include_messages else [],
        attachments=[attachment_out(a) for a in c.attachments],
        shared_doc=read_shared_doc(c.id),
        speaking_expert_id=speaking_expert_id(c),
    )

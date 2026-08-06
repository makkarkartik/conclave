from __future__ import annotations

from typing import Any

from conclave.db.models import Message


def serialize_message(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "expert_id": m.expert_id,
        "expert_name": m.expert_name,
        "provider": m.provider,
        "model": m.model,
        "thought": m.thought,
        "content": m.content,
        "action": m.action,
        "chips": m.chips,
        "doc_diff": getattr(m, "doc_diff", "") or "",
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }

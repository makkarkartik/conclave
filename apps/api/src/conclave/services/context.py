from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.config import settings
from conclave.db.models import Attachment, Conversation, Message
from conclave.domain.files import read_shared_doc

# Simple char cap on the rolling summary; oldest lap digests fall off first.
# TODO(compaction): replace the tail-trim with LLM compaction of old laps when
# canary metrics show rooms outliving the cap.
MAX_SUMMARY_CHARS = 24_000


@dataclass
class TurnContext:
    """Everything an expert sees on its turn. Cost is constant in room age:
    summary + ledger are capped, the transcript window is the last K turns only."""

    rolling_summary: str
    gist_ledger: str
    transcript_window: str
    shared_doc: str
    shared_proposal: str
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def attachments_blurb(self) -> str:
        return "\n".join(f"- id={a.id} name={a.filename}" for a in self.attachments)


def _format_turn(m: Message) -> str:
    line = f"{m.expert_name} ({m.action}): {m.content}"
    if m.thought:
        line += f"\n  thought: {m.thought[:500]}"
    return line


async def build_turn_context(db: AsyncSession, conv: Conversation) -> TurnContext:
    recent = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(settings.turn_window)
        )
    ).all()
    window = "\n\n".join(_format_turn(m) for m in reversed(recent))

    gists = (
        await db.execute(
            select(Message.lap, Message.expert_name, Message.gist)
            .where(Message.conversation_id == conv.id, Message.gist != "")
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()
    ledger = "\n".join(f"L{lap} {name}: {gist}" for lap, name, gist in gists)
    if len(ledger) > settings.gist_ledger_chars:
        ledger = "…" + ledger[-settings.gist_ledger_chars :]

    attachments = (
        await db.scalars(select(Attachment).where(Attachment.conversation_id == conv.id))
    ).all()

    return TurnContext(
        rolling_summary=conv.rolling_summary or "",
        gist_ledger=ledger,
        transcript_window=window,
        shared_doc=read_shared_doc(conv.id),
        shared_proposal=conv.shared_proposal or "",
        attachments=list(attachments),
    )


def fold_lap_into_summary(conv: Conversation, lap_no: int, lap_messages: list[Message]) -> None:
    """At a lap boundary, append the lap's digest to the rolling summary. Growth is
    one line per lap — logarithmic-ish in tokens vs. the transcript's linear growth."""
    parts = []
    for m in lap_messages:
        gist = m.gist or (m.action if m.action != "speak" else "")
        if gist:
            parts.append(f"{m.expert_name}: {gist}")
    if not parts:
        return
    digest = f"Lap {lap_no}: " + " | ".join(parts)
    summary = (conv.rolling_summary + "\n" if conv.rolling_summary else "") + digest
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = "…" + summary[-MAX_SUMMARY_CHARS:]
    conv.rolling_summary = summary

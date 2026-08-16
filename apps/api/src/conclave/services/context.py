from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.config import settings
from conclave.db.models import Attachment, Conversation, DocOp, Message
from conclave.domain.diff import is_stub_doc
from conclave.domain.docops import OpRecord, annotate_anchors, blame_lines, fold, ops_log_lines
from conclave.domain.files import read_shared_doc

# Simple char cap on the rolling summary; oldest lap digests fall off first.
# TODO(compaction): replace the tail-trim with LLM compaction of old laps when
# canary metrics show rooms outliving the cap.
MAX_SUMMARY_CHARS = 24_000


@dataclass
class TurnContext:
    """Everything an expert sees on its turn. Cost is constant in room age:
    summary + ledger are capped, the transcript window is the last K turns only.
    (The doc itself is shown whole — it is the artifact under deliberation, and
    a silent cut there is a truncation of the proposal being voted on.)"""

    rolling_summary: str
    gist_ledger: str
    transcript_window: str
    shared_doc: str
    shared_proposal: str
    attachments: list[Attachment] = field(default_factory=list)
    # Protocol v2: the op log this turn folds from. Includes a synthesized baseline
    # for pre-op-log rooms (baseline_synthesized tells the runner to persist it
    # alongside the turn's first staged ops).
    doc_ops: list[OpRecord] = field(default_factory=list)
    baseline_synthesized: bool = False
    doc_annotated: str = ""
    doc_blame: str = ""
    doc_ops_log: str = ""

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

    ops, synthesized = await load_doc_ops(db, conv)
    folded = fold(ops)
    # No ops and no real pre-existing text (a fresh or stub room): the doc is empty
    # and the prompt says so — the stub placeholder is not part of the artifact.
    doc_text = folded.text if ops else ""

    return TurnContext(
        rolling_summary=conv.rolling_summary or "",
        gist_ledger=ledger,
        transcript_window=window,
        shared_doc=doc_text,
        shared_proposal=conv.shared_proposal or "",
        attachments=list(attachments),
        doc_ops=ops,
        baseline_synthesized=synthesized,
        doc_annotated=annotate_anchors(doc_text),
        doc_blame=blame_lines(folded),
        doc_ops_log=ops_log_lines(ops),
    )


async def load_doc_ops(db: AsyncSession, conv: Conversation) -> tuple[list[OpRecord], bool]:
    """The room's op log as domain records. Pre-op-log rooms with a real document
    get a synthesized baseline op (not yet persisted) so the fold starts from
    their existing text instead of erasing it."""
    rows = (
        await db.scalars(
            select(DocOp).where(DocOp.conversation_id == conv.id).order_by(DocOp.seq.asc())
        )
    ).all()
    ops = [
        OpRecord(
            seq=r.seq,
            kind=r.kind,
            payload=r.payload,
            reason=r.reason,
            expert_name=r.expert_name,
            lap=r.lap,
        )
        for r in rows
    ]
    if ops:
        return ops, False
    existing = read_shared_doc(conv.id)
    if is_stub_doc(existing):
        return [], False
    baseline = OpRecord(
        seq=1,
        kind="baseline",
        payload={"text": existing},
        reason="Document as it stood before the operation log",
        expert_name="Chair",
        lap=conv.lap,
    )
    return [baseline], True


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

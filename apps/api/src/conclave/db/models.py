from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from conclave.db.session import Base

# Fixed sentinel tenant until auth lands (schema-first tenancy). UUIDv7-shaped so it
# sorts like every other id.
DEFAULT_TENANT_ID = "00000000-0000-7000-8000-000000000001"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ProviderKey(Base):
    """One shared BYOK key per (tenant, provider). Experts use it unless they
    carry their own override in api_key_encrypted."""

    __tablename__ = "provider_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_provider_keys_tenant_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    key_encrypted: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Expert(Base):
    __tablename__ = "experts"
    __table_args__ = (Index("ix_experts_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    persona: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(20), default="")
    accent: Mapped[str] = mapped_column(String(20), default="#6BA3FF")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_tenant_updated", "tenant_id", "updated_at"),
        # The claim query's index: runnable rooms are (status='running', lease free/expired).
        Index("ix_conversations_claimable", "status", "claimed_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    topic: Mapped[str] = mapped_column(Text)
    user_direction: Mapped[str] = mapped_column(Text, default="")
    chair_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    shared_proposal: Mapped[str] = mapped_column(Text, default="")
    converged_solution: Mapped[str] = mapped_column(Text, default="")
    rolling_summary: Mapped[str] = mapped_column(Text, default="")
    lap: Mapped[int] = mapped_column(Integer, default=0)
    chair_index: Mapped[int] = mapped_column(Integer, default=0)
    doc_rev: Mapped[int] = mapped_column(Integer, default=0)
    web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set while answering a follow-up: the room runs until this lap, then goes
    # back to converged without touching the solution.
    consult_until_lap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(Message.created_at, Message.id)",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def chair_ids(self) -> list[str]:
        return json.loads(self.chair_ids_json or "[]")

    @chair_ids.setter
    def chair_ids(self, value: list[str]) -> None:
        self.chair_ids_json = json.dumps(value)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Idempotency: one message per turn slot. A retried turn (dead worker, double
        # claim) collides here instead of double-posting.
        UniqueConstraint("conversation_id", "lap", "chair_index", name="uq_messages_turn_slot"),
        Index("ix_messages_conv_order", "conversation_id", "created_at", "id"),
        Index("ix_messages_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    expert_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expert_name: Mapped[str] = mapped_column(String(120), default="System")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    lap: Mapped[int] = mapped_column(Integer, default=0)
    chair_index: Mapped[int] = mapped_column(Integer, default=0)
    thought: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    gist: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(40), default="speak")
    # v2 semantics: consent — True when the turn staked no op and no objection.
    agree: Mapped[bool] = mapped_column(Boolean, default=False)
    # Legacy (v1 fingerprint votes); kept for old rooms, no longer written.
    proposal_hash: Mapped[str] = mapped_column(String(64), default="")
    objection_json: Mapped[str] = mapped_column(Text, default="")
    chips_json: Mapped[str] = mapped_column(Text, default="[]")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    doc_diff: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    @property
    def chips(self) -> list[str]:
        return json.loads(self.chips_json or "[]")

    @chips.setter
    def chips(self, value: list[str]) -> None:
        self.chips_json = json.dumps(value)

    @property
    def citations(self) -> list[dict]:
        return json.loads(self.citations_json or "[]")

    @citations.setter
    def citations(self, value: list[dict]) -> None:
        self.citations_json = json.dumps(value)

    @property
    def objection(self) -> dict | None:
        return json.loads(self.objection_json) if self.objection_json else None

    @objection.setter
    def objection(self, value: dict | None) -> None:
        self.objection_json = json.dumps(value) if value else ""


class DocOp(Base):
    """One attributed operation on a room's shared document (protocol v2, §3).

    The document is the fold of these rows (domain/docops.py); the shared.md file
    and conversations.shared_proposal are caches of that fold. `seq` orders ops
    within a room — turns are serialized by the claim lease, so allocation is
    race-free, and the unique constraint backstops it anyway. Reverts are rows
    too: suppression is computed at fold time, never stored.
    """

    __tablename__ = "doc_ops"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_doc_ops_conv_seq"),
        Index("ix_doc_ops_conv_seq", "conversation_id", "seq"),
        Index("ix_doc_ops_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # The turn message this op landed with; None for chair edits and migration baselines.
    message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expert_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expert_name: Mapped[str] = mapped_column(String(120), default="Chair")
    seq: Mapped[int] = mapped_column(Integer)
    lap: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20))
    anchor: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json or "{}")

    @payload.setter
    def payload(self, value: dict) -> None:
        self.payload_json = json.dumps(value)


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachments_tenant", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(260))
    path: Mapped[str] = mapped_column(Text)
    # Extraction result, recorded at upload so the room's view of a file is
    # verifiable before any turn runs.
    extracted_chars: Mapped[int] = mapped_column(Integer, default=0)
    extraction_method: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="attachments")

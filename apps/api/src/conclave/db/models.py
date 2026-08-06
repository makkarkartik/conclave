from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from conclave.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Expert(Base):
    __tablename__ = "experts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    persona: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    api_key: Mapped[str] = mapped_column(Text)
    accent: Mapped[str] = mapped_column(String(20), default="#6BA3FF")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    topic: Mapped[str] = mapped_column(Text)
    user_direction: Mapped[str] = mapped_column(Text, default="")
    chair_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="draft")
    shared_proposal: Mapped[str] = mapped_column(Text, default="")
    converged_solution: Mapped[str] = mapped_column(Text, default="")
    lap: Mapped[int] = mapped_column(Integer, default=0)
    chair_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    @property
    def chair_ids(self) -> list[str]:
        return json.loads(self.chair_ids_json or "[]")

    @chair_ids.setter
    def chair_ids(self, value: list[str]) -> None:
        self.chair_ids_json = json.dumps(value)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    expert_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expert_name: Mapped[str] = mapped_column(String(120), default="System")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    thought: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(40), default="speak")
    chips_json: Mapped[str] = mapped_column(Text, default="[]")
    doc_diff: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    @property
    def chips(self) -> list[str]:
        return json.loads(self.chips_json or "[]")

    @chips.setter
    def chips(self, value: list[str]) -> None:
        self.chips_json = json.dumps(value)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    filename: Mapped[str] = mapped_column(String(260))
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="attachments")

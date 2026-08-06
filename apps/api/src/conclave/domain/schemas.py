from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Provider = Literal["openai", "anthropic", "google"]


class ExpertCreate(BaseModel):
    name: str
    persona: str = ""
    provider: Provider
    model: str
    api_key: str
    accent: str = "#6BA3FF"


class ExpertUpdate(BaseModel):
    name: str | None = None
    persona: str | None = None
    provider: Provider | None = None
    model: str | None = None
    api_key: str | None = None
    accent: str | None = None


class ExpertOut(BaseModel):
    id: str
    name: str
    persona: str
    provider: str
    model: str
    accent: str
    api_key_masked: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    topic: str
    title: str | None = None
    chair_ids: list[str] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    topic: str | None = None
    title: str | None = None
    chair_ids: list[str] | None = None
    user_direction: str | None = None


class MessageOut(BaseModel):
    id: str
    expert_id: str | None
    expert_name: str
    provider: str
    model: str
    thought: str
    content: str
    action: str
    chips: list[str]
    doc_diff: str = ""
    created_at: datetime


class AttachmentOut(BaseModel):
    id: str
    filename: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    title: str
    topic: str
    user_direction: str
    chair_ids: list[str]
    status: str
    shared_proposal: str
    converged_solution: str
    lap: int
    chair_index: int
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    shared_doc: str = ""
    speaking_expert_id: str | None = None


class PauseBody(BaseModel):
    direction: str = ""


class SharedDocBody(BaseModel):
    content: str


class TurnAct(BaseModel):
    thought: str = ""
    action: Literal["speak", "write_proposal", "read_file", "edit_shared_doc", "forfeit"] = "speak"
    message: str = ""
    proposal: str | None = None
    file_id: str | None = None
    doc_edit_mode: Literal["append", "replace"] | None = None
    doc_edit_content: str | None = None
    agree: bool = False

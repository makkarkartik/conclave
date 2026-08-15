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
    lap: int
    thought: str
    content: str
    gist: str
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
    rolling_summary: str
    lap: int
    chair_index: int
    doc_rev: int
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    shared_doc: str = ""
    speaking_expert_id: str | None = None


class ConversationUpdates(BaseModel):
    """Polling delta: everything the client needs to catch up since its cursor."""

    status: str
    lap: int
    chair_index: int
    doc_rev: int
    speaking_expert_id: str | None
    messages: list[MessageOut] = Field(default_factory=list)


class PauseBody(BaseModel):
    direction: str = ""


class SharedDocBody(BaseModel):
    content: str


class TurnAct(BaseModel):
    """The one terminal tool of every expert turn: the expert's final act on the floor.

    Reading attachments (and, later, MCP connectors) are ordinary tools used before
    this call; TurnAct ends the turn.
    """

    thought: str = Field("", description="Private reasoning; longer than the spoken message is fine")
    action: Literal["speak", "write_proposal", "edit_shared_doc", "forfeit"] = "speak"
    message: str = Field("", description="What you say to the room, 2-5 sentences")
    gist: str = Field(
        "",
        description=(
            "One sentence, max 20 words, third person, summarizing what you did or argued "
            "this turn. Becomes the room's permanent ledger."
        ),
    )
    proposal: str | None = Field(
        None, description="write_proposal only: the full shared proposal as GitHub Markdown"
    )
    doc_edit_mode: Literal["append", "replace"] | None = None
    doc_edit_content: str | None = None
    agree: bool = False

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# "fake" is E2E-only: accepted by the API but rejected at model-build time unless
# CONCLAVE_ENABLE_FAKE_PROVIDER=1. The UI never offers it.
Provider = Literal["openai", "anthropic", "google", "fake"]


class ExpertCreate(BaseModel):
    name: str
    persona: str = ""
    provider: Provider
    model: str
    # Optional when the tenant already stores a key for this provider.
    api_key: str = ""
    accent: str = "#6BA3FF"


class ExpertUpdate(BaseModel):
    name: str | None = None
    persona: str | None = None
    provider: Provider | None = None
    model: str | None = None
    api_key: str | None = None
    # True clears the expert's own key so it falls back to the shared provider key.
    use_provider_key: bool | None = None
    accent: str | None = None


class ExpertOut(BaseModel):
    id: str
    name: str
    persona: str
    provider: str
    model: str
    accent: str
    api_key_masked: str
    # "own" = expert-specific override; "provider" = shared tenant key; "none" = no key
    key_source: Literal["own", "provider", "none"] = "none"
    created_at: datetime

    model_config = {"from_attributes": True}


class ProviderKeyOut(BaseModel):
    provider: str
    key_hint: str
    expert_count: int = 0
    updated_at: datetime


class ProviderKeyPut(BaseModel):
    api_key: str


class ConversationCreate(BaseModel):
    topic: str
    title: str | None = None
    chair_ids: list[str] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    topic: str | None = None
    title: str | None = None
    chair_ids: list[str] | None = None
    user_direction: str | None = None
    web_search: bool | None = None
    # Acknowledge that enabling search on a room holding documents sends queries
    # derived from them off the machine.
    confirm_egress: bool = False


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
    citations: list[dict] = Field(default_factory=list)
    doc_diff: str = ""
    created_at: datetime


class AttachmentOut(BaseModel):
    id: str
    filename: str
    extracted_chars: int = 0
    extraction_method: str = ""
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
    web_search: bool = False
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

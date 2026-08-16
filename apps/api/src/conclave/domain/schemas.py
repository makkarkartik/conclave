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
    # Sealed start: experts draft independently before deliberating (v2 §7).
    sealed_start: bool = False


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
    # Consent, not a vote: True when the turn staked nothing (v2 semantics).
    agree: bool = False
    objection: dict | None = None
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
    sealed_start: bool = False
    plan_phase: str = "deliberate"
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    shared_doc: str = ""
    speaking_expert_id: str | None = None


class ProposalVoteOut(BaseModel):
    expert: str
    stance: str
    reason: str = ""
    lap: int = 0


class ProposalOut(BaseModel):
    num: int
    lap: int
    expert: str
    kind: str
    target: str
    reason: str
    status: str
    supersedes: int | None = None
    superseded_by: int | None = None
    votes: list[ProposalVoteOut] = Field(default_factory=list)
    text: str = ""


class ConversationUpdates(BaseModel):
    """Polling delta: everything the client needs to catch up since its cursor."""

    status: str
    lap: int
    chair_index: int
    doc_rev: int
    plan_phase: str = "deliberate"
    speaking_expert_id: str | None
    messages: list[MessageOut] = Field(default_factory=list)


class PauseBody(BaseModel):
    direction: str = ""


class AskBody(BaseModel):
    question: str
    # False: one lap of answers, the converged solution is left alone.
    # True: deliberation resumes and convergence has to be earned again.
    reopen: bool = False


class SharedDocBody(BaseModel):
    content: str


class Objection(BaseModel):
    """A staked blocking objection: the only way besides a document operation to
    keep the room open (protocol v2, §5). It lands on the permanent record under
    the expert's name."""

    anchor: str = Field(
        "", description="Section anchor the objection targets, if it targets one"
    )
    text: str = Field(
        description="What specifically must change and why it is blocking — falsifiable, not vibes"
    )
    confidence: float = Field(
        0.7, ge=0.0, le=1.0, description="How confident you are that this objection is right (0-1)"
    )


class Vote(BaseModel):
    """A vote on an outstanding proposal (protocol v3). Rejecting is a staked act:
    it needs a reason and it lands on the record under your name."""

    proposal: int = Field(description="The proposal number, e.g. 3 for P3")
    stance: Literal["agree", "reject"]
    reason: str = Field("", description="Required for reject: what is wrong, one line")


class PollAct(BaseModel):
    """Settlement-poll response: consent to the document as it stands, or claim
    the floor for a real turn. Polls run in parallel — consent costs the room no
    serial time; claiming the floor and then changing nothing wastes everyone's."""

    stance: Literal["consent", "floor"]
    note: str = Field(
        "",
        description=(
            "One sentence: what you will change if given the floor, or why you consent"
        ),
    )


class TurnAct(BaseModel):
    """The one terminal tool of every expert turn: the expert's final act on the floor.

    Protocol v3: the shared document is FROZEN during deliberation. You change it by
    proposing — via the propose_* tools before this call — and the room changes it by
    executing the approved plan once, at the end. Reading attachments (and, later,
    MCP connectors) are ordinary tools too. TurnAct ends the turn.

    Every turn must vote on every open proposal it has not yet voted on (silence
    would be consent). Rejecting needs a reason. A turn that neither proposes nor
    rejects anything consents to the plan as it stands.
    """

    thought: str = Field("", description="Private reasoning; keep it brief")
    action: Literal["speak", "forfeit"] = "speak"
    message: str = Field("", description="What you say to the room, 2-5 sentences")
    gist: str = Field(
        "",
        description=(
            "One sentence, max 20 words, third person, summarizing what you did or argued "
            "this turn. Becomes the room's permanent ledger."
        ),
    )
    votes: list[Vote] = Field(
        default_factory=list,
        description="Your vote on each open proposal you have not voted on yet",
    )
    blocking_objection: Objection | None = Field(
        None,
        description=(
            "Stake this ONLY for a defect no proposal addresses and that genuinely blocks "
            "the document. Prefer proposing the fix. It keeps the room open and is scored "
            "on the record."
        ),
    )

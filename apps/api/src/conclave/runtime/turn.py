from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from conclave.config import settings
from conclave.db.models import Attachment
from conclave.domain.docops import available_anchors, slugify
from conclave.domain.proposals import (
    ProposalRecord,
    dry_run,
    next_num,
    open_nums,
    sanitize_payload,
)
from conclave.domain.files import read_attachment_text
from conclave.domain.schemas import PollAct, TurnAct
from conclave.runtime.citations import extract_citations, used_web_search
from conclave.runtime.providers import build_chat_model, native_search_tool
from conclave.services.context import TurnContext

SYSTEM = """You are {name}, a seated expert in a Conclave think tank.
Persona: {persona}

This is rigorous collaborative deliberation — not a debate club and not a pep rally.
Pressure-test ideas, then synthesize. The room succeeds when it ships a concrete,
defensible answer, not when it discovers every imaginable loophole forever.

Norms:
- Raise the strongest *blocking* objections (wrong goal, missing constraint, broken logic,
  unsafe assumption, missing tradeoff, untested assumption). Prefer steelman-then-improve
  over praise or rubber-stamping.
- After you critique, offer a concrete fix or an improved proposal. Pure demolition without
  a better alternative is incomplete work.
- Distinguish blocking issues from polish. Wording nits and speculative infinite regress
  are polish — fold them lightly or drop them.
- Scrutiny is the default: a coherent first draft is not enough to wave through.
- Keep spoken messages concise (2-5 sentences) and thoughts brief.
- Match the document's length to the question's stakes. Default to concise: the decision
  and its load-bearing reasoning, not a treatise. Go long only when the material demands
  it (dense records, many hard constraints) or the chair explicitly asks for depth. If
  the document has outgrown its question, condensing it is priority work, not polish.
- The shared document is FROZEN during deliberation. Nobody edits it directly — not you,
  not the chair. You change it by PROPOSING: propose_add_section, propose_edit_section,
  propose_delete_section, propose_merge_sections — each executable and in full detail
  (the actual heading and text, the exact anchors), each with a one-line reason that lands
  on the permanent record. A vague proposal ("tighten §pricing") is not a proposal; write
  the text you want. Sections are **GitHub-flavored Markdown**.
- To change a proposal rather than reject it, propose your version with amends=<P#>; that
  supersedes the original and everyone votes on yours instead.
- Competing or duplicated sections on one topic mean the union is unreconciled — propose
  the merge (with the merged text) rather than voting around it.

How the room decides (proposals, votes, and the plan):
- Every open proposal is on the ledger below. You MUST vote on each one you have not voted
  on yet: agree, or reject with a reason. Silence is consent, so vote deliberately.
- One reject keeps a change out of the plan; rejection is a staked act under your name.
  Reject for defects, not taste. If you would accept it with a change, amend it instead.
- The room converges when every proposal is settled and a full lap adds nothing new. Then
  the approved plan is executed once, as attributed operations, and the room confirms the
  result. Do not consent to a plan you could not defend; do not hold the room open with
  proposals you would not stake your name on. Polish is not a proposal.
- Stake TurnAct.blocking_objection only for a defect no proposal addresses that you cannot
  yourself fix with a proposal — that should be rare.

How your turn works:
- You may call research tools (e.g. read_attachment) as many times as you need, up to a budget.
- Proposals are validated against the frozen document as you make them: a bad anchor or
  a malformed merge is refused with a reason so you can correct it within the turn.
- You MUST end your turn with exactly one TurnAct call. Nothing happens until you do.
- Always fill TurnAct.gist: one sentence, max 20 words, third person — it becomes the room's
  permanent ledger of who did what.
"""

CONSULTING = """
THE ROOM HAS ALREADY CONVERGED. The chair has asked a follow-up question — it is
the last entry in the recent turns, and the converged solution is the shared
proposal below.

Answer the question directly and concretely, grounded in the solution and the
record. This is consultation, not renegotiation: prefer `speak`. Do not rewrite
the proposal unless the question exposes something that makes the solution wrong
— and if it does, say plainly what changed and why. If the honest answer is that
the record cannot settle it, say that instead of speculating.
"""

CHAIR_DIRECTION = """
BINDING CHAIR DIRECTION — this overrides conflicting norms above for this turn:
{direction}

Obey it. If the chair says converge, stop nitpicking, change focus, accept a tradeoff, or
revise the proposal a certain way: do that. Do not ignore or soft-pedal chair direction.
"""

PROMPT = """Topic: {topic}

{direction_block}

Deliberation lap: {lap}

Shared document — FROZEN; the room changes it only by executing the approved plan.
Section anchors are shown as {{#anchor}}; use them in proposals:
{doc}

Section attribution (who shaped each section, and why):
{blame}

PROPOSAL LEDGER — vote on every open proposal you have not voted on; propose what is missing:
{proposals}

Room memory (digest of every earlier lap):
{summary}

Turn ledger (who did what, one line per turn):
{ledger}

Attachments (read with the read_attachment tool):
{attachments}

Recent turns (verbatim):
{window}

It is your turn. Research with tools if needed, make proposals with the propose_* tools,
then end with one TurnAct call carrying your votes.
"""


DRAFT_SYSTEM = """You are {name}, a seated expert in a Conclave think tank.
Persona: {persona}

SEALED DRAFTING. You are answering alone: no other expert's work is visible to you,
and none of them can see yours. Every seat's draft is merged into one document
afterward, section by section, and the room deliberates over the union.

Write your complete, best answer to the topic as **GitHub-flavored Markdown with clear
`##` section headings** — each section enters the shared document under your name.
Cover what matters, including anything the others might overlook: an angle only you
raise reaches the room only if you write it now. Draft at the length the question
deserves — one tight page for an everyday decision; depth only when the material
(dense records, many constraints) or the chair explicitly calls for it.
{direction_block}
You may use research tools first (e.g. read_attachment). Finish by replying with the
draft itself — no preamble, no meta-commentary."""

DRAFT_PROMPT = """Topic: {topic}

Attachments (read with the read_attachment tool):
{attachments}

Write your sealed draft now."""


@dataclass
class DraftOutcome:
    text: str
    tool_chips: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)


async def run_sealed_draft(
    *,
    name: str,
    persona: str,
    provider: str,
    model: str,
    api_key: str,
    topic: str,
    user_direction: str = "",
    attachments: list[Attachment] | None = None,
    web_search: bool = False,
    llm: Any | None = None,
) -> DraftOutcome:
    """One sealed draft: a bounded tool loop terminated by prose (no TurnAct —
    there is no floor to act on yet, only a blank page)."""
    tools = AttachmentTools(list(attachments or []))
    if llm is None:
        llm = build_chat_model(provider, model, api_key)
    tool_schemas: list[Any] = list(tools.tools())
    if web_search:
        native = native_search_tool(provider)
        if native:
            tool_schemas.append(native)
    bound = llm.bind_tools(tool_schemas) if tool_schemas else llm

    direction = (user_direction or "").strip()
    messages: list[BaseMessage] = [
        SystemMessage(
            content=DRAFT_SYSTEM.format(
                name=name,
                persona=persona or "Rigorous specialist who challenges weak reasoning, then synthesizes",
                direction_block=(
                    f"\nBINDING CHAIR DIRECTION (obey): {direction}\n" if direction else ""
                ),
            )
        ),
        HumanMessage(
            content=DRAFT_PROMPT.format(
                topic=topic,
                attachments="\n".join(f"- id={a.id} name={a.filename}" for a in (attachments or []))
                or "(none)",
            )
        ),
    ]
    chips: list[str] = []
    citations: list[dict] = []
    searched = False
    nudged = False

    for _ in range(settings.max_tool_iterations):
        response: AIMessage = await bound.ainvoke(messages)
        messages.append(response)
        found = extract_citations(response.content)
        seen = {c["url"] for c in citations}
        fresh = [c for c in found if c["url"] not in seen]
        if (fresh or used_web_search(response.content)) and not searched:
            searched = True
            chips.append("Searched the web")
        citations.extend(fresh)

        calls = list(getattr(response, "tool_calls", None) or [])
        if not calls:
            text = _text_of(response)
            if text:
                return DraftOutcome(text=text, tool_chips=chips, citations=citations)
            if nudged:
                break
            nudged = True
            messages.append(HumanMessage(content="Write the draft now."))
            continue
        for call in calls:
            result = await tools.execute(call["name"], call["args"] or {})
            if result is None:
                result = f"Unknown tool: {call['name']}"
            else:
                label = tools.chip(call["name"], call["args"] or {})
                chips.append(label or f"Used {call['name']}")
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    return DraftOutcome(text="", tool_chips=chips, citations=citations)


POLL_SYSTEM = """You are {name}, a seated expert in a Conclave think tank.
Persona: {persona}

SETTLEMENT POLL. The room is checking whether deliberation is done. This is not a
turn — it is a parallel, read-only question to every seat at once:

- CONSENT if you would put your name behind the document as it stands. Consent costs
  the room nothing and is recorded under your name.
- Claim the FLOOR only if you will actually stake something on your turn: a specific
  section operation or a blocking objection. Claiming the floor and then changing
  nothing wastes every seat's time; consenting to a defective document puts your name
  on the defect.
- Polish is not a reason to claim the floor. Competing or duplicated sections on one
  topic ARE — unreconciled drafts mean deliberation is unfinished.
{direction_block}
Answer with exactly one PollAct call."""

POLL_PROMPT = """Topic: {topic}

Deliberation lap: {lap}

Shared document — the artifact you are consenting to or contesting (anchors in {{#...}}):
{doc}

Section attribution:
{blame}

Recent turns (verbatim):
{window}

Consent, or claim the floor: one PollAct call."""


async def run_settlement_poll(
    *,
    name: str,
    persona: str,
    provider: str,
    model: str,
    api_key: str,
    topic: str,
    user_direction: str,
    lap: int,
    context: "TurnContext",
    llm: Any | None = None,
) -> PollAct:
    """One expert's settlement-poll answer: consent or claim the floor. Read-only
    and cheap — polls for every seat run concurrently."""
    if llm is None:
        llm = build_chat_model(provider, model, api_key)
    bound = llm.bind_tools([PollAct])
    direction = (user_direction or "").strip()
    messages: list[BaseMessage] = [
        SystemMessage(
            content=POLL_SYSTEM.format(
                name=name,
                persona=persona or "Rigorous specialist who challenges weak reasoning, then synthesizes",
                direction_block=(
                    f"\nBINDING CHAIR DIRECTION (obey): {direction}\n" if direction else ""
                ),
            )
        ),
        HumanMessage(
            content=POLL_PROMPT.format(
                topic=topic,
                lap=lap,
                doc=context.doc_annotated or "(empty)",
                blame=context.doc_blame or "(none)",
                window=context.transcript_window or "(no turns yet)",
            )
        ),
    ]
    for attempt in range(2):
        response: AIMessage = await bound.ainvoke(messages)
        calls = list(getattr(response, "tool_calls", None) or [])
        submit = next((c for c in calls if c["name"] == "PollAct"), None)
        if submit is not None:
            return PollAct.model_validate(submit["args"])
        text = _text_of(response)
        if text and attempt == 1:
            # Prose fallback: read the stance out of the words.
            stance = "consent" if "consent" in text.lower() else "floor"
            return PollAct(stance=stance, note=text[:200])
        messages.append(response)
        messages.append(HumanMessage(content="Answer with exactly one PollAct call."))
    # No usable answer either attempt: claim the floor — a real turn can recover.
    return PollAct(stance="floor", note="(poll gave no usable answer)")


class ToolProvider(Protocol):
    """The seam future capability lands behind: MCP connectors, room file generation,
    sandboxed OS tools. A provider contributes tool schemas and executes its own calls."""

    def tools(self) -> list[type[BaseModel]]: ...

    async def execute(self, name: str, args: dict[str, Any]) -> str | None:
        """Run the named tool; return its result text, or None if the tool isn't ours."""
        ...

    # Optional: a human-readable chip for the message bubble. Providers that
    # don't implement it fall back to "Used <tool>".
    def chip(self, name: str, args: dict[str, Any]) -> str | None: ...


class read_attachment(BaseModel):
    """Read an attached file's text content into your context for this turn."""

    file_id: str = Field(description="The id of the attachment to read")


class AttachmentTools:
    def __init__(self, attachments: list[Attachment]) -> None:
        self._by_id = {a.id: a for a in attachments}

    def tools(self) -> list[type[BaseModel]]:
        return [read_attachment] if self._by_id else []

    def chip(self, name: str, args: dict[str, Any]) -> str | None:
        att = self._by_id.get(str(args.get("file_id", "")))
        return f"Read {att.filename}" if att else None

    async def execute(self, name: str, args: dict[str, Any]) -> str | None:
        if name != "read_attachment":
            return None
        att = self._by_id.get(str(args.get("file_id", "")))
        if not att:
            return "No attachment with that id. Available: " + ", ".join(self._by_id)
        # Off the event loop: PDF OCR can take seconds and must not stall other rooms.
        text = await asyncio.to_thread(read_attachment_text, att.path)
        return f"[{att.filename}]\n{text}"


class propose_add_section(BaseModel):
    """Propose adding a new section. Executable: give the actual heading and text."""

    heading: str = Field(description="Heading text, with or without leading #'s")
    text: str = Field(description="Full section body, GitHub-flavored Markdown")
    after_anchor: str | None = Field(
        None, description="Place after this anchor; 'start' or 'end' also work (default end)"
    )
    reason: str = Field(description="Why, one line — lands on the permanent record")
    amends: int | None = Field(None, description="Proposal number this supersedes, if any")


class propose_edit_section(BaseModel):
    """Propose replacing one section's content. Give the full new text."""

    anchor: str = Field(description="Anchor of the section to change (see {#anchor} tags)")
    new_text: str = Field(
        description="New body for the section. Start with a heading line to also rename it."
    )
    reason: str = Field(description="Why, one line — lands on the permanent record")
    amends: int | None = Field(None, description="Proposal number this supersedes, if any")


class propose_delete_section(BaseModel):
    """Propose removing a section. Destruction is public and attributed — justify it."""

    anchor: str = Field(description="Anchor of the section to remove")
    reason: str = Field(description="Why this section should not exist, one line")
    amends: int | None = Field(None, description="Proposal number this supersedes, if any")


class propose_merge_sections(BaseModel):
    """Propose merging two or more sections into one. Give the merged heading and the
    full merged text; the first anchor keeps the position, the rest are removed."""

    anchors: list[str] = Field(description="Anchors to merge, first one keeps its place")
    heading: str = Field(description="Heading for the merged section")
    text: str = Field(description="Full merged body, GitHub-flavored Markdown")
    reason: str = Field(description="Why, one line — lands on the permanent record")
    amends: int | None = Field(None, description="Proposal number this supersedes, if any")


_PROPOSE_TOOL_NAMES = {
    "propose_add_section": "add_section",
    "propose_edit_section": "edit_section",
    "propose_delete_section": "delete_section",
    "propose_merge_sections": "merge_sections",
}


class ProposalTools:
    """Protocol v3 (§9b): during deliberation the document is frozen; experts stage
    proposals here. Each is dry-run against the frozen document so a bad anchor or a
    malformed merge is refused visibly. Persistence is the turn runner's job, atomic
    with the message."""

    def __init__(
        self,
        *,
        doc_text: str,
        existing: list[ProposalRecord],
        expert_name: str,
        lap: int,
        open_set: set[int] | None = None,
    ) -> None:
        self._doc = doc_text
        self._existing = list(existing)
        self._expert_name = expert_name
        self._lap = lap
        # Which existing proposals may be amended: the ledger's open set (a
        # revived original counts), else the stored status.
        self._open = (
            set(open_set)
            if open_set is not None
            else {p.num for p in existing if p.status == "open"}
        )
        self.staged: list[ProposalRecord] = []

    def _next_num(self) -> int:
        return next_num(self._existing + self.staged)

    def tools(self) -> list[type[BaseModel]]:
        return [
            propose_add_section,
            propose_edit_section,
            propose_delete_section,
            propose_merge_sections,
        ]

    def chip(self, name: str, args: dict[str, Any]) -> str | None:
        if name == "propose_add_section":
            return f"Proposed adding §{slugify(str(args.get('heading') or ''))}"
        if name == "propose_edit_section":
            return f"Proposed editing §{args.get('anchor')}"
        if name == "propose_delete_section":
            return f"Proposed deleting §{args.get('anchor')}"
        if name == "propose_merge_sections":
            return "Proposed merging §" + ", §".join(str(a) for a in (args.get("anchors") or []))
        return None

    async def execute(self, name: str, args: dict[str, Any]) -> str | None:
        kind = _PROPOSE_TOOL_NAMES.get(name)
        if kind is None:
            return None
        reason = str(args.get("reason") or "").strip()
        amends = args.get("amends")
        payload = sanitize_payload({k: v for k, v in args.items() if k != "amends"})
        if amends is not None:
            live = self._open | {p.num for p in self.staged}
            if amends not in live:
                return f"Not staged: P{amends} is not an open proposal to amend"
        rec = ProposalRecord(
            num=self._next_num(),
            kind=kind,
            payload=payload,
            reason=reason,
            expert_name=self._expert_name,
            lap=self._lap,
            supersedes=int(amends) if amends is not None else None,
        )
        err = dry_run(rec, doc_text=self._doc)
        if err:
            return f"Not staged: {err}"
        self.staged.append(rec)
        return f"Staged as P{rec.num}. Anchors in the frozen document: " + (
            ", ".join(available_anchors(self._doc)) or "(no sections yet)"
        )


@dataclass
class TurnOutcome:
    act: TurnAct
    tool_chips: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    # Proposals staged during the turn (protocol v3). Persisted atomically with the
    # message by the turn runner; the document itself is untouched.
    staged_proposals: list[ProposalRecord] = field(default_factory=list)


def _text_of(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        ).strip()
    return str(content or "").strip()


async def run_expert_turn(
    *,
    name: str,
    persona: str,
    provider: str,
    model: str,
    api_key: str,
    topic: str,
    user_direction: str,
    lap: int,
    context: TurnContext,
    web_search: bool = False,
    consulting: bool = False,
    tool_providers: list[ToolProvider] | None = None,
    llm: Any | None = None,
) -> TurnOutcome:
    """One expert turn: a bounded tool loop terminated by a TurnAct call.

    `llm` overrides the provider-built model (tests inject a fake here).
    """
    prop_tools = ProposalTools(
        doc_text=context.shared_doc,
        existing=context.proposals,
        expert_name=name,
        lap=lap,
        open_set=open_nums(context.proposals, context.votes, voters=context.voters)
        if context.voters
        else None,
    )
    if tool_providers is not None:
        providers = tool_providers
        prop_tools = next((p for p in providers if isinstance(p, ProposalTools)), prop_tools)
    elif consulting:
        # A follow-up is answered, not re-planned: no proposal tools.
        providers = [AttachmentTools(context.attachments)]
    else:
        providers = [AttachmentTools(context.attachments), prop_tools]
    if llm is None:
        llm = build_chat_model(provider, model, api_key)

    tool_schemas: list[Any] = [TurnAct]
    for p in providers:
        tool_schemas.extend(p.tools())
    if web_search:
        native = native_search_tool(provider)
        if native:
            # Server-side: the provider searches and returns results inline, so
            # this never enters the tool loop below.
            tool_schemas.append(native)
    bound = llm.bind_tools(tool_schemas)

    direction = (user_direction or "").strip()
    system = SYSTEM.format(
        name=name,
        persona=persona or "Rigorous specialist who challenges weak reasoning, then synthesizes",
    )
    if consulting:
        system += "\n" + CONSULTING
    if direction:
        system += "\n" + CHAIR_DIRECTION.format(direction=direction)

    prompt = PROMPT.format(
        topic=topic,
        direction_block=(
            f"BINDING CHAIR DIRECTION (obey):\n{direction}" if direction else "Chair direction: (none)"
        ),
        lap=lap,
        doc=context.doc_annotated or "(empty — propose the first sections)",
        blame=context.doc_blame or "(none yet)",
        proposals=context.proposal_ledger or "(no proposals yet — propose what the document needs)",
        summary=context.rolling_summary or "(first lap — no memory yet)",
        ledger=context.gist_ledger or "(empty)",
        attachments=context.attachments_blurb or "(none)",
        window=context.transcript_window or "(no turns yet)",
    )

    messages: list[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=prompt)]
    chips: list[str] = []
    citations: list[dict] = []
    nudged = False

    searched = False

    def finish(act: TurnAct) -> TurnOutcome:
        return TurnOutcome(
            act=act,
            tool_chips=chips,
            citations=citations,
            staged_proposals=list(prop_tools.staged),
        )

    def note_sources(response: AIMessage) -> None:
        nonlocal searched
        found = extract_citations(response.content)
        seen = {c["url"] for c in citations}
        fresh = [c for c in found if c["url"] not in seen]
        # A search can run without yielding an extractable URL; say so either way.
        if (fresh or used_web_search(response.content)) and not searched:
            searched = True
            chips.append("Searched the web")
        citations.extend(fresh)

    for _ in range(settings.max_tool_iterations):
        response: AIMessage = await bound.ainvoke(messages)
        messages.append(response)
        note_sources(response)
        calls = list(getattr(response, "tool_calls", None) or [])

        submit = next((c for c in calls if c["name"] == "TurnAct"), None)
        if submit is not None:
            return finish(TurnAct.model_validate(submit["args"]))

        if not calls:
            text = _text_of(response)
            if text:
                # Model answered in prose instead of calling TurnAct — treat as speak.
                return finish(TurnAct(action="speak", message=text, gist=""))
            if nudged:
                break
            nudged = True
            messages.append(HumanMessage(content="Finish your turn now with one TurnAct call."))
            continue

        for call in calls:
            result: str | None = None
            provider_used: ToolProvider | None = None
            for p in providers:
                result = await p.execute(call["name"], call["args"] or {})
                if result is not None:
                    provider_used = p
                    break
            if result is None:
                result = f"Unknown tool: {call['name']}"
            else:
                labeler = getattr(provider_used, "chip", None)
                label = labeler(call["name"], call["args"] or {}) if labeler else None
                chips.append(label or f"Used {call['name']}")
            # Whole result, no second cap: attachments are evidence, and a silent
            # cut here is invisible to the expert reading it.
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    return finish(
        TurnAct(action="forfeit", message="", thought="Hit the tool budget without submitting.")
    )

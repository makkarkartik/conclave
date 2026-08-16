from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from conclave.config import settings
from conclave.db.models import Attachment
from conclave.domain.docops import (
    DocOpError,
    OpRecord,
    apply_op,
    available_anchors,
    fold,
    normalize_anchor,
    slugify,
    strip_anchor_tag_line,
    strip_anchor_tags,
    suppressed_seqs,
)
from conclave.domain.files import read_attachment_text
from conclave.domain.schemas import TurnAct
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
- Default stance is disagree. A coherent first draft is not enough to agree.
- Keep spoken messages concise (2-5 sentences). Thoughts may be longer.
- The shared document IS the proposal the room votes on. You change it with section
  operations during your turn — add_section, edit_section, delete_section, revert_edit —
  each with a one-line reason that lands on the permanent record. Write sections in
  **GitHub-flavored Markdown**: clear headings, bullets, numbered steps, bold for key
  decisions, tables when comparing options.
- There is no whole-document rewrite. Edit exactly the section you mean to change and
  leave the rest of the room's work standing. Deleting a section is a public, attributed
  act — give a real reason. If earlier work was wrongly removed, revert_edit(op=N)
  restores it exactly (op numbers are in the operations log).

agree=true is earned, not assumed. Set it ONLY when ALL hold:
1) The transcript shows real contested refinement: at least one substantive challenge was
   raised and addressed in the shared proposal (not just polite restatement).
2) You yourself have stress-tested the proposal (or a prior version) with a concrete objection
   or hard tradeoff — not only affirmed it.
3) No blocking objection remains (or yours is on the record and you explicitly accept the tradeoff).
4) The shared proposal is concrete enough to act on, and remaining dissent is polish only.
5) You would defend this under hostile scrutiny from your seat — not merely "looks fine."

If the room is still on an early draft, or critiques have been cosmetic, or you have not yet
pushed a real challenge: set agree=false and keep improving the proposal.

How your turn works:
- You may call research tools (e.g. read_attachment) as many times as you need, up to a budget.
- Document operations apply immediately: you see the result (or a correctable error, e.g.
  a wrong anchor) and can follow up within the same turn.
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

Shared document — this IS the proposal the room votes on. Section anchors are shown
as {{#anchor}}; use them with the section tools:
{doc}

Section attribution (who last shaped each section, and why):
{blame}

Recent document operations (revert_edit targets these op numbers):
{ops_log}

Room memory (digest of every earlier lap):
{summary}

Turn ledger (who did what, one line per turn):
{ledger}

Attachments (read with the read_attachment tool):
{attachments}

Recent turns (verbatim):
{window}

It is your turn. Research with tools if needed, then end with one TurnAct call.
"""


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


class add_section(BaseModel):
    """Add a new section to the shared document. Prefer this over touching others' work."""

    heading: str = Field(description="Heading text, with or without leading #'s")
    text: str = Field(description="Section body, GitHub-flavored Markdown")
    after_anchor: str | None = Field(
        None, description="Place after this anchor; 'start' or 'end' also work (default end)"
    )
    reason: str = Field(description="Why, one line — lands on the permanent record")


class edit_section(BaseModel):
    """Replace one section's content. Only that section changes; everything else stands."""

    anchor: str = Field(description="Anchor of the section to change (see {#anchor} tags)")
    new_text: str = Field(
        description="New body for the section. Start with a heading line to also rename it."
    )
    reason: str = Field(description="Why, one line — lands on the permanent record")


class delete_section(BaseModel):
    """Remove a section. Destruction is public, attributed, and revertable — justify it."""

    anchor: str = Field(description="Anchor of the section to remove")
    reason: str = Field(description="Why this section should not exist, one line")


class revert_edit(BaseModel):
    """Undo an earlier document operation exactly (e.g. restore wrongly deleted work)."""

    op: int = Field(description="Op number to revert, from the operations log")
    reason: str = Field(description="Why, one line — lands on the permanent record")


_DOC_TOOL_NAMES = {"add_section", "edit_section", "delete_section", "revert_edit"}


class DocTools:
    """Section-level operations on the shared document (protocol v2, §3).

    Ops apply immediately to a working fold — the model sees results and correctable
    errors mid-turn — but persistence is the turn runner's job, atomic with the
    message: a crashed turn stages nothing, so lease retries stay clean.
    """

    def __init__(self, committed: list[OpRecord], *, expert_name: str, lap: int) -> None:
        self._committed = list(committed)
        self._expert_name = expert_name
        self._lap = lap
        self.staged: list[OpRecord] = []

    def _all(self) -> list[OpRecord]:
        return self._committed + self.staged

    def _next_seq(self) -> int:
        return max((o.seq for o in self._all()), default=0) + 1

    @property
    def doc_text(self) -> str:
        return fold(self._all()).text

    def tools(self) -> list[type[BaseModel]]:
        return [add_section, edit_section, delete_section, revert_edit]

    def chip(self, name: str, args: dict[str, Any]) -> str | None:
        if name == "add_section":
            return f"Added §{slugify(str(args.get('heading') or ''))}"
        if name == "edit_section":
            return f"Edited §{args.get('anchor')}"
        if name == "delete_section":
            return f"Deleted §{args.get('anchor')}"
        if name == "revert_edit":
            return f"Reverted op {args.get('op')}"
        return None

    async def execute(self, name: str, args: dict[str, Any]) -> str | None:
        if name not in _DOC_TOOL_NAMES:
            return None
        reason = str(args.get("reason") or "").strip()
        try:
            if name == "revert_edit":
                rec = self._validate_revert(args, reason)
            else:
                payload = {k: v for k, v in args.items() if k != "reason" and v is not None}
                # Sanitize at ingestion only — models echo the prompt's {#anchor}
                # annotations and decorate anchors; stored ops must be clean, but
                # historical ops replay untouched so old folds stay byte-identical.
                if "heading" in payload:
                    payload["heading"] = strip_anchor_tag_line(str(payload["heading"]))
                for key in ("text", "new_text"):
                    if key in payload:
                        payload[key] = strip_anchor_tags(str(payload[key]))
                for key in ("anchor", "after_anchor"):
                    if key in payload:
                        payload[key] = normalize_anchor(str(payload[key]))
                rec = OpRecord(
                    seq=self._next_seq(),
                    kind=name,
                    payload=payload,
                    reason=reason,
                    expert_name=self._expert_name,
                    lap=self._lap,
                )
                # Strict dry-run against the working fold: bad anchors fail here,
                # visibly, instead of poisoning the log.
                apply_op(self.doc_text, rec, strict=True)
        except DocOpError as exc:
            return f"Not applied: {exc}"
        self.staged.append(rec)
        anchors = ", ".join(available_anchors(self.doc_text)) or "(no sections yet)"
        return f"Applied. Document sections are now: {anchors}"

    def _validate_revert(self, args: dict[str, Any], reason: str) -> OpRecord:
        target = args.get("op")
        if not isinstance(target, int):
            raise DocOpError("revert_edit needs op=<number> from the operations log")
        by_seq = {o.seq: o for o in self._committed}
        if target not in by_seq:
            if any(o.seq == target for o in self.staged):
                raise DocOpError(
                    "You staged that operation this turn — make a different edit instead"
                )
            raise DocOpError(f"No operation {target} in this room's log")
        if by_seq[target].kind == "baseline":
            raise DocOpError("The baseline cannot be reverted")
        if target in suppressed_seqs(self._all()):
            raise DocOpError(f"Operation {target} is already reverted")
        return OpRecord(
            seq=self._next_seq(),
            kind="revert",
            payload={"target_seq": target, "anchor": by_seq[target].payload.get("anchor", "")},
            reason=reason,
            expert_name=self._expert_name,
            lap=self._lap,
        )


@dataclass
class TurnOutcome:
    act: TurnAct
    tool_chips: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    # Document operations staged during the turn, and the resulting folded text.
    # Persisted atomically with the message by the turn runner.
    staged_ops: list[OpRecord] = field(default_factory=list)
    doc_after: str | None = None


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
    doc_tools = DocTools(context.doc_ops, expert_name=name, lap=lap)
    if tool_providers is not None:
        providers = tool_providers
        doc_tools = next((p for p in providers if isinstance(p, DocTools)), doc_tools)
    else:
        providers = [AttachmentTools(context.attachments), doc_tools]
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
        doc=context.doc_annotated or "(empty — propose something concrete with add_section)",
        blame=context.doc_blame or "(none yet)",
        ops_log=context.doc_ops_log or "(none yet)",
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
        staged = list(doc_tools.staged)
        return TurnOutcome(
            act=act,
            tool_chips=chips,
            citations=citations,
            staged_ops=staged,
            doc_after=doc_tools.doc_text if staged else None,
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

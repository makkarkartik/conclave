from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from conclave.config import settings
from conclave.db.models import Attachment
from conclave.domain.files import read_attachment_text
from conclave.domain.schemas import TurnAct
from conclave.runtime.providers import build_chat_model
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
- When you write_proposal (and for the final shared proposal that becomes the converged
  solution), write **GitHub-flavored Markdown**: clear headings, bullets, numbered steps,
  bold for key decisions, tables when comparing options.
- write_proposal updates both the voted proposal and the Shared Doc the human can open.
  Prefer write_proposal for the solution itself; use edit_shared_doc for append-only notes.

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
- You MUST end your turn with exactly one TurnAct call. Nothing happens until you do.
- Always fill TurnAct.gist: one sentence, max 20 words, third person — it becomes the room's
  permanent ledger of who did what.
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

Current shared proposal:
{proposal}

Room memory (digest of every earlier lap):
{summary}

Turn ledger (who did what, one line per turn):
{ledger}

Shared document:
{doc}

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


class read_attachment(BaseModel):
    """Read an attached file's text content into your context for this turn."""

    file_id: str = Field(description="The id of the attachment to read")


class AttachmentTools:
    def __init__(self, attachments: list[Attachment]) -> None:
        self._by_id = {a.id: a for a in attachments}

    def tools(self) -> list[type[BaseModel]]:
        return [read_attachment] if self._by_id else []

    async def execute(self, name: str, args: dict[str, Any]) -> str | None:
        if name != "read_attachment":
            return None
        att = self._by_id.get(str(args.get("file_id", "")))
        if not att:
            return "No attachment with that id. Available: " + ", ".join(self._by_id)
        return f"[{att.filename}]\n{read_attachment_text(att.path)}"


@dataclass
class TurnOutcome:
    act: TurnAct
    tool_chips: list[str] = field(default_factory=list)


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
    tool_providers: list[ToolProvider] | None = None,
    llm: Any | None = None,
) -> TurnOutcome:
    """One expert turn: a bounded tool loop terminated by a TurnAct call.

    `llm` overrides the provider-built model (tests inject a fake here).
    """
    providers = tool_providers if tool_providers is not None else [AttachmentTools(context.attachments)]
    if llm is None:
        llm = build_chat_model(provider, model, api_key)

    tool_schemas: list[type[BaseModel]] = [TurnAct]
    for p in providers:
        tool_schemas.extend(p.tools())
    bound = llm.bind_tools(tool_schemas)

    direction = (user_direction or "").strip()
    system = SYSTEM.format(
        name=name,
        persona=persona or "Rigorous specialist who challenges weak reasoning, then synthesizes",
    )
    if direction:
        system += "\n" + CHAIR_DIRECTION.format(direction=direction)

    prompt = PROMPT.format(
        topic=topic,
        direction_block=(
            f"BINDING CHAIR DIRECTION (obey):\n{direction}" if direction else "Chair direction: (none)"
        ),
        lap=lap,
        proposal=context.shared_proposal or "(none yet — propose something concrete)",
        summary=context.rolling_summary or "(first lap — no memory yet)",
        ledger=context.gist_ledger or "(empty)",
        doc=context.shared_doc[:4000],
        attachments=context.attachments_blurb or "(none)",
        window=context.transcript_window or "(no turns yet)",
    )

    messages: list[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=prompt)]
    chips: list[str] = []
    nudged = False

    for _ in range(settings.max_tool_iterations):
        response: AIMessage = await bound.ainvoke(messages)
        messages.append(response)
        calls = list(getattr(response, "tool_calls", None) or [])

        submit = next((c for c in calls if c["name"] == "TurnAct"), None)
        if submit is not None:
            return TurnOutcome(act=TurnAct.model_validate(submit["args"]), tool_chips=chips)

        if not calls:
            text = _text_of(response)
            if text:
                # Model answered in prose instead of calling TurnAct — treat as speak.
                return TurnOutcome(
                    act=TurnAct(action="speak", message=text, gist=""), tool_chips=chips
                )
            if nudged:
                break
            nudged = True
            messages.append(HumanMessage(content="Finish your turn now with one TurnAct call."))
            continue

        for call in calls:
            result: str | None = None
            for p in providers:
                result = await p.execute(call["name"], call["args"] or {})
                if result is not None:
                    break
            if result is None:
                result = f"Unknown tool: {call['name']}"
            else:
                chips.append(f"Used {call['name']}")
            messages.append(ToolMessage(content=result[:8000], tool_call_id=call["id"]))

    return TurnOutcome(
        act=TurnAct(action="forfeit", message="", thought="Hit the tool budget without submitting."),
        tool_chips=chips,
    )

"""Deterministic fake LLM for E2E tests: drives any room to convergence.

The first expert to see an empty document seeds the plan section (one add_section
op); everyone after speaks without staking anything, so the room settles exactly
at the MIN_LAPS floor. A small per-call delay keeps the UI's thinking states
observable and gives pause/resume tests room to act.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_NAME_RE = re.compile(r"You are (.+?), a seated expert")
_TOPIC_RE = re.compile(r"^Topic: (.+)$", re.MULTILINE)


def _text(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return str(content or "")


class FakeDeliberator(BaseChatModel):
    model: str = "fake"
    delay: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "fake-deliberator"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeDeliberator:
        return self

    def _result(self, messages: list[BaseMessage]) -> ChatResult:
        system = _text(messages[0].content) if messages else ""
        # The turn prompt is the last *human* message — mid-turn, the tail of the
        # transcript is tool results.
        human = next(
            (_text(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)),
            "",
        )
        name_m = _NAME_RE.search(system)
        topic_m = _TOPIC_RE.search(human)
        if not name_m or not topic_m:
            # Not a turn prompt (e.g. connection test): plain text reply.
            msg = AIMessage(content="ok")
            return ChatResult(generations=[ChatGeneration(message=msg)])

        name = name_m.group(1)
        topic = topic_m.group(1).strip()
        directed = "BINDING CHAIR DIRECTION (obey)" in human or (
            "BINDING CHAIR DIRECTION (obey)" in system
        )

        if "SETTLEMENT POLL" in system:
            # Consent once the plan exists and any chair direction has been
            # spoken to; otherwise claim the floor so a real turn happens.
            plan_missing = "**Decision**: adopt the shared plan" not in human
            direction_unspoken = directed and "Following the chair's direction" not in human
            needs_floor = plan_missing or direction_unspoken
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "PollAct",
                        "id": "call_fake_poll",
                        "type": "tool_call",
                        "args": {
                            "stance": "floor" if needs_floor else "consent",
                            "note": (
                                "Will speak to the chair's direction."
                                if needs_floor
                                else "The shared plan stands; nothing to stake."
                            ),
                        },
                    }
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        if "SEALED DRAFTING" in system:
            # Sealed draft: prose, no TurnAct. Every fake expert drafts the same
            # plan (plus a name-distinct angle so union-seeding has collisions
            # AND orphans to exercise).
            draft = (
                f"## Plan: {topic}\n\n"
                "- **Decision**: adopt the shared plan.\n"
                "- Steps: 1) draft, 2) review, 3) ship.\n\n"
                f"## {name}'s angle\n\nA consideration only {name} raised.\n"
            )
            msg = AIMessage(content=draft)
            return ChatResult(generations=[ChatGeneration(message=msg)])
        spoken = (
            f"Following the chair's direction, I endorse the shared plan for: {topic}."
            if directed
            else f"I stress-tested the plan for '{topic}' and the tradeoffs hold."
        )

        seeded = "**Decision**: adopt the shared plan" in human or any(
            isinstance(m, ToolMessage) for m in messages
        )
        if not seeded:
            # Empty document: seed the plan as one section op, then (next call,
            # after the ToolMessage lands) finish the turn with TurnAct.
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "add_section",
                        "id": "call_fake_seed",
                        "type": "tool_call",
                        "args": {
                            "heading": f"Plan: {topic}",
                            "text": (
                                "- **Decision**: adopt the shared plan.\n"
                                "- Steps: 1) draft, 2) review, 3) ship."
                            ),
                            "reason": "Seed the shared plan",
                        },
                    }
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "TurnAct",
                    "id": "call_fake_0",
                    "type": "tool_call",
                    "args": {
                        "thought": f"{name} deterministic turn (fake provider)",
                        "action": "speak",
                        "message": spoken,
                        "gist": f"{name} endorsed the shared plan",
                    },
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._result(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._result(messages)

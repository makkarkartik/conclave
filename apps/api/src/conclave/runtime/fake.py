"""Deterministic fake LLM for E2E tests: drives any room to convergence.

Every expert writes the same topic-derived proposal and votes agree, so a room
converges exactly at the MIN_LAPS floor. A small per-call delay keeps the UI's
thinking states observable and gives pause/resume tests room to act.
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
from langchain_core.messages import AIMessage, BaseMessage
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
        human = _text(messages[-1].content) if messages else ""
        name_m = _NAME_RE.search(system)
        topic_m = _TOPIC_RE.search(human)
        if not name_m or not topic_m:
            # Not a turn prompt (e.g. connection test): plain text reply.
            msg = AIMessage(content="ok")
            return ChatResult(generations=[ChatGeneration(message=msg)])

        name = name_m.group(1)
        topic = topic_m.group(1).strip()
        directed = "BINDING CHAIR DIRECTION (obey)" in human
        spoken = (
            f"Following the chair's direction, I endorse the shared plan for: {topic}."
            if directed
            else f"I stress-tested the plan for '{topic}' and the tradeoffs hold."
        )
        proposal = (
            f"# Plan: {topic}\n\n"
            "- **Decision**: adopt the shared plan.\n"
            "- Steps: 1) draft, 2) review, 3) ship.\n"
        )
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "TurnAct",
                    "id": "call_fake_0",
                    "type": "tool_call",
                    "args": {
                        "thought": f"{name} deterministic turn (fake provider)",
                        "action": "write_proposal",
                        "message": spoken,
                        "gist": f"{name} endorsed the shared plan",
                        "proposal": proposal,
                        "agree": True,
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

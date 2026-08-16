import pytest

from conclave.config import settings
from conclave.runtime.turn import run_expert_turn
from conclave.services.context import TurnContext


def ctx() -> TurnContext:
    return TurnContext(
        rolling_summary="",
        gist_ledger="",
        transcript_window="",
        shared_doc="# Shared document\n",
        shared_proposal="",
        attachments=[],
    )


async def test_fake_provider_completes_a_turn(monkeypatch):
    monkeypatch.setattr(settings, "enable_fake_provider", True)
    monkeypatch.setattr(settings, "fake_turn_delay", 0.0)
    outcome = await run_expert_turn(
        name="Ada",
        persona="",
        provider="fake",
        model="fake",
        api_key="",
        topic="Ship the canary?",
        user_direction="",
        lap=0,
        context=ctx(),
    )
    assert outcome.act.action == "speak"
    assert outcome.act.blocking_objection is None
    assert outcome.act.gist
    # The fake seeds an empty document with one section op.
    assert [op.kind for op in outcome.staged_ops] == ["add_section"]
    assert "Ship the canary?" in (outcome.doc_after or "")
    assert "**Decision**" in (outcome.doc_after or "")


async def test_fake_provider_gated_by_flag(monkeypatch):
    monkeypatch.setattr(settings, "enable_fake_provider", False)
    with pytest.raises(ValueError, match="disabled"):
        await run_expert_turn(
            name="Ada",
            persona="",
            provider="fake",
            model="fake",
            api_key="",
            topic="t",
            user_direction="",
            lap=0,
            context=ctx(),
        )

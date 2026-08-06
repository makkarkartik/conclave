from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from conclave.domain.schemas import TurnAct
from conclave.runtime.providers import build_chat_model

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
  (meta-governance of the verifier of the verifier…) are polish — fold them lightly or drop them.
- Default stance is disagree. A coherent first draft is not enough to agree.
- Keep spoken messages concise (2–5 sentences). Thoughts may be longer.
- When you write_proposal (and for the final shared proposal that becomes the converged
  solution), write **GitHub-flavored Markdown**: clear headings, bullets, numbered steps,
  bold for key decisions, and tables when comparing options. Do not dump one plain paragraph
  if structure helps. The UI renders the converged solution as Markdown.
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
Do not agree just because the text is tidy or another expert already agreed.

Actions (exactly one per turn):
- speak: critique, question, or synthesize
- write_proposal: speak AND set/update the shared proposal as Markdown (prefer this when you have a fix)
- read_file: reference an attachment by file_id (ids listed below)
- edit_shared_doc: append or replace the collaborative shared document
- forfeit: pass only if you truly have nothing new; still leave a brief thought
"""

CHAIR_DIRECTION = """
BINDING CHAIR DIRECTION — this overrides conflicting norms above for this turn:
{direction}

Obey it. If the chair says converge, stop nitpicking, change focus, accept a tradeoff, or
revise the proposal a certain way: do that. Do not ignore or soft-pedal chair direction.
"""


async def run_expert_turn(
    *,
    name: str,
    persona: str,
    provider: str,
    model: str,
    api_key: str,
    topic: str,
    user_direction: str,
    transcript: str,
    shared_proposal: str,
    shared_doc: str,
    attachments_blurb: str,
    lap: int = 0,
) -> TurnAct:
    llm = build_chat_model(provider, model, api_key).with_structured_output(TurnAct)
    direction = (user_direction or "").strip()
    system = SYSTEM.format(
        name=name,
        persona=persona or "Rigorous specialist who challenges weak reasoning, then synthesizes",
    )
    if direction:
        system = system + "\n" + CHAIR_DIRECTION.format(direction=direction)

    direction_block = (
        f"BINDING CHAIR DIRECTION (obey):\n{direction}"
        if direction
        else "Chair direction: (none)"
    )
    prompt = f"""Topic: {topic}

{direction_block}

Deliberation lap: {lap}

Current shared proposal:
{shared_proposal or "(none yet — propose something concrete)"}

Shared document:
{shared_doc[:4000]}

Attachments:
{attachments_blurb or "(none)"}

Transcript so far:
{transcript[-12000:]}

It is your turn. Respond with structured fields.
"""
    result = await llm.ainvoke(
        [
            SystemMessage(content=system),
            HumanMessage(content=prompt),
        ]
    )
    if isinstance(result, TurnAct):
        return result
    return TurnAct.model_validate(result)

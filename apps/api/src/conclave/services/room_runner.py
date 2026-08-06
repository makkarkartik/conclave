from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from conclave.db.models import Conversation, Expert, Message
from conclave.db.session import SessionLocal
from conclave.domain.converge import can_converge
from conclave.domain.diff import format_doc_change
from conclave.domain.files import (
    edit_shared_doc,
    read_attachment_text,
    read_shared_doc,
    write_shared_doc,
)
from conclave.runtime.react_turn import run_expert_turn
from conclave.services.events import bus
from conclave.services.messages import serialize_message

SAFETY_LAP_CEILING = 40

_tasks: dict[str, asyncio.Task] = {}
_pause_flags: dict[str, asyncio.Event] = {}


class RoomState(TypedDict, total=False):
    conversation_id: str
    status: str
    chair_index: int
    lap: int
    lap_votes: list[dict[str, Any]]
    stop: bool


def _get_pause_event(conversation_id: str) -> asyncio.Event:
    if conversation_id not in _pause_flags:
        ev = asyncio.Event()
        ev.set()  # not paused
        _pause_flags[conversation_id] = ev
    return _pause_flags[conversation_id]


def request_pause(conversation_id: str) -> None:
    _get_pause_event(conversation_id).clear()


def request_resume(conversation_id: str) -> None:
    _get_pause_event(conversation_id).set()


def is_running(conversation_id: str) -> bool:
    t = _tasks.get(conversation_id)
    return t is not None and not t.done()


def stop_room(conversation_id: str) -> None:
    """Cancel an in-flight room task and clear pause state (used on delete)."""
    request_pause(conversation_id)
    task = _tasks.pop(conversation_id, None)
    if task and not task.done():
        task.cancel()
    _pause_flags.pop(conversation_id, None)


async def _observe_and_act(state: RoomState) -> RoomState:
    cid = state["conversation_id"]
    await _get_pause_event(cid).wait()

    db = SessionLocal()
    try:
        conv: Conversation | None = db.get(Conversation, cid)
        if not conv or conv.status != "running":
            return {**state, "stop": True, "status": conv.status if conv else "stopped"}

        chairs = conv.chair_ids
        if not chairs:
            conv.status = "paused"
            db.commit()
            return {**state, "stop": True, "status": "paused"}

        idx = state.get("chair_index", conv.chair_index) % len(chairs)
        expert = db.get(Expert, chairs[idx])
        if not expert:
            return {**state, "chair_index": (idx + 1) % len(chairs), "stop": False}

        await bus.publish(
            cid,
            "floor",
            {"expert_id": expert.id, "expert_name": expert.name, "lap": state.get("lap", 0)},
        )

        messages = (
            db.query(Message)
            .filter(Message.conversation_id == cid)
            .order_by(Message.created_at.asc())
            .all()
        )
        transcript = "\n\n".join(
            f"{m.expert_name} ({m.action}): {m.content}\nThought: {m.thought}" for m in messages
        )
        attachments = conv.attachments
        att_blurb = "\n".join(f"- id={a.id} name={a.filename}" for a in attachments)
        shared_doc = read_shared_doc(cid)

        await bus.publish(cid, "thinking", {"expert_id": expert.id, "expert_name": expert.name})

        try:
            act = await run_expert_turn(
                name=expert.name,
                persona=expert.persona,
                provider=expert.provider,
                model=expert.model,
                api_key=expert.api_key,
                topic=conv.topic,
                user_direction=conv.user_direction,
                transcript=transcript,
                shared_proposal=conv.shared_proposal,
                shared_doc=shared_doc,
                attachments_blurb=att_blurb,
                lap=state.get("lap", 0),
            )
        except Exception as exc:  # noqa: BLE001
            msg = Message(
                id=str(uuid.uuid4()),
                conversation_id=cid,
                expert_id=expert.id,
                expert_name=expert.name,
                provider=expert.provider,
                model=expert.model,
                thought=f"Error during turn: {exc}",
                content="I hit an error and must pass.",
                action="forfeit",
            )
            msg.chips = ["Error"]
            db.add(msg)
            db.commit()
            await bus.publish(cid, "act", serialize_message(msg))
            return {
                **state,
                "chair_index": (idx + 1) % len(chairs),
                "lap_votes": state.get("lap_votes", [])
                + [{"expert_id": expert.id, "agree": False, "proposal": "", "forfeit": True}],
            }

        chips: list[str] = []
        content = act.message or ""
        doc_diff = ""
        if act.action == "forfeit":
            content = content or "Passed — listening."
            chips.append("Passed")
        if act.action == "write_proposal" and act.proposal:
            before_doc = read_shared_doc(cid)
            conv.shared_proposal = act.proposal
            # Keep the human-visible Shared Doc in sync with the working proposal.
            write_shared_doc(cid, act.proposal)
            doc_diff = format_doc_change(before_doc, act.proposal, mode="replace")
            chips.append("Updated proposal")
            chips.append("Updated shared doc")
            content = content or "Updated the shared proposal and document."
            await bus.publish(
                cid,
                "doc_updated",
                {"content": act.proposal, "diff": doc_diff, "mode": "replace"},
            )
        if act.action == "read_file" and act.file_id:
            att = next((a for a in attachments if a.id == act.file_id), None)
            if att:
                excerpt = read_attachment_text(att.path)
                content = (content + f"\n\n(Read {att.filename})\n{excerpt[:1500]}").strip()
                chips.append(f"Read {att.filename}")
        if act.action == "edit_shared_doc":
            doc_body = (act.doc_edit_content or act.proposal or act.message or "").strip()
            if doc_body:
                mode = act.doc_edit_mode or "append"
                before_doc = read_shared_doc(cid)
                edit_shared_doc(cid, mode, doc_body)
                after_doc = read_shared_doc(cid)
                doc_diff = format_doc_change(before_doc, after_doc, mode=mode)
                chips.append("Updated shared doc")
                await bus.publish(
                    cid,
                    "doc_updated",
                    {"content": after_doc, "diff": doc_diff, "mode": mode},
                )
                content = content or (
                    "Appended to the shared document."
                    if mode == "append"
                    else "Replaced the shared document."
                )

        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=cid,
            expert_id=expert.id,
            expert_name=expert.name,
            provider=expert.provider,
            model=expert.model,
            thought=act.thought or "",
            content=content,
            action=act.action,
            doc_diff=doc_diff,
        )
        msg.chips = chips
        db.add(msg)
        conv.chair_index = (idx + 1) % len(chairs)
        db.commit()
        db.refresh(msg)
        await bus.publish(cid, "act", serialize_message(msg))

        vote = {
            "expert_id": expert.id,
            "agree": bool(act.agree) and act.action != "forfeit",
            "proposal": act.proposal or conv.shared_proposal,
            "forfeit": act.action == "forfeit",
        }
        return {
            **state,
            "chair_index": conv.chair_index,
            "lap_votes": state.get("lap_votes", []) + [vote],
            "stop": False,
        }
    finally:
        db.close()


async def _lap_check(state: RoomState) -> RoomState:
    cid = state["conversation_id"]
    db = SessionLocal()
    try:
        conv = db.get(Conversation, cid)
        if not conv:
            return {**state, "stop": True}

        chairs = conv.chair_ids
        # Completed a lap when chair_index wrapped to 0 after acting
        if state.get("chair_index", 0) != 0:
            return {**state, "stop": False}

        lap = state.get("lap", 0) + 1
        conv.lap = lap
        votes = state.get("lap_votes", [])
        active = [v for v in votes if not v.get("forfeit")]

        if can_converge(lap=lap, chair_count=len(chairs), votes=votes):
            solution = active[0].get("proposal") or conv.shared_proposal
            conv.shared_proposal = solution
            conv.converged_solution = solution
            conv.status = "converged"
            db.commit()
            await bus.publish(cid, "converged", {"solution": solution, "lap": lap})
            return {**state, "lap": lap, "lap_votes": [], "stop": True, "status": "converged"}

        if lap >= SAFETY_LAP_CEILING:
            conv.status = "safety_pause"
            db.commit()
            await bus.publish(
                cid,
                "paused",
                {"reason": "safety", "message": "Paused — add direction to continue."},
            )
            return {**state, "lap": lap, "lap_votes": [], "stop": True, "status": "safety_pause"}

        if not _get_pause_event(cid).is_set():
            conv.status = "paused"
            db.commit()
            await bus.publish(cid, "paused", {"reason": "user"})
            return {**state, "lap": lap, "lap_votes": [], "stop": True, "status": "paused"}

        db.commit()
        return {**state, "lap": lap, "lap_votes": [], "stop": False}
    finally:
        db.close()


def _route_after_act(state: RoomState) -> Literal["lap_check", "observe_and_act", "__end__"]:
    if state.get("stop"):
        return END  # type: ignore[return-value]
    if state.get("chair_index", 0) == 0 and state.get("lap_votes"):
        return "lap_check"
    return "observe_and_act"


def _route_after_lap(state: RoomState) -> Literal["observe_and_act", "__end__"]:
    if state.get("stop"):
        return END  # type: ignore[return-value]
    return "observe_and_act"


def build_graph():
    g = StateGraph(RoomState)
    g.add_node("observe_and_act", _observe_and_act)
    g.add_node("lap_check", _lap_check)
    g.set_entry_point("observe_and_act")
    g.add_conditional_edges("observe_and_act", _route_after_act)
    g.add_conditional_edges("lap_check", _route_after_lap)
    return g.compile()


_graph = build_graph()


async def _run_room(conversation_id: str) -> None:
    try:
        await _graph.ainvoke(
            {
                "conversation_id": conversation_id,
                "status": "running",
                "chair_index": 0,
                "lap": 0,
                "lap_votes": [],
                "stop": False,
            },
            config={"recursion_limit": 500},
        )
    except Exception as exc:  # noqa: BLE001
        await bus.publish(conversation_id, "error", {"message": str(exc)})
        db = SessionLocal()
        try:
            conv = db.get(Conversation, conversation_id)
            if conv and conv.status == "running":
                conv.status = "paused"
                db.commit()
        finally:
            db.close()
    finally:
        _tasks.pop(conversation_id, None)


def start_room(conversation_id: str, db: Session) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError("Conversation not found")
    if len(conv.chair_ids) < 2:
        raise ValueError("Seat at least two experts")
    if is_running(conversation_id):
        return conv
    conv.status = "running"
    conv.chair_index = 0
    db.commit()
    request_resume(conversation_id)
    _tasks[conversation_id] = asyncio.create_task(_run_room(conversation_id))
    return conv


def pause_room(conversation_id: str, db: Session, direction: str = "") -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError("Conversation not found")
    request_pause(conversation_id)
    if direction:
        conv.user_direction = direction
    conv.status = "paused"
    db.commit()
    return conv


def resume_room(conversation_id: str, db: Session, direction: str = "") -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise ValueError("Conversation not found")
    if direction:
        conv.user_direction = direction
    conv.status = "running"
    db.commit()
    request_resume(conversation_id)
    if not is_running(conversation_id):
        _tasks[conversation_id] = asyncio.create_task(_run_room(conversation_id))
    return conv

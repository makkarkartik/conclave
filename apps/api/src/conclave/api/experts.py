from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from conclave.api.serializers import expert_out
from conclave.db.models import Expert
from conclave.db.session import get_db
from conclave.domain.schemas import ExpertCreate, ExpertOut, ExpertUpdate
from conclave.runtime.providers import test_connection

router = APIRouter(prefix="/experts", tags=["experts"])


@router.get("", response_model=list[ExpertOut])
def list_experts(db: Session = Depends(get_db)):
    rows = db.query(Expert).order_by(Expert.created_at.desc()).all()
    return [expert_out(e) for e in rows]


@router.post("", response_model=ExpertOut)
def create_expert(body: ExpertCreate, db: Session = Depends(get_db)):
    e = Expert(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        persona=body.persona,
        provider=body.provider,
        model=body.model.strip(),
        api_key=body.api_key.strip(),
        accent=body.accent,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return expert_out(e)


@router.patch("/{expert_id}", response_model=ExpertOut)
def update_expert(expert_id: str, body: ExpertUpdate, db: Session = Depends(get_db)):
    e = db.get(Expert, expert_id)
    if not e:
        raise HTTPException(404, "Expert not found")
    data = body.model_dump(exclude_unset=True)
    # Empty api_key means "keep existing" (UI leaves the field blank on edit).
    if "api_key" in data and (data["api_key"] is None or not str(data["api_key"]).strip()):
        data.pop("api_key")
    for k, v in data.items():
        if isinstance(v, str) and k != "persona":
            v = v.strip()
            if not v and k in ("name", "model"):
                raise HTTPException(400, f"{k} required")
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return expert_out(e)


@router.delete("/{expert_id}")
def delete_expert(expert_id: str, db: Session = Depends(get_db)):
    e = db.get(Expert, expert_id)
    if not e:
        raise HTTPException(404, "Expert not found")
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.post("/{expert_id}/test")
async def test_expert(expert_id: str, db: Session = Depends(get_db)):
    e = db.get(Expert, expert_id)
    if not e:
        raise HTTPException(404, "Expert not found")
    try:
        reply = await test_connection(e.provider, e.model, e.api_key)
        return {"ok": True, "reply": reply}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Connection failed: {exc}") from exc

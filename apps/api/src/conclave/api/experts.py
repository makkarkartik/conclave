from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.api.serializers import expert_out
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Expert
from conclave.db.session import get_db
from conclave.domain.crypto import decrypt_secret, encrypt_secret
from conclave.domain.mask import mask_key
from conclave.domain.schemas import ExpertCreate, ExpertOut, ExpertUpdate
from conclave.runtime.providers import test_connection

router = APIRouter(prefix="/experts", tags=["experts"])


@router.get("", response_model=list[ExpertOut])
async def list_experts(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(Expert)
        .where(Expert.tenant_id == DEFAULT_TENANT_ID)
        .order_by(Expert.created_at.desc())
    )
    return [expert_out(e) for e in rows]


@router.post("", response_model=ExpertOut)
async def create_expert(body: ExpertCreate, db: AsyncSession = Depends(get_db)):
    key = body.api_key.strip()
    e = Expert(
        id=new_id(),
        tenant_id=DEFAULT_TENANT_ID,
        name=body.name.strip(),
        persona=body.persona,
        provider=body.provider,
        model=body.model.strip(),
        api_key_encrypted=encrypt_secret(key),
        api_key_hint=mask_key(key),
        accent=body.accent,
    )
    db.add(e)
    await db.commit()
    return expert_out(e)


@router.patch("/{expert_id}", response_model=ExpertOut)
async def update_expert(expert_id: str, body: ExpertUpdate, db: AsyncSession = Depends(get_db)):
    e = await db.get(Expert, expert_id)
    if not e or e.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(404, "Expert not found")
    data = body.model_dump(exclude_unset=True)
    # Empty api_key means "keep existing" (UI leaves the field blank on edit).
    key = str(data.pop("api_key", "") or "").strip()
    if key:
        e.api_key_encrypted = encrypt_secret(key)
        e.api_key_hint = mask_key(key)
    for k, v in data.items():
        if isinstance(v, str) and k != "persona":
            v = v.strip()
            if not v and k in ("name", "model"):
                raise HTTPException(400, f"{k} required")
        setattr(e, k, v)
    await db.commit()
    return expert_out(e)


@router.delete("/{expert_id}")
async def delete_expert(expert_id: str, db: AsyncSession = Depends(get_db)):
    e = await db.get(Expert, expert_id)
    if not e or e.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(404, "Expert not found")
    await db.delete(e)
    await db.commit()
    return {"ok": True}


@router.post("/{expert_id}/test")
async def test_expert(expert_id: str, db: AsyncSession = Depends(get_db)):
    e = await db.get(Expert, expert_id)
    if not e or e.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(404, "Expert not found")
    try:
        reply = await test_connection(e.provider, e.model, decrypt_secret(e.api_key_encrypted))
        return {"ok": True, "reply": reply}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Connection failed: {exc}") from exc

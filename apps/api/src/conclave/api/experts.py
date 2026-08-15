from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.api.serializers import expert_out
from conclave.db.ids import new_id
from conclave.db.models import DEFAULT_TENANT_ID, Expert, ProviderKey
from conclave.db.session import get_db
from conclave.domain.crypto import decrypt_secret, encrypt_secret
from conclave.domain.mask import mask_key
from conclave.domain.schemas import ExpertCreate, ExpertOut, ExpertUpdate
from conclave.runtime.providers import test_connection
from conclave.services.keys import get_provider_key, resolve_api_key, set_provider_key

router = APIRouter(prefix="/experts", tags=["experts"])


async def _provider_hints(db: AsyncSession) -> dict[str, str]:
    rows = await db.scalars(
        select(ProviderKey).where(ProviderKey.tenant_id == DEFAULT_TENANT_ID)
    )
    return {r.provider: r.key_hint for r in rows}


@router.get("", response_model=list[ExpertOut])
async def list_experts(db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(Expert)
        .where(Expert.tenant_id == DEFAULT_TENANT_ID)
        .order_by(Expert.created_at.desc())
    )
    hints = await _provider_hints(db)
    return [expert_out(e, hints) for e in rows]


@router.post("", response_model=ExpertOut)
async def create_expert(body: ExpertCreate, db: AsyncSession = Depends(get_db)):
    key = body.api_key.strip()
    shared = await get_provider_key(db, DEFAULT_TENANT_ID, body.provider)

    own = ""
    if key:
        if shared is None:
            # First key for this provider becomes the tenant's shared key
            await set_provider_key(db, DEFAULT_TENANT_ID, body.provider, key)
        elif decrypt_secret(shared.key_encrypted) == key:
            pass  # same key pasted again — reuse the shared one, no override
        else:
            own = key  # explicitly different key — expert-specific override
    elif shared is None:
        raise HTTPException(
            400, f"No stored {body.provider} key — provide api_key for the first expert"
        )

    e = Expert(
        id=new_id(),
        tenant_id=DEFAULT_TENANT_ID,
        name=body.name.strip(),
        persona=body.persona,
        provider=body.provider,
        model=body.model.strip(),
        api_key_encrypted=encrypt_secret(own) if own else "",
        api_key_hint=mask_key(own) if own else "",
        accent=body.accent,
    )
    db.add(e)
    await db.commit()
    return expert_out(e, await _provider_hints(db))


@router.patch("/{expert_id}", response_model=ExpertOut)
async def update_expert(expert_id: str, body: ExpertUpdate, db: AsyncSession = Depends(get_db)):
    e = await db.get(Expert, expert_id)
    if not e or e.tenant_id != DEFAULT_TENANT_ID:
        raise HTTPException(404, "Expert not found")
    data = body.model_dump(exclude_unset=True)

    # Key semantics follow intent: a new key on an expert that uses the shared
    # provider key rotates the shared key; on an expert with its own override it
    # updates the override. use_provider_key=True drops the override.
    key = str(data.pop("api_key", "") or "").strip()
    use_shared = data.pop("use_provider_key", None)
    if key:
        if e.api_key_encrypted:
            e.api_key_encrypted = encrypt_secret(key)
            e.api_key_hint = mask_key(key)
        else:
            await set_provider_key(db, DEFAULT_TENANT_ID, e.provider, key)
    if use_shared:
        e.api_key_encrypted = ""
        e.api_key_hint = ""

    for k, v in data.items():
        if isinstance(v, str) and k != "persona":
            v = v.strip()
            if not v and k in ("name", "model"):
                raise HTTPException(400, f"{k} required")
        setattr(e, k, v)
    await db.commit()
    return expert_out(e, await _provider_hints(db))


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
        reply = await test_connection(e.provider, e.model, await resolve_api_key(db, e))
        return {"ok": True, "reply": reply}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Connection failed: {exc}") from exc

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.db.models import DEFAULT_TENANT_ID, Expert, ProviderKey
from conclave.db.session import get_db
from conclave.domain.schemas import ProviderKeyOut, ProviderKeyPut
from conclave.services.keys import get_provider_key, set_provider_key

router = APIRouter(prefix="/provider-keys", tags=["provider-keys"])


@router.get("", response_model=list[ProviderKeyOut])
async def list_provider_keys(db: AsyncSession = Depends(get_db)):
    keys = (
        await db.scalars(
            select(ProviderKey).where(ProviderKey.tenant_id == DEFAULT_TENANT_ID)
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(Expert.provider, func.count())
                .where(Expert.tenant_id == DEFAULT_TENANT_ID, Expert.api_key_encrypted == "")
                .group_by(Expert.provider)
            )
        ).all()
    )
    return [
        ProviderKeyOut(
            provider=k.provider,
            key_hint=k.key_hint,
            expert_count=counts.get(k.provider, 0),
            updated_at=k.updated_at,
        )
        for k in keys
    ]


@router.put("/{provider}", response_model=ProviderKeyOut)
async def put_provider_key(
    provider: str, body: ProviderKeyPut, db: AsyncSession = Depends(get_db)
):
    key = body.api_key.strip()
    if not key:
        raise HTTPException(400, "api_key required")
    pk = await set_provider_key(db, DEFAULT_TENANT_ID, provider.lower(), key)
    await db.commit()
    return ProviderKeyOut(provider=pk.provider, key_hint=pk.key_hint, updated_at=pk.updated_at)


@router.delete("/{provider}")
async def delete_provider_key(provider: str, db: AsyncSession = Depends(get_db)):
    pk = await get_provider_key(db, DEFAULT_TENANT_ID, provider.lower())
    if pk is None:
        raise HTTPException(404, "No key for that provider")
    await db.delete(pk)
    await db.commit()
    return {"ok": True}

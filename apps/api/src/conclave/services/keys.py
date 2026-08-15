"""Provider-key resolution: an expert's own override wins, else the tenant's
shared key for that provider."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from conclave.db.ids import new_id
from conclave.db.models import Expert, ProviderKey
from conclave.domain.crypto import decrypt_secret, encrypt_secret
from conclave.domain.mask import mask_key


async def get_provider_key(
    db: AsyncSession, tenant_id: str, provider: str
) -> ProviderKey | None:
    return await db.scalar(
        select(ProviderKey).where(
            ProviderKey.tenant_id == tenant_id, ProviderKey.provider == provider
        )
    )


async def set_provider_key(
    db: AsyncSession, tenant_id: str, provider: str, plaintext: str
) -> ProviderKey:
    """Upsert the tenant's shared key for a provider (rotation included)."""
    pk = await get_provider_key(db, tenant_id, provider)
    if pk is None:
        pk = ProviderKey(id=new_id(), tenant_id=tenant_id, provider=provider,
                         key_encrypted="", key_hint="")
        db.add(pk)
    pk.key_encrypted = encrypt_secret(plaintext)
    pk.key_hint = mask_key(plaintext)
    return pk


async def resolve_api_key(db: AsyncSession, expert: Expert) -> str:
    """The key an expert's turns run on: own override first, else the shared key."""
    if expert.api_key_encrypted:
        return decrypt_secret(expert.api_key_encrypted)
    pk = await get_provider_key(db, expert.tenant_id, expert.provider)
    return decrypt_secret(pk.key_encrypted) if pk else ""

from __future__ import annotations

from uuid6 import uuid7


def new_id() -> str:
    """UUIDv7 as canonical string: time-ordered for B-tree locality, no cross-shard coordination."""
    return str(uuid7())

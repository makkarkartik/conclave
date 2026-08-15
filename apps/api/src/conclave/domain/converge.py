from __future__ import annotations

import hashlib
import re
from typing import Any

# Soft floor: prompt alone is not enough — rooms cannot converge on lap 1-2 chumminess.
MIN_LAPS_BEFORE_CONVERGE = 3


def normalize_proposal(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def proposal_fingerprint(text: str) -> str:
    """Stable hash of a normalized proposal; stored per turn so lap votes are
    comparable from DB rows alone (no in-memory state)."""
    norm = normalize_proposal(text)
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def lap_converged(*, laps_done: int, chair_count: int, turns: list[dict[str, Any]]) -> bool:
    """True when a full lap of non-forfeit turns endorses one identical proposal
    after enough debate.

    `turns` are the completed lap's rows: {agree: bool, forfeit: bool, proposal_hash: str}.
    """
    if laps_done < MIN_LAPS_BEFORE_CONVERGE:
        return False
    active = [t for t in turns if not t.get("forfeit")]
    if len(active) < max(2, chair_count - 1):
        return False
    if not all(t.get("agree") for t in active):
        return False
    hashes = {t.get("proposal_hash") or "" for t in active}
    return len(hashes) == 1 and "" not in hashes

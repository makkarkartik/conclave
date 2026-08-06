from __future__ import annotations

import re

# Soft floor: prompt alone is not enough — rooms cannot converge on lap 1–2 chumminess.
MIN_LAPS_BEFORE_CONVERGE = 3


def normalize_proposal(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    return cleaned


def proposals_agree(proposals: list[str]) -> bool:
    norms = [normalize_proposal(p) for p in proposals if normalize_proposal(p)]
    if len(norms) < 2:
        return False
    return len(set(norms)) == 1


def can_converge(
    *,
    lap: int,
    chair_count: int,
    votes: list[dict],
) -> bool:
    """True when a full lap of non-forfeit votes endorses one shared proposal after enough debate."""
    if lap < MIN_LAPS_BEFORE_CONVERGE:
        return False
    active = [v for v in votes if not v.get("forfeit")]
    if len(active) < max(2, chair_count - 1):
        return False
    if not all(v.get("agree") for v in active):
        return False
    proposals = [v.get("proposal") or "" for v in active]
    return proposals_agree(proposals)

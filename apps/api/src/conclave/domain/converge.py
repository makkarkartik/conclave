from __future__ import annotations

from typing import Any

# Soft floor: prompt alone is not enough — rooms cannot converge on lap 1-2 chumminess.
MIN_LAPS_BEFORE_CONVERGE = 3


def lap_settled(*, laps_done: int, chair_count: int, turns: list[dict[str, Any]]) -> bool:
    """Protocol v2 convergence (§6): the room converges when a full lap passes in
    which no expert staked a document operation or a blocking objection. Silence
    is consent — and unlike v1's fingerprint votes, one polish edit per lap can
    no longer hold the room open forever, because the editor pays for it by
    restarting the quiet-lap clock, visibly, under their own name.

    `turns` are the completed lap's rows: {forfeit: bool, staked: bool}.
    """
    if laps_done < MIN_LAPS_BEFORE_CONVERGE:
        return False
    active = [t for t in turns if not t.get("forfeit")]
    # An all-error or mostly-forfeit lap must not settle a room by default.
    if len(active) < max(2, chair_count - 1):
        return False
    return not any(t.get("staked") for t in active)

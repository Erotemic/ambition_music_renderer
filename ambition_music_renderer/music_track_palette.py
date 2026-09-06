"""Stable semantic track colors shared by music authoring UIs.

A single group can always receive a deterministic fallback color.  When the UI
knows the complete cue's group set, :func:`group_palette_hsl` spaces those hues
across the wheel so simultaneously visible stems cannot accidentally collapse
to nearly the same color.
"""

from __future__ import annotations

import hashlib
from typing import Iterable


_SATURATION = 155
_LIGHTNESS = 145
_PALETTE_OFFSET_DEGREES = 210.0


def group_hsl(group: str) -> tuple[int, int, int]:
    """Return a deterministic fallback HSL color for one group name."""
    digest = hashlib.sha256(group.encode("utf8")).digest()
    hue = int.from_bytes(digest[:2], "big") % 360
    return hue, _SATURATION, _LIGHTNESS


def group_palette_hsl(groups: Iterable[str]) -> dict[str, tuple[int, int, int]]:
    """Assign maximally separated hues to the complete set of visible groups.

    Ordering is lexical and therefore deterministic for an unchanged cue.  The
    complete group set should be used rather than only enabled/routed groups so
    toggling a stem never changes the colors of its neighbors.
    """
    names = sorted({str(group) for group in groups if str(group)})
    if not names:
        return {}
    step = 360.0 / len(names)
    return {
        name: (int(round((_PALETTE_OFFSET_DEGREES + index * step) % 360.0)) % 360, _SATURATION, _LIGHTNESS)
        for index, name in enumerate(names)
    }

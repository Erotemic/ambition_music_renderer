"""Explain silent sampled-instrument renders using the MIDI actually sent to sfizz.

This is a failure-only *diagnostic*, not a second SFZ parser or an attempt to
predict which regions a particular sampler will activate. Keep authoritative
range parsing in ``backends.sfizz_backend`` and report controller conditions as
clues rather than claiming that any one condition necessarily caused silence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pretty_midi

from ..backends.sfizz_backend import sfz_key_span


_CC_CONDITION_RE = re.compile(
    r"(?<![A-Za-z0-9_])(locc|hicc|amplitude_oncc)(\d{1,3})\s*=\s*(-?\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)


def _pitch(pitch: int) -> str:
    return f"{pitch} ({pretty_midi.note_number_to_name(pitch)})"


def _cc_conditions(path: Path) -> dict[int, list[str]]:
    """Return a compact inventory of literal CC conditions in one SFZ file.

    Includes/macros, opcodes inherited between SFZ regions and the exact
    sampler-specific defaults are deliberately outside this diagnostic.
    """
    try:
        text = path.read_text(encoding="utf8", errors="replace")
    except OSError:
        return {}
    conditions: dict[int, set[str]] = {}
    for op, number, value in _CC_CONDITION_RE.findall(text):
        cc = int(number)
        if not 0 <= cc <= 127:
            continue
        description = {
            "locc": ">=",
            "hicc": "<=",
            "amplitude_oncc": "amplitude_oncc=",
        }[op.lower()] + value
        conditions.setdefault(cc, set()).add(description)
    return {cc: sorted(values) for cc, values in sorted(conditions.items())}


def silent_sfz_diagnostic(
    inst: pretty_midi.Instrument,
    sfz_path: str | Path,
    *,
    library_ref: str | None = None,
) -> str:
    """Describe a zero/near-zero audio render without asserting an unproven cause."""
    sfz = Path(sfz_path)
    notes = list(inst.notes)
    lines = [
        f"instrument {inst.name!r} SFZ {sfz} rendered SILENCE despite active notes",
        f"  catalog reference: {library_ref or '(none; explicit SFZ)'}",
    ]
    if not notes:
        lines.append("  MIDI notes: none (unexpected at the silence-check call site)")
        return "\n".join(lines)
    lo, hi = min(n.pitch for n in notes), max(n.pitch for n in notes)
    first_onset = min(n.start for n in notes)
    velocities = [n.velocity for n in notes]
    lines.append(
        f"  MIDI notes: {len(notes)}, range {_pitch(lo)} .. {_pitch(hi)}, "
        f"velocity {min(velocities)}..{max(velocities)}, first onset {first_onset:.3f}s"
    )
    span = sfz_key_span(str(sfz))
    if span is None:
        lines.append("  SFZ key span: unknown (could not parse mapped keys)")
    else:
        outside = sum(n.pitch < span[0] or n.pitch > span[1] for n in notes)
        lines.append(
            f"  SFZ key span: {_pitch(span[0])} .. {_pitch(span[1])}; "
            f"notes outside: {outside}/{len(notes)}"
        )
        if outside == len(notes):
            lines.append("  LIKELY ISSUE: every played note falls outside the sampled key span")

    # Controllers at the first sounding note are the most useful activation
    # clue. A later CC does not activate notes that already finished.
    startup: dict[int, int] = {}
    for cc in sorted(inst.control_changes, key=lambda event: event.time):
        if cc.time > first_onset + 1e-7:
            break
        startup[int(cc.number)] = int(cc.value)
    conditions = _cc_conditions(sfz)
    relevant = sorted(set(startup) | set(conditions))
    if relevant:
        lines.append(
            "  MIDI controllers by first note: "
            + ", ".join(
                f"CC{cc}={startup[cc] if cc in startup else 'UNSET'}" for cc in relevant
            )
        )
    else:
        lines.append("  MIDI controllers by first note: none")
    if conditions:
        lines.append(
            "  SFZ controller conditions (informational, not full region evaluation): "
            + ", ".join(
                f"CC{cc} {' / '.join(values)}" for cc, values in conditions.items()
            )
        )
        possible_gates = []
        for cc, values in conditions.items():
            if cc in startup:
                continue
            thresholds = [float(v[2:]) for v in values if v.startswith(">=")]
            if thresholds and min(thresholds) > 0:
                possible_gates.append(f"CC{cc} (SFZ has minimum {min(thresholds):g})")
            elif any(v.startswith("amplitude_oncc=") for v in values):
                possible_gates.append(f"CC{cc} (SFZ controls amplitude)")
        if possible_gates:
            lines.append(
                "  POSSIBLE ISSUE: no startup value for "
                + ", ".join(possible_gates)
                + "; check the selected patch's controller requirements"
            )
    lines.append(
        "  Next: verify the resolved SFZ's keyswitch/CC requirements and sample files "
        "using 'instruments doctor'; if the patch uses a gated CC, initialize it "
        "under instruments[].controls in the score."
    )
    return "\n".join(lines)

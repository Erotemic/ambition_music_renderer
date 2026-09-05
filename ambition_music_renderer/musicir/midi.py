"""Shared MIDI-instrument construction for all MusicIR frontends."""

from __future__ import annotations

from typing import Any, Mapping

import pretty_midi

from ..render.score_core import CC_NUMBERS, GM_PROGRAMS
from ..render.score_theory import clamp


def create_midi_instrument(spec: Mapping[str, Any]) -> pretty_midi.Instrument:
    """Create the PrettyMIDI instrument represented by one canonical spec."""

    name = str(spec["name"])
    if bool(spec.get("is_drum", False)):
        return pretty_midi.Instrument(program=0, is_drum=True, name=name)
    program_name = spec.get("program", "string_ensemble_1")
    if isinstance(program_name, int):
        program = int(program_name)
    elif program_name in GM_PROGRAMS:
        program = GM_PROGRAMS[program_name]
    else:
        raise ValueError(
            f"instrument {name!r}: unknown program {program_name!r}. "
            "Use a GM program name or an int 0-127. "
            f"Valid names: {', '.join(sorted(GM_PROGRAMS))}"
        )
    return pretty_midi.Instrument(program=program, is_drum=False, name=name)


def initial_control_values(spec: Mapping[str, Any]) -> dict[int, int]:
    """Return canonical t=0 controller state for one instrument.

    Explicit ``controls`` entries win over convenience fields when both address
    the same controller.  Existing committed scores do not depend on duplicate
    declarations, and making precedence explicit removes the v1/v2 divergence.
    """

    values: dict[int, int] = {
        7: int(spec.get("volume", 100)),
        10: int(spec.get("pan", 64)),
        11: int(spec.get("expression", 100)),
    }
    for key, cc_num in CC_NUMBERS.items():
        if key in spec and key not in {"volume", "pan", "expression"}:
            values[int(cc_num)] = int(spec[key])
    for key, value in dict(spec.get("controls") or {}).items():
        if isinstance(key, int) or str(key).isdigit():
            cc_num = int(key)
        elif key in CC_NUMBERS:
            cc_num = int(CC_NUMBERS[key])
        else:
            raise KeyError(
                f"instrument {spec.get('name')!r}: unknown controls key {key!r}; "
                f"use a MIDI CC number or one of {sorted(CC_NUMBERS)}"
            )
        if not 0 <= cc_num <= 127:
            raise ValueError(
                f"instrument {spec.get('name')!r}: MIDI CC number must be 0..127; "
                f"got {cc_num}"
            )
        values[cc_num] = int(value)
    return {number: int(clamp(value, 0, 127)) for number, value in values.items()}


def add_initial_controls(inst: pretty_midi.Instrument, spec: Mapping[str, Any]) -> None:
    """Apply canonical t=0 controller state to ``inst``."""

    for number, value in sorted(initial_control_values(spec).items()):
        inst.control_changes.append(
            pretty_midi.ControlChange(number=int(number), value=int(value), time=0.0)
        )

"""Determinism checks for procedural MusicIR compilation."""
from __future__ import annotations

import copy
from typing import Any, Mapping

from ..musicir.compile import compile_score
from ..musicir.model import compiled_score_fingerprint


def compilation_determinism_report(spec: Mapping[str, Any], *, rounds: int = 3) -> dict[str, Any]:
    if rounds < 2:
        raise ValueError("determinism check needs at least two rounds")
    fingerprints = []
    authoring_fingerprints = []
    note_events = []
    controller_events = []
    for _ in range(rounds):
        compiled = compile_score(copy.deepcopy(dict(spec)))
        fingerprints.append(compiled_score_fingerprint(compiled))
        authoring_fingerprints.append(compiled.authoring_graph_fingerprint)
        note_events.append(copy.deepcopy(compiled.note_events))
        controller_events.append(copy.deepcopy(compiled.controller_events))
    return {
        "schema": "ambition.compilation_determinism_report.v1",
        "rounds": rounds,
        "deterministic": (
            len(set(fingerprints)) == 1
            and all(row == note_events[0] for row in note_events[1:])
            and all(row == controller_events[0] for row in controller_events[1:])
        ),
        "compiled_fingerprints": fingerprints,
        "authoring_graph_fingerprints": authoring_fingerprints,
    }

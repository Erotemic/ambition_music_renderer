"""Checked-in MusicIR performance-technique vocabulary.

The catalog describes musical intent independent of the concrete sampled patch.
MusicIR v3 may use the default gate immediately, while ``part.technique_map``
selects a different instrument realization when the score has one.  This keeps
"play staccato" separate from "which SFZ/keyswitch implements staccato".
"""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

TECHNIQUE_CATALOG_SCHEMA = "ambition.musicir.technique_catalog.v1"


@dataclass(frozen=True)
class TechniqueSpec:
    name: str
    summary: str
    default_gate: float
    aliases: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "default_gate": self.default_gate,
            "aliases": list(self.aliases),
        }


def _resource():
    return resources.files("ambition_music_renderer").joinpath("data/technique_catalog.json")


@functools.lru_cache(maxsize=1)
def load_technique_catalog() -> dict[str, Any]:
    data = json.loads(_resource().read_text(encoding="utf8"))
    if data.get("schema") != TECHNIQUE_CATALOG_SCHEMA:
        raise ValueError(
            f"technique catalog schema mismatch: {data.get('schema')!r} != {TECHNIQUE_CATALOG_SCHEMA!r}"
        )
    if not isinstance(data.get("techniques"), dict):
        raise ValueError("technique catalog needs a techniques mapping")
    return data


@functools.lru_cache(maxsize=1)
def technique_specs() -> dict[str, TechniqueSpec]:
    result: dict[str, TechniqueSpec] = {}
    for name, raw in load_technique_catalog()["techniques"].items():
        gate = float(raw.get("default_gate", 0.86))
        if gate <= 0:
            raise ValueError(f"technique {name!r} default_gate must be > 0")
        result[str(name)] = TechniqueSpec(
            name=str(name),
            summary=str(raw.get("summary", "")),
            default_gate=gate,
            aliases=tuple(str(x) for x in raw.get("aliases", []) or []),
        )
    aliases: dict[str, str] = {}
    for name, spec in result.items():
        for alias in spec.aliases:
            if alias in result or alias in aliases:
                raise ValueError(f"duplicate technique alias {alias!r}")
            aliases[alias] = name
    return result


def canonical_technique_name(value: str | None) -> str:
    name = str(value or "normal").strip().lower().replace(" ", "_")
    specs = technique_specs()
    if name in specs:
        return name
    for canonical, spec in specs.items():
        if name in spec.aliases:
            return canonical
    raise ValueError(
        f"unknown MusicIR technique {value!r}; expected one of {sorted(specs)}"
    )


def technique_default_gate(value: str | None, *, allow_custom: bool = False) -> float:
    try:
        name = canonical_technique_name(value)
    except ValueError:
        if allow_custom:
            return technique_specs()["normal"].default_gate
        raise
    return technique_specs()[name].default_gate


def technique_gate_map(*, include_aliases: bool = True) -> dict[str, float]:
    result = {name: spec.default_gate for name, spec in technique_specs().items()}
    if include_aliases:
        for name, spec in technique_specs().items():
            for alias in spec.aliases:
                result[alias] = spec.default_gate
    return result

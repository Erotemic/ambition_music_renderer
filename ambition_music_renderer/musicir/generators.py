"""Checked-in MusicIR v3 generator capability registry.

The JSON catalog is deliberately source-control data rather than prose copied
from implementation functions.  It is readable by source-only agents, while
this module gives the compiler/CLI a typed view of the same authority.
"""
from __future__ import annotations

import copy
import dataclasses as dc
import json
from importlib import resources
from typing import Any, Mapping

GENERATOR_CATALOG_SCHEMA = "ambition.musicir.generator_catalog.v1"


@dc.dataclass(frozen=True)
class GeneratorSpec:
    name: str
    bridge_kind: str
    summary: str
    harmony: str
    parameters: dict[str, dict[str, Any]]
    example: dict[str, Any]
    capabilities: dict[str, Any]
    notes: tuple[str, ...] = ()

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.parameters))

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bridge_kind": self.bridge_kind,
            "summary": self.summary,
            "harmony": self.harmony,
            "parameters": copy.deepcopy(self.parameters),
            "example": copy.deepcopy(self.example),
            "capabilities": copy.deepcopy(self.capabilities),
            "notes": list(self.notes),
        }


def _catalog_path():
    return resources.files("ambition_music_renderer").joinpath("data/generator_catalog.json")


def load_generator_catalog() -> dict[str, Any]:
    data = json.loads(_catalog_path().read_text(encoding="utf8"))
    if data.get("schema") != GENERATOR_CATALOG_SCHEMA:
        raise ValueError(
            f"generator catalog schema mismatch: {data.get('schema')!r} != {GENERATOR_CATALOG_SCHEMA!r}"
        )
    return data


def generator_specs() -> dict[str, GeneratorSpec]:
    data = load_generator_catalog()
    result: dict[str, GeneratorSpec] = {}
    for name, raw in data.get("generators", {}).items():
        result[str(name)] = GeneratorSpec(
            name=str(name),
            bridge_kind=str(raw["bridge_kind"]),
            summary=str(raw.get("summary", "")),
            harmony=str(raw.get("harmony", "required")),
            parameters=copy.deepcopy(dict(raw.get("parameters", {}))),
            example=copy.deepcopy(dict(raw.get("example", {}))),
            capabilities=copy.deepcopy(dict(raw.get("capabilities", {}))),
            notes=tuple(str(x) for x in raw.get("notes", []) or []),
        )
    return result


def get_generator_spec(name: str) -> GeneratorSpec:
    specs = generator_specs()
    try:
        return specs[str(name)]
    except KeyError as ex:
        raise ValueError(
            f"unknown MusicIR v3 generator kind {name!r}; expected one of {sorted(specs)}"
        ) from ex


def validate_generator_mapping(value: Mapping[str, Any]) -> GeneratorSpec:
    """Validate the public generator surface and return its registry entry."""

    if not isinstance(value, Mapping):
        raise TypeError("MusicIR v3 generate must be a mapping")
    kind = str(value.get("kind", ""))
    spec = get_generator_spec(kind)
    unknown = sorted(set(value) - {"kind"} - set(spec.parameters))
    if unknown:
        raise ValueError(
            f"MusicIR v3 generator {kind!r} has unknown parameter(s) {unknown}; "
            f"known parameters: {list(spec.parameter_names)}"
        )
    missing = sorted(
        key
        for key, meta in spec.parameters.items()
        if bool(meta.get("required")) and key not in value
    )
    if missing:
        raise ValueError(
            f"MusicIR v3 generator {kind!r} is missing required parameter(s) {missing}"
        )
    return spec


def _json_type_for_default(value: Any) -> str | None:
    if value is None or value == "derived":
        return None
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def generator_json_schema(name: str) -> dict[str, Any]:
    """Return an inspectable JSON Schema fragment for one ``generate`` block."""

    spec = get_generator_spec(name)
    properties: dict[str, Any] = {
        "kind": {"const": spec.name, "description": spec.summary}
    }
    required = ["kind"]
    for key, meta in spec.parameters.items():
        item: dict[str, Any] = {}
        if meta.get("description"):
            item["description"] = str(meta["description"])
        if "default" in meta and meta["default"] != "derived":
            item["default"] = copy.deepcopy(meta["default"])
        json_type = meta.get("type")
        if json_type is None and "default" in meta:
            json_type = _json_type_for_default(meta["default"])
        if json_type is not None:
            item["type"] = str(json_type)
        for constraint in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "enum", "items"):
            if constraint in meta:
                item[constraint] = copy.deepcopy(meta[constraint])
        if bool(meta.get("required")):
            required.append(key)
        properties[key] = item
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"MusicIR v3 generator: {spec.name}",
        "description": spec.summary,
        "x-ambition-capabilities": copy.deepcopy(spec.capabilities),
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
        "examples": [copy.deepcopy(spec.example)],
    }


def public_generator_names() -> tuple[str, ...]:
    return tuple(sorted(generator_specs()))

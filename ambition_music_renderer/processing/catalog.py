"""Checked-in processing/effect vocabulary.

The JSON catalog is the public authority for static render-time processing names,
aliases, parameter metadata, and inspector templates.  Runtime code consumes the
same catalog that source-only agents can inspect directly.
"""
from __future__ import annotations

import copy
import dataclasses as dc
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "processing_catalog.json"


@dc.dataclass(frozen=True)
class ProcessorSpec:
    name: str
    aliases: tuple[str, ...]
    backend: str
    summary: str
    parameters: dict[str, Any]
    automation: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "backend": self.backend,
            "summary": self.summary,
            "parameters": copy.deepcopy(self.parameters),
            "automation": copy.deepcopy(self.automation),
        }


@lru_cache(maxsize=1)
def processing_catalog() -> dict[str, Any]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf8"))
    if data.get("schema") != "ambition.processing_catalog.v1":
        raise ValueError(f"unsupported processing catalog schema: {data.get('schema')!r}")
    return data


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name, row in processing_catalog()["processors"].items():
        aliases[str(name).lower()] = str(name)
        for alias in row.get("aliases") or []:
            key = str(alias).lower()
            previous = aliases.get(key)
            if previous is not None and previous != name:
                raise ValueError(f"processing alias {alias!r} maps to both {previous!r} and {name!r}")
            aliases[key] = str(name)
    return aliases


def processor_names() -> tuple[str, ...]:
    return tuple(sorted(processing_catalog()["processors"]))


def canonical_processor_name(value: str) -> str:
    key = str(value).strip().lower()
    try:
        return _alias_map()[key]
    except KeyError:
        choices = ", ".join(processor_names())
        raise ValueError(f"unknown processing processor {value!r}; choose one of: {choices}") from None


def get_processor_spec(value: str) -> ProcessorSpec:
    name = canonical_processor_name(value)
    row = processing_catalog()["processors"][name]
    return ProcessorSpec(
        name=name,
        aliases=tuple(str(x) for x in row.get("aliases") or []),
        backend=str(row.get("backend") or "builtin"),
        summary=str(row.get("summary") or ""),
        parameters=copy.deepcopy(dict(row.get("parameters") or {})),
        automation=copy.deepcopy(dict(row.get("automation") or {})),
    )


def normalize_processor_mapping(raw: Mapping[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(dict(raw))
    raw_name = row.pop("processor", None)
    if raw_name is None:
        raw_name = row.pop("kind", None)
    if raw_name is None:
        raw_name = row.pop("effect", None)
    if raw_name is None:
        raw_name = row.pop("type", None)
    if raw_name is None:
        raw_name = row.pop("backend", None)
    if not raw_name:
        raise ValueError(f"processing step needs `processor`: {raw!r}")
    name = canonical_processor_name(str(raw_name))
    row["processor"] = name
    return row


def inspector_templates() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(dict(processing_catalog().get("inspector_templates") or {}))



@lru_cache(maxsize=1)
def _pedalboard_alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for name, row in processing_catalog().get("pedalboard_effects", {}).items():
        aliases[str(name).lower()] = str(name)
        for alias in row.get("aliases") or []:
            aliases[str(alias).lower()] = str(name)
    return aliases


def canonical_pedalboard_effect_name(value: str) -> str:
    key = str(value).strip().lower()
    try:
        return _pedalboard_alias_map()[key]
    except KeyError:
        choices = ", ".join(sorted(processing_catalog().get("pedalboard_effects", {})))
        raise ValueError(f"unknown Pedalboard effect {value!r}; choose one of: {choices}") from None

def pedalboard_effect_catalog() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(dict(processing_catalog().get("pedalboard_effects") or {}))


def is_pedalboard_effect_name(value: str) -> bool:
    """Return whether *value* is a public Pedalboard effect name or alias."""
    return str(value).strip().lower() in _pedalboard_alias_map()


def processor_json_schema(value: str) -> dict[str, Any]:
    spec = get_processor_spec(value)
    properties: dict[str, Any] = {"processor": {"const": spec.name}}
    required = ["processor"]
    for key, meta in spec.parameters.items():
        item = {k: copy.deepcopy(v) for k, v in meta.items() if k not in {"aliases", "default"}}
        if "default" in meta:
            item["default"] = copy.deepcopy(meta["default"])
        properties[str(key)] = item
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }

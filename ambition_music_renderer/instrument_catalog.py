"""Checked-in instrument vocabulary for agent-native music authoring.

The catalog answers the durable repository question: which sampled instruments
Ambition expects, how a score should request them, and what an author should know
about them.  Generated files under ``AMBITION_AUDIO_TOOLS_ROOT`` answer a
different question: which concrete files are installed on one machine today.

Keep resolver heuristics and curated usage guidance here.  Do not copy machine-
specific paths or generated census output into this module.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

import yaml


CATALOG_SCHEMA = "ambition.instrument_catalog.v1"


@dataclass(frozen=True)
class ResolverHints:
    """Filesystem search hints for one stable ``library_ref``."""

    required_any: tuple[tuple[str, ...], ...] = ()
    prefer: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    prefer_source: bool = True


@dataclass(frozen=True)
class InstrumentCatalogEntry:
    """One stable authoring identity from the checked-in instrument catalog."""

    ref: str
    family: str
    role: str
    source: str | None
    expected: bool
    install_profile: str | None
    is_drum: bool
    resolver: ResolverHints
    usage: Mapping[str, Any]

    def authoring_snippet(self) -> dict[str, Any]:
        instrument: dict[str, Any] = {
            "instrument_backend": {"kind": "sfz", "library_ref": self.ref},
        }
        if self.is_drum:
            instrument["is_drum"] = True
        return instrument

    def to_dict(self, *, include_resolver: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ref": self.ref,
            "family": self.family,
            "role": self.role,
            "source": self.source,
            "expected": self.expected,
            "install_profile": self.install_profile,
            "is_drum": self.is_drum,
            "usage": dict(self.usage),
            "musicir": self.authoring_snippet(),
        }
        if include_resolver:
            data["resolver"] = {
                "required_any": [list(group) for group in self.resolver.required_any],
                "prefer": list(self.resolver.prefer),
                "avoid": list(self.resolver.avoid),
                "prefer_source": self.resolver.prefer_source,
            }
        return data


def _catalog_resource():
    return resources.files("ambition_music_renderer").joinpath("data/instrument_catalog.yaml")


@functools.lru_cache(maxsize=1)
def load_instrument_catalog_document() -> dict[str, Any]:
    """Load and minimally validate the checked-in catalog document."""

    with _catalog_resource().open("r", encoding="utf8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise ValueError("instrument catalog must be a YAML mapping")
    if raw.get("schema") != CATALOG_SCHEMA:
        raise ValueError(
            f"unsupported instrument catalog schema {raw.get('schema')!r}; expected {CATALOG_SCHEMA!r}"
        )
    for key in ("policy", "sources", "instruments", "smoke_profiles"):
        if key not in raw:
            raise ValueError(f"instrument catalog is missing top-level key {key!r}")
    if not isinstance(raw["sources"], dict):
        raise ValueError("instrument catalog 'sources' must be a mapping")
    if not isinstance(raw["instruments"], dict):
        raise ValueError("instrument catalog 'instruments' must be a mapping")
    if not isinstance(raw["smoke_profiles"], list):
        raise ValueError("instrument catalog 'smoke_profiles' must be a list")

    known_sources = set(map(str, raw["sources"]))
    for source_name, source_raw in raw["sources"].items():
        if not isinstance(source_raw, dict):
            raise ValueError(f"catalog source {source_name!r} must be a mapping")
        if bool(source_raw.get("expected", False)) and not source_raw.get("relative_root"):
            raise ValueError(f"expected catalog source {source_name!r} needs a relative_root")
    for ref, instrument_raw in raw["instruments"].items():
        if not isinstance(instrument_raw, dict):
            raise ValueError(f"catalog instrument {ref!r} must be a mapping")
        source = instrument_raw.get("source")
        if source and str(source) not in known_sources:
            raise ValueError(f"catalog instrument {ref!r} names unknown source {source!r}")
    for index, smoke_raw in enumerate(raw["smoke_profiles"]):
        if not isinstance(smoke_raw, dict):
            raise ValueError(f"catalog smoke profile #{index} must be a mapping")
        source = smoke_raw.get("source")
        if source and str(source) not in known_sources:
            raise ValueError(f"catalog smoke profile #{index} names unknown source {source!r}")
    return raw


@functools.lru_cache(maxsize=1)
def instrument_catalog() -> dict[str, InstrumentCatalogEntry]:
    """Return the stable catalog keyed by MusicIR ``library_ref``."""

    doc = load_instrument_catalog_document()
    entries: dict[str, InstrumentCatalogEntry] = {}
    for ref, raw in doc["instruments"].items():
        if not isinstance(raw, dict):
            raise ValueError(f"catalog instrument {ref!r} must be a mapping")
        resolver_raw = raw.get("resolver") or {}
        if not isinstance(resolver_raw, dict):
            raise ValueError(f"catalog instrument {ref!r}.resolver must be a mapping")
        required_any = tuple(
            tuple(str(token) for token in group)
            for group in (resolver_raw.get("required_any") or [])
        )
        resolver = ResolverHints(
            required_any=required_any,
            prefer=tuple(str(token) for token in (resolver_raw.get("prefer") or [])),
            avoid=tuple(str(token) for token in (resolver_raw.get("avoid") or [])),
            prefer_source=bool(resolver_raw.get("prefer_source", True)),
        )
        entries[str(ref)] = InstrumentCatalogEntry(
            ref=str(ref),
            family=str(raw.get("family") or "other"),
            role=str(raw.get("role") or ref),
            source=str(raw["source"]) if raw.get("source") else None,
            expected=bool(raw.get("expected", False)),
            install_profile=str(raw["install_profile"]) if raw.get("install_profile") else None,
            is_drum=bool(raw.get("is_drum", False)),
            resolver=resolver,
            usage=dict(raw.get("usage") or {}),
        )
    return entries


def get_instrument_catalog_entry(ref: str | None) -> InstrumentCatalogEntry | None:
    if not ref:
        return None
    return instrument_catalog().get(str(ref))


def instrument_source_catalog() -> dict[str, dict[str, Any]]:
    """Return checked-in sample-library/source metadata."""

    raw = load_instrument_catalog_document().get("sources") or {}
    return {str(key): dict(value or {}) for key, value in raw.items()}


def instrument_catalog_policy() -> dict[str, Any]:
    return dict(load_instrument_catalog_document().get("policy") or {})


def sfz_smoke_profile_specs() -> tuple[dict[str, Any], ...]:
    """Return curated real-library smoke profiles from the same catalog authority."""

    rows = load_instrument_catalog_document().get("smoke_profiles") or []
    return tuple(dict(row) for row in rows if isinstance(row, dict))


def instrument_catalog_report(*, family: str | None = None, expected_only: bool = False) -> dict[str, Any]:
    """Machine-readable authoring vocabulary, independent of local installation."""

    doc = load_instrument_catalog_document()
    entries = []
    for entry in instrument_catalog().values():
        if family and entry.family != family:
            continue
        if expected_only and not entry.expected:
            continue
        entries.append(entry.to_dict())
    sources = instrument_source_catalog()
    return {
        "schema": CATALOG_SCHEMA,
        "policy": dict(doc.get("policy") or {}),
        "instrument_count": len(entries),
        "instruments": entries,
        "sources": sources,
    }


def describe_instrument(ref: str) -> dict[str, Any]:
    """Describe one authoring identity and its source-level installation contract."""

    entry = get_instrument_catalog_entry(ref)
    if entry is None:
        raise KeyError(ref)
    result = entry.to_dict()
    if entry.source:
        result["source_info"] = dict(instrument_source_catalog().get(entry.source) or {})
        patch_profiles = [
            dict(row)
            for row in sfz_smoke_profile_specs()
            if row.get("source") == entry.source
        ]
        if patch_profiles:
            result["known_patch_profiles"] = patch_profiles
    return result

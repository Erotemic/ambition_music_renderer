"""Canonical instrument-backend normalization and resolution.

MusicIR compatibility spellings are normalized here once.  Rendering, audits,
cache keys, plugin validation, and inspector tooling should consume the same
``InstrumentResolutionPlan`` instead of independently reinterpreting YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pretty_midi

from .instrument_catalog import InstrumentCatalogEntry, get_instrument_catalog_entry
from . import instrument_libraries


SFZ_BACKEND_KINDS = frozenset({"sfz", "sfizz", "sample", "sampled"})
PROCEDURAL_FM_KINDS = frozenset({"procedural_fm", "fm", "fm_synth", "subtractive_fm"})
TUNING_CORRECTION_SCHEMA = "ambition.instrument_tuning_correction.v1"


def _tuning_midi_key(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a MIDI pitch")
    if isinstance(value, (int, float)) and float(value).is_integer():
        pitch = int(value)
    else:
        token = str(value).strip()
        if token.lstrip("-").isdigit():
            pitch = int(token)
        else:
            pitch = pretty_midi.note_name_to_number(token)
    if not 0 <= pitch <= 127:
        raise ValueError(f"tuning-correction pitch must be MIDI 0..127; got {value!r}")
    return pitch


def normalize_tuning_correction(raw: Any) -> dict[str, Any] | None:
    """Canonicalize opt-in synthesis tuning calibration for one instrument."""

    if raw in (None, False):
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        cents = float(raw)
        if abs(cents) < 1e-9:
            return None
        return {
            "schema": TUNING_CORRECTION_SCHEMA,
            "mode": "global",
            "cents": cents,
            "max_abs_cents": 100.0,
        }
    if not isinstance(raw, Mapping):
        raise TypeError("instrument tuning_correction must be a number or mapping")
    data = dict(raw)
    if data.get("enabled") is False:
        return None
    points_raw = data.get("points") or {}
    if not isinstance(points_raw, Mapping):
        raise TypeError("tuning_correction.points must be a mapping of MIDI/note -> cents")
    points = {_tuning_midi_key(key): float(value) for key, value in points_raw.items()}
    mode = str(data.get("mode") or ("curve" if points else "global")).strip().lower().replace("-", "_")
    if mode in {"off", "none", "disabled"}:
        return None
    if mode not in {"global", "curve", "per_note", "per_note_cents"}:
        raise ValueError(f"unsupported tuning_correction mode {mode!r}")
    if mode != "global" and not points:
        raise ValueError("curve tuning_correction requires at least one point")
    interpolation = str(data.get("interpolation", "linear")).strip().lower()
    if interpolation not in {"linear", "nearest"}:
        raise ValueError("tuning_correction.interpolation must be linear or nearest")
    max_abs = float(data.get("max_abs_cents", 100.0))
    if max_abs <= 0.0 or max_abs > 199.0:
        raise ValueError("tuning_correction.max_abs_cents must be in (0, 199]")
    cents = float(data.get("cents", data.get("global_cents", 0.0)))
    values = [cents] if mode == "global" else list(points.values())
    if any(abs(value) > max_abs + 1e-9 for value in values):
        raise ValueError(
            f"tuning_correction exceeds max_abs_cents={max_abs:g}; "
            "inspect the audit before applying a larger shift"
        )
    canonical_mode = "global" if mode == "global" else "curve"
    if canonical_mode == "global" and abs(cents) < 1e-9:
        return None
    if canonical_mode == "curve" and not any(abs(value) >= 1e-9 for value in points.values()):
        return None
    out: dict[str, Any] = {
        "schema": TUNING_CORRECTION_SCHEMA,
        "mode": canonical_mode,
        "max_abs_cents": max_abs,
    }
    if canonical_mode == "global":
        out["cents"] = cents
    else:
        out["interpolation"] = interpolation
        out["points"] = dict(sorted(points.items()))
    if data.get("source") is not None:
        import copy
        out["source"] = copy.deepcopy(data["source"])
    return out


def tuning_correction_for_instrument(instrument_spec: Mapping[str, Any]) -> dict[str, Any] | None:
    return normalize_tuning_correction(instrument_spec.get("tuning_correction"))


def normalize_backend_spec(raw: Any) -> dict[str, Any]:
    """Normalize one backend mapping, including legacy field aliases."""

    if isinstance(raw, str):
        spec: dict[str, Any] = {"kind": raw}
    elif isinstance(raw, Mapping):
        spec = dict(raw)
    elif raw is None:
        spec = {}
    else:
        raise TypeError(f"instrument backend must be a mapping or string, got {type(raw).__name__}")

    if "kind" not in spec and "type" in spec:
        spec["kind"] = spec["type"]
    if "library_ref" not in spec and "library" in spec:
        spec["library_ref"] = spec["library"]
    if "prefer" not in spec and "prefer_keywords" in spec:
        spec["prefer"] = spec["prefer_keywords"]
    if "sfz" not in spec:
        for alias in ("path", "sfz_path", "sfz_glob"):
            if spec.get(alias):
                spec["sfz"] = spec[alias]
                break

    prefer = spec.get("prefer") or []
    if isinstance(prefer, str):
        prefer = [prefer]
    spec["prefer"] = [str(item) for item in prefer]

    roots = spec.get("library_roots") or []
    if isinstance(roots, (str, Path)):
        roots = [roots]
    spec["library_roots"] = [str(item) for item in roots]

    kind = str(spec.get("kind") or "").strip().lower()
    if not kind and any(spec.get(key) for key in ("sfz", "library_ref")):
        kind = "sfz"
    if kind:
        spec["kind"] = kind
    return spec


def instrument_backend_spec(instrument_specs: Mapping[str, Any], inst_name: str) -> dict[str, Any]:
    """Return the canonical backend mapping for one named instrument."""

    raw_inst = instrument_specs.get(inst_name, {}) or {}
    return backend_spec_from_instrument(raw_inst)


def backend_spec_from_instrument(instrument: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize backend metadata embedded in a MusicIR instrument mapping."""

    raw = instrument.get("instrument_backend", instrument.get("backend", None))
    if raw is None and "sfz" in instrument:
        raw = {"sfz": instrument.get("sfz")}
    spec = normalize_backend_spec(raw)
    if instrument.get("sfz") and not spec.get("sfz"):
        spec["sfz"] = instrument["sfz"]
        if not spec.get("kind"):
            spec["kind"] = "sfz"
    return spec


def backend_is_optional(spec: Mapping[str, Any]) -> bool:
    """Whether failure may fall back instead of aborting the render."""

    if "required" in spec:
        return not bool(spec.get("required"))
    return bool(spec.get("optional", True))


def backend_prefers_sfizz(spec: Mapping[str, Any]) -> bool:
    canonical = normalize_backend_spec(spec)
    return str(canonical.get("kind") or "") in SFZ_BACKEND_KINDS or any(
        canonical.get(key) for key in ("sfz", "library_ref")
    )


def backend_prefers_procedural_fm(spec: Mapping[str, Any]) -> bool:
    canonical = normalize_backend_spec(spec)
    return str(canonical.get("kind") or "") in PROCEDURAL_FM_KINDS


@dataclass(frozen=True)
class InstrumentResolutionPlan:
    """Canonical static decision for one authored instrument backend."""

    backend: Mapping[str, Any]
    kind: str
    wants_sfz: bool
    wants_procedural_fm: bool
    library_ref: str | None = None
    requested: str | None = None
    prefer: tuple[str, ...] = ()
    roots: tuple[str, ...] = ()
    resolved_sfz: Path | None = None
    fallback_backend: str | None = None
    optional: bool = True
    sfizz_settings: Mapping[str, Any] = field(default_factory=dict)
    catalog_entry: InstrumentCatalogEntry | None = None

    @property
    def expected_catalog_instrument(self) -> bool:
        return bool(self.catalog_entry and self.catalog_entry.expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "wants_sfz": self.wants_sfz,
            "wants_procedural_fm": self.wants_procedural_fm,
            "library_ref": self.library_ref,
            "requested": self.requested,
            "prefer": list(self.prefer),
            "roots": list(self.roots),
            "resolved_sfz": str(self.resolved_sfz) if self.resolved_sfz else None,
            "fallback_backend": self.fallback_backend,
            "optional": self.optional,
            "expected_catalog_instrument": self.expected_catalog_instrument,
            "catalog": self.catalog_entry.to_dict(include_resolver=False) if self.catalog_entry else None,
        }


def resolve_instrument_backend(
    raw_backend: Mapping[str, Any] | str | None,
    *,
    base_dir: Path | None = None,
    sfizz_cfg: Mapping[str, Any] | None = None,
    default_fallback_backend: str | None = None,
    force_sfz: bool = False,
) -> InstrumentResolutionPlan:
    """Normalize and resolve an instrument backend against the current machine.

    ``sfizz_cfg`` is the global render-level SFZ configuration. Per-instrument
    roots/settings override or extend it exactly once here.
    """

    backend = normalize_backend_spec(raw_backend)
    sfizz_cfg = dict(sfizz_cfg or {})
    kind = str(backend.get("kind") or "").lower().strip()
    wants_sfz = force_sfz or backend_prefers_sfizz(backend)
    wants_fm = backend_prefers_procedural_fm(backend)

    library_ref_raw = backend.get("library_ref")
    library_ref = str(library_ref_raw) if library_ref_raw else None
    catalog_entry = get_instrument_catalog_entry(library_ref)
    prefer = tuple(str(item) for item in (backend.get("prefer") or []))

    roots = [str(item) for item in (sfizz_cfg.get("library_roots") or [])]
    roots.extend(str(item) for item in (backend.get("library_roots") or []))

    resolved: Path | None = None
    requested: str | None = None
    if wants_sfz:
        requested_raw = backend.get("library_ref") or backend.get("sfz")
        requested = str(requested_raw) if requested_raw else None
        resolved = instrument_libraries.resolve_sfz_reference(
            backend.get("sfz"),
            library_ref=library_ref,
            prefer=prefer,
            base_dir=base_dir,
            roots=roots,
        )
        if resolved is None and sfizz_cfg.get("default_sfz"):
            default_sfz = sfizz_cfg.get("default_sfz")
            requested = requested or str(default_sfz)
            resolved = instrument_libraries.resolve_sfz_reference(default_sfz, base_dir=base_dir, roots=roots)

    fallback = backend.get("fallback_backend", default_fallback_backend)
    fallback_backend = str(fallback) if fallback is not None else None

    settings = dict(sfizz_cfg)
    settings.update(dict(backend.get("settings") or {}))
    if "command" in backend:
        settings["command"] = backend["command"]
    if "binary" in backend:
        settings["binary"] = backend["binary"]

    return InstrumentResolutionPlan(
        backend=backend,
        kind=kind,
        wants_sfz=wants_sfz,
        wants_procedural_fm=wants_fm,
        library_ref=library_ref,
        requested=requested,
        prefer=prefer,
        roots=tuple(roots),
        resolved_sfz=resolved,
        fallback_backend=fallback_backend,
        optional=backend_is_optional(backend),
        sfizz_settings=settings,
        catalog_entry=catalog_entry,
    )

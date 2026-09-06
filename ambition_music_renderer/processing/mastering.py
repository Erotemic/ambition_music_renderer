"""Canonical composition-master signal flow and legacy adaptive compatibility."""
from __future__ import annotations

import copy
import dataclasses as dc
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .legacy import legacy_processing_plan
from .pipeline import apply_processing_plan
from .plans import processing_plan_for_master, processing_plan_for_section


COMPOSITION_MASTER = "composition_master"
LEGACY_SECTION_POSTPROCESS = "legacy_section_postprocess"
_MODE_ALIASES = {
    COMPOSITION_MASTER: COMPOSITION_MASTER,
    "global_master_slices": COMPOSITION_MASTER,
    LEGACY_SECTION_POSTPROCESS: LEGACY_SECTION_POSTPROCESS,
    "section_postprocess": LEGACY_SECTION_POSTPROCESS,
}


@dc.dataclass(frozen=True)
class MasteringPolicy:
    mode: str
    source: str
    authored_mode: str | None

    @property
    def composition_master(self) -> bool:
        return self.mode == COMPOSITION_MASTER

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "ambition.mastering_policy.v1",
            "mode": self.mode,
            "source": self.source,
            "authored_mode": self.authored_mode,
        }


def mastering_policy(spec: Mapping[str, Any]) -> MasteringPolicy:
    processing = spec.get("processing") or {}
    if isinstance(processing, Mapping):
        adaptive = processing.get("adaptive_sections") or processing.get("mastering") or {}
        if isinstance(adaptive, Mapping) and adaptive.get("mode") is not None:
            raw = str(adaptive.get("mode"))
            if raw not in _MODE_ALIASES:
                raise ValueError(f"processing adaptive mastering mode must be one of {sorted(_MODE_ALIASES)}, got {raw!r}")
            return MasteringPolicy(_MODE_ALIASES[raw], "processing", raw)

    render_cfg = spec.get("render") or {}
    if isinstance(render_cfg, Mapping):
        cfg = render_cfg.get("adaptive_section_mastering") or render_cfg.get("adaptive_sections") or {}
        if isinstance(cfg, Mapping) and cfg:
            raw = str(cfg.get("mode", cfg.get("full_mix_mode", "section_postprocess")))
            if raw not in _MODE_ALIASES:
                raise ValueError(f"render.adaptive_section_mastering.mode must be one of {sorted(_MODE_ALIASES)}, got {raw!r}")
            return MasteringPolicy(_MODE_ALIASES[raw], "legacy_render_config", raw)

    # New v3 music receives the coherent composition-master policy by default.
    # Historical v1/v2 scores retain the old behavior so source regeneration is
    # not audibly changed merely by the architecture migration.
    if str(spec.get("schema") or "") == "ambition.musicir.v3":
        return MasteringPolicy(COMPOSITION_MASTER, "v3_default", None)
    return MasteringPolicy(LEGACY_SECTION_POSTPROCESS, "legacy_schema_default", None)


def _slice(audio: np.ndarray, sample_rate: int, start_seconds: float, end_seconds: float) -> np.ndarray:
    lo = max(0, int(round(float(start_seconds) * sample_rate)))
    hi = min(len(audio), int(round(float(end_seconds) * sample_rate)))
    return np.asarray(audio[lo:hi], dtype=np.float32)


def _fit_length(audio: np.ndarray, length: int) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    if len(x) == length:
        return x
    if len(x) > length:
        return x[:length].astype(np.float32, copy=False)
    out = np.zeros((length, 2), dtype=np.float32)
    if len(x):
        out[: len(x)] = x
    return out


def apply_section_bus_processing(
    audio: np.ndarray,
    sample_rate: int,
    spec: Mapping[str, Any],
    sections: Sequence[Mapping[str, Any]],
    *,
    base_dir: Path | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply canonical section-local processing before the composition master."""
    out = np.asarray(audio, dtype=np.float32).copy()
    applied: dict[str, Any] = {}
    for section in sections:
        section_id = str(section.get("id"))
        plan = processing_plan_for_section(spec, section_id)
        if plan is None or not plan.operations:
            continue
        lo = max(0, int(round(float(section["start_seconds"]) * sample_rate)))
        hi = min(len(out), int(round(float(section["end_seconds"]) * sample_rate)))
        before = out[lo:hi].copy()
        processed = apply_processing_plan(before, sample_rate, plan, base_dir=base_dir)
        out[lo:hi] = _fit_length(processed, hi - lo)
        applied[section_id] = plan.as_dict()
    return out, applied


def master_composition(
    raw_composition: np.ndarray,
    sample_rate: int,
    spec: Mapping[str, Any],
    *,
    base_dir: Path | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    plan = processing_plan_for_master(spec)
    return apply_processing_plan(raw_composition, sample_rate, plan, base_dir=base_dir), plan.as_dict()


def adaptive_full_mix(
    *,
    mastered_timeline: np.ndarray,
    pre_master_timeline: np.ndarray,
    sample_rate: int,
    spec: Mapping[str, Any],
    section: Mapping[str, Any],
    base_dir: Path | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    policy = mastering_policy(spec)
    section_id = str(section.get("id"))
    if policy.composition_master:
        return _slice(mastered_timeline, sample_rate, section["start_seconds"], section["end_seconds"]), {
            "mode": COMPOSITION_MASTER,
            "section": section_id,
            "section_postprocess_ignored": bool(
                next((s for s in spec.get("sections", []) if str(s.get("id")) == section_id and s.get("postprocess")), None)
            ),
        }

    section_specs = {str(s.get("id")): s for s in spec.get("sections", []) if isinstance(s, Mapping)}
    section_spec = section_specs.get(section_id, {})
    section_pp = section_spec.get("postprocess") if isinstance(section_spec, Mapping) else None
    if not section_pp:
        return _slice(mastered_timeline, sample_rate, section["start_seconds"], section["end_seconds"]), {
            "mode": LEGACY_SECTION_POSTPROCESS,
            "section": section_id,
            "section_postprocess_applied": False,
        }
    raw_piece = _slice(pre_master_timeline, sample_rate, section["start_seconds"], section["end_seconds"])
    settings = dict(spec.get("postprocess", {}) or {})
    settings.setdefault("normalize", True)
    settings.setdefault("target_peak_db", -1.2)
    settings.update(copy.deepcopy(dict(section_pp)))
    plan = legacy_processing_plan(settings, stage="legacy_section_master", section=section_id)
    return apply_processing_plan(raw_piece, sample_rate, plan, base_dir=base_dir), {
        "mode": LEGACY_SECTION_POSTPROCESS,
        "section": section_id,
        "section_postprocess_applied": True,
        "plan": plan.as_dict(),
    }

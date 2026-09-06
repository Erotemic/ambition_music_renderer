"""Compatibility translation from historical flat postprocess mappings."""
from __future__ import annotations

import copy
from typing import Any, Mapping

from .model import ProcessingPlan


def legacy_postprocess_chain(settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Translate the historical ``post_process`` mapping without changing order.

    This function deliberately mirrors the pre-Phase-5 operation order.  It is
    the compatibility boundary for v1/v2 scores and old v3 sources that still
    use ``postprocess`` / ``stem_postprocess`` / ``group_postprocess``.
    """
    s = copy.deepcopy(dict(settings or {}))
    chain: list[dict[str, Any]] = []
    if s.get("gain_db", 0):
        chain.append({"processor": "gain", "gain_db": float(s["gain_db"])})
    if s.get("highpass_hz", 0):
        chain.append({"processor": "highpass", "cutoff_hz": float(s["highpass_hz"])})
    tame = float(s.get("transient_tame", 0.0))
    if tame > 0:
        chain.append({
            "processor": "transient_tame",
            "amount": tame,
            "lowpass_hz": float(s.get("transient_lowpass_hz", 6500)),
        })
    if s.get("presence_db", 0):
        chain.append({
            "processor": "band_gain",
            "low_hz": float(s.get("presence_low_hz", 2000)),
            "high_hz": float(s.get("presence_high_hz", 4500)),
            "gain_db": float(s["presence_db"]),
        })
    if s.get("high_shelf_db", 0):
        chain.append({
            "processor": "high_shelf",
            "hz": float(s.get("high_shelf_hz", 4500)),
            "gain_db": float(s["high_shelf_db"]),
        })
    eq_bands = s.get("eq_bands") or s.get("parametric_eq") or []
    if eq_bands:
        chain.append({"processor": "parametric_eq", "bands": copy.deepcopy(list(eq_bands))})
    if s.get("lowpass_hz", 0):
        chain.append({"processor": "lowpass", "cutoff_hz": float(s["lowpass_hz"])})
    if "compressor_threshold_db" in s:
        chain.append({
            "processor": "compressor",
            "threshold_db": float(s["compressor_threshold_db"]),
            "ratio": float(s.get("compressor_ratio", 3.0)),
            "attack_ms": float(s.get("compressor_attack_ms", 10.0)),
            "release_ms": float(s.get("compressor_release_ms", 100.0)),
            "makeup_db": float(s.get("compressor_makeup_db", 0.0)),
            "knee_db": float(s.get("compressor_knee_db", 6.0)),
        })
    reverb_wet = float(s.get("reverb_wet", 0.18))
    if s.get("reverb_enabled", True) and reverb_wet > 0:
        chain.append({
            "processor": "reverb",
            "wet": reverb_wet,
            "decay_seconds": float(s.get("reverb_decay_seconds", 1.4)),
            "damping_hz": float(s.get("reverb_damping_hz", 6000)),
        })
    if s.get("post_reverb_high_shelf_db", 0):
        chain.append({
            "processor": "high_shelf",
            "hz": float(s.get("post_reverb_high_shelf_hz", 5000)),
            "gain_db": float(s["post_reverb_high_shelf_db"]),
        })
    # Historical default: width processing is active unless explicitly zero.
    width = float(s.get("stereo_width", 0.10))
    if width > 0:
        chain.append({"processor": "stereo_width", "amount": width})
    effect_chain = s.get("effect_chain") or []
    for step in effect_chain:
        if isinstance(step, Mapping):
            row = copy.deepcopy(dict(step))
            # The historical chain accepts kind/type/backend/effect spellings.
            row["processor"] = (
                row.pop("processor", None)
                or row.pop("kind", None)
                or row.pop("type", None)
                or row.pop("backend", None)
                or row.get("effect")
            )
            chain.append(row)
        else:
            chain.append({"processor": str(step)})
    lufs_requested = (
        s.get("target_lufs") is not None
        or s.get("loudness_target_lufs") is not None
        or s.get("loudness") is not None
    )
    if lufs_requested:
        target_lufs = s.get("target_lufs", s.get("loudness_target_lufs", s.get("loudness")))
        chain.append({
            "processor": "loudness",
            "target_lufs": float(target_lufs),
            "true_peak_db": float(s.get("true_peak_db", s.get("target_peak_db", -1.0))),
            "_legacy_settings": copy.deepcopy(s),
        })
    if s.get("limiter_enabled", True):
        chain.append({
            "processor": "limiter",
            "target_peak_db": float(s.get("true_peak_db", s.get("target_peak_db", -1.0))),
            "drive": float(s.get("limiter_drive", 1.08)),
            "normalize": bool(s.get("normalize", True)) and not lufs_requested,
        })
    return chain


def legacy_processing_plan(
    settings: Mapping[str, Any],
    *,
    stage: str,
    group: str | None = None,
    section: str | None = None,
) -> ProcessingPlan:
    return ProcessingPlan.from_chain(
        legacy_postprocess_chain(settings),
        stage=stage,
        source="legacy_postprocess",
        group=group,
        section=section,
    )

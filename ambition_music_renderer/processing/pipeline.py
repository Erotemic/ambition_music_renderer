"""Execution of canonical static processing plans."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np

from ..audio_utils import coerce_stereo
from .model import ProcessingOperation, ProcessingPlan


def _apply_operation(
    audio: np.ndarray,
    sample_rate: int,
    op: ProcessingOperation,
    *,
    base_dir: Path | None = None,
) -> np.ndarray:
    # Import DSP primitives lazily to keep ``render.effects.post_process`` as a
    # compatibility facade without creating an import cycle at module import.
    from ..render import effects as fx

    p = copy.deepcopy(op.parameters)
    name = op.processor
    if name == "gain":
        return (audio * (10 ** (float(p.get("gain_db", 0.0)) / 20.0))).astype(np.float32, copy=False)
    if name == "highpass":
        return fx.highpass(audio, sample_rate, float(p.get("cutoff_hz", p.get("hz", 80.0))))
    if name == "lowpass":
        return fx.lowpass(audio, sample_rate, float(p.get("cutoff_hz", p.get("hz", 9000.0))))
    if name == "transient_tame":
        amount = float(p.get("amount", 0.0))
        if amount <= 0:
            return audio.astype(np.float32, copy=False)
        dark = fx.lowpass(audio, sample_rate, float(p.get("lowpass_hz", 6500.0)))
        return (audio * (1.0 - amount) + dark * amount).astype(np.float32)
    if name == "band_gain":
        return fx.band_gain(
            audio,
            sample_rate,
            low_hz=float(p.get("low_hz", 2000.0)),
            high_hz=float(p.get("high_hz", 4500.0)),
            db=float(p.get("gain_db", p.get("db", 0.0))),
        )
    if name == "high_shelf":
        return fx.high_shelf(
            audio,
            sample_rate,
            hz=float(p.get("hz", 4500.0)),
            db=float(p.get("gain_db", p.get("db", 0.0))),
        )
    if name == "parametric_eq":
        return fx.parametric_eq(audio, sample_rate, list(p.get("bands") or []))
    if name == "compressor":
        return fx.compressor(
            audio,
            sample_rate,
            threshold_db=float(p.get("threshold_db", -18.0)),
            ratio=float(p.get("ratio", 3.0)),
            attack_ms=float(p.get("attack_ms", 10.0)),
            release_ms=float(p.get("release_ms", 100.0)),
            makeup_db=float(p.get("makeup_db", 0.0)),
            knee_db=float(p.get("knee_db", 6.0)),
        )
    if name == "reverb":
        return fx.simple_reverb(
            audio,
            sample_rate,
            wet=float(p.get("wet", 0.18)),
            decay=float(p.get("decay_seconds", 1.4)),
            damping_hz=float(p.get("damping_hz", 6000.0)),
        )
    if name == "stereo_width":
        return fx.stereo_widen(audio, float(p.get("amount", 0.10)))
    if name == "loudness":
        from ..loudness import apply_loudness_settings

        legacy = p.pop("_legacy_settings", None)
        settings = dict(legacy or {})
        settings["target_lufs"] = float(p.get("target_lufs", settings.get("target_lufs", -14.0)))
        settings["true_peak_db"] = float(p.get("true_peak_db", settings.get("true_peak_db", -1.0)))
        return apply_loudness_settings(audio, sample_rate, settings)
    if name == "limiter":
        return fx.soft_limit(
            audio,
            float(p.get("target_peak_db", -1.0)),
            drive=float(p.get("drive", 1.08)),
            normalize=bool(p.get("normalize", True)),
        )
    if name in {"pedalboard", "vst3", "lv2", "command"}:
        from ..backends.plugin_chain import apply_effect_chain

        step = copy.deepcopy(p)
        step["kind"] = name
        return apply_effect_chain(audio, sample_rate, [step], base_dir=base_dir)
    raise ValueError(f"unsupported canonical processor {name!r}")


def apply_processing_plan(
    audio: np.ndarray,
    sample_rate: int,
    plan: ProcessingPlan,
    *,
    base_dir: Path | None = None,
) -> np.ndarray:
    out = coerce_stereo(audio)
    for operation in plan.operations:
        out = coerce_stereo(_apply_operation(out, sample_rate, operation, base_dir=base_dir))
    return out.astype(np.float32, copy=False)

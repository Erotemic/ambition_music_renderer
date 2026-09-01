"""Unified optional effect-chain application.

``effect_chain`` is the recommended YAML surface for optional pro-audio tools.
Each step is explicit and can delegate to Pedalboard/VST3, LV2/lv2proc, or a
file-command adapter while keeping the lightweight renderer path dependency-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import sys

import numpy as np
from ..audio_utils import coerce_stereo


def _step_kind(spec: dict[str, Any]) -> str:
    return str(
        spec.get("kind")
        or spec.get("type")
        or spec.get("backend")
        or spec.get("effect")
        or ""
    ).lower().strip()


def _is_optional_step(spec: dict[str, Any]) -> bool:
    return bool(spec.get("optional") or spec.get("required") is False)


def _warn_optional_skip(idx: int, kind: str, ex: BaseException) -> None:
    print(
        f"[ambition_music_renderer] skipped optional effect_chain step {idx} "
        f"({kind or 'unknown'}): {ex}",
        file=sys.stderr,
    )


def _dbfs_levels(audio: np.ndarray) -> tuple[float, float]:
    x = np.asarray(audio, dtype=np.float64)
    if not x.size:
        return -240.0, -240.0
    rms = float(np.sqrt(np.mean(np.square(x))))
    peak = float(np.max(np.abs(x)))
    return (
        float(20.0 * np.log10(max(rms, 1e-12))),
        float(20.0 * np.log10(max(peak, 1e-12))),
    )


def _shape_change_db(before: np.ndarray, after: np.ndarray) -> float:
    """Residual after removing the best scalar gain match, relative to output."""
    x = np.asarray(before, dtype=np.float64).reshape(-1)
    y = np.asarray(after, dtype=np.float64).reshape(-1)
    if not x.size or not y.size or x.shape != y.shape:
        return -240.0
    scale = float(np.dot(y, x) / max(float(np.dot(x, x)), 1e-30))
    residual = y - scale * x
    residual_rms = float(np.sqrt(np.mean(np.square(residual))))
    output_rms = float(np.sqrt(np.mean(np.square(y))))
    return float(
        20.0 * np.log10(max(residual_rms / max(output_rms, 1e-30), 1e-12))
    )


def _parallel_blend(before: np.ndarray, processed: np.ndarray, wet_mix: float) -> np.ndarray:
    dry = coerce_stereo(before)
    wet = coerce_stereo(processed)
    if dry.shape != wet.shape:
        raise RuntimeError(
            f"effect_chain wet/dry shape mismatch: dry={dry.shape!r} wet={wet.shape!r}"
        )
    mix = float(np.clip(float(wet_mix), 0.0, 1.0))
    return ((1.0 - mix) * dry + mix * wet).astype(np.float32, copy=False)


def apply_effect_chain(
    audio: np.ndarray,
    sample_rate: int,
    chain: list[dict[str, Any]],
    *,
    base_dir: Path | None = None,
) -> np.ndarray:
    """Apply an explicit cross-backend chain to a stereo audio buffer."""

    out = coerce_stereo(audio)
    for idx, raw_spec in enumerate(chain or []):
        spec = dict(raw_spec or {})
        kind = _step_kind(spec)
        before = out
        try:
            if kind in {"pedalboard", "pb"}:
                from .pedalboard_backend import apply_pedalboard_effects

                effects = spec.get("effects") or spec.get("chain") or spec.get("plugins") or []
                processed = apply_pedalboard_effects(
                    before,
                    sample_rate,
                    list(effects),
                    base_dir=base_dir,
                    report_levels=bool(spec.get("report_levels", False)),
                    label=spec.get("label"),
                )
            elif kind in {"vst3", "vst", "plugin"}:
                from .pedalboard_backend import apply_pedalboard_effects

                vst_spec = {**spec, "effect": "vst3"}
                # Top-level wet_mix belongs to the whole effect_chain step, not
                # the VST plugin's Pedalboard sub-spec (which also understands
                # wet_mix).  Remove it here to avoid blending twice.
                vst_spec.pop("wet_mix", None)
                processed = apply_pedalboard_effects(
                    before, sample_rate, [vst_spec], base_dir=base_dir
                )
            elif kind in {"lv2", "lv2proc", "nam_lv2", "neural_amp_modeler"}:
                from .lv2_backend import apply_lv2_effects

                processed = apply_lv2_effects(before, sample_rate, [spec])
            elif kind in {"command", "external", "nam", "guitarix"} or spec.get("command"):
                from .external_fx import apply_external_effects

                processed = apply_external_effects(before, sample_rate, [spec])
            else:
                raise ValueError(
                    f"unknown effect_chain step {idx} kind {kind!r}; "
                    "use pedalboard, vst3, lv2proc, command, nam, or guitarix"
                )
            if "wet_mix" in spec:
                out = _parallel_blend(before, processed, float(spec["wet_mix"]))
            else:
                out = coerce_stereo(processed)

            if bool(spec.get("report_levels", False)):
                in_rms, in_peak = _dbfs_levels(before)
                out_rms, out_peak = _dbfs_levels(out)
                shape_db = _shape_change_db(before, out)
                label = str(spec.get("label") or f"step-{idx}")
                wet_text = (
                    f" wet_mix={float(spec['wet_mix']):.3f}"
                    if "wet_mix" in spec
                    else ""
                )
                print(
                    f"[music fx] chain={label} backend={kind} "
                    f"in_rms_dbfs={in_rms:.2f} in_peak_dbfs={in_peak:.2f} "
                    f"out_rms_dbfs={out_rms:.2f} out_peak_dbfs={out_peak:.2f} "
                    f"shape_change_db={shape_db:.2f}{wet_text}",
                    file=sys.stderr,
                )
        except Exception as ex:
            if _is_optional_step(spec):
                _warn_optional_skip(idx, kind, ex)
                continue
            raise
    return coerce_stereo(out)

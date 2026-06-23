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
        try:
            if kind in {"pedalboard", "pb"}:
                from .pedalboard_backend import apply_pedalboard_effects

                effects = spec.get("effects") or spec.get("chain") or spec.get("plugins") or []
                out = apply_pedalboard_effects(out, sample_rate, list(effects), base_dir=base_dir)
            elif kind in {"vst3", "vst", "plugin"}:
                from .pedalboard_backend import apply_pedalboard_effects

                vst_spec = {**spec, "effect": "vst3"}
                out = apply_pedalboard_effects(out, sample_rate, [vst_spec], base_dir=base_dir)
            elif kind in {"lv2", "lv2proc", "nam_lv2", "neural_amp_modeler"}:
                from .lv2_backend import apply_lv2_effects

                out = apply_lv2_effects(out, sample_rate, [spec])
            elif kind in {"command", "external", "nam", "guitarix"} or spec.get("command"):
                from .external_fx import apply_external_effects

                out = apply_external_effects(out, sample_rate, [spec])
            else:
                raise ValueError(
                    f"unknown effect_chain step {idx} kind {kind!r}; "
                    "use pedalboard, vst3, lv2proc, command, nam, or guitarix"
                )
        except Exception as ex:
            if _is_optional_step(spec):
                _warn_optional_skip(idx, kind, ex)
                continue
            raise
    return coerce_stereo(out)

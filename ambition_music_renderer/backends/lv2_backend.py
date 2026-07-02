"""Optional LV2 file-processing backend.

This module intentionally focuses on offline file-in/file-out processing via
``lv2proc``.  Full LV2 graph hosting is host-specific; for complex graphs use
``effect_chain`` with command steps or a future dedicated host adapter.

Only the lv2proc command construction lives here; the actual file-based
execution (temp WAV round-trip, timeout, error reporting, resampling) is the
shared :func:`ambition_music_renderer.backends.external_fx.run_file_effect`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np
from ..audio_utils import coerce_stereo
from .external_fx import run_file_effect


def build_lv2proc_command(input_path: Path, output_path: Path, spec: dict[str, Any]) -> list[str]:
    """Build a conservative lv2proc invocation for one plugin spec."""

    binary = str(spec.get("binary", "lv2proc"))
    if not shutil.which(binary):
        raise FileNotFoundError(f"{binary!r} not found for LV2 postprocess")
    plugin_uri = str(spec.get("plugin_uri") or spec.get("uri") or "")
    if not plugin_uri:
        raise ValueError("LV2 effect requires plugin_uri or uri")
    cmd = [binary, "-i", str(input_path), "-o", str(output_path)]
    for key, value in dict(spec.get("params") or spec.get("parameters") or {}).items():
        cmd.extend(["-c", f"{key}={value}"])
    cmd.append(plugin_uri)
    return cmd


def apply_lv2_effect(audio: np.ndarray, sample_rate: int, spec: dict[str, Any]) -> np.ndarray:
    """Apply one LV2 effect to audio through lv2proc or a command override."""

    if not spec.get("command") and not spec.get("kind"):
        spec = {**spec, "kind": "lv2proc"}
    return run_file_effect(audio, sample_rate, spec)


def apply_lv2_effects(audio: np.ndarray, sample_rate: int, effects: list[dict[str, Any]]) -> np.ndarray:
    out = coerce_stereo(audio)
    for spec in effects or []:
        out = apply_lv2_effect(out, sample_rate, spec)
    return coerce_stereo(out)

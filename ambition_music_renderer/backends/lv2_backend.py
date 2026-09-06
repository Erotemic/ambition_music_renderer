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
from .external_fx import run_file_effect, run_file_effect_raw


def build_lv2proc_command(input_path: Path, output_path: Path, spec: dict[str, Any]) -> list[str]:
    """Build an offline LV2-host invocation for one plugin spec.

    ``lv2proc`` and Lilv's newer ``lv2apply`` expose nearly the same job but
    use different control-assignment syntax.  Supporting both keeps authored
    LV2 chains portable across Ubuntu releases and lets scores prefer
    ``lv2apply`` for plugins with richer LV2 feature requirements.
    """

    binary = str(spec.get("binary", "lv2proc"))
    if not shutil.which(binary):
        raise FileNotFoundError(f"{binary!r} not found for LV2 postprocess")
    plugin_uri = str(spec.get("plugin_uri") or spec.get("uri") or "")
    if not plugin_uri:
        raise ValueError("LV2 effect requires plugin_uri or uri")
    cmd = [binary, "-i", str(input_path), "-o", str(output_path)]
    params = dict(spec.get("params") or spec.get("parameters") or {})
    binary_name = Path(binary).name
    if binary_name == "lv2apply":
        # Lilv lv2apply: ``-c symbol value``.
        for key, value in params.items():
            cmd.extend(["-c", str(key), str(value)])
    else:
        # lv2proc: ``-c port:value``.  ``port=value`` looks plausible but is
        # not its control-assignment syntax.
        for key, value in params.items():
            cmd.extend(["-c", f"{key}:{value}"])
    cmd.append(plugin_uri)
    return cmd


def apply_lv2_effect(audio: np.ndarray, sample_rate: int, spec: dict[str, Any]) -> np.ndarray:
    """Apply one LV2 effect to audio through lv2proc or a command override."""

    if not spec.get("command") and not spec.get("kind"):
        spec = {**spec, "kind": "lv2proc"}
    channel_mode = str(spec.get("channel_mode", "stereo")).lower().strip()
    if channel_mode in {"dual_mono", "split_mono"}:
        stereo = coerce_stereo(audio)
        rendered_channels: list[np.ndarray] = []
        for channel_idx in range(2):
            rendered = run_file_effect_raw(stereo[:, channel_idx], sample_rate, spec)
            if rendered.ndim != 2 or rendered.shape[1] < 1:
                raise RuntimeError(
                    f"dual-mono LV2 effect returned invalid shape {rendered.shape!r}"
                )
            channel = rendered[:, 0]
            if channel.shape[0] != stereo.shape[0]:
                raise RuntimeError(
                    "dual-mono LV2 effect changed sample count: "
                    f"{stereo.shape[0]} -> {channel.shape[0]}"
                )
            rendered_channels.append(channel.astype(np.float32, copy=False))
        return np.column_stack(rendered_channels).astype(np.float32, copy=False)
    if channel_mode not in {"stereo", "auto", ""}:
        raise ValueError(
            f"unsupported LV2 channel_mode {channel_mode!r}; use stereo or dual_mono"
        )
    return run_file_effect(audio, sample_rate, spec)


def apply_lv2_effects(audio: np.ndarray, sample_rate: int, effects: list[dict[str, Any]]) -> np.ndarray:
    out = coerce_stereo(audio)
    for spec in effects or []:
        out = apply_lv2_effect(out, sample_rate, spec)
    return coerce_stereo(out)

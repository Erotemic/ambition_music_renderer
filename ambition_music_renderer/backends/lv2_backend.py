"""Optional LV2 file-processing backend.

This module intentionally focuses on offline file-in/file-out processing via
``lv2proc``.  Full LV2 graph hosting is host-specific; for complex graphs use
``effect_chain`` with command steps or a future dedicated host adapter.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from ..audio_utils import coerce_stereo
import soundfile as sf
from scipy import signal


def _format_command(template: str | list[str], mapping: dict[str, str]) -> list[str]:
    if isinstance(template, str):
        parts = shlex.split(template)
    else:
        parts = [str(x) for x in template]
    return [part.format(**mapping) for part in parts]


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

    with tempfile.TemporaryDirectory() as d:
        tempdir = Path(d)
        input_path = tempdir / "input.wav"
        output_path = tempdir / "output.wav"
        sf.write(input_path, coerce_stereo(audio), int(sample_rate), subtype="PCM_24")
        mapping = {
            "input": str(input_path),
            "output": str(output_path),
            "sample_rate": str(int(sample_rate)),
        }
        if spec.get("command"):
            cmd = _format_command(spec["command"], mapping)
        else:
            cmd = build_lv2proc_command(input_path, output_path, spec)
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not output_path.exists():
            raise RuntimeError(f"LV2 effect did not create output file: {output_path}")
        out, sr = sf.read(output_path, dtype="float32", always_2d=True)
        if sr != int(sample_rate):
            out = signal.resample_poly(out, int(sample_rate), int(sr), axis=0).astype(np.float32)
        return coerce_stereo(out)


def apply_lv2_effects(audio: np.ndarray, sample_rate: int, effects: list[dict[str, Any]]) -> np.ndarray:
    out = coerce_stereo(audio)
    for spec in effects or []:
        out = apply_lv2_effect(out, sample_rate, spec)
    return coerce_stereo(out)

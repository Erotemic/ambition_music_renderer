"""Optional file-based external effect adapters.

These adapters intentionally expose conservative YAML contracts.  LV2/NAM and
Guitarix setups vary by host and plugin version, so every adapter supports a
``command`` override with ``{input}``, ``{output}``, and ``{sample_rate}``
placeholders.  Built-in command generation is provided only for simple lv2proc
chains.
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from ..audio_utils import coerce_stereo
import soundfile as sf
from scipy import signal


# An external effect that runs longer than this per stem is assumed hung. The
# sfizz backend grew the same guard after an orphaned render filled the disk
# with a ~100 GB WAV; arbitrary command/lv2proc steps deserve it too.
EXTERNAL_EFFECT_TIMEOUT_S = 600.0


def _format_command(template: str | list[str], mapping: dict[str, str]) -> list[str]:
    if isinstance(template, str):
        parts = shlex.split(template)
    else:
        parts = [str(x) for x in template]
    return [part.format(**mapping) for part in parts]


def run_file_effect(audio: np.ndarray, sample_rate: int, spec: dict[str, Any]) -> np.ndarray:
    """Run one file-in/file-out external effect (command, lv2proc, ...).

    This is the single shared runner for every external effect family;
    ``lv2_backend`` delegates here rather than keeping a drifted copy.
    """
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
        command = spec.get("command")
        kind = str(spec.get("kind") or spec.get("type") or "command").lower().strip()
        if command:
            cmd = _format_command(command, mapping)
        elif kind in {"lv2proc", "lv2"}:
            from .lv2_backend import build_lv2proc_command

            cmd = build_lv2proc_command(input_path, output_path, spec)
        elif kind in {"nam", "nam_lv2", "neural_amp_modeler"}:
            raise ValueError(
                "NAM/LV2 setups need a command override or a host-specific adapter. "
                "Use kind: command with {input}/{output} placeholders, or kind: lv2proc "
                "if your NAM LV2 build exposes simple lv2proc controls."
            )
        elif kind == "guitarix":
            raise ValueError(
                "Guitarix offline invocation is host/setup-specific. Provide kind: command "
                "with {input}/{output}/{sample_rate} placeholders."
            )
        else:
            raise ValueError(f"unknown external effect kind {kind!r}")
        timeout_s = float(spec.get("timeout_s", EXTERNAL_EFFECT_TIMEOUT_S))
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as ex:
            raise RuntimeError(
                f"external effect timed out after {timeout_s:.0f}s: {shlex.join(cmd)}"
            ) from ex
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or b"").decode("utf8", errors="replace")[-2000:]
            raise RuntimeError(
                f"external effect failed rc={proc.returncode}: {shlex.join(cmd)}\n{stderr_tail}"
            )
        if not output_path.exists():
            raise RuntimeError(f"external effect did not create output file: {output_path}")
        out, sr = sf.read(output_path, dtype="float32", always_2d=True)
        if sr != int(sample_rate):
            out = signal.resample_poly(out, int(sample_rate), int(sr), axis=0).astype(np.float32)
        return coerce_stereo(out)


def apply_external_effects(audio: np.ndarray, sample_rate: int, effects: list[dict[str, Any]]) -> np.ndarray:
    out = coerce_stereo(audio)
    for spec in effects or []:
        out = run_file_effect(out, sample_rate, spec)
    return coerce_stereo(out)

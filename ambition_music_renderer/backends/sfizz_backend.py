"""Optional SFZ rendering through the external sfizz_render command."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pretty_midi
import soundfile as sf
from scipy import signal


def _coerce_stereo(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = np.column_stack([x, x])
    if x.shape[1] == 1:
        x = np.column_stack([x[:, 0], x[:, 0]])
    if x.shape[1] > 2:
        x = x[:, :2]
    return x.astype(np.float32, copy=False)


def resolve_path(path: str | Path, *, base_dir: Path | None = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p.resolve()


def _format_command(template: str | list[str], mapping: dict[str, str]) -> list[str]:
    if isinstance(template, str):
        parts = shlex.split(template)
    else:
        parts = [str(x) for x in template]
    return [part.format(**mapping) for part in parts]


def render_sfizz(
    pm: pretty_midi.PrettyMIDI,
    *,
    sfz_path: str | Path,
    sample_rate: int,
    tempdir: Path,
    output_name: str,
    minimum_duration: float = 0.0,
    base_dir: Path | None = None,
    settings: dict[str, Any] | None = None,
) -> np.ndarray:
    """Render a PrettyMIDI object using sfizz_render and an SFZ file.

    Default command shape is intentionally conservative and may be overridden
    by YAML with ``render.sfizz.command`` or instrument_backend.command if a
    local sfizz build uses different flags.
    """
    settings = settings or {}
    binary = str(settings.get("binary", "sfizz_render"))
    if not shutil.which(binary):
        raise FileNotFoundError(
            f"{binary!r} not found. Install sfizz_render or choose another backend."
        )
    sfz = resolve_path(sfz_path, base_dir=base_dir)
    if not sfz.exists():
        raise FileNotFoundError(f"SFZ instrument does not exist: {sfz}")
    midi_path = tempdir / f"{output_name}.sfizz.mid"
    wav_path = tempdir / f"{output_name}.sfizz.wav"
    pm.write(str(midi_path))
    mapping = {
        "binary": binary,
        "sfz": str(sfz),
        "midi": str(midi_path),
        "wav": str(wav_path),
        "sample_rate": str(int(sample_rate)),
    }
    template = settings.get("command")
    if template:
        cmd = _format_command(template, mapping)
    else:
        # sfizz_render's CLI has changed across builds.  This is the documented
        # long-option form for recent versions; use command override if needed.
        cmd = [
            binary,
            "--sfz",
            str(sfz),
            "--midi",
            str(midi_path),
            "--wav",
            str(wav_path),
            "--sample-rate",
            str(int(sample_rate)),
        ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    if sr != int(sample_rate):
        audio = signal.resample_poly(audio, int(sample_rate), int(sr), axis=0).astype(np.float32)
    if minimum_duration > 0:
        target = int(round(float(minimum_duration) * int(sample_rate)))
        if len(audio) < target:
            audio = np.pad(audio, ((0, target - len(audio)), (0, 0)))
    return _coerce_stereo(audio)

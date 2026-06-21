"""Optional Pedalboard effect backend for music stems and buses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def _import_pedalboard():
    try:
        import pedalboard as pb  # type: ignore
    except Exception as ex:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "pedalboard is required for configured VST3/Pedalboard effects. "
            "Install the optional music renderer effects environment."
        ) from ex
    return pb


def _chans_first(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        return np.expand_dims(x, 0)
    if x.shape[0] in (1, 2) and x.shape[1] > x.shape[0]:
        return x.astype(np.float32, copy=False)
    return x.T.astype(np.float32, copy=False)


def _samples_first(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = np.expand_dims(x, 0)
    if x.shape[0] in (1, 2) and x.shape[1] > x.shape[0]:
        x = x.T
    if x.shape[1] == 1:
        x = np.column_stack([x[:, 0], x[:, 0]])
    if x.shape[1] > 2:
        x = x[:, :2]
    return x.astype(np.float32, copy=False)


def _resolve(path: str | Path, *, base_dir: Path | None = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p.resolve()


def _set_parameters(plugin: Any, parameters: dict[str, Any]) -> None:
    for key, value in dict(parameters or {}).items():
        try:
            setattr(plugin, str(key), value)
        except Exception:
            # Pedalboard plugin parameter surfaces differ by plugin.  Preserve a
            # strong error only for authors who explicitly ask for it.
            if bool(parameters.get("strict", False)):
                raise


def build_plugin(spec: dict[str, Any], *, base_dir: Path | None = None) -> Any:
    pb = _import_pedalboard()
    effect = str(spec.get("effect") or spec.get("type") or spec.get("kind") or "").lower().strip()
    if effect in {"compressor", "compress"}:
        return pb.Compressor(
            threshold_db=float(spec.get("threshold_db", -18.0)),
            ratio=float(spec.get("ratio", 3.0)),
            attack_ms=float(spec.get("attack_ms", 10.0)),
            release_ms=float(spec.get("release_ms", 100.0)),
        )
    if effect in {"limiter", "limit"}:
        return pb.Limiter(
            threshold_db=float(spec.get("threshold_db", -1.0)),
            release_ms=float(spec.get("release_ms", 50.0)),
        )
    if effect == "reverb":
        return pb.Reverb(
            room_size=float(spec.get("room_size", 0.25)),
            damping=float(spec.get("damping", 0.65)),
            wet_level=float(spec.get("wet_level", spec.get("wet", 0.10))),
            dry_level=float(spec.get("dry_level", 1.0)),
            width=float(spec.get("width", 1.0)),
            freeze_mode=float(spec.get("freeze_mode", 0.0)),
        )
    if effect == "chorus":
        plugin = pb.Chorus()
        for key in ("rate_hz", "depth", "centre_delay_ms", "feedback", "mix"):
            if key in spec:
                setattr(plugin, key, float(spec[key]))
        return plugin
    if effect == "phaser":
        plugin = pb.Phaser()
        for key in ("rate_hz", "depth", "centre_frequency_hz", "feedback", "mix"):
            if key in spec:
                setattr(plugin, key, float(spec[key]))
        return plugin
    if effect in {"distortion", "distort", "drive"}:
        return pb.Distortion(drive_db=float(spec.get("drive_db", 12.0)))
    if effect == "delay":
        return pb.Delay(
            delay_seconds=float(spec.get("delay_seconds", float(spec.get("delay_ms", 90.0)) / 1000.0)),
            feedback=float(spec.get("feedback", 0.15)),
            mix=float(spec.get("mix", 0.18)),
        )
    if effect in {"pitch_shift", "pitchshift"}:
        return pb.PitchShift(semitones=float(spec.get("semitones", 0.0)))
    if effect in {"highpass", "highpass_filter", "hp"}:
        return pb.HighpassFilter(cutoff_frequency_hz=float(spec.get("cutoff_hz", spec.get("hz", 80.0))))
    if effect in {"lowpass", "lowpass_filter", "lp"}:
        return pb.LowpassFilter(cutoff_frequency_hz=float(spec.get("cutoff_hz", spec.get("hz", 9000.0))))
    if effect in {"vst3", "vst", "plugin"}:
        plugin_path = _resolve(spec["path"], base_dir=base_dir)
        plugin = pb.load_plugin(str(plugin_path))
        _set_parameters(plugin, dict(spec.get("parameters") or {}))
        return plugin
    raise ValueError(
        f"unknown Pedalboard effect {effect!r}; use compressor, limiter, reverb, chorus, "
        "phaser, distortion, delay, pitch_shift, highpass, lowpass, or vst3."
    )


def apply_pedalboard_effects(
    audio: np.ndarray,
    sample_rate: int,
    effects: list[dict[str, Any]],
    *,
    base_dir: Path | None = None,
) -> np.ndarray:
    pb = _import_pedalboard()
    plugins = [build_plugin(spec, base_dir=base_dir) for spec in effects or []]
    if not plugins:
        return _samples_first(audio)
    board = pb.Pedalboard(plugins)
    rendered = board(_chans_first(audio), int(sample_rate))
    return _samples_first(rendered)

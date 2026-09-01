"""Optional Pedalboard effect backend for music stems and buses."""

from __future__ import annotations

import sys
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
    params = dict(parameters or {})
    # `strict` controls parameter-assignment errors; it is not a plugin parameter.
    strict = bool(params.pop("strict", False))
    for key, value in params.items():
        try:
            setattr(plugin, str(key), value)
        except Exception as ex:
            # Pedalboard plugin parameter surfaces differ by plugin. Never
            # drop an authored parameter silently — that is dead config.
            if strict:
                raise
            print(
                f"[ambition_music_renderer] VST3 parameter {key!r} could not be "
                f"set on {type(plugin).__name__}: {ex}",
                file=sys.stderr,
            )


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
    if effect in {"gain", "volume", "level"}:
        return pb.Gain(gain_db=float(spec.get("gain_db", spec.get("db", 0.0))))
    if effect in {"distortion", "distort", "drive"}:
        return pb.Distortion(drive_db=float(spec.get("drive_db", 12.0)))
    if effect in {"clipping", "clip", "hard_clip"}:
        return pb.Clipping(threshold_db=float(spec.get("threshold_db", -6.0)))
    if effect in {"bitcrush", "bit_crush", "crusher"}:
        return pb.Bitcrush(bit_depth=float(spec.get("bit_depth", 8.0)))
    if effect in {"resample", "downsample", "sample_rate_reduce"}:
        return pb.Resample(
            target_sample_rate=float(spec.get("target_sample_rate", spec.get("sample_rate", 12000.0)))
        )
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
        # Match validation semantics: accept a path or a plugin name resolved
        # through the discovered VST3 search directories.
        raw = spec.get("path") or spec.get("plugin")
        if not raw:
            raise ValueError("vst3 effect step needs a `path` or `plugin` key")
        plugin_path = _resolve(raw, base_dir=base_dir)
        if not plugin_path.exists():
            from ..audio_plugins import resolve_vst3_reference

            resolved = resolve_vst3_reference(str(raw), base_dir=base_dir)
            if resolved is None:
                raise FileNotFoundError(
                    f"VST3 {raw!r} not found as a path or a discoverable plugin "
                    "name; run `plugins list_vst3` to see local candidates"
                )
            plugin_path = Path(resolved)
        plugin = pb.load_plugin(str(plugin_path))
        _set_parameters(plugin, dict(spec.get("parameters") or {}))
        return plugin
    raise ValueError(
        f"unknown Pedalboard effect {effect!r}; use gain, compressor, limiter, "
        "reverb, chorus, phaser, distortion, clipping, bitcrush, resample, "
        "delay, pitch_shift, highpass, lowpass, or vst3."
    )


def _dbfs_levels(audio: np.ndarray) -> tuple[float, float]:
    """Return (rms_dbfs, peak_dbfs) without letting silence become -inf."""
    x = np.asarray(audio, dtype=np.float64)
    if x.size == 0:
        return -240.0, -240.0
    rms = float(np.sqrt(np.mean(np.square(x))))
    peak = float(np.max(np.abs(x)))
    rms_db = 20.0 * np.log10(max(rms, 1e-12))
    peak_db = 20.0 * np.log10(max(peak, 1e-12))
    return float(rms_db), float(peak_db)


def _effect_name(spec: dict[str, Any]) -> str:
    return str(spec.get("effect") or spec.get("type") or spec.get("kind") or "unknown")


def _shape_change_db(before: np.ndarray, after: np.ndarray) -> float:
    """Residual level after removing the best scalar gain match, relative to output."""
    x = np.asarray(before, dtype=np.float64).reshape(-1)
    y = np.asarray(after, dtype=np.float64).reshape(-1)
    if not x.size or not y.size:
        return -240.0
    denom = float(np.dot(x, x))
    scale = float(np.dot(y, x) / max(denom, 1e-30))
    residual = y - scale * x
    resid_rms = float(np.sqrt(np.mean(np.square(residual))))
    out_rms = float(np.sqrt(np.mean(np.square(y))))
    return float(20.0 * np.log10(max(resid_rms / max(out_rms, 1e-30), 1e-12)))


def _apply_one_plugin(
    audio: np.ndarray,
    sample_rate: int,
    plugin: Any,
    spec: dict[str, Any],
) -> np.ndarray:
    """Apply one plugin with optional explicit parallel wet/dry blending."""
    dry = _samples_first(audio)
    board = _import_pedalboard().Pedalboard([plugin])
    rendered = _samples_first(board(_chans_first(dry), int(sample_rate)))
    if "wet_mix" not in spec:
        return rendered
    wet_mix = float(np.clip(float(spec.get("wet_mix", 1.0)), 0.0, 1.0))
    return ((1.0 - wet_mix) * dry + wet_mix * rendered).astype(np.float32, copy=False)


def apply_pedalboard_effects(
    audio: np.ndarray,
    sample_rate: int,
    effects: list[dict[str, Any]],
    *,
    base_dir: Path | None = None,
    report_levels: bool = False,
    label: str | None = None,
) -> np.ndarray:
    pb = _import_pedalboard()
    specs = [dict(spec or {}) for spec in effects or []]
    plugins = [build_plugin(spec, base_dir=base_dir) for spec in specs]
    if not plugins:
        return _samples_first(audio)
    if not report_levels and not any("wet_mix" in spec for spec in specs):
        board = pb.Pedalboard(plugins)
        rendered = board(_chans_first(audio), int(sample_rate))
        return _samples_first(rendered)

    # Process one plugin at a time when diagnostics or explicit wet/dry mixing
    # are requested. This exposes the actual level hitting nonlinear stages and
    # makes parallel degradation deterministic without requiring a plugin-specific
    # mix control.
    out = _samples_first(audio)
    chain_label = str(label or "pedalboard")
    in_rms, in_peak = _dbfs_levels(out)
    print(
        f"[music fx] chain={chain_label} input rms_dbfs={in_rms:.2f} peak_dbfs={in_peak:.2f}",
        file=sys.stderr,
    )
    for idx, (spec, plugin) in enumerate(zip(specs, plugins)):
        before = out
        before_rms, before_peak = _dbfs_levels(before)
        out = _apply_one_plugin(before, sample_rate, plugin, spec)
        after_rms, after_peak = _dbfs_levels(out)
        shape_db = _shape_change_db(before, out)
        wet_text = f" wet_mix={float(spec['wet_mix']):.3f}" if "wet_mix" in spec else ""
        print(
            f"[music fx] chain={chain_label} effect={idx}:{_effect_name(spec)} "
            f"in_rms_dbfs={before_rms:.2f} in_peak_dbfs={before_peak:.2f} "
            f"out_rms_dbfs={after_rms:.2f} out_peak_dbfs={after_peak:.2f} "
            f"shape_change_db={shape_db:.2f}{wet_text}",
            file=sys.stderr,
        )
    return out

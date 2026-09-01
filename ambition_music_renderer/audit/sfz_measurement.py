"""Independent measurements for installed SFZ instruments.

The smoke renderer answers "does this patch make audio?".  This module answers
the harder questions that a renderer cannot infer from a key span: which region
was selected, what pitch the SFZ author assigned to its sample, whether a raw
sample supports that claim, and whether repeated rendered attacks contain
evidence of round-robin variation.
"""

from __future__ import annotations

import itertools
import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import soundfile as sf


_OPCODE_RE = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>[^\s]+)")
_INCLUDE_RE = re.compile(r"#include\s+[\"<]([^\">]+)[\">]", re.IGNORECASE)
_DEFINE_RE = re.compile(
    r"#define\s+(\$[A-Za-z_][A-Za-z0-9_]*)\s+(.+?)(?=\s+#define|$)"
)
_MACRO_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")
_REGION_CACHE: dict[Path, tuple[int, list[dict[str, Any]]]] = {}
_STARTUP_CC_CACHE: dict[Path, tuple[int, dict[int, int]]] = {}


def midi_frequency(midi: float) -> float:
    return 440.0 * 2.0 ** ((float(midi) - 69.0) / 12.0)


def _midi(value: str) -> int | None:
    value = value.strip().lower()
    if value.lstrip("-").isdigit():
        return int(value)
    names = {"c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3,
             "e": 4, "f": 5, "f#": 6, "gb": 6, "g": 7, "g#": 8,
             "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11}
    match = re.fullmatch(r"([a-g](?:#|b)?)(-?\d+)", value)
    if not match or match.group(1) not in names:
        return None
    return 12 * (int(match.group(2)) + 1) + names[match.group(1)]


def _value(value: str) -> int | float | str:
    parsed = _midi(value)
    if parsed is not None and not value.lstrip("-").isdigit():
        return parsed
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _sample_path(source_file: Path, sample: str) -> Path | None:
    relative = Path(sample.replace("\\", "/"))
    for parent in (source_file.parent, *source_file.parents):
        candidate = (parent / relative).resolve()
        if candidate.is_file():
            return candidate
    return None


def _include_path(source_file: Path, include: str) -> Path:
    """Resolve both normal relative includes and libraries rooted above maps."""

    relative = Path(include.replace("\\", "/"))
    for parent in (source_file.parent, *source_file.parents):
        candidate = (parent / relative).resolve()
        if candidate.is_file():
            return candidate
    return (source_file.parent / relative).resolve()


def sfz_startup_cc(path: str | Path) -> dict[int, int]:
    """Collect numeric ``set_cc`` defaults from the expanded SFZ program."""

    root = Path(path).resolve()
    try:
        stamp = root.stat().st_mtime_ns
    except OSError:
        return {}
    cached = _STARTUP_CC_CACHE.get(root)
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])

    values: dict[int, int] = {}
    seen: set[Path] = set()

    def walk(current: Path) -> None:
        current = current.resolve()
        if current in seen or not current.is_file():
            return
        seen.add(current)
        try:
            lines = current.read_text(errors="ignore").splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.split("//", 1)[0].split(";", 1)[0]
            for include in _INCLUDE_RE.findall(line):
                walk(_include_path(current, include))
            match = re.search(r"\bset_cc(\d+)=(-?\d+)\b", line)
            if match:
                values[int(match.group(1))] = int(match.group(2))

    walk(root)
    _STARTUP_CC_CACHE[root] = (stamp, dict(values))
    return values


def sfz_regions(path: str | Path) -> list[dict[str, Any]]:
    """Expand includes and return effective region opcodes with provenance."""

    root = Path(path).resolve()
    try:
        stamp = root.stat().st_mtime_ns
    except OSError:
        return []
    cached = _REGION_CACHE.get(root)
    if cached is not None and cached[0] == stamp:
        return [dict(region) for region in cached[1]]

    regions: list[dict[str, Any]] = []
    seen_stack: set[Path] = set()

    def walk(
        current: Path,
        global_ops: dict[str, Any],
        master_ops: dict[str, Any],
        group_ops: dict[str, Any],
        macros: dict[str, str],
    ) -> None:
        current = current.resolve()
        if current in seen_stack or not current.is_file():
            return
        seen_stack.add(current)
        section = ""
        current_region: dict[str, Any] | None = None
        try:
            lines = current.read_text(errors="ignore").splitlines()
        except OSError:
            seen_stack.remove(current)
            return

        def finish() -> None:
            if current_region is None or "sample" not in current_region:
                return
            item = dict(current_region)
            item["source_file"] = str(current)
            item["sample_path"] = str(_sample_path(current, str(item["sample"]))) if _sample_path(current, str(item["sample"])) else None
            regions.append(item)

        for raw in lines:
            line = raw.split("//", 1)[0].split(";", 1)[0].strip()
            if not line:
                continue
            defines = list(_DEFINE_RE.finditer(line))
            if defines:
                for define in defines:
                    value = define.group(2).strip()
                    for _ in range(8):
                        expanded = _MACRO_RE.sub(lambda match: macros.get(match.group(0), match.group(0)), value)
                        if expanded == value:
                            break
                        value = expanded
                    macros[define.group(1)] = value
                continue
            for include in _INCLUDE_RE.findall(line):
                walk(
                    _include_path(current, include),
                    global_ops,
                    master_ops,
                    group_ops,
                    macros,
                )
            line = _MACRO_RE.sub(lambda match: macros.get(match.group(0), match.group(0)), line)
            tag = re.search(r"<(global|master|group|region|control)>", line, re.IGNORECASE)
            if tag:
                section = tag.group(1).lower()
                if section == "region":
                    finish()
                    current_region = {**global_ops, **master_ops, **group_ops}
                    current_region["source_file"] = str(current)
                elif section == "group":
                    group_ops = {}
                elif section == "master":
                    master_ops = {}
                elif section == "global":
                    global_ops = {}
                elif section == "control":
                    current_region = None
            target = current_region if section == "region" and current_region is not None else (
                group_ops if section == "group" else master_ops if section == "master" else global_ops if section == "global" else None
            )
            if target is not None:
                for match in _OPCODE_RE.finditer(line):
                    target[match.group("key").lower()] = _value(match.group("value"))
        finish()
        seen_stack.remove(current)

    walk(root, {}, {}, {}, {})
    _REGION_CACHE[root] = (stamp, [dict(region) for region in regions])
    return regions


def _bound(
    region: dict[str, Any],
    low: str,
    high: str,
    default_low: int,
    default_high: int,
) -> tuple[int, int]:
    key = region.get("key") if low == "lokey" else None
    lo = region.get(low, key if key is not None else default_low)
    hi = region.get(high, key if key is not None else default_high)
    try:
        return int(lo), int(hi)
    except (TypeError, ValueError):
        return default_low, default_high


def select_regions(
    path: str | Path,
    note: int,
    *,
    velocity: int = 100,
    controls: dict[int, int] | None = None,
    keyswitch: int | None = None,
) -> list[dict[str, Any]]:
    """Return all effective regions that can respond to a MIDI trigger."""

    controls = sfz_startup_cc(path) if controls is None else controls
    selected: list[dict[str, Any]] = []
    for region in sfz_regions(path):
        lo, hi = _bound(region, "lokey", "hikey", 0, 127)
        vlo, vhi = _bound(region, "lovel", "hivel", 1, 127)
        if not (lo <= note <= hi and vlo <= velocity <= vhi):
            continue
        if keyswitch is not None and "sw_last" in region and int(region["sw_last"]) != int(keyswitch):
            continue
        matched = True
        for key, value in region.items():
            match = re.fullmatch(r"(?:lo|hi)cc(\d+)", key)
            if not match:
                continue
            cc = int(match.group(1))
            actual = int(controls.get(cc, 0))
            if not isinstance(value, (int, float)):
                continue
            if key.startswith("lo") and actual < int(value):
                matched = False
            if key.startswith("hi") and actual > int(value):
                matched = False
        if matched:
            selected.append({
                "source_file": region.get("source_file"),
                "sample": region.get("sample"),
                "sample_path": region.get("sample_path"),
                "lokey": lo,
                "hikey": hi,
                "lovel": vlo,
                "hivel": vhi,
                "pitch_keycenter": region.get("pitch_keycenter"),
                "transpose": region.get("transpose", 0),
                "tune": region.get("tune", 0),
                "pitch_keytrack": region.get("pitch_keytrack", 100),
                "seq_length": region.get("seq_length"),
                "seq_position": region.get("seq_position"),
                "lorand": region.get("lorand"),
                "hirand": region.get("hirand"),
            })
    return selected


def _steady_audio(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    mono = np.asarray(audio, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    mono = mono[np.isfinite(mono)]
    if not len(mono):
        return mono
    start = min(len(mono) // 4, int(0.08 * sample_rate))
    end = min(len(mono), start + int(0.65 * sample_rate))
    return mono[start:end]


def _spectral_score(audio: np.ndarray, sample_rate: int, frequency: float) -> float:
    if frequency <= 0 or len(audio) < 1024:
        return 0.0
    window = np.hanning(len(audio))
    spectrum = np.abs(np.fft.rfft(audio * window))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    total = float(np.sum(spectrum[(freqs >= max(20.0, frequency / 2)) & (freqs <= frequency * 12)])) + 1e-12
    score = 0.0
    for harmonic in range(1, 9):
        center = harmonic * frequency
        width = max(3.0, center * 0.025)
        mask = np.abs(freqs - center) <= width
        if np.any(mask):
            score += float(np.max(spectrum[mask])) / total / math.sqrt(harmonic)
    return score


def _autocorrelation_score(audio: np.ndarray, sample_rate: int, frequency: float) -> float:
    if frequency <= 0 or len(audio) < 1024:
        return 0.0
    centered = audio - float(np.mean(audio))
    denom = float(np.dot(centered, centered)) + 1e-12
    period = sample_rate / frequency
    scores = []
    for multiplier in (0.995, 1.0, 1.005):
        lag = int(round(period * multiplier))
        if 1 <= lag < len(centered):
            scores.append(float(np.dot(centered[:-lag], centered[lag:]) / denom))
    return max(scores, default=0.0)


def raw_pitch_diagnostic(audio: np.ndarray, sample_rate: int, expected_midi: float) -> dict[str, Any]:
    """Compare expected F0, F0/2, and 2*F0 with two independent measures."""

    window = _steady_audio(audio, sample_rate)
    expected_hz = midi_frequency(expected_midi)
    if len(window) < 1024 or float(np.max(np.abs(window), initial=0.0)) < 1e-6:
        return {"status": "unreliable", "expected_midi": expected_midi, "scores": {}}
    candidates = {"half": expected_hz / 2.0, "expected": expected_hz, "double": expected_hz * 2.0}
    spectral = {name: _spectral_score(window, sample_rate, freq) for name, freq in candidates.items()}
    autocorrelation = {name: _autocorrelation_score(window, sample_rate, freq) for name, freq in candidates.items()}
    combined = {
        name: 0.55 * spectral[name] / max(spectral.values(), default=1e-12)
        + 0.45 * max(0.0, autocorrelation[name]) / max(max(autocorrelation.values()), 1e-12)
        for name in candidates
    }
    ordered = sorted(combined, key=combined.get, reverse=True)
    top, second = ordered[0], ordered[1]
    margin = combined[top] - combined[second]
    if margin < 0.08:
        status = "octave_ambiguous"
    elif top == "expected":
        status = "reliable"
    elif combined["expected"] >= combined[top] - 0.18:
        # A strong second harmonic can win the narrow spectral competition
        # while autocorrelation still supports the written fundamental.
        status = "octave_ambiguous"
    else:
        status = "actual_pitch_mismatch"
    return {
        "status": status,
        "expected_midi": round(float(expected_midi), 3),
        "expected_hz": round(expected_hz, 3),
        "winner": top,
        "scores": {name: round(float(combined[name]), 4) for name in candidates},
        "spectral_scores": {name: round(float(value), 6) for name, value in spectral.items()},
        "autocorrelation_scores": {name: round(float(value), 6) for name, value in autocorrelation.items()},
        "margin": round(float(margin), 4),
    }


def read_audio(path: str | Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(str(path), always_2d=True, dtype="float32")
    return np.asarray(audio), int(sample_rate)


def repeat_variation(
    audio: np.ndarray,
    sample_rate: int,
    *,
    count: int,
    start_s: float = 0.08,
    interval_s: float = 0.55,
    window_s: float = 0.18,
) -> dict[str, Any]:
    """Measure normalized attack similarity, not merely peak-level spread."""

    attacks: list[np.ndarray] = []
    mono = np.asarray(audio, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    width = max(128, int(window_s * sample_rate))
    for index in range(max(1, int(count))):
        start = int((start_s + interval_s * index) * sample_rate)
        segment = mono[start:start + width]
        if len(segment) < width // 2:
            continue
        segment = segment - float(np.mean(segment))
        norm = float(np.linalg.norm(segment))
        if norm > 1e-8:
            attacks.append(segment / norm)
    correlations = [float(np.dot(a, b)) for a, b in itertools.combinations(attacks, 2)]
    unique = sum(1 for value in correlations if value < 0.985)
    if len(attacks) < 2:
        status = "insufficient_evidence"
    elif unique >= max(1, len(attacks) // 2):
        status = "variation_evidenced"
    elif unique:
        status = "weak_variation_evidence"
    else:
        status = "no_variation_evidence"
    return {
        "requested_count": int(count),
        "measured_attacks": len(attacks),
        "unique_attack_evidence": int(unique),
        "pairwise_correlation_min": round(min(correlations), 5) if correlations else None,
        "pairwise_correlation_median": round(float(np.median(correlations)), 5) if correlations else None,
        "repeat_variation_status": status,
    }

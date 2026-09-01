"""Render smoke probes for the optional real-instrument SFZ libraries.

This is intentionally a library audit, not a song test.  The probe exercises a
small set of notes through the same ``sfizz_render`` path used by MusicIR and
records enough provenance to explain a silent or misleading patch.
"""

from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pretty_midi
import librosa
from ..backends.sfizz_backend import render_sfizz, sfz_key_span
from ..instrument_libraries import configured_sfz_roots, resolve_sfz_reference
from .sfz_measurement import repeat_variation, select_regions


_OPCODE_RE = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>[^\s]+)")
_INCLUDE_RE = re.compile(r"#include\s+[\"<]([^\">]+)[\">]", re.IGNORECASE)
_KEYSWITCH_KEYS = {"sw_lokey", "sw_hikey", "sw_last", "sw_default", "sw_label"}
_RANGE_KEYS = {"lokey", "hikey", "key", "pitch_keycenter"}


@dataclass(frozen=True)
class SmokeCandidate:
    name: str
    path: str | None = None
    library_ref: str | None = None
    prefer: tuple[str, ...] = ()
    family: str = "pitched"
    articulation: str = "sustain"
    startup_cc: tuple[tuple[int, int], ...] = ()
    probes: tuple[int, ...] = ()
    drum: bool = False
    pitch_probe: bool = True
    keyswitch_probes: tuple[int, ...] = ()
    velocity_probes: tuple[int, ...] = (32, 80, 120)
    repeat_count: int = 8


# These are the patches SOL identified as useful for the fast rock cue.  Paths
# are relative to an SFZ root when the archive has a stable upstream layout;
# aliases are used for families whose chosen program name is installation data.
CANDIDATES: tuple[SmokeCandidate, ...] = (
    SmokeCandidate("emily_basic", "Karoryfer/Emilyguitar/Emilyguitar/emily_basic.sfz", family="guitar", articulation="basic", probes=(48, 55, 60), pitch_probe=False),
    SmokeCandidate("emily_chords", library_ref="guitar.emily", prefer=("chords", "emily"), family="guitar", articulation="power-chord", probes=(40, 48, 55), pitch_probe=False, keyswitch_probes=(33, 34, 35)),
    SmokeCandidate("emily_chords_wide", "Karoryfer/Emilyguitar/Emilyguitar/emily_chords_wide.sfz", family="guitar", articulation="wide-power-chord", probes=(40, 48, 55), pitch_probe=False, keyswitch_probes=(33, 34, 35)),
    SmokeCandidate("blackgreen_green", "Karoryfer/BlackAndGreenGuitars/Programs/01-green_keyswitch.sfz", family="guitar", articulation="green", probes=(52, 60, 67), keyswitch_probes=(36, 37, 38)),
    SmokeCandidate("blackgreen_black", "Karoryfer/BlackAndGreenGuitars/Programs/02-black_keyswitch.sfz", family="guitar", articulation="black", probes=(52, 60, 67), keyswitch_probes=(36, 37, 38)),
    SmokeCandidate("blackgreen_twang", "Karoryfer/BlackAndGreenGuitars/Programs/04-green_twang.sfz", family="guitar", articulation="twang", probes=(52, 60, 67)),
    SmokeCandidate("blackgreen_staccato", "Karoryfer/BlackAndGreenGuitars/Programs/05-green_staccato.sfz", family="guitar", articulation="staccato", probes=(52, 60, 67)),
    SmokeCandidate("shiny_electric", "Karoryfer/Shinyguitar/Shinyguitar/Programs/electric_five.sfz", family="guitar", articulation="electric-sustain", startup_cc=((100, 64), (107, 127)), probes=(37, 52, 64, 76)),
    SmokeCandidate("growlybass", library_ref="bass.growly", family="bass", articulation="clean-finger", probes=(36, 43, 52)),
    SmokeCandidate("swagbass", library_ref="bass.swag", family="bass", articulation="clean-finger", probes=(36, 43, 52)),
    SmokeCandidate("black_and_blue_bass", library_ref="bass.black_and_blue", prefer=("babyblue all", "black and blue"), family="bass", articulation="baby-blue", probes=(36, 43, 52)),
    SmokeCandidate("fashionbass", "Karoryfer/Fashionbass/Fashionbass/fashionbass_clean.sfz", family="bass", articulation="clean", probes=(36, 48, 60)),
    SmokeCandidate("pastabass", "Karoryfer/Pastabass/Pastabass/linguine.sfz", family="bass", articulation="linguine", probes=(36, 40, 48)),
    SmokeCandidate("gogodze", "Karoryfer/GogodzePhuVolII/Gogodze_Phu_vol_II/Programs/Kit.sfz", family="drums", articulation="kit", probes=(35, 36, 38, 42, 46, 49), drum=True, pitch_probe=False),
    SmokeCandidate("big_rusty", library_ref="drums.big_rusty", prefer=("01 full", "big rusty"), family="drums", articulation="full-kit", probes=(35, 36, 38, 42, 46, 49), drum=True, pitch_probe=False),
    SmokeCandidate("naked_drums", "WilkinsonAudio/NakedDrums/WilkinsonAudio.NakedDrums-master/Wilkinson Audio/Naked Drums/User/Naked Drums GM.sfz", family="drums", articulation="gm-kit", probes=(35, 36, 38, 42, 46, 49), drum=True, pitch_probe=False),
    SmokeCandidate("muldjord", "DrumGizmo/MuldjordKit/DrumGizmo.MuldjordKit-master/DrumGizmo/MuldjordKit/Stereo/DrumGizmo MuldjordKit.sfz", family="drums", articulation="stereo-kit", probes=(35, 36, 38, 42, 46, 49), drum=True, pitch_probe=False),
)


def _parse_value(value: str) -> int | None:
    value = value.strip().lower()
    if value.lstrip("-").isdigit():
        return int(value)
    # SFZ note names use the same c4 == MIDI 60 convention as the backend.
    from ..backends.sfizz_backend import _note_to_midi

    return _note_to_midi(value)


def inspect_sfz(path: Path) -> dict[str, Any]:
    """Inspect an SFZ and recursively read its includes and sample references."""

    files: list[Path] = []
    samples: list[str] = []
    range_opcode_count = 0
    keyswitches: list[dict[str, int | str]] = []
    startup_cc: dict[str, int] = {}
    missing: list[str] = []
    seen: set[Path] = set()
    include_base = path.resolve().parent

    def visit(current: Path) -> None:
        nonlocal range_opcode_count
        current = current.resolve()
        if current in seen or not current.exists():
            return
        seen.add(current)
        files.append(current)
        try:
            text = current.read_text(errors="ignore")
        except OSError:
            return
        for include in _INCLUDE_RE.findall(text):
            visit((include_base / include.replace("\\", "/")).resolve())

        current_range: dict[str, int] = {}
        for line in text.splitlines():
            line = line.split("//", 1)[0].split(";", 1)[0]
            for match in _OPCODE_RE.finditer(line):
                key = match.group("key").lower()
                value = match.group("value")
                if key == "sample":
                    samples.append(value)
                    if "$" not in value and "*" not in value:
                        sample_path = _find_sample(current, value)
                        if sample_path is None:
                            missing.append(str((current.parent / value.replace("\\", "/")).resolve()))
                elif key in _RANGE_KEYS:
                    parsed = _parse_value(value)
                    if parsed is not None:
                        range_opcode_count += 1
                elif key in _KEYSWITCH_KEYS:
                    parsed = _parse_value(value)
                    if parsed is not None:
                        keyswitches.append({"opcode": key, "value": parsed})
                elif key.startswith("set_cc"):
                    cc = key.removeprefix("set_cc")
                    if cc.isdigit() and value.lstrip("-").isdigit():
                        startup_cc[cc] = int(value)

    visit(path)
    span = sfz_key_span(str(path))
    return {
        "files_read": len(files),
        "include_files": [str(item) for item in files[1:]],
        "sample_count": len(samples),
        "sample_count_unique": len(set(samples)),
        "missing_samples": sorted(set(missing)),
        "key_span": list(span) if span else None,
        "keyswitches": keyswitches,
        "keyswitch_ranges": _keyswitch_ranges(keyswitches),
        "keyswitch_values": _keyswitch_values(keyswitches),
        "startup_cc": {str(key): value for key, value in sorted(startup_cc.items(), key=lambda item: int(item[0]))},
        "range_opcode_count": range_opcode_count,
    }


def _keyswitch_ranges(keys: Iterable[dict[str, int | str]]) -> list[list[int]]:
    lows = sorted({int(item["value"]) for item in keys if item.get("opcode") == "sw_lokey"})
    highs = sorted({int(item["value"]) for item in keys if item.get("opcode") == "sw_hikey"})
    if not lows and not highs:
        return []
    if not lows:
        return [[value, value] for value in highs]
    if not highs:
        return [[value, value] for value in lows]
    return [[low, next((high for high in highs if high >= low), low)] for low in lows]


def _keyswitch_values(keys: Iterable[dict[str, int | str]]) -> list[int]:
    """List actual switch states without confusing them with playable notes."""
    return sorted({
        int(item["value"])
        for item in keys
        if item.get("opcode") in {"sw_last", "sw_default"}
    })


def _find_sample(sfz_file: Path, sample: str) -> Path | None:
    """Resolve samples as sfizz does for include-heavy libraries.

    Many distributed SFZs put regions in ``Programs/modules`` while keeping
    their sample tree beside the top-level ``Programs`` directory.  Searching
    the including file's ancestor chain catches that layout without declaring
    valid samples missing merely because an include fragment is nested.
    """

    relative = Path(sample.replace("\\", "/"))
    for parent in (sfz_file.parent, *sfz_file.parents):
        candidate = (parent / relative).resolve()
        if candidate.is_file():
            return candidate
    return None


def _db(value: float) -> float:
    return round(20.0 * math.log10(max(float(value), 1e-10)), 2)


def _pitch_diagnostic(audio: np.ndarray, sample_rate: int, expected: int) -> dict[str, Any]:
    """Estimate pitch with a harmonic score anchored to the requested note.

    A free-running YIN estimate can report a loud guitar harmonic as the note
    itself. This search allows a genuine octave or mapping error, scores the
    fundamental and its harmonics together, and reports ambiguity as
    ``pitch_unreliable`` rather than turning an audible render into a failure.
    """
    mono = np.asarray(audio, dtype=np.float64)
    if mono.ndim == 2:
        mono = mono.mean(axis=1)
    if not np.any(np.abs(mono) > 1e-5):
        return {
            "estimated_midi": None, "pitch_error_cents": None,
            "pitch_confidence": 0.0, "pitch_unreliable": True,
            "pitch_status": "unavailable",
        }
    start = min(len(mono) // 4, int(0.10 * sample_rate))
    window = mono[start : start + int(0.65 * sample_rate)]
    if len(window) < 2048:
        return {
            "estimated_midi": None, "pitch_error_cents": None,
            "pitch_confidence": 0.0, "pitch_unreliable": True,
            "pitch_status": "unavailable",
        }

    expected_frequency = 440.0 * 2.0 ** ((float(expected) - 69.0) / 12.0)
    # The old free-running estimator searched 55..1400 Hz and regularly chose
    # an upper guitar partial. Keep YIN's periodicity model, but constrain it to
    # a generous two-sided window around the authored mapping. That still admits
    # a true octave/mapping error while making the expected register decisive
    # when a harmonic-rich note has several plausible explanations.
    f0 = librosa.yin(
        window.astype(np.float32),
        fmin=max(20.0, expected_frequency / 2.05),
        fmax=min(sample_rate / 2.0 - 1.0, expected_frequency * 2.05),
        sr=sample_rate,
        frame_length=4096,
        hop_length=256,
    )
    finite = f0[np.isfinite(f0)]
    if not len(finite):
        return {
            "estimated_midi": None, "pitch_error_cents": None,
            "pitch_confidence": 0.0, "pitch_unreliable": True,
            "pitch_status": "unavailable",
        }
    frame_midi = 69.0 + 12.0 * np.log2(finite / 440.0)
    # Short guitar attacks can make YIN alternate between the fundamental and
    # its octave on adjacent frames. Select the densest local pitch cluster;
    # this preserves a consistent real octave error while rejecting isolated
    # harmonic/octave frames from the confidence calculation.
    cluster_width = 0.20
    cluster_sizes = np.array([
        np.count_nonzero(np.abs(frame_midi - value) <= cluster_width)
        for value in frame_midi
    ])
    best_frame = max(
        range(len(frame_midi)),
        key=lambda index: (int(cluster_sizes[index]), -abs(float(frame_midi[index]) - float(expected))),
    )
    cluster = frame_midi[np.abs(frame_midi - frame_midi[best_frame]) <= cluster_width]
    midi = float(np.median(cluster))
    frequency = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    cents = (midi - float(expected)) * 100.0
    deviation_semitones = float(np.median(np.abs(cluster - midi)))
    # Periodicity distinguishes a quiet/noisy or polyphonic probe from a clean
    # note. It is intentionally a warning signal, never a render failure.
    centered = window - float(np.mean(window))
    lag = max(1, min(len(centered) - 1, int(round(sample_rate / frequency))))
    denominator = float(np.dot(centered, centered)) + 1e-12
    periodicity = max(0.0, min(1.0, float(np.dot(centered[:-lag], centered[lag:]) / denominator)))
    confidence = max(0.0, min(1.0, periodicity * math.exp(-deviation_semitones * 3.0)))
    unreliable = confidence < 0.25 or deviation_semitones > 0.08 or abs(cents) > 500.0
    return {
        "estimated_midi": round(midi, 2),
        "pitch_error_cents": round(cents, 2),
        "pitch_confidence": round(confidence, 3),
        "pitch_unreliable": bool(unreliable),
        "pitch_status": "unreliable" if unreliable else "reliable",
        "pitch_expected_hz": round(expected_frequency, 3),
        "pitch_method": "expected_anchored_yin",
        "pitch_periodicity": round(periodicity, 3),
    }


def _estimate_pitch(audio: np.ndarray, sample_rate: int, expected: int) -> tuple[float | None, float | None]:
    """Backward-compatible two-value view of :func:`_pitch_diagnostic`."""
    diagnostic = _pitch_diagnostic(audio, sample_rate, expected)
    return diagnostic["estimated_midi"], diagnostic["pitch_error_cents"]


def _make_probe_pm(
    candidate: SmokeCandidate,
    note: int,
    *,
    velocity: int = 108,
    keyswitch: int | None = None,
    repeats: int = 1,
) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=120, resolution=960)
    inst = pretty_midi.Instrument(program=0, is_drum=candidate.drum, name=candidate.name)
    if keyswitch is not None:
        # Switch notes are deliberately short and quiet; the report evaluates
        # the following playable note, not accidental audio from the controller.
        inst.notes.append(pretty_midi.Note(velocity=1, pitch=keyswitch, start=0.01, end=0.04))
    for index in range(max(1, int(repeats))):
        start = (0.05 if repeats == 1 else 0.08) + 0.55 * index
        duration = 0.80 if repeats == 1 else 0.42
        inst.notes.append(pretty_midi.Note(velocity=int(velocity), pitch=note, start=start, end=start + duration))
    for number, value in candidate.startup_cc:
        inst.control_changes.append(pretty_midi.ControlChange(number, value, 0.0))
    pm.instruments.append(inst)
    return pm


def _resolve_candidate(candidate: SmokeCandidate, roots: list[Path]) -> Path | None:
    if candidate.path:
        for root in roots:
            direct = (root / candidate.path).resolve()
            if direct.is_file():
                return direct
    if candidate.library_ref:
        return resolve_sfz_reference(
            library_ref=candidate.library_ref, prefer=candidate.prefer, roots=roots
        )
    return None


def run_sfz_smoke(
    *,
    roots: Iterable[str | Path] | None = None,
    candidates: Iterable[SmokeCandidate] = CANDIDATES,
    sample_rate: int = 24000,
    render_timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Render all configured candidates and return a JSON-ready audit report."""

    search_roots = configured_sfz_roots(roots)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ambition-sfz-smoke-") as temp:
        tempdir = Path(temp)
        for candidate in candidates:
            resolved = _resolve_candidate(candidate, search_roots)
            row: dict[str, Any] = {
                "name": candidate.name,
                "family": candidate.family,
                "articulation": candidate.articulation,
                "requested": candidate.path or candidate.library_ref,
                "prefer_requested": list(candidate.prefer),
                "resolved": str(resolved) if resolved else None,
                "startup_cc_requested": {str(key): value for key, value in candidate.startup_cc},
                "probes": [],
            }
            if resolved is None:
                row["status"] = "UNRESOLVED"
                rows.append(row)
                continue
            row.update(inspect_sfz(resolved))
            key_span = row.get("key_span")
            in_range_count = 0
            failed_count = 0
            for index, note in enumerate(candidate.probes):
                probe: dict[str, Any] = {"note": note, "note_name": pretty_midi.note_number_to_name(note)}
                probe["selected_regions"] = select_regions(
                    resolved,
                    note,
                    velocity=80,
                    controls=dict(candidate.startup_cc) if candidate.startup_cc else None,
                )
                if key_span and not (int(key_span[0]) <= note <= int(key_span[1])):
                    probe.update({"status": "OUT_OF_RANGE", "skipped": True, "rendered": False})
                    row["probes"].append(probe)
                    continue
                in_range_count += 1
                try:
                    audio = render_sfizz(
                        _make_probe_pm(candidate, note),
                        sfz_path=resolved,
                        sample_rate=sample_rate,
                        tempdir=tempdir,
                        output_name=f"{candidate.name}-{index}",
                        minimum_duration=1.1,
                        settings={
                            "renderer": "cli",
                            "binary": "sfizz_render",
                            "fold_to_range": False,
                            "render_timeout_s": render_timeout_s,
                            "eot_padding_seconds": 0.5,
                        },
                    )
                    array = np.asarray(audio)
                    peak = float(np.max(np.abs(array))) if array.size else 0.0
                    rms = float(np.sqrt(np.mean(np.square(array)))) if array.size else 0.0
                    pitch_diagnostic: dict[str, Any] = {
                        "estimated_midi": None,
                        "pitch_error_cents": None,
                        "pitch_confidence": None,
                        "pitch_unreliable": False,
                        "pitch_status": "not_requested",
                    }
                    if candidate.pitch_probe and not candidate.drum:
                        pitch_diagnostic = _pitch_diagnostic(array, sample_rate, note)
                    probe.update({
                        "status": "ok",
                        "rendered": True,
                        "duration_s": round(float(len(array) / sample_rate), 3),
                        "peak_dbfs": _db(peak),
                        "rms_dbfs": _db(rms),
                        "silent": bool(peak < 1e-3),
                        **pitch_diagnostic,
                    })
                except Exception as ex:  # one broken library should not hide the rest
                    failed_count += 1
                    probe.update({"rendered": False, "silent": True, "error": f"{type(ex).__name__}: {ex}"})
                row["probes"].append(probe)

            # Use one in-range note for the performance-condition probes. These
            # are separate renders so velocity and round-robin failures remain
            # attributable instead of being hidden inside a mixed waveform.
            condition_note = next(
                (note for note in candidate.probes if not key_span or key_span[0] <= note <= key_span[1]),
                None,
            )
            velocity_report: list[dict[str, Any]] = []
            repeat_report: list[dict[str, Any]] = []
            if condition_note is not None:
                for velocity in candidate.velocity_probes:
                    variant: dict[str, Any] = {"velocity": int(velocity), "rendered": False}
                    try:
                        audio = render_sfizz(
                            _make_probe_pm(candidate, condition_note, velocity=int(velocity)),
                            sfz_path=resolved, sample_rate=sample_rate, tempdir=tempdir,
                            output_name=f"{candidate.name}-velocity-{velocity}", minimum_duration=1.1,
                            settings={"renderer": "cli", "binary": "sfizz_render", "fold_to_range": False, "render_timeout_s": render_timeout_s, "eot_padding_seconds": 0.5},
                        )
                        array = np.asarray(audio)
                        peak = float(np.max(np.abs(array))) if array.size else 0.0
                        variant.update({"rendered": True, "peak_dbfs": _db(peak), "silent": bool(peak < 1e-3)})
                    except Exception as ex:
                        failed_count += 1
                        variant["error"] = f"{type(ex).__name__}: {ex}"
                    velocity_report.append(variant)

                repeats = max(1, int(candidate.repeat_count))
                repeat: dict[str, Any] = {"note": condition_note, "count": repeats, "rendered": False}
                try:
                    audio = render_sfizz(
                        _make_probe_pm(candidate, condition_note, repeats=repeats),
                        sfz_path=resolved, sample_rate=sample_rate, tempdir=tempdir,
                        output_name=f"{candidate.name}-repeats", minimum_duration=2.8,
                        settings={"renderer": "cli", "binary": "sfizz_render", "fold_to_range": False, "render_timeout_s": render_timeout_s, "eot_padding_seconds": 0.5},
                    )
                    array = np.asarray(audio)
                    peaks = []
                    for repeat_index in range(repeats):
                        a = int((0.08 + 0.55 * repeat_index) * sample_rate)
                        b = min(len(array), int((0.50 + 0.55 * repeat_index) * sample_rate))
                        peaks.append(float(np.max(np.abs(array[a:b]))) if b > a else 0.0)
                    peak_db = [_db(value) for value in peaks]
                    repeat.update({
                        "rendered": True,
                        "peaks_dbfs": peak_db,
                        "peak_spread_db": round(max(peak_db, default=-120.0) - min(peak_db, default=-120.0), 2),
                        "silent": any(value < 1e-3 for value in peaks),
                        **repeat_variation(array, sample_rate, count=repeats),
                    })
                except Exception as ex:
                    failed_count += 1
                    repeat["error"] = f"{type(ex).__name__}: {ex}"
                repeat_report.append(repeat)

            articulation_report: list[dict[str, Any]] = []
            for switch in candidate.keyswitch_probes:
                switch_row: dict[str, Any] = {"keyswitch": int(switch), "rendered": False}
                if condition_note is None:
                    switch_row["status"] = "NO_IN_RANGE_NOTE"
                else:
                    try:
                        audio = render_sfizz(
                            _make_probe_pm(candidate, condition_note, keyswitch=int(switch)),
                            sfz_path=resolved, sample_rate=sample_rate, tempdir=tempdir,
                            output_name=f"{candidate.name}-keyswitch-{switch}", minimum_duration=1.1,
                            settings={"renderer": "cli", "binary": "sfizz_render", "fold_to_range": False, "render_timeout_s": render_timeout_s, "eot_padding_seconds": 0.5},
                        )
                        array = np.asarray(audio)
                        peak = float(np.max(np.abs(array))) if array.size else 0.0
                        switch_row.update({"status": "ok", "rendered": True, "peak_dbfs": _db(peak), "silent": bool(peak < 1e-3)})
                    except Exception as ex:
                        failed_count += 1
                        switch_row["error"] = f"{type(ex).__name__}: {ex}"
                articulation_report.append(switch_row)
            row["velocity_probes"] = velocity_report
            row["repeat_probes"] = repeat_report
            row["articulation_probes"] = articulation_report
            rendered = [probe for probe in row["probes"] if probe.get("rendered")]
            row["pitch_unreliable_count"] = sum(bool(probe.get("pitch_unreliable")) for probe in rendered)
            row["pitch_reliable_count"] = sum(probe.get("pitch_status") == "reliable" for probe in rendered)
            render_ok = bool(rendered) and not any(probe.get("silent") for probe in rendered) and failed_count == 0
            row["render_status"] = "ok" if render_ok else "SILENT_OR_FAILED"
            if not render_ok:
                row["validation_status"] = row["render_status"]
            elif candidate.pitch_probe and row["pitch_unreliable_count"]:
                row["validation_status"] = "PITCH_UNRELIABLE"
            else:
                row["validation_status"] = "ok"
            # Keep the original field as the renderability status for v1 readers.
            row["status"] = row["render_status"]
            rows.append(row)
    return {
        "schema": "ambition.music_sfz_smoke.v1",
        "sample_rate": sample_rate,
        "sfz_roots": [str(root) for root in search_roots],
        "candidate_count": len(rows),
        "ok_count": sum(row.get("render_status", row.get("status")) == "ok" for row in rows),
        "validated_count": sum(row.get("validation_status") == "ok" for row in rows),
        "rows": rows,
    }


def write_sfz_smoke_report(report: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    return output

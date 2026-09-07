"""Loop-boundary evidence over CompiledScore and the actual exported audio.

A matching pre-roll is evidence about musical inputs, not a guarantee that a
sample engine, effect, or codec returns the same waveform. Report those two
questions separately. Never crossfade or otherwise repair the audition here.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from ..musicir.model import CompiledScore


def _state(inst: Any, at: float) -> tuple:
    controls: dict[int, int] = {}
    for event in sorted(inst.control_changes, key=lambda e: e.time):
        if event.time <= at + 1e-9:
            controls[event.number] = event.value
    bend = 0
    for event in sorted(inst.pitch_bends, key=lambda e: e.time):
        if event.time <= at + 1e-9:
            bend = event.pitch
    return tuple(sorted(controls.items())), bend


def _window(inst: Any, start: float, end: float) -> dict[str, Any]:
    def rel(t: float) -> float:
        return round(float(t) - start, 8)

    return {
        # Keep negative offsets for notes that cross the window's left edge.
        "notes": sorted((rel(n.start), rel(n.end), n.pitch, n.velocity)
                        for n in inst.notes if n.start < end - 1e-9 and n.end > start + 1e-9),
        "initial_state": _state(inst, start),
        "controls": sorted((rel(e.time), e.number, e.value)
                           for e in inst.control_changes if start + 1e-9 < e.time < end - 1e-9),
        "pitch_bends": sorted((rel(e.time), e.pitch)
                             for e in inst.pitch_bends if start + 1e-9 < e.time < end - 1e-9),
    }


def score_loop_report(compiled: CompiledScore) -> dict[str, Any]:
    """Compare each loop's preceding section with its equally long ending.

    Uses compiled seconds, so changing meters or tempi need no second clock.
    Note velocities, durations, controller histories, and bend state all count.
    """
    rows = []
    for index, section in enumerate(compiled.sections):
        if not section.get("loopable"):
            continue
        start, end = float(section["start_seconds"]), float(section["end_seconds"])
        if end <= start:
            raise ValueError(f"loop {section['id']!r} has no positive duration")
        previous = compiled.sections[index - 1] if index else None
        warmup = 0.0
        if previous and abs(float(previous["end_seconds"]) - start) < 1e-8:
            warmup = min(start - float(previous["start_seconds"]), end - start)
        instruments = []
        for inst in compiled.pm.instruments:
            before = _window(inst, start - warmup, start) if warmup else None
            ending = _window(inst, end - warmup, end) if warmup else None
            instruments.append({
                "instrument": inst.name,
                "pre_roll_note_count": len(before["notes"]) if before else 0,
                "ending_note_count": len(ending["notes"]) if ending else 0,
                "pre_roll_matches_ending": before == ending if warmup else None,
                "boundary_controller_state_equal": _state(inst, start) == _state(inst, end),
                "notes_crossing_start": sum(n.start < start - 1e-9 and n.end > start + 1e-9 for n in inst.notes),
                "notes_crossing_end": sum(n.start < end - 1e-9 and n.end > end + 1e-9 for n in inst.notes),
            })
        rows.append({
            "section": section["id"], "start_seconds": start, "end_seconds": end,
            "period_seconds": end - start, "pre_roll_seconds": warmup,
            "pre_roll_matches_ending": all(r["pre_roll_matches_ending"] for r in instruments) if warmup else None,
            "boundary_controller_state_equal": all(r["boundary_controller_state_equal"] for r in instruments),
            "notes_crossing_end": sum(r["notes_crossing_end"] for r in instruments),
            "instruments": instruments,
        })
    duplicates = overlaps = out_of_form = 0
    form_end = max((float(s["end_seconds"]) for s in compiled.sections), default=compiled.duration_seconds)
    for inst in compiled.pm.instruments:
        keys = Counter((round(n.start, 8), round(n.end, 8), n.pitch) for n in inst.notes)
        duplicates += sum(count - 1 for count in keys.values())
        latest_end: dict[int, float] = {}
        for n in sorted(inst.notes, key=lambda n: (n.start, n.end)):
            overlaps += n.start < latest_end.get(n.pitch, -1.0) - 1e-9
            latest_end[n.pitch] = max(latest_end.get(n.pitch, -1.0), n.end)
            out_of_form += n.start < 0 or n.end > form_end + 1e-8
    return {
        "schema": "ambition.loop_review.v1", "loops": rows,
        "duplicate_notes": duplicates, "same_pitch_overlaps": overlaps,
        "out_of_form_notes": out_of_form,
        "interpretation": "Source agreement does not certify sample/reverb/codec continuity. Audition the exported loop seam.",
    }


def audio_loop_report(audio: np.ndarray, sample_rate: int, *, period_seconds: float,
                      context_seconds: float = 8.0) -> tuple[dict[str, Any], np.ndarray]:
    """Measure an exported loop and return tail + head without a crossfade.

    The expected period comes from CompiledScore, not a file-name convention.
    Measurements remain observations; no universal audible-click threshold is
    imposed on percussion transients or intentionally contrasting phrases.
    """
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2 or x.shape[1] not in (1, 2) or len(x) < 2:
        raise ValueError("audio must contain at least two mono/stereo frames")
    if not np.isfinite(x).all():
        raise ValueError("audio contains non-finite samples")
    if sample_rate <= 0 or not np.isfinite(period_seconds) or period_seconds <= 0:
        raise ValueError("sample rate and period must be positive")
    if not np.isfinite(context_seconds) or context_seconds <= 0:
        raise ValueError("context_seconds must be positive")
    n = min(len(x), max(1, round(context_seconds * sample_rate)))
    head, tail = x[:n], x[-n:]

    def db(value: float) -> float:
        return float(20 * np.log10(max(value, 1e-12)))

    def rms(value: np.ndarray) -> float:
        return float(np.sqrt(np.mean(value.astype(np.float64) ** 2)))

    seam = np.concatenate([tail, head])
    # Derivative evidence from both neighborhoods; exclude the join itself.
    differences = np.concatenate([np.diff(tail, axis=0).ravel(), np.diff(head, axis=0).ravel()])
    jump = float(np.max(np.abs(x[0] - x[-1])))
    stereo_rms = rms(x)
    mono_rms = rms(x.mean(axis=1))
    expected_frames = round(period_seconds * sample_rate)
    report = {
        "schema": "ambition.loop_audio_review.v1", "sample_rate": sample_rate,
        "frames": len(x), "expected_frames": expected_frames,
        "period_error_frames": len(x) - expected_frames,
        "duration_matches_score": abs(len(x) - expected_frames) <= 1,
        "sample_peak_dbfs": db(float(np.max(np.abs(x)))),
        "samples_at_or_above_full_scale": int(np.count_nonzero(np.abs(x) >= 1)),
        "rms_dbfs": db(stereo_rms), "mono_fold_change_db": db(mono_rms) - db(stereo_rms),
        "head_rms_dbfs": db(rms(head)), "tail_rms_dbfs": db(rms(tail)),
        "hard_join_step_dbfs": db(jump),
        "neighborhood_delta_p99_9_dbfs": db(float(np.quantile(np.abs(differences), .999))) if differences.size else None,
        "audition_join_seconds": n / sample_rate,
        "interpretation": "The audition contains one real wrap at the stated time. No crossfade, normalization, or timing repair was applied.",
    }
    return report, seam

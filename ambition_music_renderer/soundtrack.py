"""The soundtrack of a cue: its mastered mix with no silent gaps between sections.

A score whose playback sections do not touch has a gap of no notes between
them (a section's ``tail``, the next one's ``lead_in``: see
``render.playback_layers``), so a game can cut each section with its ring.
Listened to as one piece (the radio, a soundtrack), each gap is seconds of
silence. The publish step makes the listening version from the mastered
preview and the playback plan in the run's manifest, and publishes it as the
cue's ``full.ogg``.

It is made at publish and not in the render, so it is in no render's
fingerprint (``render.dependencies._NON_AUDIO_MODULES``): no render reads it,
and a change here re-renders nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .render.playback_layers import FADE_IN_SECONDS, FADE_OUT_SECONDS, _frame

#: The Vorbis quality of the soundtrack. It is encoded from the decoded
#: preview, so it is a step above the render's 5 to lose less again.
SOUNDTRACK_OGG_QUALITY = 8.0


#: Under this level the ring at the end of a soundtrack is silence, and cut.
SOUNDTRACK_FLOOR_DBFS = -60.0
SOUNDTRACK_END_FADE_SECONDS = 0.05


def soundtrack_audio(sections: list[dict[str, Any]], master: np.ndarray, sample_rate: int) -> np.ndarray | None:
    """The listening version of the mastered composition: its sections back to
    back, or ``None`` when the timeline already is that.

    The composition timeline has a gap of no notes between two sections that
    do not touch (a ``tail`` and a ``lead_in``), so a game can cut each
    section with its ring. Listened to as one piece, the gap is seconds of
    silence. Here each gap is joined as a loop joins its seam: its ring is
    added onto the head of the next section, and its last beat (the early
    starts of that head) onto the end of the one before. Time before the first
    section keeps its last beat, and the ring after the last section is cut
    where it falls under ``SOUNDTRACK_FLOOR_DBFS``.

    Only a gap that the score says has no notes is joined: the tail of the
    section before it or the lead-in of the one after it. Time between
    sections that is neither (a form section no playback section plays)
    stays as it is.
    """
    timeline = np.asarray(master, dtype=np.float32)
    # [start, end, beat, the end of the tail after it, the start of the lead-in before it]
    spans: list[list[Any]] = []
    for section in sorted(sections, key=lambda s: (s["start_seconds"], s["end_seconds"])):
        beat = (section["end_seconds"] - section["start_seconds"]) / max(1e-9, section["duration_beats"])
        if spans and section["start_seconds"] <= spans[-1][1] + 1e-6:
            if section["end_seconds"] >= spans[-1][1]:
                spans[-1][1], spans[-1][3] = section["end_seconds"], section.get("tail_end_seconds")
        else:
            spans.append([section["start_seconds"], section["end_seconds"], beat,
                          section.get("tail_end_seconds"), section.get("lead_in_first_seconds")])
    if not spans:
        return None
    shape = (-1,) + (1,) * (timeline.ndim - 1)

    def faded(piece: np.ndarray, fade_in: bool) -> np.ndarray:
        piece = np.array(piece, dtype=np.float32, copy=True)
        n = min(len(piece), int(round((FADE_IN_SECONDS if fade_in else FADE_OUT_SECONDS) * sample_rate)))
        if n:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32) if fade_in else np.linspace(1.0, 0.0, n, dtype=np.float32)
            if fade_in:
                piece[:n] *= ramp.reshape(shape)
            else:
                piece[-n:] *= ramp.reshape(shape)
        return piece

    changed = False
    first = _frame(spans[0][0], sample_rate)
    lead_first = max(0, first - _frame(spans[0][2], sample_rate))
    changed |= lead_first > 0
    out = np.concatenate([faded(timeline[lead_first:first], True), timeline[first:_frame(spans[0][1], sample_rate)]])
    for (_a0, a1, _beat, tail_end, _lead), (b0, b1, beat, _tail, lead_first_seconds) in zip(spans, spans[1:]):
        gap_first, gap_last = _frame(a1, sample_rate), _frame(b0, sample_rate)
        silent = (tail_end is not None and abs(tail_end - b0) < 1e-6) or (
            lead_first_seconds is not None and abs(lead_first_seconds - a1) < 1e-6
        )
        if not silent:
            gap_last = gap_first
        body = np.array(timeline[gap_last:_frame(b1, sample_rate)], dtype=np.float32, copy=True)
        if gap_last > gap_first:
            changed = True
            split = max(gap_first, gap_last - _frame(beat, sample_rate))
            ring = faded(timeline[gap_first:split], False)
            lead = faded(timeline[split:gap_last], True)
            n = min(len(lead), len(out))
            if n:
                out[len(out) - n:] += lead[len(lead) - n:]
            m = min(len(ring), len(body))
            body[:m] += ring[:m]
        out = np.concatenate([out, body])
    ring = np.asarray(timeline[_frame(spans[-1][1], sample_rate):], dtype=np.float32)
    if len(ring):
        floor = 10.0 ** (SOUNDTRACK_FLOOR_DBFS / 20.0)
        loud = np.flatnonzero(np.abs(ring.reshape(len(ring), -1)).max(axis=1) > floor)
        keep = 0 if not len(loud) else min(len(ring), int(loud[-1]) + 1 + int(round(SOUNDTRACK_END_FADE_SECONDS * sample_rate)))
        changed |= keep < len(ring)
        ring = np.array(ring[:keep], dtype=np.float32, copy=True)
        fade = min(len(ring), int(round(SOUNDTRACK_END_FADE_SECONDS * sample_rate)))
        if fade:
            ring[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32).reshape(shape)
        out = np.concatenate([out, ring])
    if not changed:
        return None
    # A ring on a head can sum over the master's peak; keep the master's.
    peak, master_peak = float(np.max(np.abs(out))) if len(out) else 0.0, float(np.max(np.abs(timeline)))
    if peak > master_peak > 0.0:
        out *= master_peak / peak
    return out


def soundtrack_sections(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """The playback sections of a run's manifest, each with where its lead-in starts."""
    form = {str(sec["id"]): sec for sec in manifest.get("sections") or []}
    sections = []
    for section in (manifest.get("playback_layers") or {}).get("sections") or []:
        section = dict(section)
        lead_in = section.get("lead_in")
        section["lead_in_first_seconds"] = float(form[lead_in]["start_seconds"]) if lead_in in form else None
        sections.append(section)
    return sections


def write_soundtrack(preview: Path, manifest: dict[str, Any], out: Path) -> Path | None:
    """Write the soundtrack of ``preview`` to ``out``, or return ``None`` when
    the preview already is its soundtrack. A soundtrack newer than its preview
    is kept."""
    import soundfile as sf

    from .render.export import write_ogg_from_audio

    if out.is_file() and out.stat().st_mtime >= preview.stat().st_mtime:
        return out
    sections = soundtrack_sections(manifest)
    if not sections:
        return None
    audio, sample_rate = sf.read(preview, dtype="float32", always_2d=True)
    soundtrack = soundtrack_audio(sections, audio, sample_rate)
    if soundtrack is None:
        return None
    return write_ogg_from_audio(soundtrack, sample_rate, out, quality=SOUNDTRACK_OGG_QUALITY, keep_wav=False,
                                metadata={"PREVIEW_TYPE": "soundtrack", "CUE_ID": str(manifest.get("id") or "")})

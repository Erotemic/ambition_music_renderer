"""Foreground-melody collision audit for MusicIR scores.

The dissonance audit ranks ALL simultaneous rubs, which buries the
perceptually severe case: two foreground melodies (motif / guitar_lead /
notes layers) sounding a second/seventh/tritone apart in the same register.
A pad voicing an add9 is color; two lead lines fighting over a step is a
mistake a listener hears immediately ("the second note is sour").

This audit looks ONLY at melody-carrying layers and reports:

* **lead-vs-lead collisions** - concurrent notes from different foreground
  layers at a dissonant interval within ~an octave, with wall-clock
  timestamps (tempo-map aware) so a listener note like "1:27" maps straight
  to a row.
* **exposed tensions** - a foreground note held >= ``exposed_min_beats``
  whose pitch class is a maj7/9/#11 against the bar's chord. Passing
  eighths are fine; a phrase ENDING on the 9th for a full second is the
  thing an ear flags as "off".

Score-level (no audio render needed), so it runs in milliseconds and can
gate a composition iteration before spending a render.
"""

from __future__ import annotations

from ..profiler import profile

import kwconf
import json
from pathlib import Path
from typing import Any

from ._common import round3 as _round3
from ._score_common import chord_pitch_classes

FOREGROUND_KINDS = {"motif", "guitar_lead", "notes"}

# interval class (semitones mod 12) -> severity weight for two LEADS.
LEAD_INTERVAL_SEVERITY = {
    1: 1.0,   # minor second / major seventh
    2: 0.75,  # major second / minor seventh
    6: 0.55,  # tritone
    11: 0.9,
    10: 0.6,
}

# Tension pitch classes relative to the chord root that read as "unresolved"
# when a melody SITS on them: maj7, 9th(2), #11(6). The 4th and 6th are
# common enough melody tones that flagging them drowns the signal.
EXPOSED_TENSION_PCS = {11, 2, 6}


def _fmt_time(seconds: float) -> str:
    m, s = divmod(max(0.0, float(seconds)), 60.0)
    return f"{int(m)}:{s:05.2f}"


@profile
def audit_events(
    events: list[dict[str, Any]],
    spec: dict[str, Any],
    *,
    beats_per_bar: float,
    min_overlap_s: float = 0.08,
    max_register_gap: int = 14,
    exposed_min_beats: float = 1.0,
    max_rows: int = 40,
) -> dict[str, Any]:
    leads = [
        e for e in events
        if str(e.get("layer_kind")) in FOREGROUND_KINDS
        and not str(e.get("instrument", "")).startswith("drum")
    ]
    leads.sort(key=lambda e: float(e["start_time"]))

    collisions: list[dict[str, Any]] = []
    for i, a in enumerate(leads):
        a_end = float(a["end_time"])
        for b in leads[i + 1:]:
            b_start = float(b["start_time"])
            if b_start >= a_end:
                break
            # Different foreground sources only: a melody doubling itself
            # (same layer+instrument) is thickening, not a collision.
            if a.get("layer") == b.get("layer") and a.get("instrument") == b.get("instrument"):
                continue
            overlap = min(a_end, float(b["end_time"])) - b_start
            if overlap < min_overlap_s:
                continue
            diff = abs(int(a["pitch"]) - int(b["pitch"]))
            if diff == 0 or diff > max_register_gap:
                continue
            severity_base = LEAD_INTERVAL_SEVERITY.get(diff % 12, 0.0)
            if severity_base <= 0.0:
                continue
            vel = min(int(a.get("velocity", 64)), int(b.get("velocity", 64))) / 96.0
            severity = severity_base * vel * min(1.0, overlap / 0.5)
            start = max(float(a["start_time"]), b_start)
            collisions.append({
                "time": _fmt_time(start),
                "start_seconds": _round3(start),
                "overlap_seconds": _round3(overlap),
                "bar": int(float(b["start_beat"]) // beats_per_bar) + 1,
                "section": b.get("section") or a.get("section"),
                "notes": [a.get("note"), b.get("note")],
                "interval_semitones": diff,
                "layers": [a.get("layer"), b.get("layer")],
                "instruments": [a.get("instrument"), b.get("instrument")],
                "severity": _round3(severity),
            })
    collisions.sort(key=lambda row: -row["severity"])

    exposed: list[dict[str, Any]] = []
    for e in leads:
        dur_beats = float(e.get("end_beat", 0.0)) - float(e.get("start_beat", 0.0))
        if dur_beats < exposed_min_beats:
            continue
        chord = _chord_at(spec, float(e["start_beat"]), beats_per_bar)
        if not chord:
            continue
        pcs = chord_pitch_classes(chord)
        if not pcs:
            continue
        pitch_pc = int(e["pitch"]) % 12
        if pitch_pc in pcs:
            continue
        root_pc = min(pcs) if pcs else 0
        root_pc = _chord_root_pc(chord)
        if root_pc is None:
            continue
        rel = (pitch_pc - root_pc) % 12
        if rel not in EXPOSED_TENSION_PCS:
            continue
        exposed.append({
            "time": _fmt_time(float(e["start_time"])),
            "start_seconds": _round3(float(e["start_time"])),
            "bar": int(float(e["start_beat"]) // beats_per_bar) + 1,
            "section": e.get("section"),
            "note": e.get("note"),
            "chord": chord,
            "tension": {11: "maj7", 2: "9th", 6: "#11"}[rel],
            "duration_beats": _round3(dur_beats),
            "layer": e.get("layer"),
            "instrument": e.get("instrument"),
            "severity": _round3(dur_beats * int(e.get("velocity", 64)) / 96.0),
        })
    exposed.sort(key=lambda row: -row["severity"])

    return {
        "schema": "ambition.music_lead_collision.v1",
        "id": spec.get("id"),
        "collision_count": len(collisions),
        "exposed_tension_count": len(exposed),
        "collisions": collisions[:max_rows],
        "exposed_tensions": exposed[:max_rows],
    }


def _chord_root_pc(chord: str) -> int | None:
    from ..render.score_theory import chord_intervals, note_to_midi

    try:
        root, _intervals, _slash = chord_intervals(chord)
        return note_to_midi(f"{root}4") % 12
    except Exception:
        return None


def _chord_at(spec: dict[str, Any], beat: float, beats_per_bar: float) -> str:
    from ..render.score_theory import chord_for_bar

    bar = int(beat // beats_per_bar)
    cursor = 0
    for section in spec.get("sections", []):
        bars = int(section.get("bars", 0))
        if cursor <= bar < cursor + bars:
            try:
                return str(chord_for_bar(section, bar - cursor))
            except Exception:
                return ""
        cursor += bars
    return ""


@profile
def audit_spec(spec: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    from ..render.score_layers import build_score

    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    pm, _groups, _meta = build_score(spec)
    events = list(getattr(pm, "_ambition_note_events", []))
    return audit_events(events, spec, beats_per_bar=beats_per_bar, **kwargs)


class LeadCollisionConfig(kwconf.Config):
    """Flag dissonant overlaps between foreground melodies + exposed tensions."""

    spec: Path = kwconf.Value(None, position=1, parser=Path, help="path to a .music.yaml")
    min_overlap_s: float = kwconf.Value(0.08, help="minimum overlap to count a collision")
    exposed_min_beats: float = kwconf.Value(1.0, help="minimum held beats for an exposed tension")
    max_rows: int = kwconf.Value(40, help="rows per table")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        import yaml

        args = cls.cli(argv=argv, data=kwargs)
        spec = yaml.safe_load(Path(args.spec).read_text(encoding="utf8"))
        report = audit_spec(
            spec,
            min_overlap_s=float(args.min_overlap_s),
            exposed_min_beats=float(args.exposed_min_beats),
            max_rows=int(args.max_rows),
        )
        print(json.dumps(report, indent=2))
        return 0


def main(argv: list[str] | None = None) -> int:
    return int(LeadCollisionConfig.main(argv=argv))


if __name__ == "__main__":
    raise SystemExit(main())

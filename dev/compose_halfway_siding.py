"""Halfway Siding and the Number 9: the music of the Frontier's first slice,
west of Dry Dock (Ambition's
`docs/planning/game/techno-western-frontier-first-slice.md`). Writes two
MusicIR v3 scores:

    python3 dev/compose_halfway_siding.py scores/active

- `halfway_siding`: the auxiliary gate town on the gulch rim, its recovery
  inn and its trestle, and Clinker Flats down the line: four sections the
  game binds to rooms.
- `the_rustler`: the train robbery: the Number 9 ore freight at speed, and
  the outlaw engine at its head.

The request (Jon, 2026-11-20): a cue for the gate town and the inn, and a
driving cue for the train stage; the feel of a western with industrial
science fiction in it. No melody, progression or arrangement is taken from
any work.

THE TWO MOTIFS (both original):
  the detour: A D E F#, E D B, A: up a fourth and a step, then a turn back
      down past where it started: a road that goes round. Every section of
      the town cue says it.
  the rustler: E G A B, D B A G E: an outlaw's swagger up the minor
      pentatonic and back down. The train cue is built on it.

HALFWAY SIDING (84 BPM, D major), sections:
  platform     1-24   the siding: a fingerpicked guitar, an upright bass in
                      two, brushes, the detour on the clarinet, a flute and a
                      Rhodes high up, for the gate.                     (loop)
  lie_down    25-40   the inn: a harp, a cello, the detour slow on the
                      clarinet; nothing on the beat.                    (loop)
  trestle     41-56   the trestle: B minor, a ticking rim, a tuba walking,
                      tremolo strings, the detour on the twang guitar.  (loop)
  clinker     57-80   Clinker Flats: a heavy half-time kit, the tuba and a
                      string pulse like machinery, the detour on a tenor
                      sax, low horns.                                   (loop)

THE RUSTLER (152 BPM, E minor), sections:
  boxcars      1-32   the freight at speed: the snare in sixteenths like
                      wheels on rail joints, a galloping bass, banjo rolls,
                      the rustler on the fiddle, the trumpet answering.  (loop)
  rustler     33-56   the outlaw engine: the big kit, the trombones on the
                      rustler, a string pulse, timpani, the fiddle over.  (loop)
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

OUT_DIR = Path(sys.argv[1])

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


CHORD = {
    "Am": ["A", "C", "E"], "C": ["C", "E", "G"], "Dm": ["D", "F", "A"], "D": ["D", "F#", "A"], "E": ["E", "G#", "B"],
    "E7": ["E", "G#", "B", "D"], "F": ["F", "A", "C"], "G": ["G", "B", "D"], "G7": ["G", "B", "D", "F"],
    "A7": ["A", "C#", "E", "G"], "D7": ["D", "F#", "A", "C"], "Bb": ["Bb", "D", "F"], "Em": ["E", "G", "B"],
    "B7": ["B", "D#", "F#", "A"], "Fm": ["F", "Ab", "C"], "Db": ["Db", "F", "Ab"], "Eb": ["Eb", "G", "Bb"],
    "C7": ["C", "E", "G", "Bb"], "Bbm": ["Bb", "Db", "F"], "Fmaj7": ["F", "A", "C", "E"], "Am7": ["A", "C", "E", "G"],
    "Cmaj7": ["C", "E", "G", "B"], "Em7": ["E", "G", "B", "D"],
    "Bm": ["B", "D", "F#"], "F#m": ["F#", "A", "C#"], "F#7": ["F#", "A#", "C#", "E"], "Gmaj7": ["G", "B", "D", "F#"],
    "Dmaj7": ["D", "F#", "A", "C#"], "A": ["A", "C#", "E"], "Bm7": ["B", "D", "F#", "A"], "Cm": ["C", "Eb", "G"],
    "Gm": ["G", "Bb", "D"], "Ab": ["Ab", "C", "Eb"], "Bb7": ["Bb", "D", "F", "Ab"], "Asus4": ["A", "D", "E"],
}


def tones(chord: str, octave: int) -> list[int]:
    out = []
    for name in CHORD[chord]:
        p = midi(f"{name}{octave}")
        while out and p <= out[-1]:
            p += 12
        out.append(p)
    return out


def root(chord: str, octave: int) -> int:
    return midi(f"{CHORD[chord][0]}{octave}")


class Cue:
    """One score: its tempo, its sections and its clips."""

    def __init__(self, cue_id: str, bpm: int, seed: int, segments):
        self.id, self.bpm, self.rng = cue_id, bpm, random.Random(seed)
        self.seed = seed
        # (id, first logical bar, last logical bar, first score bar): each
        # section has two silent bars before and after it, for its ring and
        # its lead-in.
        self.segments = segments
        self.end_bar = segments[-1][3] + segments[-1][2] - segments[-1][1] + 3
        self.harmony: dict[int, str] = {}
        self.clips: dict[str, Clip] = {}

    def clip(self, name: str, jitter_ms: float = 5.0, vel_jitter: int = 4) -> "Clip":
        self.clips[name] = Clip(self, jitter_ms, vel_jitter)
        return self.clips[name]

    def score_bar(self, bar: int) -> int:
        for _, first, last, at in self.segments:
            if first <= bar <= last:
                return at + bar - first
        raise ValueError(f"logical bar {bar} is in no section")

    def t(self, bar: int, beat: float = 0.0) -> float:
        return (self.score_bar(bar) - 1) * 4 + beat


class Clip:
    def __init__(self, cue: Cue, jitter_ms: float, vel_jitter: int):
        self.cue = cue
        self.events: list[tuple] = []
        self.jitter = jitter_ms / 1000.0 * cue.bpm / 60.0
        self.vel_jitter = vel_jitter

    def note(self, at, dur, pitches, vel):
        rng = self.cue.rng
        at = F(at).limit_denominator(960)
        if self.jitter and at > 0:
            at += F(rng.uniform(-self.jitter, self.jitter)).limit_denominator(960)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        pitches = [p if isinstance(p, int) else midi(p) for p in pitches]
        self.events.append((at, F(dur).limit_denominator(960), pitches, vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


def cell(clip: Clip, start: float, base: int, steps, rhythm, vel: int, *, stretch: float = 1.0, legato: float = 0.92,
         accent_first: int = 6, shape=None) -> float:
    at = start
    for i, (step, span) in enumerate(zip(steps, rhythm)):
        span *= stretch
        clip.note(at, span * legato, base + step, vel + (accent_first if i == 0 else 0) + (shape(i) if shape else 0))
        at += span
    return at


# GM drum notes of the kits (Big Rusty Drums and Naked Drums map like GM).
KICK, SNARE, RIM, SIDESTICK, HAT, HAT_OPEN, RIDE, RIDE_BELL, CRASH, TOM_LO, TOM_HI = 36, 38, 37, 37, 42, 46, 51, 53, 49, 45, 50
BRUSH = 38


def sfz(ref: str, extra: str = "") -> str:
    return f"{extra}instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def glob(pattern: str, controls: str = "") -> str:
    return f"{controls}instrument_backend: {{kind: sfz, optional: false, sfz_glob: '{pattern}', settings: {{fold_to_range: false}}}}"


SHINY = glob("**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz", "controls: {100: 0, 107: 0}, ")
TRUMPET_SOLO = glob("**/Virtual-Playing-Orchestra3/Brass/trumpet-SOLO-PERF.sfz", "controls: {1: 100}, ")


def form_and_playback(cue: Cue, shapes: dict, loops: set) -> tuple[str, str]:
    rows, play = [], []
    previous_end = 1
    for sid, first, last, at in cue.segments:
        if at > previous_end:
            rows.append(f"  - {{id: before_{sid}, from: {{bar: {previous_end}, beat: 1}}, to: {{bar: {at}, beat: 1}}, energy: 0.1, density: 0.0, role: 'silence: a ring and a lead-in'}}")
        end = at + last - first + 1
        rows.append(f"  - {{id: {sid}, from: {{bar: {at}, beat: 1}}, to: {{bar: {end}, beat: 1}}, {shapes[sid]}}}")
        previous_end = end
    rows.append(f"  - {{id: after_all, from: {{bar: {previous_end}, beat: 1}}, to: {{bar: {cue.end_bar}, beat: 1}}, energy: 0.1, density: 0.0, role: 'silence: the last ring'}}")
    for i, (sid, *_rest) in enumerate(cue.segments):
        fields = [f"id: {sid}", f"form: [{sid}]"]
        if sid in loops:
            fields += ["loop: true", f"lead_in: before_{sid}"]
        fields.append(f"tail: before_{cue.segments[i + 1][0]}" if i + 1 < len(cue.segments) else "tail: after_all")
        play.append("    - {" + ", ".join(fields) + "}")
    return "\n".join(rows), "\n".join(play)


def parts_yaml(cue: Cue) -> str:
    out = []
    for name, clip in cue.clips.items():
        out.append("\n".join([f"  - id: {name}_part", f"    instrument: {name}", "    voices:", f"      - id: {name}_main",
                              "        clips:", clip.yaml(f"{name}_all", "          ")]))
    return "\n".join(out)


def harmony_list(cue: Cue, default: str) -> str:
    score_harmony = {cue.score_bar(b): chord for b, chord in cue.harmony.items()}
    return ", ".join(score_harmony.get(b, default) for b in range(1, cue.end_bar))



COMMON_MASTER = """  master:
    chain:
      - {processor: highpass, cutoff_hz: 30}
      - processor: parametric_eq
        bands:
          - {type: peak, hz: 350, q: 0.8, db: -1.0}
      - {processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 120.0, makeup_db: 1.5, knee_db: 6.0}
      - {processor: reverb, wet: 0.05, decay_seconds: 1.6}
      - {processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}
  adaptive_sections:
    mode: composition_master"""

# ---- The motifs ----------------------------------------------------------
# The detour, from A: A D E F#, E D B, A.
DETOUR = [0, 5, 7, 9, 7, 5, 2, 0]
DETOUR_RHYTHM = [1.0, 0.5, 0.5, 2.0, 1.0, 1.0, 1.0, 1.0]
# The rustler, from E: E G A B, D B A G E.
RUSTLER = [0, 3, 5, 7, 10, 7, 5, 3, 0]
RUSTLER_RHYTHM = [0.5, 0.5, 0.5, 1.5, 0.5, 0.5, 0.5, 0.5, 2.5]
CRASH_ = 49


def low(pitch: int, floor: str = "E1") -> int:
    while pitch < midi(floor):
        pitch += 12
    return pitch


# ===========================================================================
# HALFWAY SIDING
# ===========================================================================
town = Cue("halfway_siding", 84, 1130, [
    ("platform", 1, 24, 3),
    ("lie_down", 25, 40, 29),
    ("trestle", 41, 56, 47),
    ("clinker", 57, 80, 65),
])
t = town.t
guitar = town.clip("guitar", 6, 6)
clarinet = town.clip("clarinet", 6, 4)
flute = town.clip("flute", 6, 4)
rhodes = town.clip("rhodes", 5, 4)
bass = town.clip("bass", 5, 5)
kit = town.clip("kit", 3, 6)
harp = town.clip("harp", 5, 5)
cello = town.clip("cello", 4, 3)
tuba = town.clip("tuba", 5, 4)
tremolo = town.clip("tremolo", 3, 3)
twang = town.clip("twang", 5, 5)
heavy_kit = town.clip("heavy_kit", 3, 6)
pulse = town.clip("pulse", 3, 5)
sax = town.clip("sax", 7, 5)
horns = town.clip("horns", 4, 3)

# ---- PLATFORM (1-24): the siding -------------------------------------------
PLATFORM = ["D", "D", "G", "D", "Bm", "G", "A", "A", "D", "D", "G", "Gmaj7", "Em", "A", "D", "D",
            "G", "D", "Em", "A", "Bm", "G", "A", "D"]
for i, chord in enumerate(PLATFORM):
    bar = 1 + i
    town.harmony[bar] = chord
    # Travis picking: the thumb on the root and the fifth, the fingers between.
    r = root(chord, 2)
    if r < midi("E2"):
        r += 12
    up = [p for p in tones(chord, 3) if p > r][:3] + [tones(chord, 4)[0]]
    for beat in range(4):
        guitar.note(t(bar, beat), 0.9, r if beat % 2 == 0 else r + 7, 80 if beat % 2 == 0 else 72)
        guitar.note(t(bar, beat + 0.5), 0.45, up[(beat + i) % len(up)], 62)
    bass.note(t(bar), 1.8, low(root(chord, 1)), 86)
    bass.note(t(bar, 2), 1.8, low(root(chord, 1) + 7, "E1") if root(chord, 1) + 7 <= midi("D3") else low(root(chord, 1)), 78)
    kit.note(t(bar, 1), 0.3, BRUSH, 48)
    kit.note(t(bar, 3), 0.3, BRUSH, 50)
    for beat in (0, 1, 1.66, 2, 3, 3.66):
        kit.note(t(bar, beat), 0.2, RIDE, 38 if beat % 1 else 46)
    if i % 4 == 0:
        rhodes.note(t(bar), 15.4, [p + 12 for p in tones(chord, 4)[:2]], 64)
# The detour on the clarinet; the flute answers it; the clarinet again, higher.
cell(clarinet, t(3), midi("A4"), DETOUR, DETOUR_RHYTHM, 84, legato=0.95)
cell(flute, t(7), midi("D5"), [0, 2, 4, 2, 0, -3, -5], [1, 0.5, 0.5, 2, 2, 1, 1], 78, legato=0.95)
cell(clarinet, t(11), midi("D5"), DETOUR, DETOUR_RHYTHM, 82, legato=0.95)
clarinet.note(t(13), 3.6, midi("B4"), 74)
clarinet.note(t(14), 3.6, midi("C#5"), 74)
cell(flute, t(17), midi("A5"), DETOUR, DETOUR_RHYTHM, 76, legato=0.95)
cell(clarinet, t(19), midi("A4"), [0, 2, 4, 5, 7, 5, 4, 2], [1, 0.5, 0.5, 1, 1, 1, 1, 2], 80, legato=0.95)
cell(clarinet, t(21), midi("B4"), [0, -2, -4, -5, -2, 0], [1, 1, 1, 1, 2, 2], 78, legato=0.95)
clarinet.note(t(23), 3.4, midi("A4"), 76)
clarinet.note(t(24), 3.4, midi("F#4"), 72)
flute.note(t(24), 3.4, midi("D5"), 64)

# ---- LIE DOWN (25-40): the inn -----------------------------------------------
LIE = ["Dmaj7", "Gmaj7", "Dmaj7", "Gmaj7", "Bm7", "Em7", "Asus4", "A", "Dmaj7", "Gmaj7", "Bm7", "Gmaj7", "Em7", "Asus4", "A", "Dmaj7"]
for i, chord in enumerate(LIE):
    bar = 25 + i
    town.harmony[bar] = chord
    arp = tones(chord, 3) + [p + 12 for p in tones(chord, 3)]
    for k in range(8):
        harp.note(t(bar, 0.5 * k), 1.6, arp[[0, 2, 1, 3, 4, 3, 2, 1][k] % len(arp)], 60 if k == 0 else 50)
    cello.note(t(bar), 3.9, low(root(chord, 2), "C2"), 58)
cell(clarinet, t(27), midi("A4"), DETOUR, [x * 2 for x in DETOUR_RHYTHM], 66, legato=0.97)
cell(flute, t(35), midi("F#5"), [0, -2, -4, -5, -7], [2, 2, 2, 2, 8], 56, legato=0.97)
rhodes.note(t(33), 31.0, [midi("F#5"), midi("A5")], 56)

# ---- TRESTLE (41-56): the gulch under the road --------------------------------
TRESTLE = ["Bm", "Bm", "G", "F#7", "Bm", "Bm", "Em", "F#7", "Bm", "D", "G", "F#7", "Em", "G", "F#7", "F#7"]
for i, chord in enumerate(TRESTLE):
    bar = 41 + i
    town.harmony[bar] = chord
    # The tick: a rim on every beat, like a clock in the signal box.
    for beat in range(4):
        kit.note(t(bar, beat), 0.15, RIM, 58 if beat == 0 else 44)
    # The tuba walks.
    walk = [root(chord, 1), tones(chord, 1)[2], root(chord, 2), tones(chord, 1)[2]]
    for k, p in enumerate(walk):
        tuba.note(t(bar, k), 0.85, low(p, "D1"), 84 if k == 0 else 70)
    if i % 2 == 0:
        tremolo.note(t(bar), 7.8, tones(chord, 4)[:3], 46 + 2 * i)
cell(twang, t(43), midi("F#3"), [0, 5, 7, 8, 7, 5, 2, 0], DETOUR_RHYTHM, 86, legato=0.8)
cell(twang, t(47), midi("B3"), [0, 3, 5, 7, 5, 3, 0], [1, 0.5, 0.5, 2, 1, 1, 2], 84, legato=0.8)
cell(twang, t(51), midi("F#3"), [0, 5, 7, 8, 7, 5, 2, 0], DETOUR_RHYTHM, 88, legato=0.8)
twang.note(t(55), 3.6, [midi("F#3"), midi("C#4")], 84)
twang.note(t(56), 3.6, [midi("F#3"), midi("A#3")], 82)

# ---- CLINKER (57-80): the smelter town ------------------------------------------
CLINKER = ["Bm", "Bm", "G", "A", "Bm", "Bm", "Em", "F#7"]
for block in range(3):
    for i, chord in enumerate(CLINKER):
        bar = 57 + 8 * block + i
        town.harmony[bar] = chord
        heavy_kit.note(t(bar), 0.4, KICK, 108)
        heavy_kit.note(t(bar, 1.5), 0.4, KICK, 90)
        heavy_kit.note(t(bar, 2), 0.4, SNARE, 106)
        for k in range(8):
            heavy_kit.note(t(bar, 0.5 * k), 0.2, RIDE_BELL if k % 4 == 2 else HAT, 64 if k % 2 == 0 else 46)
        if i == 7:
            for k in range(4):
                heavy_kit.note(t(bar, 3 + 0.25 * k), 0.2, TOM_HI if k < 2 else TOM_LO, 88 + 4 * k)
        r = root(chord, 3)
        for k in range(8):
            pulse.note(t(bar, 0.5 * k), 0.35, r + (7 if k in (3, 6) else 0), 82 if k % 2 == 0 else 68)
        tuba.note(t(bar), 1.4, low(root(chord, 1), "D1"), 92)
        tuba.note(t(bar, 1.5), 0.4, low(root(chord, 1), "D1"), 78)
        tuba.note(t(bar, 2.5), 1.2, low(root(chord, 1) + 7, "D1"), 82)
        if block > 0 and i % 2 == 0:
            horns.note(t(bar), 7.6, tones(chord, 3)[:3], 60 + 6 * block)
# The detour on the tenor sax, minor and bluesy.
cell(sax, t(59), midi("F#3"), [0, 5, 7, 8, 10, 8, 7, 5, 3, 0], [1, 0.5, 0.5, 1, 1, 0.5, 0.5, 1, 1, 1], 92, legato=0.9)
cell(sax, t(67), midi("B3"), [0, 3, 5, 6, 5, 3, 0, -2, 0], [0.5, 0.5, 1, 2, 1, 1, 1, 1, 0.5 + 7.5], 94, legato=0.9)
cell(sax, t(75), midi("F#3"), [0, 5, 7, 8, 7, 5, 2, 0], DETOUR_RHYTHM, 92, legato=0.9)
sax.note(t(79), 3.6, midi("B3"), 88)
sax.note(t(80), 3.6, midi("A#3"), 86)

town_shapes = {
    "platform": "energy: 0.35, density: 0.45, loopable: true, role: 'the siding: fingerpicked guitar, the detour on the clarinet and the flute'",
    "lie_down": "energy: 0.15, density: 0.25, loopable: true, role: 'the recovery inn: harp, cello, the detour slow'",
    "trestle": "energy: 0.5, density: 0.45, loopable: true, role: 'the trestle: a ticking rim, a walking tuba, the detour on the twang'",
    "clinker": "energy: 0.65, density: 0.65, loopable: true, role: 'Clinker Flats: half-time kit, tuba and string pulse, the detour on the sax'",
}
town_form, town_play = form_and_playback(town, town_shapes, {"platform", "lie_down", "trestle", "clinker"})

town_score = f"""schema: ambition.musicir.v3
id: halfway_siding
title: Halfway Siding
description: >-
  The Frontier's first slice: Halfway Siding, the auxiliary gate town on the
  gulch rim, its recovery inn and its trestle, and Clinker Flats down the
  line, on one motif, the detour. Generated by dev/compose_halfway_siding.py:
  edit that, not this file.
notes:
  - 'Jon, 2026-11-20: a cue for the gate town and the inn and a driving cue for the train stage. The references were mood only.'
  - 'The detour: A D E F#, E D B, A. The trestle and Clinker Flats turn it minor.'
  - 'The game binds the sections to rooms (Ambition music_cues.ron): platform (the station, the street, Sprocket Row), lie_down (the inn), trestle (the trestle), clinker (the yard, the works, the Row, the railhead).'
seed: {town.seed}
timebase: {{ppq: 960}}
meter: 4/4
tempo: {town.bpm}
key: {{tonic: D, mode: major}}
end: {{bar: {town.end_bar}, beat: 1}}
form:
{town_form}
harmony:
  every_bars: 1
  cycle: false
  progression: [{harmony_list(town, "D")}]
instruments:
  - {{name: guitar, group: guitar, program: steel_guitar, volume: 100, pan: 64, expression: 104, {sfz("guitar.acoustic", "controls: {100: 126}, ")}}}
  - {{name: clarinet, group: clarinet, program: clarinet, volume: 100, pan: 64, expression: 104, controls: {{1: 100}}, {sfz("vpo.clarinet_solo_perf")}}}
  - {{name: flute, group: flute, program: flute, volume: 100, pan: 64, expression: 104, controls: {{1: 100}}, {sfz("vpo.flute_solo_perf")}}}
  - {{name: rhodes, group: rhodes, program: electric_piano_1, volume: 96, pan: 64, expression: 100, {sfz("epiano.rhodes")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 106, pan: 64, expression: 108, {sfz("bass.upright")}}}
  - {{name: kit, group: kit, volume: 112, pan: 64, expression: 112, is_drum: true, {sfz("drums.naked")}}}
  - {{name: harp, group: harp, program: orchestral_harp, volume: 100, pan: 64, expression: 104, {sfz("folk.harp")}}}
  - {{name: cello, group: cello, program: cello, volume: 100, pan: 64, expression: 104, {sfz("strings.cello")}}}
  - {{name: tuba, group: tuba, program: tuba, volume: 106, pan: 64, expression: 108, {sfz("orchestra.tuba_sustain")}}}
  - {{name: tremolo, group: strings, program: tremolo_strings, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1")}}}
  - {{name: twang, group: twang, program: clean_guitar, volume: 104, pan: 64, expression: 110, {SHINY}}}
  - {{name: heavy_kit, group: heavy_kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz("drums.big_rusty")}}}
  - {{name: pulse, group: pulse, program: string_ensemble_2, volume: 100, pan: 64, expression: 104, {sfz("strings.cyborg")}}}
  - {{name: sax, group: sax, program: tenor_sax, volume: 104, pan: 64, expression: 108, {sfz("winds.tenor_sax")}}}
  - {{name: horns, group: horns, program: french_horn, volume: 100, pan: 64, expression: 104, {sfz("orchestra.horns_sustain")}}}
parts:
{parts_yaml(town)}
processing:
  groups:
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: -0.3}}
    clarinet:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 4.0}}
        - {{processor: balance, position: 0.15}}
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: 0.3}}
    rhodes:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 12.0}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3500}}
        - {{processor: gain, gain_db: 5.0}}
    kit:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 12.0}}
    harp:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 10.0}}
    cello:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 4.0}}
    tuba:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 5.0}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 4.0}}
    twang:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: 0.3}}
    heavy_kit:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 90.0}}
    pulse:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 2.0}}
        - {{processor: balance, position: -0.2}}
    sax:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: 0.2}}
    horns:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: -0.15}}
{COMMON_MASTER}
playback:
  full: true
  sections:
{town_play}
"""

# ===========================================================================
# THE RUSTLER
# ===========================================================================
train = Cue("the_rustler", 152, 1131, [
    ("boxcars", 1, 32, 3),
    ("rustler", 33, 56, 37),
])
t = train.t
r_fiddle = train.clip("fiddle", 6, 5)
r_trumpet = train.clip("trumpet", 5, 4)
r_banjo = train.clip("banjo", 4, 5)
r_bass = train.clip("bass", 4, 4)
r_kit = train.clip("kit", 2, 6)
r_heavy = train.clip("heavy_kit", 2, 6)
r_bones = train.clip("trombones", 5, 4)
r_pulse = train.clip("pulse", 3, 5)
r_timpani = train.clip("timpani", 3, 4)
r_twang = train.clip("twang", 4, 5)


def tim(pitch: int) -> int:
    """`pitch` folded into the sampled range of the catalog's timpani (F2-G3)."""
    while pitch < midi("F2"):
        pitch += 12
    while pitch > midi("G3"):
        pitch -= 12
    return pitch


def wheels(bar: int, hard: bool = False):
    """The train's rhythm: the snare in sixteenths with a push on each
    beat's last, like wheels over rail joints; the kick on 1 and 3."""
    clip = r_heavy if hard else r_kit
    for k in range(16):
        v = (88 if k % 4 == 3 else 52 + (6 if k % 2 else 0)) + (8 if hard else 0)
        clip.note(t(bar, 0.25 * k), 0.1, SNARE, v)
    clip.note(t(bar), 0.4, KICK, 106)
    clip.note(t(bar, 2), 0.4, KICK, 98)
    if hard:
        clip.note(t(bar, 1), 0.4, KICK, 90)
        clip.note(t(bar, 3), 0.4, KICK, 92)


BOX = ["Em", "Em", "G", "D", "Em", "Em", "C", "B7", "Em", "Em", "G", "D", "Am", "C", "B7", "B7"]
for half in (0, 16):
    for i, chord in enumerate(BOX):
        bar = 1 + half + i
        train.harmony[bar] = chord
        wheels(bar)
        b = low(root(chord, 1))
        for k, step in enumerate([0, 7, 12, 7, 0, 7, 12, 7]):
            r_bass.note(t(bar, 0.5 * k), 0.4, b + step if b + step <= midi("E3") else b + step - 12, 92 if k % 4 == 0 else 74)
        roll = tones(chord, 3) + [tones(chord, 3)[0] + 12]
        for k in range(8):
            r_banjo.note(t(bar, 0.5 * k), 0.4, roll[[0, 1, 2, 3, 1, 2, 0, 3][k]], 70 if k % 2 else 78)
        if half:
            r_pulse.note(t(bar, 1.5), 0.3, tones(chord, 4), 74)
            r_pulse.note(t(bar, 3.5), 0.3, tones(chord, 4), 70)
# The rustler on the fiddle, the trumpet answering an octave down.
for bar, base in ((3, midi("E5")), (11, midi("E5")), (19, midi("A5")), (27, midi("E5"))):
    cell(r_fiddle, t(bar), base, RUSTLER, RUSTLER_RHYTHM, 92, legato=0.9)
    cell(r_trumpet, t(bar + 2), base - 12, [0, 3, 5, 7, 5, 3, 0], [0.5, 0.5, 1, 2, 1, 1, 2], 88, legato=0.9)
for bar in (7, 15, 23, 31):
    cell(r_fiddle, t(bar), midi("B4"), [0, 1, 3, 5, 3, 1, 0, -2, -5], [0.5] * 8 + [4.0], 86, legato=0.85)

ROB = ["Em", "Em", "C", "B7", "Am", "Am", "B7", "B7"]
for block in range(3):
    for i, chord in enumerate(ROB):
        bar = 33 + 8 * block + i
        train.harmony[bar] = chord
        wheels(bar, hard=True)
        for k in range(8):
            r_heavy.note(t(bar, 0.5 * k), 0.15, HAT, 70 if k % 2 == 0 else 52)
        if i == 0:
            r_heavy.note(t(bar), 1.0, CRASH_, 100)
        b = low(root(chord, 1))
        for k in range(8):
            r_bass.note(t(bar, 0.5 * k), 0.4, b if k % 2 == 0 else b + 12, 96 if k % 4 == 0 else 80)
        r_pulse.note(t(bar), 0.3, tones(chord, 4), 84)
        r_pulse.note(t(bar, 1.5), 0.3, tones(chord, 4), 80)
        r_pulse.note(t(bar, 3), 0.3, tones(chord, 4), 80)
        r_timpani.note(t(bar), 0.6, tim(root(chord, 2)), 96)
        r_twang.note(t(bar, 3.5), 0.4, [root(chord, 3), root(chord, 3) + 7], 90)
for bar in (33, 41, 49):
    cell(r_bones, t(bar), midi("E3"), RUSTLER, [x * 2 for x in RUSTLER_RHYTHM], 100, legato=0.92)
for bar in (37, 45, 53):
    cell(r_fiddle, t(bar), midi("B5"), [0, -2, -4, -5, -7, -5, -4, -2, 0], [0.5] * 8 + [4.0], 92, legato=0.88)
    cell(r_trumpet, t(bar + 2), midi("E4"), [0, 3, 5, 7, 10, 7], [0.5, 0.5, 0.5, 0.5, 2, 4], 94, legato=0.9)
r_timpani.note(t(56, 3), 0.8, tim(midi("B2")), 108)

train_shapes = {
    "boxcars": "energy: 0.7, density: 0.6, loopable: true, role: 'the freight at speed: wheels on the snare, banjo rolls, the rustler on the fiddle'",
    "rustler": "energy: 0.85, density: 0.75, loopable: true, role: 'the outlaw engine: the big kit, the rustler in the trombones, timpani'",
}
train_form, train_play = form_and_playback(train, train_shapes, {"boxcars", "rustler"})

train_score = f"""schema: ambition.musicir.v3
id: the_rustler
title: The Rustler
description: >-
  The Frontier's train robbery: the Number 9 ore freight running down the
  gulch with an outlaw engine at its head. A snare like wheels on rail
  joints, a galloping bass and a banjo, the rustler on the fiddle; at the
  engine the big kit, the trombones and timpani. Generated by
  dev/compose_halfway_siding.py: edit that, not this file.
notes:
  - 'Jon, 2026-11-20: a driving cue for the train stage. The references were mood only.'
  - 'The rustler: E G A B, D B A G E.'
  - 'The game binds the sections to rooms (Ambition music_cues.ron): boxcars (the tail, the cars), rustler (the head of the train).'
seed: {train.seed}
timebase: {{ppq: 960}}
meter: 4/4
tempo: {train.bpm}
key: {{tonic: E, mode: minor}}
end: {{bar: {train.end_bar}, beat: 1}}
form:
{train_form}
harmony:
  every_bars: 1
  cycle: false
  progression: [{harmony_list(train, "Em")}]
instruments:
  - {{name: fiddle, group: fiddle, program: violin, volume: 100, pan: 64, expression: 106, {sfz("strings.violin_solo")}}}
  - {{name: trumpet, group: trumpet, program: trumpet, volume: 100, pan: 64, expression: 106, {TRUMPET_SOLO}}}
  - {{name: banjo, group: banjo, program: banjo, volume: 100, pan: 64, expression: 104, {sfz("folk.banjo")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 108, pan: 64, expression: 110, {sfz("bass.upright")}}}
  - {{name: kit, group: kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz("drums.naked")}}}
  - {{name: heavy_kit, group: heavy_kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz("drums.big_rusty")}}}
  - {{name: trombones, group: brass, program: trombone, volume: 104, pan: 64, expression: 108, {sfz("orchestra.trombones_sustain")}}}
  - {{name: pulse, group: pulse, program: string_ensemble_2, volume: 100, pan: 64, expression: 104, {sfz("strings.cyborg")}}}
  - {{name: timpani, group: timpani, volume: 110, pan: 64, expression: 112, is_drum: true, {sfz("orchestra.timpani")}}}
  - {{name: twang, group: twang, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
parts:
{parts_yaml(train)}
processing:
  groups:
    fiddle:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 14.0}}
        - {{processor: balance, position: 0.25}}
    trumpet:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: -0.1}}
    banjo:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 7.0}}
        - {{processor: balance, position: 0.35}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3500}}
        - {{processor: gain, gain_db: 5.0}}
    kit:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: 2.0}}
    heavy_kit:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 90.0}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 4.0}}
    pulse:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 2.0}}
        - {{processor: balance, position: -0.3}}
    timpani:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 2.0}}
    twang:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: 0.3}}
{COMMON_MASTER}
playback:
  full: true
  sections:
{train_play}
"""

for cue, text in ((town, town_score), (train, train_score)):
    path = OUT_DIR / f"{cue.id}.music.yaml"
    path.write_text(text)
    print(f"wrote {path}: {cue.end_bar - 1} bars, {(cue.end_bar - 1) * 4 * 60 / cue.bpm:.0f} s")

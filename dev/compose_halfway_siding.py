"""Halfway Siding, the Number 9 and Clinker Flats: the music of the
Frontier's first slice, west of Dry Dock (Ambition's
`docs/planning/game/techno-western-frontier-first-slice.md`). Writes three
MusicIR v3 scores:

    python3 dev/compose_halfway_siding.py scores/active

- `halfway_siding`: the auxiliary gate town on the gulch rim: the station
  and the street, the recovery inn, the trestle, and Sprocket Row, the
  mechanics' street over it.
- `the_rustler`: the train robbery: the Number 9 ore freight at speed, and
  the outlaw engine at its head.
- `clinker_flats`: the smelter town down the line: the yard and the works,
  and the Row of shacks under them on the way to the railhead.

The request (Jon, 2026-11-20): a cue for the gate town and the inn, and a
driving cue for the train stage; the feel of a western with industrial
science fiction in it. No melody, progression or arrangement is taken from
any work. His review of the first renders: the town cue opened on silence and
was too schmaltzy (a clarinet and a flute over major sevenths, a harp and a
cello at the inn), the train cue had its structure but not its balance, every
cue must loop, and the Frontier needed more than two western tracks.

So the town is dry: a boom-chuck guitar, an upright bass in two, a chromatic
harmonica on the tune, a baritone twang answering, plain triads with the flat
seventh of the mixolydian (C in D) instead of major sevenths; the inn is an
upright saloon piano alone. Each section is a loop whose last bar turns back
to its first chord.

THE MOTIFS (all original):
  the detour: A D E F#, E D B, A: up a fourth and a step, then a turn back
      down past where it started: a road that goes round. The town says it
      in every section; the Row says it in minor, the road out.
  the rustler: E G A B, D B A G E: an outlaw's swagger up the minor
      pentatonic and back down. The train cue is built on it.
  the clinker: A C D Eb, D C A: a grind up to the blue fifth and back.

HALFWAY SIDING (88 BPM, D major), sections:
  platform   24  the station, the street: boom-chuck guitar, bass, kit; the
                 detour on the harmonica, the twang answering; a telegraph
                 sounder clicks CQ in the second half.
  lie_down   16  the inn: an upright piano alone, the detour slow.
  trestle    16  B minor: a rim ticking every beat, a tuba walking, the
                 detour on the twang, the harmonica's long notes over it.
  sprocket   16  the mechanics' street: banjo rolls, tuba oom-pah, a
                 woodblock, an anvil and a ratchet at work; the detour traded
                 between the twang and the harmonica.

THE RUSTLER (152 BPM, E minor), sections:
  boxcars    32  the freight at speed: the snare in sixteenths like wheels on
                 rail joints, a galloping bass, banjo rolls, the rustler on
                 the fiddle, the trumpet answering.
  rustler    24  the outlaw engine: the big kit, the trombones on the
                 rustler, a string pulse, timpani, a counter fiddle over.

CLINKER FLATS (76 BPM, A minor), sections:
  works      24  the yard and the works: a half-time big kit, anvils on the
                 backbeat, a brake drum, a tuba riff, baritone stabs, low male
                 voices; the clinker on a trumpet.
  row        16  the Row and the railhead: a fingerpicked guitar, the detour
                 in minor on the harmonica, the works far off.

LAYOUT. The first section starts the score (a silent opening is dead air in
the radio mix and in the inspector's preview). Between sections, and after
the last, a silent gap at least RING_SECONDS long: the tail the section
before rings into and the lead-in of the one after. The game plays each
section as its own loop, with its tail folded onto its head.

BALANCE is set by group gains and measured per section on the rendered
stems (K-weighted loudness of each group against the section's sum), not
from velocities: a lead must stand clear of the bass and the kit.
"""

from __future__ import annotations

import math
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
    "A7": ["A", "C#", "E", "G"], "D7": ["D", "F#", "A", "C"], "Em": ["E", "G", "B"], "B7": ["B", "D#", "F#", "A"],
    "Bm": ["B", "D", "F#"], "F#m": ["F#", "A", "C#"], "F#7": ["F#", "A#", "C#", "E"], "A": ["A", "C#", "E"],
}

# Open-position guitar voicings, low to high (what a hand on six strings plays).
VOICING = {
    "D": [50, 57, 62, 66], "C": [48, 52, 55, 60, 64], "G": [43, 47, 50, 55, 59, 67], "A": [45, 52, 57, 61, 64],
    "A7": [45, 52, 55, 61, 64], "E": [40, 47, 52, 56, 59, 64], "E7": [40, 47, 50, 56, 59, 64],
    "Em": [40, 47, 52, 55, 59, 64], "Am": [45, 52, 57, 60, 64], "Dm": [50, 57, 62, 65], "F": [41, 48, 53, 57, 60, 65],
    "Bm": [47, 54, 59, 62, 66], "F#7": [42, 49, 52, 58, 61, 66], "D7": [50, 57, 60, 66], "B7": [47, 51, 57, 59, 66],
    "G7": [43, 47, 50, 55, 59, 65],
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


def low(pitch: int, floor: str = "E1") -> int:
    while pitch < midi(floor):
        pitch += 12
    return pitch


def third(chord: str) -> int:
    """Semitones from the root to the chord's third."""
    return (NOTE[CHORD[chord][1]] - NOTE[CHORD[chord][0]]) % 12


# The longest group reverb in these cues decays within this, so a gap of it
# holds a section's ring.
RING_SECONDS = 2.5


class Cue:
    """One score: its tempo, its sections and its clips."""

    def __init__(self, cue_id: str, bpm: int, seed: int, segments):
        self.id, self.bpm, self.rng = cue_id, bpm, random.Random(seed)
        self.seed = seed
        gap = max(1, math.ceil(RING_SECONDS * bpm / 240))
        # (id, first logical bar, last logical bar, first score bar).
        at, self.segments = 1, []
        for sid, first, last in segments:
            self.segments.append((sid, first, last, at))
            at += last - first + 1 + gap
        self.end_bar = at
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
         accent_first: int = 6) -> float:
    at = start
    for i, (step, span) in enumerate(zip(steps, rhythm)):
        span *= stretch
        clip.note(at, span * legato, base + step, vel + (accent_first if i == 0 else 0))
        at += span
    return at


def line(cue: Cue, clip: Clip, bar: int, notes, vel: int, *, legato: float = 0.92, octave_doubled: bool = False):
    """Lay `notes` [(name or "r", beats), ...] from the start of logical bar
    `bar`, bar after bar; each bar must sum to four beats. A phrase's first
    note is a touch stronger, a long note a touch softer."""
    beat, first = 0.0, True
    for name, span in notes:
        if name != "r":
            p = midi(name)
            v = vel + (4 if first else 0) - (4 if span >= 3 else 0)
            clip.note(cue.t(bar + int(beat // 4), beat % 4), span * legato, [p, p - 12] if octave_doubled else p, v)
            first = False
        else:
            first = True
        beat += span
    assert abs(beat % 4) < 1e-9, f"{cue.id} bar {bar}: the line fills {beat} beats, not whole bars"


def strum(clip: Clip, at: float, notes: list[int], vel: int, *, down: bool = True, spread: float = 0.022, dur: float = 0.45):
    order = notes if down else list(reversed(notes))
    for k, p in enumerate(order):
        clip.note(at + k * spread, dur, p, vel - 2 * k)


# GM drum notes of the kits (Big Rusty Drums and Naked Drums map like GM).
KICK, SNARE, SIDESTICK, HAT, RIDE_BELL, CRASH, TOM_LO, TOM_HI = 36, 38, 37, 42, 53, 49, 45, 50
# The VCSL single-object instruments sound at middle C (60) and the keys just above.
STRIKE = 60


def sfz(ref: str, extra: str = "") -> str:
    return f"{extra}instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def glob(pattern: str, controls: str = "") -> str:
    return f"{controls}instrument_backend: {{kind: sfz, optional: false, sfz_glob: '{pattern}', settings: {{fold_to_range: false}}}}"


def vcsl(path: str) -> str:
    return glob(f"**/VCSL-1.2.2-RC/{path}.sfz")


SHINY = glob("**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz", "controls: {100: 0, 107: 0}, ")
TRUMPET_SOLO = glob("**/Virtual-Playing-Orchestra3/Brass/trumpet-SOLO-PERF.sfz", "controls: {1: 100}, ")
HARMONICA = vcsl("Aerophones/Free Aerophones/Harmonica-Hohner-Super64 - Normal")
HARMONICA_VIB = vcsl("Aerophones/Free Aerophones/Harmonica-Hohner-Super64 - Vib")


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
            fields.append("loop: true")
            if i > 0:
                fields.append(f"lead_in: before_{sid}")
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


def group(name: str, *, highpass: int, gain: float, wet: float, decay: float, balance: float | None = None,
          lowpass: int | None = None, compress: bool = False) -> str:
    rows = [f"    {name}:", "      chain:", f"        - {{processor: highpass, cutoff_hz: {highpass}}}"]
    if lowpass:
        rows.append(f"        - {{processor: lowpass, cutoff_hz: {lowpass}}}")
    if compress:
        rows.append("        - {processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 90.0}")
    rows.append(f"        - {{processor: reverb, wet: {wet}, decay_seconds: {decay}}}")
    if gain:
        rows.append(f"        - {{processor: gain, gain_db: {gain}}}")
    if balance is not None:
        rows.append(f"        - {{processor: balance, position: {balance}}}")
    return "\n".join(rows)


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


def score_text(cue: Cue, *, title: str, description: str, notes: list[str], key: str, mode: str, default_chord: str,
               shapes: dict, instruments: list[str], groups: list[str]) -> str:
    form, play = form_and_playback(cue, shapes, set(shapes))
    note_rows = "\n".join(f"  - '{n}'" for n in notes)
    inst_rows = "\n".join(f"  - {{{row}}}" for row in instruments)
    return f"""schema: ambition.musicir.v3
id: {cue.id}
title: {title}
description: >-
  {description} Generated by dev/compose_halfway_siding.py: edit that, not
  this file.
notes:
{note_rows}
seed: {cue.seed}
timebase: {{ppq: 960}}
meter: 4/4
tempo: {cue.bpm}
key: {{tonic: {key}, mode: {mode}}}
end: {{bar: {cue.end_bar}, beat: 1}}
form:
{form}
harmony:
  every_bars: 1
  cycle: false
  progression: [{harmony_list(cue, default_chord)}]
instruments:
{inst_rows}
parts:
{parts_yaml(cue)}
processing:
  groups:
{chr(10).join(groups)}
{COMMON_MASTER}
playback:
  full: true
  sections:
{play}
"""


# ---- The motifs ----------------------------------------------------------
DETOUR = [0, 5, 7, 9, 7, 5, 2, 0]                 # from A: A D E F#, E D B, A
DETOUR_RHYTHM = [1.0, 0.5, 0.5, 2.0, 1.0, 1.0, 1.0, 1.0]
RUSTLER = [0, 3, 5, 7, 10, 7, 5, 3, 0]             # from E: E G A B, D B A G E
RUSTLER_RHYTHM = [0.5, 0.5, 0.5, 1.5, 0.5, 0.5, 0.5, 0.5, 2.5]

# Morse for CQ (-.-. --.-), the telegrapher's call to any station. A sounder
# clicks at key-down and clacks at key-up: a dot is one unit, a dash three.
CQ = "-.-. --.-"


def sounder(cue: Cue, clip: Clip, bar: int, unit: float = 0.25):
    at = 0.0
    for symbol in CQ:
        if symbol == " ":
            at += 2 * unit  # a letter gap is three units; one already follows each symbol
            continue
        length = unit if symbol == "." else 3 * unit
        clip.note(cue.t(bar + int(at // 4), at % 4), 0.1, SIDESTICK, 40)
        up = at + length
        clip.note(cue.t(bar + int(up // 4), up % 4), 0.1, SIDESTICK, 28)
        at = up + unit


# ===========================================================================
# HALFWAY SIDING
# ===========================================================================
town = Cue("halfway_siding", 88, 1130, [
    ("platform", 1, 24),
    ("lie_down", 25, 40),
    ("trestle", 41, 56),
    ("sprocket", 57, 72),
])
t = town.t
guitar = town.clip("guitar", 6, 5)
harmonica = town.clip("harmonica", 7, 4)
twang = town.clip("twang", 5, 5)
bass = town.clip("bass", 5, 4)
kit = town.clip("kit", 3, 5)
piano = town.clip("piano", 8, 5)
tuba = town.clip("tuba", 5, 4)
banjo = town.clip("banjo", 4, 5)
woodblock = town.clip("woodblock", 3, 4)
anvil = town.clip("anvil", 4, 4)
ratchet = town.clip("ratchet", 3, 3)
vibraslap = town.clip("vibraslap", 0, 3)


def boom_chuck(bar: int, chord: str, vel: int = 76):
    """The thumb on the root (beat 1) and the fifth (beat 3); the hand strums
    the top strings on 2 and 4, an upstroke after 4."""
    v = VOICING[chord]
    bass_note, alt = v[0], next((p for p in v if (p - v[0]) % 12 == 7), v[1])
    top = v[-4:] if len(v) > 4 else v[1:]
    guitar.note(t(bar), 0.9, bass_note, vel)
    strum(guitar, t(bar, 1), top, vel - 12)
    guitar.note(t(bar, 2), 0.9, alt, vel - 6)
    strum(guitar, t(bar, 3), top, vel - 12)
    strum(guitar, t(bar, 3.5), top[-3:], vel - 30, down=False, dur=0.3)


# ---- PLATFORM (1-24): the station and the street ----------------------------
PLATFORM = ["D", "D", "D", "D", "D", "C", "D", "A", "G", "D", "C", "D", "G", "D", "A", "A",
            "D", "D", "C", "G", "D", "C", "G", "A"]
# Where the bass walks into the next chord: (bar, beat-4 approach note).
WALKS = {8: "F#2", 16: "C#2", 24: "C#2"}
for i, chord in enumerate(PLATFORM):
    bar = 1 + i
    town.harmony[bar] = chord
    boom_chuck(bar, chord)
    r = low(root(chord, 1), "D2") if root(chord, 1) < midi("D2") else root(chord, 1)
    r = r if r <= midi("A2") else r - 12
    bass.note(t(bar), 1.7, r, 84)
    bass.note(t(bar, 2), 0.9 if bar in WALKS else 1.7, r + 7 if r + 7 <= midi("D3") else r - 5, 74)
    if bar in WALKS:
        bass.note(t(bar, 3), 0.9, midi(WALKS[bar]), 70)
    kit.note(t(bar), 0.3, KICK, 58)
    kit.note(t(bar, 2), 0.3, KICK, 52)
    kit.note(t(bar, 1), 0.3, SNARE, 44)
    kit.note(t(bar, 3), 0.3, SNARE, 48)
    for k in range(4):
        kit.note(t(bar, k + 0.5), 0.15, HAT, 30)
# The detour on the harmonica, two bars in; the twang answers in the gaps.
line(town, harmonica, 3, [("A4", 1), ("D5", .5), ("E5", .5), ("F#5", 2), ("E5", 1), ("D5", 1), ("B4", 1), ("A4", 1),
                          ("F#5", 1.5), ("E5", .5), ("D5", 2), ("C5", 1), ("D5", .5), ("C5", .5), ("G4", 2),
                          ("A4", 4), ("r", 4),
                          ("D5", 1), ("G5", .5), ("A5", .5), ("B5", 2), ("A5", 1), ("G5", 1), ("E5", 1), ("D5", 1),
                          ("G5", 1), ("E5", 1), ("C5", 2), ("D5", 4),
                          ("B4", 1), ("D5", 1), ("G5", 2), ("F#5", 1), ("E5", 1), ("D5", 2),
                          ("E5", 1), ("C#5", 1), ("A4", 2), ("r", 4)], 80)
line(town, harmonica, 19, [("E5", 4), ("D5", 4), ("F#5", 2), ("A5", 2), ("G5", 2), ("E5", 2), ("D5", 2), ("B4", 2),
                           ("C#5", 2), ("B4", 1), ("A4", 1)], 76)
line(town, twang, 2, [("r", 2), ("A2", .5), ("B2", .5), ("C#3", .5), ("E3", .5), ("D3", 1), ("r", 3)], 82, legato=0.8)
line(town, twang, 8, [("r", 1), ("A2", .5), ("C#3", .5), ("E3", .5), ("G3", .5), ("A3", 1)], 84, legato=0.8)
line(town, twang, 16, [("E3", .5), ("D3", .5), ("C#3", .5), ("B2", .5), ("A2", 2)], 84, legato=0.8)
# The second half: the detour low on the twang while the harmonica holds on.
line(town, twang, 17, [("A2", 1), ("D3", .5), ("E3", .5), ("F#3", 2), ("E3", 1), ("D3", 1), ("B2", 1), ("A2", 1)], 86, legato=0.85)
line(town, twang, 21, [("D4", 2), ("F#4", 2), ("E4", 2), ("C4", 2), ("B3", 2), ("G3", 2), ("A3", 2), ("G3", 1), ("E3", 1)], 74, legato=0.9)
# The telegraph office on the street: a sounder clicking CQ.
sounder(town, kit, 17)
sounder(town, kit, 21)

# ---- LIE DOWN (25-40): the inn: an upright piano alone ------------------------
LIE = ["D", "D", "G", "D", "Bm", "E", "A", "A", "D", "D7", "G", "G", "D", "A", "D", "A"]
for i, chord in enumerate(LIE):
    bar = 25 + i
    town.harmony[bar] = chord
    r = root(chord, 2)
    r = r if r >= midi("A1") else r + 12
    hand = tones(chord, 3)
    piano.note(t(bar), 1.9, r, 58)
    piano.note(t(bar, 1), 0.9, hand, 44)
    piano.note(t(bar, 2), 0.9, r + 7 if r + 7 < midi("D3") else r - 5, 50)
    piano.note(t(bar, 3), 0.9, hand, 40)
line(town, piano, 25, [("A4", 1), ("D5", .5), ("E5", .5), ("F#5", 2), ("E5", 1), ("D5", 1), ("B4", 1), ("A4", 1),
                       ("B4", 2), ("A4", 1), ("G4", 1), ("F#4", 4),
                       ("D5", 1.5), ("C#5", .5), ("B4", 2), ("G#4", 2), ("B4", 2),
                       ("C#5", 2), ("E5", 2), ("r", 4),
                       ("D5", 1), ("G5", .5), ("A5", .5), ("B5", 2), ("A5", 1), ("G5", 1), ("E5", 1), ("D5", 1),
                       ("B4", 2), ("D5", 2), ("G4", 4),
                       ("F#4", 1), ("A4", 1), ("D5", 2), ("E5", 2), ("C#5", 2),
                       ("D5", 4), ("r", 4)], 64, legato=0.97)
piano.note(t(37) - 0.12, 0.12, midi("F4"), 50)  # a honky-tonk slip into the F#
piano.note(t(40, 2), 0.9, midi("A2"), 50)
piano.note(t(40, 3), 0.9, midi("C#3"), 52)       # the walk back up to D

# ---- TRESTLE (41-56): the gulch under the road --------------------------------
TRESTLE = ["Bm", "Bm", "G", "F#7", "Bm", "Bm", "Em", "F#7", "Bm", "D", "G", "F#7", "Em", "G", "F#7", "F#7"]
for i, chord in enumerate(TRESTLE):
    bar = 41 + i
    town.harmony[bar] = chord
    # The tick: a rim on every beat, like a clock in the signal box.
    for beat in range(4):
        kit.note(t(bar, beat), 0.15, SIDESTICK, 70 if beat == 0 else 56)
    walk = [root(chord, 1), tones(chord, 1)[2], root(chord, 2), tones(chord, 1)[2]]
    for k, p in enumerate(walk):
        tuba.note(t(bar, k), 0.85, low(p, "D1"), 82 if k == 0 else 68)
cell(twang, t(43), midi("F#3"), [0, 5, 7, 8, 7, 5, 2, 0], DETOUR_RHYTHM, 86, legato=0.8)
cell(twang, t(47), midi("B3"), [0, 3, 5, 7, 5, 3, 0], [1, 0.5, 0.5, 2, 1, 1, 2], 84, legato=0.8)
cell(twang, t(51), midi("F#3"), [0, 5, 7, 8, 7, 5, 2, 0], DETOUR_RHYTHM, 88, legato=0.8)
twang.note(t(55), 3.6, [midi("F#3"), midi("C#4")], 84)
twang.note(t(56), 3.6, [midi("F#3"), midi("A#3")], 82)
line(town, harmonica, 49, [("F#5", 4), ("A5", 2), ("F#5", 2), ("G5", 4), ("F#5", 2), ("E5", 2),
                           ("E5", 4), ("D5", 4), ("C#5", 4), ("A#4", 2), ("C#5", 2)], 58, legato=0.96)
vibraslap.note(t(48, 3), 1.0, STRIKE, 60)
vibraslap.note(t(56, 2.5), 1.0, STRIKE, 54)

# ---- SPROCKET (57-72): the mechanics' street ------------------------------------
SPROCKET = ["D", "D", "C", "D", "D", "D", "A", "A", "G", "G", "D", "D", "C", "G", "A", "A"]
for i, chord in enumerate(SPROCKET):
    bar = 57 + i
    town.harmony[bar] = chord
    r = low(root(chord, 1), "D1")
    tuba.note(t(bar), 0.8, r, 86)
    tuba.note(t(bar, 2), 0.8, r + 7 if r + 7 <= midi("A2") else r - 5, 76)
    # A forward roll, thumb-index-middle, over the chord.
    v = VOICING[chord]
    roll = [v[1], v[-2], v[-1]]
    for k in range(8):
        banjo.note(t(bar, 0.5 * k), 0.45, roll[k % 3], 74 if k % 3 == 0 else 64)
    kit.note(t(bar), 0.3, KICK, 66)
    kit.note(t(bar, 2), 0.3, KICK, 60)
    woodblock.note(t(bar, 1), 0.2, STRIKE, 70)
    woodblock.note(t(bar, 3), 0.2, STRIKE + 1, 64)
    if i % 2 == 1:
        anvil.note(t(bar, 2.5), 0.5, STRIKE, 62)
    if i in (3, 11):
        ratchet.note(t(bar, 2), 1.0, STRIKE, 54)
anvil.note(t(72, 3), 0.5, STRIKE, 70)
anvil.note(t(72, 3.5), 0.5, STRIKE + 1, 64)
# The detour traded: the twang says it dotted, the harmonica answers.
line(town, twang, 57, [("A3", .75), ("D4", .25), ("E4", .5), ("F#4", 1.5), ("r", 1),
                       ("E4", .75), ("D4", .25), ("B3", .5), ("A3", 1.5), ("r", 1)], 86, legato=0.85)
line(town, harmonica, 59, [("G5", .5), ("E5", .5), ("C5", 1), ("r", 2), ("D5", .5), ("F#5", .5), ("A5", 1), ("r", 2)], 78)
line(town, twang, 61, [("D4", .75), ("G4", .25), ("A4", .5), ("B4", 1.5), ("r", 1),
                       ("A4", .75), ("G4", .25), ("E4", .5), ("D4", 1.5), ("r", 1)], 86, legato=0.85)
line(town, harmonica, 63, [("C#5", .5), ("E5", .5), ("A5", 1), ("r", 2), ("G5", .5), ("E5", .5), ("C#5", 1), ("r", 2)], 78)
line(town, harmonica, 65, [("D5", 1), ("G5", .5), ("A5", .5), ("B5", 2), ("A5", 1), ("G5", 1), ("E5", 1), ("D5", 1),
                           ("F#5", 2), ("A5", 2), ("D5", 4),
                           ("G5", 2), ("E5", 2), ("D5", 2), ("B4", 2), ("C#5", 1), ("E5", 1), ("A5", 2),
                           ("G5", 1), ("E5", 1), ("C#5", 1), ("A4", 1)], 76)
line(town, twang, 65, [("D4", 1), ("G4", .5), ("A4", .5), ("B4", 2), ("A4", 1), ("G4", 1), ("E4", 1), ("D4", 1),
                       ("F#4", 2), ("A4", 2), ("D4", 4),
                       ("C3", .5), ("E3", .5), ("G3", 1), ("r", 2), ("G2", .5), ("B2", .5), ("D3", 1), ("r", 2),
                       ("A2", .5), ("C#3", .5), ("E3", 1), ("r", 2), ("A2", .5), ("C#3", .5), ("E3", .5), ("G3", .5), ("A3", 1), ("r", 1)],
     80, legato=0.85)

town_text = score_text(
    town, title="Halfway Siding", key="D", mode="major", default_chord="D",
    description="The Frontier's first slice: Halfway Siding, the auxiliary gate town on the gulch rim, its station and street, its recovery inn, its trestle and Sprocket Row, on one motif, the detour.",
    notes=["Jon, 2026-11-20: a cue for the gate town and the inn. The references were mood only. His first review: it opened on silence and was too schmaltzy; it must loop.",
           "The detour: A D E F#, E D B, A. The trestle turns it minor.",
           "The game binds the sections to rooms (Ambition music_cues.ron): platform (the station, the street), lie_down (the inn), trestle (the trestle), sprocket (Sprocket Row)."],
    shapes={
        "platform": "energy: 0.4, density: 0.45, loopable: true, role: 'the station and the street: boom-chuck guitar, the detour on the harmonica, the twang answering'",
        "lie_down": "energy: 0.15, density: 0.25, loopable: true, role: 'the inn: an upright piano alone'",
        "trestle": "energy: 0.5, density: 0.45, loopable: true, role: 'the trestle: a ticking rim, a walking tuba, the detour on the twang, the harmonica held over it'",
        "sprocket": "energy: 0.55, density: 0.6, loopable: true, role: 'Sprocket Row: banjo, tuba, woodblock and anvil, the detour traded'",
    },
    instruments=[
        f"name: guitar, group: guitar, program: steel_guitar, volume: 100, pan: 64, expression: 104, {sfz('guitar.acoustic', 'controls: {100: 126}, ')}",
        f"name: harmonica, group: harmonica, program: 22, volume: 100, pan: 64, expression: 106, {HARMONICA}",
        f"name: twang, group: twang, program: clean_guitar, volume: 104, pan: 64, expression: 110, {SHINY}",
        f"name: bass, group: bass, program: acoustic_bass, volume: 104, pan: 64, expression: 106, {sfz('bass.upright')}",
        f"name: kit, group: kit, volume: 110, pan: 64, expression: 110, is_drum: true, {sfz('drums.naked')}",
        f"name: piano, group: piano, program: honky_tonk_piano, volume: 100, pan: 64, expression: 104, {sfz('freepats.upright_piano_kw')}",
        f"name: tuba, group: tuba, program: tuba, volume: 104, pan: 64, expression: 106, {sfz('orchestra.tuba_sustain')}",
        f"name: banjo, group: banjo, program: banjo, volume: 100, pan: 64, expression: 104, {sfz('folk.banjo')}",
        f"name: woodblock, group: shop, program: woodblock, volume: 96, pan: 64, expression: 100, {vcsl('Idiophones/Struck Idiophones/Woodblock')}",
        f"name: anvil, group: shop, program: tinkle_bell, volume: 88, pan: 64, expression: 96, {vcsl('Idiophones/Struck Idiophones/Anvil')}",
        f"name: ratchet, group: shop, program: woodblock, volume: 90, pan: 64, expression: 96, {vcsl('Idiophones/Struck Idiophones/Ratchet')}",
        f"name: vibraslap, group: shop, program: woodblock, volume: 96, pan: 64, expression: 100, {vcsl('Idiophones/Struck Idiophones/Vibraslap')}",
    ],
    groups=[
        group("guitar", highpass=80, gain=5.0, wet=0.12, decay=1.4, balance=-0.3),
        group("harmonica", highpass=180, gain=5.0, wet=0.2, decay=1.8, balance=0.1),
        group("twang", highpass=90, gain=5.0, wet=0.24, decay=2.0, balance=0.35),
        group("bass", highpass=35, lowpass=3500, gain=6.0, wet=0.04, decay=1.0),
        group("kit", highpass=40, gain=15.0, wet=0.1, decay=1.2),
        group("piano", highpass=60, gain=6.0, wet=0.2, decay=1.8),
        group("tuba", highpass=30, lowpass=5000, gain=4.0, wet=0.12, decay=1.4),
        group("banjo", highpass=150, gain=12.0, wet=0.1, decay=1.2, balance=0.3),
        group("shop", highpass=120, gain=18.0, wet=0.18, decay=1.6, balance=-0.25),
    ],
)

# ===========================================================================
# THE RUSTLER
# ===========================================================================
train = Cue("the_rustler", 152, 1131, [
    ("boxcars", 1, 32),
    ("rustler", 33, 56),
])
t = train.t
r_fiddle = train.clip("fiddle", 6, 5)
r_counter = train.clip("counter", 6, 5)
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
    beat's last, like wheels over rail joints; the kick on 1 and 3. The
    ghost strokes stay low so the line on top carries."""
    clip = r_heavy if hard else r_kit
    for k in range(16):
        v = (84 if k % 4 == 3 else 40 + (6 if k % 2 else 0)) + (8 if hard else 0)
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
            r_bass.note(t(bar, 0.5 * k), 0.4, b + step if b + step <= midi("E3") else b + step - 12, 88 if k % 4 == 0 else 70)
        roll = tones(chord, 3) + [tones(chord, 3)[0] + 12]
        for k in range(8):
            r_banjo.note(t(bar, 0.5 * k), 0.4, roll[[0, 1, 2, 3, 1, 2, 0, 3][k]], 74 if k % 2 else 82)
        if half:
            r_pulse.note(t(bar, 1.5), 0.3, tones(chord, 4), 70)
            r_pulse.note(t(bar, 3.5), 0.3, tones(chord, 4), 66)
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
            r_heavy.note(t(bar, 0.5 * k), 0.15, HAT, 64 if k % 2 == 0 else 46)
        if i == 0:
            r_heavy.note(t(bar), 1.0, CRASH, 100)
        b = low(root(chord, 1))
        for k in range(8):
            r_bass.note(t(bar, 0.5 * k), 0.4, b if k % 2 == 0 else b + 12, 90 if k % 4 == 0 else 72)
        r_pulse.note(t(bar), 0.3, tones(chord, 4), 76)
        r_pulse.note(t(bar, 1.5), 0.3, tones(chord, 4), 70)
        r_timpani.note(t(bar), 0.6, tim(root(chord, 2)), 100)
        r_twang.note(t(bar, 3.5), 0.4, [root(chord, 3), root(chord, 3) + 7], 86)
for bar in (33, 41, 49):
    cell(r_bones, t(bar), midi("E3"), RUSTLER, [x * 2 for x in RUSTLER_RHYTHM], 104, legato=0.92)
for bar in (37, 45, 53):
    cell(r_counter, t(bar), midi("B5"), [0, -2, -4, -5, -7, -5, -4, -2, 0], [0.5] * 8 + [4.0], 88, legato=0.88)
    cell(r_trumpet, t(bar + 2), midi("E4"), [0, 3, 5, 7, 10, 7], [0.5, 0.5, 0.5, 0.5, 2, 4], 92, legato=0.9)
r_timpani.note(t(56, 3), 0.8, tim(midi("B2")), 108)

train_text = score_text(
    train, title="Coq on the Walk", key="E", mode="minor", default_chord="Em",
    description="The Frontier's train robbery: the Number 9 ore freight running down the gulch with an outlaw engine at its head. A snare like wheels on rail joints, a galloping bass and a banjo, the rustler on the fiddle; at the engine the big kit, the trombones and timpani.",
    notes=["Jon, 2026-11-20: a driving cue for the train stage. The references were mood only. His first review: good structure, not balanced; it must loop.",
           "The rustler: E G A B, D B A G E.",
           "The game binds the sections to rooms (Ambition music_cues.ron): boxcars (the tail, the cars), rustler (the head of the train)."],
    shapes={
        "boxcars": "energy: 0.7, density: 0.6, loopable: true, role: 'the freight at speed: wheels on the snare, banjo rolls, the rustler on the fiddle'",
        "rustler": "energy: 0.85, density: 0.75, loopable: true, role: 'the outlaw engine: the big kit, the rustler in the trombones, timpani'",
    },
    instruments=[
        f"name: fiddle, group: fiddle, program: violin, volume: 100, pan: 64, expression: 106, {sfz('strings.violin_solo')}",
        f"name: counter, group: counter, program: violin, volume: 100, pan: 64, expression: 104, {sfz('strings.violin_solo')}",
        f"name: trumpet, group: trumpet, program: trumpet, volume: 100, pan: 64, expression: 106, {TRUMPET_SOLO}",
        f"name: banjo, group: banjo, program: banjo, volume: 100, pan: 64, expression: 104, {sfz('folk.banjo')}",
        f"name: bass, group: bass, program: acoustic_bass, volume: 104, pan: 64, expression: 106, {sfz('bass.upright')}",
        f"name: kit, group: kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz('drums.naked')}",
        f"name: heavy_kit, group: heavy_kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz('drums.big_rusty')}",
        f"name: trombones, group: brass, program: trombone, volume: 108, pan: 64, expression: 112, {sfz('orchestra.trombones_sustain')}",
        f"name: pulse, group: pulse, program: string_ensemble_2, volume: 96, pan: 64, expression: 100, {sfz('strings.cyborg')}",
        f"name: timpani, group: timpani, volume: 110, pan: 64, expression: 112, is_drum: true, {sfz('orchestra.timpani')}",
        f"name: twang, group: twang, program: clean_guitar, volume: 100, pan: 64, expression: 106, {SHINY}",
    ],
    groups=[
        group("fiddle", highpass=180, gain=14.0, wet=0.18, decay=1.6, balance=0.25),
        group("counter", highpass=180, gain=9.0, wet=0.24, decay=1.8, balance=0.3),
        group("trumpet", highpass=150, gain=7.0, wet=0.26, decay=2.2, balance=-0.15),
        group("banjo", highpass=150, gain=12.0, wet=0.1, decay=1.2, balance=0.35),
        group("bass", highpass=40, lowpass=3000, gain=3.0, wet=0.04, decay=1.0),
        group("kit", highpass=40, gain=2.0, wet=0.1, decay=1.0),
        group("heavy_kit", highpass=30, gain=5.0, wet=0.14, decay=1.6, compress=True),
        group("brass", highpass=50, lowpass=7000, gain=8.0, wet=0.2, decay=2.0, balance=-0.1),
        group("pulse", highpass=90, gain=-2.0, wet=0.14, decay=1.2, balance=-0.3),
        group("timpani", highpass=30, gain=3.0, wet=0.18, decay=2.0),
        group("twang", highpass=90, gain=1.0, wet=0.18, decay=1.4, balance=0.3),
    ],
)

# ===========================================================================
# CLINKER FLATS
# ===========================================================================
flats = Cue("clinker_flats", 76, 1132, [
    ("works", 1, 24),
    ("row", 25, 40),
])
t = flats.t
c_heavy = flats.clip("heavy_kit", 3, 6)
c_anvil = flats.clip("anvil", 4, 4)
c_brake = flats.clip("brake", 3, 4)
c_tuba = flats.clip("tuba", 5, 4)
c_twang = flats.clip("twang", 4, 5)
c_choir = flats.clip("choir", 4, 3)
c_trumpet = flats.clip("trumpet", 7, 4)
c_guitar = flats.clip("guitar", 6, 5)
c_harmonica = flats.clip("harmonica", 8, 4)
c_bass = flats.clip("bass", 5, 4)
c_far = flats.clip("far", 4, 3)

# ---- WORKS (1-24): the yard and the smelter -----------------------------------
WORKS = ["Am", "Am", "Am", "Am", "F", "F", "E", "E", "Am", "Am", "Am", "Am",
         "Dm", "Dm", "E", "E", "F", "G", "Am", "Am", "Dm", "Dm", "E", "E"]
for i, chord in enumerate(WORKS):
    bar = 1 + i
    flats.harmony[bar] = chord
    c_heavy.note(t(bar), 0.4, KICK, 110)
    c_heavy.note(t(bar, 1.5), 0.4, KICK, 88)
    c_heavy.note(t(bar, 2), 0.4, SNARE, 104)
    if bar >= 9:
        for k in range(8):
            c_heavy.note(t(bar, 0.5 * k), 0.15, HAT, 46 if k % 2 == 0 else 32)
    if bar in (9, 17):
        c_heavy.note(t(bar), 1.0, CRASH, 92)
    if i == 23:
        for k in range(4):
            c_heavy.note(t(bar, 3 + 0.25 * k), 0.2, TOM_HI if k < 2 else TOM_LO, 84 + 4 * k)
    # The anvils on the backbeat; a brake drum on the offbeats once the works run.
    c_anvil.note(t(bar, 1), 0.5, STRIKE, 60)
    c_anvil.note(t(bar, 3), 0.5, STRIKE + 1, 54)
    if bar >= 9:
        c_brake.note(t(bar, 0.5), 0.3, STRIKE + 2, 50)
        c_brake.note(t(bar, 2.5), 0.3, STRIKE + 4, 46)
    # The tuba's riff: root, root, third, fourth, fifth.
    r = low(root(chord, 1), "D1")
    for at, step, v in ((0, 0, 92), (1, 0, 74), (1.5, third(chord), 78), (2, 5, 80), (3, 7, 84)):
        c_tuba.note(t(bar, at), 0.45 if at in (1, 1.5) else 0.9, r + step, v)
    if bar >= 5:
        stab = [root(chord, 2) + (12 if root(chord, 2) < midi("E2") else 0)]
        stab.append(stab[0] + 7)
        c_twang.note(t(bar), 0.4, stab, 82)
        c_twang.note(t(bar, 1.5), 0.4, stab, 74)
    if bar >= 9 and bar % 2 == 1:
        c_choir.note(t(bar), 7.6, [root(chord, 2) + (12 if root(chord, 2) < midi("C2") else 0) + d for d in (0, 7, 12)], 56)
# The clinker on the trumpet, from bar 5.
line(flats, c_trumpet, 5, [("C5", 4), ("A4", 2), ("C5", 1), ("D5", 1), ("B4", 4), ("G#4", 2), ("r", 2),
                           ("A4", 1), ("C5", .5), ("D5", .5), ("Eb5", 1.5), ("D5", .5), ("C5", 1), ("A4", 3),
                           ("A4", 1), ("C5", .5), ("D5", .5), ("Eb5", 1.5), ("E5", .5), ("G5", 1), ("A5", 3),
                           ("F5", 1), ("E5", 1), ("D5", 2), ("A4", 4), ("G#4", 1), ("B4", 1), ("D5", 2), ("E5", 4),
                           ("C5", 2), ("A4", 2), ("B4", 2), ("D5", 2),
                           ("A4", 1), ("C5", .5), ("D5", .5), ("Eb5", 1.5), ("D5", .5), ("C5", 1), ("A4", 3),
                           ("D5", 1), ("F5", 1), ("E5", 1), ("D5", 1), ("C5", 4), ("B4", 2), ("G#4", 2), ("E4", 4)], 86, legato=0.9)

# ---- ROW (25-40): the shacks under the works, and the line out -----------------
ROW = ["Am", "Am", "G", "G", "F", "F", "E", "E", "Am", "Am", "C", "G", "F", "E", "Am", "E"]
for i, chord in enumerate(ROW):
    bar = 25 + i
    flats.harmony[bar] = chord
    v = VOICING[chord]
    bass_note = v[0]
    alt = next((p for p in v if (p - v[0]) % 12 == 7), v[1])
    up = v[2:]
    for beat in range(4):
        c_guitar.note(t(bar, beat), 0.9, bass_note if beat % 2 == 0 else alt, 70 if beat % 2 == 0 else 62)
        c_guitar.note(t(bar, beat + 0.5), 0.45, up[(beat + i) % len(up)], 54)
    c_bass.note(t(bar), 3.0, low(root(chord, 1), "E1"), 62)
    # The works, far off.
    c_far.note(t(bar), 0.5, STRIKE, 44)
    if i % 2 == 1:
        c_far.note(t(bar, 2), 0.5, STRIKE + 1, 38)
line(flats, c_harmonica, 27, [("G4", 1.5), ("A4", .5), ("B4", 2), ("D5", 4), ("C5", 2), ("A4", 2), ("F4", 4),
                              ("G#4", 2), ("B4", 2), ("E5", 4),
                              ("A4", 1), ("D5", .5), ("E5", .5), ("F5", 2), ("E5", 1), ("D5", 1), ("B4", 1), ("A4", 1),
                              ("E5", 2), ("G5", 2), ("D5", 4), ("C5", 1), ("B4", 1), ("A4", 2), ("G#4", 4), ("A4", 4)],
     74, legato=0.95)

flats_text = score_text(
    flats, title="Clinker Flats", key="A", mode="minor", default_chord="Am",
    description="The Frontier's smelter town down the line from Halfway Siding: the yard and the works on a half-time kit with anvils on the backbeat, and the Row of shacks under them on the way to the railhead, where the town's detour turns minor on a harmonica.",
    notes=["Jon, 2026-11-20: the Frontier needs more than two western tracks. Clinker Flats had borrowed a section of the town cue; this is its own.",
           "The clinker: A C D Eb, D C A. The Row says the detour in minor: A D E F, E D B, A.",
           "The game binds the sections to rooms (Ambition music_cues.ron): works (the yard, the works), row (the Row, the railhead)."],
    shapes={
        "works": "energy: 0.7, density: 0.65, loopable: true, role: 'the yard and the works: big kit, anvils, tuba riff, the clinker on the trumpet'",
        "row": "energy: 0.25, density: 0.3, loopable: true, role: 'the Row and the railhead: guitar, the detour in minor on the harmonica, the works far off'",
    },
    instruments=[
        f"name: heavy_kit, group: heavy_kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz('drums.big_rusty')}",
        f"name: anvil, group: metal, program: tinkle_bell, volume: 90, pan: 64, expression: 96, {vcsl('Idiophones/Struck Idiophones/Anvil')}",
        f"name: brake, group: metal, program: tinkle_bell, volume: 90, pan: 64, expression: 96, {vcsl('Idiophones/Struck Idiophones/Brake Drum')}",
        f"name: tuba, group: tuba, program: tuba, volume: 106, pan: 64, expression: 108, {sfz('orchestra.tuba_sustain')}",
        f"name: twang, group: twang, program: clean_guitar, volume: 100, pan: 64, expression: 106, {SHINY}",
        f"name: choir, group: choir, program: choir_aahs, volume: 96, pan: 64, expression: 100, {sfz('vpo.choir_male')}",
        f"name: trumpet, group: trumpet, program: trumpet, volume: 100, pan: 64, expression: 106, {TRUMPET_SOLO}",
        f"name: guitar, group: guitar, program: steel_guitar, volume: 100, pan: 64, expression: 104, {sfz('guitar.acoustic', 'controls: {100: 126}, ')}",
        f"name: harmonica, group: harmonica, program: 22, volume: 100, pan: 64, expression: 106, {HARMONICA_VIB}",
        f"name: bass, group: bass, program: acoustic_bass, volume: 100, pan: 64, expression: 104, {sfz('bass.upright')}",
        f"name: far, group: far, program: tinkle_bell, volume: 80, pan: 64, expression: 90, {vcsl('Idiophones/Struck Idiophones/Anvil')}",
    ],
    groups=[
        group("heavy_kit", highpass=30, gain=4.0, wet=0.16, decay=1.8, compress=True),
        group("metal", highpass=200, gain=20.0, wet=0.22, decay=1.6, balance=0.3),
        group("tuba", highpass=30, lowpass=5000, gain=2.0, wet=0.12, decay=1.4),
        group("twang", highpass=90, gain=3.0, wet=0.2, decay=1.6, balance=-0.3),
        group("choir", highpass=80, gain=5.0, wet=0.3, decay=2.4),
        group("trumpet", highpass=150, gain=7.0, wet=0.28, decay=2.4, balance=0.1),
        group("guitar", highpass=80, gain=2.0, wet=0.16, decay=1.8, balance=-0.25),
        group("harmonica", highpass=180, gain=6.0, wet=0.24, decay=2.2, balance=0.1),
        group("bass", highpass=35, lowpass=3000, gain=7.0, wet=0.06, decay=1.2),
        group("far", highpass=300, lowpass=5000, gain=16.0, wet=0.5, decay=2.4, balance=0.4),
    ],
)

for cue, text in ((town, town_text), (train, train_text), (flats, flats_text)):
    path = OUT_DIR / f"{cue.id}.music.yaml"
    path.write_text(text)
    print(f"wrote {path}: {cue.end_bar - 1} bars, {(cue.end_bar - 1) * 4 * 60 / cue.bpm:.0f} s")

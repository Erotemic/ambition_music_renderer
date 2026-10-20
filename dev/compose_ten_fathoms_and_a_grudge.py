"""Ten Fathoms and a Grudge: a pirate song. Writes its MusicIR v3 score:

    python3 dev/compose_ten_fathoms_and_a_grudge.py scores/active/ten_fathoms_and_a_grudge.music.yaml

Jon, 2026-10-19: "now I want a new pirate themed song." Composed from first
principles: D minor in 6/8 at a dotted quarter of 100, a swashbuckler that
is half orchestra and half ship's band. The cellos gallop under everything;
the horns have the tune over D minor, C, B-flat, A (the falling line every
sea-dog knows, with a tune of its own on it); a fiddle takes a jig over a
tuba and accordion oom-pah; the crew sings a shanty in trombones and men's
voices over stamping feet; a storm turns the chords dark (a Neapolitan
E-flat, a diminished seventh) before the tune comes back with everyone.

Form, 6/8, two dotted-quarter beats a bar:
  intro    1-8     the ship's bell, the sea, a low D; the fiddle calls.
  sail     9-24    the gallop; the horns' tune twice.                    (loop start)
  jig      25-40   the ship's band: fiddle jig, tuba, accordion, bodhran.
  sail     41-56   the tune again, the violins an octave above the horns.
  shanty   57-72   the crew: trombones and men's voices, stamps and claps.
  storm    73-88   the Neapolitan E-flat and a diminished seventh; the fiddle runs.
  home     89-104  the tune with everyone, and back to the top on A.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 150  # quarter notes; a 6/8 bar is three of them
OUT = Path(sys.argv[1])
rng = random.Random(1715)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


def at(n: int, eighth: float = 0) -> float:
    """Quarter-note time of eighth `eighth` (0-5) of 6/8 bar `n`."""
    return (n - 1) * 3.0 + 0.5 * eighth


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.drift = drift
        self.vel_jitter = vel_jitter

    def note(self, when, dur, pitches, vel):
        when = F(when).limit_denominator(960)
        if self.drift and when > 0:
            when += F(rng.uniform(0, self.drift)).limit_denominator(960)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        self.events.append((when, F(dur).limit_denominator(960), [p if isinstance(p, int) else midi(p) for p in pitches], vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for when, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(when)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


celli = Clip(0.008, 5)
basses = Clip(0.01, 4)
violins = Clip(0.012, 4)
horns = Clip(0.012, 4)
trombones = Clip(0.012, 4)
tuba = Clip(0.01, 4)
fiddle = Clip(0.01, 5)
accordion = Clip(0.012, 5)
choir = Clip(0.015, 3)
bells = Clip()
timpani = Clip(0.005, 4)
frame = Clip(0.012, 7)
tamb = Clip(0.012, 7)
stomp = Clip(0.015, 6)
claps = Clip(0.02, 6)
ocean = Clip()
crash = Clip()

# ---- Harmony ---------------------------------------------------------------------
TONES = {"Dm": "D F A", "C": "C E G", "Bb": "Bb D F", "A": "A C# E", "Gm": "G Bb D", "F": "F A C",
         "Eb": "Eb G Bb", "C#dim7": "C# E G Bb"}
ROOT = {"Dm": "D", "C": "C", "Bb": "Bb", "A": "A", "Gm": "G", "F": "F", "Eb": "Eb", "C#dim7": "C#"}


def tones(chord: str) -> list[int]:
    return [NOTE[t] for t in TONES[chord].split()]


def voice(chord: str, low: int, count: int = 3) -> list[int]:
    """`count` chord tones stacked upward from the first one at or above `low`."""
    pcs = tones(chord)
    out, p = [], low
    while len(out) < count:
        if p % 12 in pcs:
            out.append(p)
        p += 1
    return out


def root(chord: str, low: int) -> int:
    """The chord's root in the octave at or above `low`."""
    p = low
    while p % 12 != NOTE[ROOT[chord]]:
        p += 1
    return p


#: Each bar's chords as (first eighth, chord); most bars have one.
SAIL = [[(0, "Dm")], [(0, "C")], [(0, "Bb")], [(0, "A")], [(0, "Dm")], [(0, "C")], [(0, "Bb"), (3, "A")], [(0, "Dm")]]
JIG = [[(0, "Dm")], [(0, "C")], [(0, "Dm")], [(0, "A")], [(0, "Dm")], [(0, "C")], [(0, "Bb")], [(0, "A")]]
SHANTY = [[(0, "Dm")], [(0, "Dm")], [(0, "Bb")], [(0, "C")], [(0, "Dm")], [(0, "Dm")], [(0, "Gm")], [(0, "A")]]
STORM = [[(0, "Dm")], [(0, "Eb")], [(0, "Dm")], [(0, "Eb")], [(0, "Bb")], [(0, "Gm")], [(0, "C#dim7")], [(0, "A")],
         [(0, "F")], [(0, "C")], [(0, "Dm")], [(0, "A")], [(0, "Bb")], [(0, "Gm")], [(0, "A")], [(0, "A")]]
harmony: dict[int, list] = {}


def halves(n: int):
    """(first eighth, length in eighths, chord) for each chord of bar `n`."""
    rows = harmony[n]
    for i, (e, chord) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else 6
        yield e, end - e, chord


# ---- Figures ---------------------------------------------------------------------
def gallop(n: int, vel=86):
    """Cellos: six eighths a bar, accents on the two beats, the fifth and the
    octave on the off-eighths."""
    for e, length, chord in halves(n):
        r = root(chord, midi("C3"))
        step = [0, 0, 6 if chord.endswith("dim7") else 7, 0, 0, 12]
        for k in range(e, e + length):
            accent = 14 if k in (0, 3) else 0
            celli.note(at(n, k), 0.42, r + step[k], vel - 14 + accent)


def low_beats(n: int, vel=84, long=False):
    """Basses: the root on each dotted-quarter beat (or held through the bar)."""
    for e, length, chord in halves(n):
        r = root(chord, midi("C2"))
        if long:
            basses.note(at(n, e), 0.5 * length - 0.05, r, vel)
        else:
            for k in (0, 3):
                if e <= k < e + length:
                    basses.note(at(n, k), 1.4, r, vel - (0 if k == 0 else 8))


def oompah(n: int, vel=82):
    """Tuba on the beats, accordion chords on the off-eighths."""
    for e, length, chord in halves(n):
        r = root(chord, midi("D2"))
        for k in range(e, e + length):
            if k in (0, 3):
                tuba.note(at(n, k), 0.9, r if k == 0 else r - 5 if r - 5 >= midi("A1") else r + 7, vel)
            else:
                accordion.note(at(n, k), 0.4, voice(chord, midi("D4")), vel - 18 + (6 if k in (1, 4) else 0))


def bodhran(n: int, vel=84, busy=True):
    """Frame drum: the big hit on the beats, muted strokes between."""
    for k in range(6):
        if k in (0, 3):
            frame.note(at(n, k), 0.3, 61, vel)
        elif busy or k == 5:
            frame.note(at(n, k), 0.2, 62 if k % 2 else 65, vel - 26)


def pad(clip: Clip, n: int, low: int, vel: int, count=3):
    for e, length, chord in halves(n):
        clip.note(at(n, e), 0.5 * length - 0.05, voice(chord, low, count), vel)


def play(clip: Clip, n: int, phrase, vel=84, transpose=0, length=0.95):
    """`phrase`: one list a bar of (first eighth, length in eighths, note)."""
    for k, notes in enumerate(phrase):
        for e, dur, name in notes:
            clip.note(at(n + k, e), 0.5 * dur * length, midi(name) + transpose, vel + (6 if e in (0, 3) else 0))


def eighths(clip: Clip, n: int, bars, vel=80, length=0.9):
    """`bars`: one string of six notes a bar; '-' holds the note before."""
    for k, row in enumerate(bars):
        names = row.split()
        e = 0
        while e < 6:
            hold = 1
            while e + hold < 6 and names[e + hold] == "-":
                hold += 1
            clip.note(at(n + k, e), 0.5 * hold * length, midi(names[e]), vel + (8 if e in (0, 3) else 0))
            e += hold


# ---- Tunes -------------------------------------------------------------------------
TUNE = [
    [(0, 2, "D4"), (2, 1, "E4"), (3, 2, "F4"), (5, 1, "G4")],
    [(0, 3, "A4"), (3, 2, "G4"), (5, 1, "E4")],
    [(0, 2, "F4"), (2, 1, "D4"), (3, 3, "Bb4")],
    [(0, 3, "A4"), (3, 1, "C#5"), (4, 1, "Bb4"), (5, 1, "A4")],
    [(0, 2, "D5"), (2, 1, "C5"), (3, 2, "A4"), (5, 1, "F4")],
    [(0, 2, "G4"), (2, 1, "E4"), (3, 2, "C5"), (5, 1, "G4")],
    [(0, 2, "F4"), (2, 1, "G4"), (3, 2, "E4"), (5, 1, "C#4")],
    [(0, 5, "D4")],
]
# The last time round the tune ends on A, to send the loop back to the top.
TUNE_TO_TOP = TUNE[:7] + [[(0, 2, "E4"), (2, 1, "C#4"), (3, 3, "A3")]]

JIG_TUNE = [
    "A4 D5 E5 F5 E5 D5",
    "E5 C5 G4 E4 G4 C5",
    "D5 A4 F4 D4 F4 A4",
    "C#5 A4 E4 A4 C#5 E5",
    "F5 E5 D5 E5 F5 G5",
    "E5 D5 C5 G4 C5 E5",
    "D5 C5 Bb4 F4 G4 A4",
    "C#5 A4 E4 A4 B4 C#5",
]
JIG_TUNE_2 = JIG_TUNE[:7] + ["D5 - - A4 F4 D4"]

# The shanty: two bars a line, sung by the crew.
SHANTY_TUNE = [
    [(0, 3, "A3"), (3, 2, "D4"), (5, 1, "D4")], [(0, 3, "F4"), (3, 3, "D4")],
    [(0, 2, "F4"), (2, 1, "F4"), (3, 3, "G4")], [(0, 2, "E4"), (2, 1, "C4"), (3, 3, "C4")],
    [(0, 3, "A4"), (3, 2, "G4"), (5, 1, "F4")], [(0, 3, "E4"), (3, 3, "D4")],
    [(0, 2, "Bb3"), (2, 1, "D4"), (3, 3, "G4")], [(0, 3, "E4"), (3, 2, "C#4"), (5, 1, "A3")],
]
# The fiddle answers each line in the gap at its end.
SHANTY_ANSWERS = {1: "A4 G4 F4", 3: "G4 A4 Bb4", 5: "F5 E5 D5", 7: "E5 C#5 A4"}

STORM_RUNS = [
    "D4 E4 F4 G4 A4 Bb4", "G4 - - Eb5 D5 C5", "A4 Bb4 C#5 D5 E5 F5", "G5 - - Eb5 D5 Bb4",
    "F4 G4 A4 Bb4 C5 D5", "Bb4 - - G4 A4 Bb4", "C#5 E5 G5 E5 C#5 Bb4", "A4 - - - - -",
]
# The second half of the storm turns to F and C, and the runs turn with it.
STORM_RUNS_2 = [
    "C5 A4 F4 A4 C5 F5", "E5 - - G5 E5 C5", "D5 E5 F5 E5 D5 A4", "C#5 - - E5 C#5 A4",
    "F4 G4 A4 Bb4 C5 D5", "Bb4 - - G4 A4 Bb4", "C#5 E5 G5 E5 C#5 A4", "A4 - - - - -",
]

# ---- Intro, bars 1-8 ------------------------------------------------------------
for n in range(1, 5):
    harmony[n] = [(0, "Dm")]
for n, chord in zip(range(5, 9), ("Dm", "C", "Bb", "A")):
    harmony[n] = [(0, chord)]
for n in (1, 3):  # the ship's bell, two strokes at a time
    bells.note(at(n, 0), 1.3, "A4", 88)
    bells.note(at(n, 1), 2.6, "A4", 78)
ocean.note(at(1), 12.0, 61, 70)
ocean.note(at(5), 12.0, 62, 60)
basses.note(at(1), 11.9, "D2", 70)
for n in range(5, 9):
    pad(horns, n, midi("F3"), 62)
    low_beats(n, vel=70, long=True)
play(fiddle, 5, [
    [(0, 3, "A4"), (3, 2, "D5"), (5, 1, "E5")],
    [(0, 2, "F5"), (2, 1, "E5"), (3, 3, "C5")],
    [(0, 2, "D5"), (2, 1, "Bb4"), (3, 3, "F4")],
    [(0, 3, "E4")],
], vel=78)
for i in range(12):  # the timpani rolls into the gallop
    timpani.note(at(8, 3) + 0.125 * i, 0.12, "A2", 40 + 4 * i)


def sail(n0: int, last_to_top=False, violins_up=False, everyone=False):
    """Sixteen bars of the tune over the gallop."""
    for k in range(16):
        n = n0 + k
        harmony[n] = SAIL[k % 8] if not (last_to_top and k == 15) else [(0, "A")]
        gallop(n, vel=90 if everyone else 86)
        low_beats(n, vel=88)
        bodhran(n, vel=86, busy=False)
        if k % 2 == 0:
            timpani.note(at(n), 0.5, root(harmony[n][0][1], midi("F2")), 84)
    play(horns, n0, TUNE, vel=86)
    play(horns, n0 + 8, TUNE_TO_TOP if last_to_top else TUNE, vel=90)
    if violins_up or everyone:
        play(violins, n0, TUNE, vel=80, transpose=12)
        play(violins, n0 + 8, TUNE_TO_TOP if last_to_top else TUNE, vel=84, transpose=12)
    else:  # the second time round the trombones double the horns an octave down
        play(trombones, n0 + 8, TUNE, vel=76, transpose=-12)
    if everyone:
        play(trombones, n0, TUNE, vel=78, transpose=-12)
        play(trombones, n0 + 8, TUNE_TO_TOP if last_to_top else TUNE, vel=82, transpose=-12)
        for k in range(16):
            pad(choir, n0 + k, midi("D3"), 70)
            if k % 2 == 1:
                tamb.note(at(n0 + k, 3), 0.3, 60, 74)
        bells.note(at(n0), 2.8, "D5", 84)
        crash.note(at(n0), 3.0, 60, 96)
        crash.note(at(n0 + 8), 3.0, 60, 88)
    else:
        crash.note(at(n0), 3.0, 60, 82)


# ---- Sail, bars 9-24 ------------------------------------------------------------
sail(9)

# ---- Jig, bars 25-40: the ship's band -------------------------------------------
for k in range(16):
    n = 25 + k
    harmony[n] = JIG[k % 8] if k != 15 else [(0, "Dm")]
    oompah(n)
    bodhran(n, vel=82)
    tamb.note(at(n, 3), 0.25, 60, 66)
    if k % 4 == 3:
        tamb.note(at(n, 4), 0.6, 61, 50)
eighths(fiddle, 25, JIG_TUNE, vel=82)
eighths(fiddle, 33, JIG_TUNE_2, vel=86)
# The second time round the accordion plays the tune's skeleton under the fiddle.
for k, row in enumerate(JIG_TUNE_2):
    names = row.split()
    accordion.note(at(33 + k, 0), 1.4, midi(names[0]) - 12, 64)
    accordion.note(at(33 + k, 3), 1.4, midi(names[3]) - 12, 60)

# ---- Sail again, bars 41-56: the violins an octave above the horns --------------
sail(41, violins_up=True)

# ---- Shanty, bars 57-72: the crew -----------------------------------------------
for k in range(16):
    n = 57 + k
    harmony[n] = SHANTY[k % 8] if k != 15 else [(0, "A")]
    pad(choir, n, midi("D3"), 72 if k < 8 else 80)
    low_beats(n, vel=78, long=True)
    tuba.note(at(n, 0), 1.3, root(harmony[n][0][1], midi("D2")), 80)
    stomp.note(at(n, 0), 0.4, 60, 100)
    claps.note(at(n, 3), 0.3, 60, 88)
    if k % 2 == 1:
        stomp.note(at(n, 5), 0.3, 60, 78)
    pad(accordion, n, midi("F4"), 52)
ocean.note(at(57), 24.0, 60, 54)
play(trombones, 57, SHANTY_TUNE, vel=84)
play(trombones, 65, SHANTY_TUNE, vel=90)
play(horns, 65, SHANTY_TUNE, vel=72)
for line, answer in SHANTY_ANSWERS.items():
    for i, name in enumerate(answer.split()):
        fiddle.note(at(57 + line, 3 + i), 0.45, midi(name), 74)
        fiddle.note(at(65 + line, 3 + i), 0.45, midi(name), 78)

# ---- Storm, bars 73-88 ------------------------------------------------------------
for k in range(16):
    n = 73 + k
    harmony[n] = STORM[k]
    gallop(n, vel=92)
    low_beats(n, vel=90)
    pad(horns, n, midi("F3"), 74 if k < 8 else 82)
    pad(violins, n, midi("A4"), 70 if k < 8 else 78)
    if k >= 8:
        pad(choir, n, midi("D3"), 76)
    timpani.note(at(n), 0.5, root(harmony[n][0][1], midi("F2")), 90)
    if harmony[n][0][1] in ("Eb", "C#dim7"):
        play(trombones, n, [[(0, 1, "Eb3" if harmony[n][0][1] == "Eb" else "E3"), (3, 1, "G3")]], vel=96)
    bodhran(n, vel=88)
eighths(fiddle, 73, STORM_RUNS, vel=84)
eighths(fiddle, 81, STORM_RUNS_2, vel=88)
for i in range(12):  # a roll into home
    timpani.note(at(88, 3) + 0.125 * i, 0.12, "A2", 50 + 5 * i)
crash.note(at(73), 3.0, 60, 90)
crash.note(at(81), 3.0, 60, 96)

# ---- Home, bars 89-104: everyone; back to the top on A -----------------------------
sail(89, last_to_top=True, everyone=True)

END_BAR = 105
progression = [harmony[n][0][1] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz'}}"


PARTS = [("celli", celli), ("basses", basses), ("violins", violins), ("horns", horns), ("trombones", trombones),
         ("tuba", tuba), ("fiddle", fiddle), ("accordion", accordion), ("choir", choir), ("bells", bells),
         ("timpani", timpani), ("frame", frame), ("tamb", tamb), ("stomp", stomp), ("claps", claps),
         ("ocean", ocean), ("crash", crash)]


def group(name: str, chain: list[str], gain: float, pan: float = 0.0) -> str:
    lines = [f"    {name}:", "      chain:"] + [f"        - {c}" for c in chain]
    lines.append(f"        - {{processor: gain, gain_db: {gain}}}")
    if pan:
        lines.append(f"        - {{processor: balance, position: {pan}}}")
    return "\n".join(lines)


HALL = "{processor: reverb, wet: 0.2, decay_seconds: 2.2}"
groups = "\n".join([
    group("strings", ["{processor: highpass, cutoff_hz: 35}", HALL], -3.0),
    group("violins", ["{processor: highpass, cutoff_hz: 150}", HALL], 5.0, -0.25),
    group("brass", ["{processor: highpass, cutoff_hz: 45}", HALL], 1.0, 0.15),
    group("fiddle", ["{processor: highpass, cutoff_hz: 180}", "{processor: reverb, wet: 0.14, decay_seconds: 1.6}"], 16.0, -0.1),
    group("band", ["{processor: highpass, cutoff_hz: 120}", "{processor: reverb, wet: 0.14, decay_seconds: 1.6}"], -3.0, 0.2),
    group("choir", ["{processor: highpass, cutoff_hz: 90}", "{processor: reverb, wet: 0.26, decay_seconds: 2.6}"], 0.0),
    group("bells", ["{processor: reverb, wet: 0.3, decay_seconds: 3.0}"], 0.0, 0.3),
    group("drums", ["{processor: highpass, cutoff_hz: 35}", "{processor: reverb, wet: 0.12, decay_seconds: 1.4}"], -2.0),
    group("sea", ["{processor: highpass, cutoff_hz: 120}", "{processor: lowpass, cutoff_hz: 6000}"], 0.0),
])

score = f"""schema: ambition.musicir.v3
id: ten_fathoms_and_a_grudge
title: Ten Fathoms and a Grudge
description: >-
  A pirate song: D minor in 6/8, half orchestra and half ship's band. The
  cellos gallop, the horns have the tune, a fiddle takes a jig over a tuba
  and accordion, the crew sings a shanty in trombones and men's voices over
  stamps and claps, and a storm darkens the chords before the tune comes home
  with everyone. Composed from first principles (Jon, 2026-10-19).
  Generated by dev/compose_ten_fathoms_and_a_grudge.py: edit that, not this
  file.
notes:
  - 'The intro plays once; the loop is bars 9-104, and its last chord (A) leads back to D minor at bar 9.'
  - 'Six-eight at a dotted quarter of 100: the score''s tempo counts quarters (150).'
seed: 1715
timebase: {{ppq: 960}}
meter: 6/8
tempo: {BPM}
key: D minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.3, density: 0.25, role: 'the bell, the sea, the fiddle calls'}}
  - {{id: sail, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.7, density: 0.6, loopable: true, role: 'the gallop; the horns have the tune'}}
  - {{id: jig, from: {{bar: 25, beat: 1}}, to: {{bar: 41, beat: 1}}, energy: 0.65, density: 0.55, loopable: true, role: 'the ship''s band'}}
  - {{id: sail_again, from: {{bar: 41, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.75, density: 0.65, loopable: true, role: 'the tune with the violins above'}}
  - {{id: shanty, from: {{bar: 57, beat: 1}}, to: {{bar: 73, beat: 1}}, energy: 0.6, density: 0.5, loopable: true, role: 'the crew sings'}}
  - {{id: storm, from: {{bar: 73, beat: 1}}, to: {{bar: 89, beat: 1}}, energy: 0.85, density: 0.75, loopable: true, role: 'dark chords, fiddle runs'}}
  - {{id: home, from: {{bar: 89, beat: 1}}, to: {{bar: 105, beat: 1}}, energy: 0.95, density: 0.85, loopable: true, role: 'everyone; back to the top on A'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: celli, group: strings, program: cello, volume: 106, pan: 64, expression: 110, instrument_backend: {{kind: sfz, library_ref: strings.celli_staccato}}}}
  - {{name: basses, group: strings, program: contrabass, volume: 106, pan: 64, expression: 110, instrument_backend: {{kind: sfz, library_ref: strings.basses}}}}
  - {{name: violins, group: violins, program: string_ensemble_1, volume: 100, pan: 64, expression: 106, instrument_backend: {{kind: sfz, library_ref: strings.violins_1}}}}
  - {{name: horns, group: brass, program: french_horn, volume: 106, pan: 64, expression: 110, instrument_backend: {{kind: sfz, library_ref: orchestra.horns_sustain}}}}
  - {{name: trombones, group: brass, program: trombone, volume: 104, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trombones_sustain}}}}
  - {{name: tuba, group: band, program: tuba, volume: 106, pan: 64, expression: 110, instrument_backend: {{kind: sfz, library_ref: orchestra.tuba_sustain}}}}
  - {{name: fiddle, group: fiddle, program: fiddle, volume: 104, pan: 64, expression: 110, instrument_backend: {{kind: sfz, library_ref: strings.violin_solo}}}}
  - {{name: accordion, group: band, program: accordion, volume: 96, pan: 64, expression: 100}}
  - {{name: choir, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, library_ref: vpo.choir_male}}}}
  - {{name: bells, group: bells, program: tubular_bells, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, sfz_glob: '**/Virtual-Playing-Orchestra3/Percussion/tubular-bells.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: timpani, group: drums, volume: 110, pan: 64, expression: 112, is_drum: true, instrument_backend: {{kind: sfz, library_ref: orchestra.timpani}}}}
  - {{name: frame, group: drums, volume: 110, pan: 64, expression: 112, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
  - {{name: tamb, group: drums, volume: 100, pan: 64, expression: 104, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Tambourine 1")}}}
  - {{name: stomp, group: drums, volume: 112, pan: 64, expression: 114, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Bass Drum 1")}}}
  - {{name: claps, group: drums, volume: 104, pan: 64, expression: 108, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Claps")}}}
  - {{name: ocean, group: sea, volume: 96, pan: 64, expression: 100, is_drum: true, {vcsl("Membranophones/Other Membranophones/Ocean Drum")}}}
  - {{name: crash, group: drums, volume: 100, pan: 64, expression: 104, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Clash Cymbals 1")}}}
parts:
{chr(10).join(part(f"{name}_part", name, clip) for name, clip in PARTS)}
processing:
  groups:
{groups}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.0, attack_ms: 20.0, release_ms: 160.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    orchestra: [strings, violins, brass, choir]
    band: [band, fiddle]
    drums: [drums, bells, sea]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [sail, jig, sail_again, shanty, storm, home], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 3 * 60 / BPM:.0f} s")

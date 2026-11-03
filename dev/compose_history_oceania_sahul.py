"""Sahul: the Oceania floor of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_oceania_sahul.py scores/active/history_oceania_sahul.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different
locations in the history dimension." Each region floor of the History grid
gets its own cue; this one plays on every room of the Oceania floor, from
Sahul (Australia and New Guinea joined, reached by sea about 50,000 years
ago, home of the oldest continuous cultures) east to the New Guinea
Highlands (Kuk Swamp, where people farmed taro and bananas very early). It
is exploration music under dialogue and light fighting.

The sound goes from deep time and heat, over the sea, to green highlands.
A didgeridoo is the drone voice of the Sahul sections: real held drones and
breathing phrases, never barks or jokes. Its sustained samples sound C#2,
so the cue is in C# minor and the highlands turn to the relative E major.
Claves are the clapsticks, a slit drum is in the role of the garamut,
bongos are in the role of the kundu hand drum, an ocean drum is the sea,
and a choir sings without words. A marimba and a kalimba are the melodic
colour of the highlands.

C# minor (with the Dorian A#) at 84 BPM, 4/4, then E major:
  - THE SONGLINE: a slow wordless tune that rises a fourth and settles:
    G# C# | D# C# | E C# B | C#.
  - THE GARDEN THEME: a syncopated marimba tune that falls a step and
    lifts again: G# F# E F# B.

Form, 64 bars, about 3:03. The file loops as a whole: bar 65 is bar 1.
  deep_time     1-8    the didgeridoo drone, the sea far off, a low hum;
                       clapsticks from bar 5.
  songline      9-16   the songline in wordless voices over the drone.
  sea_crossing  17-24  the drone stops; the ocean drum waves, the kalimba
                       rolls, the garamut calls; the voices hold the sail.
  ancestors     25-32  the drone returns; the songline on the low marimba,
                       the clapsticks in eighths.
  highlands     33-40  E major: the garden theme on the marimba over the
                       kalimba; the kundu hand drum.
  kuk_garden    41-48  the marimba calls and the voices answer.
  canopy        49-56  the garden theme with the kalimba an octave below
                       and the voices in a counter-line.
  return        57-64  the drone again; a piece of the songline; G#
                       leads to C# minor at bar 1.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 84
OUT = Path(sys.argv[1])
rng = random.Random(50000)  # years since the crossing to Sahul

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0, lo: int = 0, hi: int = 127):
        self.events: list[tuple] = []
        self.drift = drift
        self.vel_jitter = vel_jitter
        #: the playable keys of the sample; a note outside them is a script error
        self.lo, self.hi = lo, hi

    def note(self, at, dur, pitches, vel):
        at = F(at).limit_denominator(960)
        if self.drift and at > 0:
            at += F(rng.uniform(-self.drift, self.drift)).limit_denominator(960)
        at = max(F(0), at)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        keys = [p if isinstance(p, int) else midi(p) for p in pitches]
        for k in keys:
            if not self.lo <= k <= self.hi:
                raise ValueError(f"key {k} at beat {float(at)} is outside {self.lo}-{self.hi}")
        self.events.append((at, F(dur).limit_denominator(960), keys, vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


def T(n: int) -> float:
    """The first beat of bar n, in beats."""
    return (n - 1) * 4.0


# Each clip carries the playable key span of its sample, so a note out of range fails here.
didge = Clip(0.0, 0, 60, 71)            # VCSL Didgeridoo: one recorded drone or phrase per key
choir_f = Clip(0.008, 2, 67, 84)
choir_m = Clip(0.008, 2, 43, 66)
marimba = Clip(0.006, 4, 41, 97)        # VCSL Marimba
marimba_low = Clip(0.006, 3, 41, 97)
kalimba = Clip(0.006, 4, 59, 84)        # VCSL Kalimba, Kenya
claves = Clip(0.006, 4, 60, 61)         # VCSL Claves: two pairs of sticks
slit = Clip(0.008, 4, 60, 61)           # VCSL Slit Drum: 60 the high tongue, 61 the low tongue
sea = Clip(0.0, 0, 60, 62)              # VCSL Ocean Drum: three long sustains
bongos = Clip(0.006, 4, 60, 65)         # VCSL Bongos
frame = Clip(0.008, 4, 60, 65)          # VCSL Frame Drum
harmony: dict[int, str] = {}

# The didgeridoo keys, and the velocity that brings each recording to one level.
# Measured fundamentals (harmonic peaks): Sus2 C#2 +5 cents, Sus3 +13, Phrase1 -10,
# Phrase5 +11, Phrase8 -8. Sus8 (+42 cents) and the barks are not used.
DRONE_A, DRONE_B, BREATH_1, BREATH_5, BREATH_8 = 68, 69, 62, 64, 66
DIDGE_VEL = {DRONE_A: 118, DRONE_B: 108, BREATH_1: 74, BREATH_5: 44, BREATH_8: 90}
STICK_A, STICK_B = 60, 61
SLIT_HI, SLIT_LO = 60, 61
WAVE_1, WAVE_2, WAVE_3 = 60, 61, 62
BO_HI, BO_HI_MUTE, BO_HI_ROLL, BO_LO, BO_LO_MUTE, BO_LO_ROLL = 60, 61, 62, 63, 64, 65
FR_LOW_HIT, FR_LOW_MUTE, FR_SMALL_HIT = 61, 62, 64


def drone(n: int, key: int, beats: float, scale: float = 1.0):
    didge.note(T(n), beats, key, int(DIDGE_VEL[key] * scale))


# ---- Harmony ------------------------------------------------------------------------------
#: chord -> (low hum voicing, marimba bass root)
CHORD = {
    "C#m": (["C#3", "G#3", "E4"], "C#3"),
    "B": (["B2", "F#3", "D#4"], "B2"),
    "A": (["A2", "E3", "C#4"], "A2"),
    "G#m": (["G#2", "D#3", "B3"], "G#2"),
    "E": (["B2", "E3", "G#3"], "E3"),
    "F#m": (["A2", "C#3", "F#3"], "F#2"),
    "G#": (["G#2", "D#3", "C4"], "G#2"),
    "G#sus4": (["G#2", "D#3", "C#4"], "G#2"),
}


def hum(n: int, chord: str, vel: int, beats: float = 3.9):
    harmony[n] = chord
    choir_m.note(T(n), beats, CHORD[chord][0], vel)


def sing(clip: Clip, n0: int, phrase, vel=90, octave=0, legato=0.97):
    """A phrase, one list of (beat, duration, note) per bar."""
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            long = dur >= 1.5
            clip.note(T(n0 + k) + at, dur * (legato if long else 0.9), midi(name) + 12 * octave, vel + (4 if long else 0))


# ---- Percussion ---------------------------------------------------------------------------
def sticks(n: int, style: str, vel=70):
    """Clapsticks: 'pulse' is quarter notes, 'pair' adds a pair on four, 'eighths' is a steady eighth beat."""
    t = T(n)
    if style == "pulse":
        for b in range(4):
            claves.note(t + b, 0.2, STICK_A, vel - (0 if b % 2 == 0 else 10))
    elif style == "pair":
        for b in (0, 1, 2):
            claves.note(t + b, 0.2, STICK_A, vel - (0 if b == 0 else 10))
        claves.note(t + 3, 0.2, STICK_B, vel - 6)
        claves.note(t + 3.5, 0.2, STICK_B, vel - 14)
    elif style == "eighths":
        for i in range(8):
            claves.note(t + 0.5 * i, 0.2, STICK_A if i % 2 == 0 else STICK_B, vel - (0 if i % 4 == 0 else 14))


def garamut(n: int, vel=84, signal=False):
    """The slit drum: a low stroke on one; a high-high-low signal at a phrase end."""
    slit.note(T(n), 0.8, SLIT_LO, vel)
    if signal:
        for at, key, dv in ((2.0, SLIT_HI, -6), (2.5, SLIT_HI, -12), (3.0, SLIT_LO, -4)):
            slit.note(T(n) + at, 0.4, key, vel + dv)


def kundu(n: int, vel=74, fill=False):
    """The hand drum (bongos in the kundu's role): low on one and the and of two, highs between."""
    t = T(n)
    for at, key, dv in ((0, BO_LO, 0), (0.75, BO_HI_MUTE, -20), (1.5, BO_HI, -10), (2.0, BO_LO, -6),
                        (2.5, BO_HI_MUTE, -18), (3.0, BO_HI, -8), (3.5, BO_HI_MUTE, -22)):
        bongos.note(t + at, 0.3, key, vel + dv)
    if fill:
        for i, key in enumerate((BO_HI, BO_HI, BO_LO, BO_LO)):
            bongos.note(t + 3 + 0.25 * i, 0.2, key, vel - 14 + 4 * i)


# ---- Melodies (beat in bar, duration, note) -------------------------------------------------
SONGLINE = [  # over C#m B A C#m | C#m B A B
    [(0.0, 2.0, "G#4"), (2.0, 2.0, "C#5")],
    [(0.0, 3.0, "D#5"), (3.0, 1.0, "C#5")],
    [(0.0, 2.0, "E5"), (2.0, 1.0, "C#5"), (3.0, 1.0, "B4")],
    [(0.0, 3.5, "C#5")],
    [(0.0, 2.0, "E5"), (2.0, 2.0, "G#5")],
    [(0.0, 2.0, "F#5"), (2.0, 2.0, "D#5")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "E5")],
    [(0.0, 3.5, "D#5")],
]
SAIL = [  # sea_crossing, the voices hold long notes over A B C#m G#m | A B C#m C#m
    [(0.0, 4.0, "E5")],
    [(0.0, 4.0, "F#5")],
    [(0.0, 2.0, "G#5"), (2.0, 2.0, "E5")],
    [(0.0, 4.0, "D#5")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "E5")],
    [(0.0, 3.0, "F#5"), (3.0, 1.0, "D#5")],
    [(0.0, 4.0, "E5")],
    [(0.0, 3.0, "G#4")],
]
GARDEN = [  # over E A E B | C#m A B E
    [(0.0, 1.5, "G#5"), (1.5, 0.5, "F#5"), (2.0, 0.5, "E5"), (2.5, 1.0, "F#5"), (3.5, 0.5, "B4")],
    [(0.0, 1.5, "C#6"), (1.5, 0.5, "B5"), (2.0, 0.5, "A5"), (2.5, 1.5, "E5")],
    [(0.0, 0.5, "E5"), (0.5, 0.5, "F#5"), (1.0, 1.0, "G#5"), (2.0, 0.5, "B5"), (2.5, 0.5, "G#5"), (3.0, 1.0, "F#5")],
    [(0.0, 3.0, "D#5"), (3.0, 1.0, "F#5")],
    [(0.0, 1.5, "E5"), (1.5, 0.5, "D#5"), (2.0, 0.5, "C#5"), (2.5, 1.0, "E5"), (3.5, 0.5, "G#4")],
    [(0.0, 1.5, "A5"), (1.5, 0.5, "G#5"), (2.0, 0.5, "F#5"), (2.5, 1.5, "C#5")],
    [(0.0, 0.5, "D#5"), (0.5, 0.5, "E5"), (1.0, 1.0, "F#5"), (2.0, 1.0, "B5"), (3.0, 1.0, "A5")],
    [(0.0, 3.0, "G#5")],
]
CALLS = [  # kuk_garden, the marimba calls over C#m . E . C#m . F#m .
    (41, [(0.0, 0.5, "G#5"), (0.5, 0.5, "E5"), (1.0, 1.0, "C#5"), (2.0, 0.5, "E5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "G#5")]),
    (43, [(0.0, 0.5, "B5"), (0.5, 0.5, "G#5"), (1.0, 1.0, "E5"), (2.0, 0.5, "G#5"), (2.5, 0.5, "A5"), (3.0, 1.0, "B5")]),
    (45, [(0.0, 0.5, "C#6"), (0.5, 0.5, "B5"), (1.0, 0.5, "G#5"), (1.5, 0.5, "E5"), (2.0, 1.0, "F#5"), (3.0, 1.0, "G#5")]),
    (47, [(0.0, 0.5, "F#5"), (0.5, 0.5, "A5"), (1.0, 1.0, "C#6"), (2.0, 1.0, "B5"), (3.0, 1.0, "A5")]),
]
ANSWERS = [  # the voices answer over A . B . A . B
    (42, [(0.0, 2.0, "A5"), (2.0, 2.0, "E5")]),
    (44, [(0.0, 2.0, "B5"), (2.0, 2.0, "F#5")]),
    (46, [(0.0, 1.0, "E5"), (1.0, 1.0, "F#5"), (2.0, 2.0, "A5")]),
    (48, [(0.0, 3.0, "F#5")]),
]
COUNTER = [  # canopy, the voices hold a slow line under the garden theme
    [(0.0, 4.0, "B4")],
    [(0.0, 4.0, "C#5")],
    [(0.0, 2.0, "B4"), (2.0, 2.0, "E5")],
    [(0.0, 4.0, "D#5")],
    [(0.0, 4.0, "C#5")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "E5")],
    [(0.0, 4.0, "B4")],
    [(0.0, 3.0, "B4")],
]
REMEMBER = [  # return, the songline's first half on the marimba, over C#m B A C#m
    [(0.0, 2.0, "G#4"), (2.0, 2.0, "C#5")],
    [(0.0, 3.0, "D#5"), (3.0, 1.0, "C#5")],
    [(0.0, 2.0, "E5"), (2.0, 1.0, "C#5"), (3.0, 1.0, "B4")],
    [(0.0, 3.0, "C#5")],
]

#: kalimba figures, a bar of eighths each, in the register below the marimba tune
KALIMBA = {
    "E": ["E4", "B4", "G#4", "B4", "E4", "B4", "G#4", "F#4"],
    "A": ["A4", "E4", "C#5", "E4", "A4", "E4", "B4", "C#5"],
    "B": ["B4", "F#4", "D#5", "F#4", "B4", "F#4", "C#5", "D#5"],
    "C#m": ["C#5", "G#4", "E4", "G#4", "C#5", "G#4", "B4", "G#4"],
    "G#m": ["B4", "G#4", "D#5", "G#4", "B4", "G#4", "F#4", "G#4"],
    "F#m": ["F#4", "C#5", "A4", "C#5", "F#4", "C#5", "A4", "E4"],
}


def kalimba_bar(n: int, chord: str, vel=64, half=False):
    for i, name in enumerate(KALIMBA[chord]):
        if half and i % 2:
            continue
        kalimba.note(T(n) + 0.5 * i, 0.9 if half else 0.45, name, vel + (8 if i % 4 == 0 else 0))


def walking_bass(n: int, chord: str, vel=74):
    """The low marimba: root on one, fifth on the and of two, root again on four."""
    root = midi(CHORD[chord][1])
    marimba_low.note(T(n), 1.4, root, vel)
    marimba_low.note(T(n) + 1.5, 1.0, root + 7, vel - 12)
    marimba_low.note(T(n) + 3, 0.9, root, vel - 8)


# ---- deep_time, 1-8 --------------------------------------------------------------------------
for n in range(1, 9):
    harmony[n] = "C#m"
drone(1, DRONE_A, 15.5)
drone(5, BREATH_1, 15.5)
sea.note(T(1), 7.5, WAVE_1, 52)
sea.note(T(5) + 2, 7.5, WAVE_3, 46)
hum(3, "C#m", 46, beats=7.8)
hum(5, "C#m", 50, beats=7.8)
hum(7, "C#m", 52, beats=7.8)
for n in range(5, 9):
    sticks(n, "pulse", 56 + 3 * (n - 5))
marimba_low.note(T(4) + 2, 1.5, "G#3", 52)
marimba_low.note(T(8), 2.0, "C#3", 56)

# ---- songline, 9-16 --------------------------------------------------------------------------
SONG_CH = ["C#m", "B", "A", "C#m", "C#m", "B", "A", "B"]
for k, chord in enumerate(SONG_CH):
    n = 9 + k
    hum(n, chord, 52)
    sticks(n, "pair" if k % 2 else "pulse", 66)
drone(9, DRONE_B, 13.5)
drone(13, BREATH_8, 15.5)
sing(choir_f, 9, SONGLINE, vel=74)
sea.note(T(15), 6.0, WAVE_2, 40)

# ---- sea_crossing, 17-24 ---------------------------------------------------------------------
SEA_CH = ["A", "B", "C#m", "G#m", "A", "B", "C#m", "C#m"]
for k, chord in enumerate(SEA_CH):
    n = 17 + k
    hum(n, chord, 54)
    kalimba_bar(n, chord, 60 + (4 if k in (2, 6) else 0))
    garamut(n, 80, signal=k in (3, 7))
    marimba_low.note(T(n), 3.6, CHORD[chord][1], 60)
sing(choir_f, 17, SAIL, vel=70)
for n, wave in ((17, WAVE_1), (19, WAVE_2), (21, WAVE_3), (23, WAVE_1)):
    sea.note(T(n), 7.0, wave, 66)

# ---- ancestors, 25-32 -----------------------------------------------------------------------
for k, chord in enumerate(SONG_CH):
    n = 25 + k
    hum(n, chord, 56)  # no high voices here: the marimba tune is in their register
    sticks(n, "eighths", 66)
    if k % 4 == 3:
        garamut(n, 70, signal=True)
drone(25, BREATH_5, 14.5)
drone(29, DRONE_A, 15.5)
sing(marimba, 25, SONGLINE, vel=84, legato=0.9)

# ---- highlands, 33-40 -----------------------------------------------------------------------
GARDEN_CH = ["E", "A", "E", "B", "C#m", "A", "B", "E"]
for k, chord in enumerate(GARDEN_CH):
    n = 33 + k
    harmony[n] = chord
    kalimba_bar(n, chord, 62)
    walking_bass(n, chord, 72)
    kundu(n, 74, fill=k == 7)
    if k >= 4:
        hum(n, chord, 48)
sing(marimba, 33, GARDEN, vel=92, legato=0.9)

# ---- kuk_garden, 41-48 ----------------------------------------------------------------------
KUK_CH = ["C#m", "A", "E", "B", "C#m", "A", "F#m", "B"]
for k, chord in enumerate(KUK_CH):
    n = 41 + k
    harmony[n] = chord
    kalimba_bar(n, chord, 56, half=True)
    walking_bass(n, chord, 70)
    kundu(n, 70, fill=k == 7)
    frame.note(T(n), 0.6, FR_LOW_HIT, 66)
    frame.note(T(n) + 2, 0.5, FR_LOW_MUTE, 56)
    if k % 2 == 0:
        garamut(n, 72)
for n, notes in CALLS:
    sing(marimba, n, [notes], vel=90, legato=0.9)
for n, notes in ANSWERS:
    sing(choir_f, n, [notes], vel=72)

# ---- canopy, 49-56 --------------------------------------------------------------------------
for k, chord in enumerate(GARDEN_CH):
    n = 49 + k
    harmony[n] = chord
    walking_bass(n, chord, 76)
    kundu(n, 78, fill=k in (3, 7))
    frame.note(T(n), 0.6, FR_LOW_HIT, 70)
    frame.note(T(n) + 2, 0.5, FR_SMALL_HIT, 56)
    sticks(n, "pair", 58)
sing(marimba, 49, GARDEN, vel=96, legato=0.9)
# The kalimba doubles the tune an octave below; a note below its lowest tine stays at the tune's pitch.
for k, notes in enumerate(GARDEN):
    for at, dur, name in notes:
        key = midi(name) - 12 if midi(name) - 12 >= kalimba.lo else midi(name)
        kalimba.note(T(49 + k) + at, dur * 0.9, key, 70)
sing(choir_f, 49, COUNTER, vel=62)

# ---- return, 57-64 --------------------------------------------------------------------------
RET_CH = ["C#m", "B", "A", "C#m", "C#m", "A", "G#sus4", "G#"]
for k, chord in enumerate(RET_CH):
    n = 57 + k
    if n == 64:  # the last bar stops on beat 3, so nothing rings across the loop seam
        hum(n, chord, 46, beats=2.6)
        marimba_low.note(T(n), 1.5, "G#2", 52)
    else:
        hum(n, chord, 52 - k)
    if n <= 62:
        sticks(n, "pulse" if n < 61 else "pair", 60 - 2 * k)
drone(57, DRONE_A, 15.5)
drone(61, BREATH_1, 7.0, scale=0.9)
sea.note(T(59), 6.0, WAVE_2, 44)
sing(marimba, 57, REMEMBER, vel=74, legato=0.9)
garamut(60, 62)

END_BAR = 65
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    """An explicit VCSL program: these instruments are not in the instrument catalog."""
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


FORM = [
    ("deep_time", 1, "Deep time: the drone and the sea far off", 0.3, 0.3),
    ("songline", 9, "Songline: the wordless tune over the drone", 0.45, 0.45),
    ("sea_crossing", 17, "Sea crossing: waves, kalimba and garamut", 0.6, 0.6),
    ("ancestors", 25, "Ancestors: the songline on the marimba", 0.55, 0.6),
    ("highlands", 33, "Highlands: the garden theme in E major", 0.7, 0.7),
    ("kuk_garden", 41, "Kuk garden: the marimba calls, the voices answer", 0.7, 0.7),
    ("canopy", 49, "Canopy: the garden theme, full", 0.8, 0.8),
    ("return", 57, "Return: the drone again, back to C# minor", 0.35, 0.35),
]
form_lines = []
for i, (fid, start, label, energy, density) in enumerate(FORM):
    end = FORM[i + 1][1] if i + 1 < len(FORM) else END_BAR
    form_lines.append(f"  - {{id: {fid}, label: '{label}', from: {{bar: {start}, beat: 1}}, to: {{bar: {end}, beat: 1}}, "
                      f"energy: {energy}, density: {density}, role: loop_component, loopable: true}}")
form_text = "\n".join(form_lines)

score = f"""schema: ambition.musicir.v3
id: history_oceania_sahul
title: Sahul
description: >-
  The Oceania floor of the History dimension, from Sahul (Australia and New
  Guinea joined, reached by sea about 50,000 years ago) to the gardens of
  the New Guinea Highlands at Kuk Swamp. C# minor turning to E major at 84
  BPM. A didgeridoo drone and wordless voices carry a slow songline; claves
  are the clapsticks; an ocean drum, a kalimba and a slit drum (in the role
  of the garamut) make the sea crossing; in the highlands a marimba has a
  green garden tune over the kalimba and bongos in the role of the kundu.
  Generated by dev/compose_history_oceania_sahul.py: edit that, not this
  file.
notes:
  - 'Jon, 2026-11-03: "I also think we will want new music for different locations in the history dimension." One cue for each region floor; this one plays on every room of the Oceania floor.'
  - 'The file loops as a whole: bar 65 is bar 1. The last bar (G#) stops on beat 3 and leads to C# minor.'
  - 'The didgeridoo is a drone voice only: its held drones and breathing phrases, at the key of its own fundamental (C#2). Its keys are recordings, not pitches, so it is is_drum, like the percussion.'
  - 'All melodies are original. The VCSL instruments are explicit sfz_glob programs because they are not in the instrument catalog.'
seed: 50000
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: C# minor
end: {{bar: {END_BAR}, beat: 1}}
form:
{form_text}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: didge, group: didge, volume: 110, pan: 64, expression: 112, is_drum: true, {vcsl("Aerophones/Lip Aerophones/Didgeridoo")}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 96, pan: 70, expression: 100, {sfz("vpo.choir")}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 96, pan: 58, expression: 100, {sfz("vpo.choir_male")}}}
  - {{name: marimba, group: marimba, program: marimba, volume: 104, pan: 60, expression: 108, {vcsl("Idiophones/Struck Idiophones/Marimba")}}}
  - {{name: marimba_low, group: marimba_low, program: marimba, volume: 100, pan: 66, expression: 104, {vcsl("Idiophones/Struck Idiophones/Marimba")}}}
  - {{name: kalimba, group: kalimba, program: kalimba, volume: 100, pan: 80, expression: 104, {vcsl("Idiophones/Plucked Idiophones/Kalimba, Kenya")}}}
  - {{name: claves, group: sticks, volume: 100, pan: 48, expression: 104, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Claves")}}}
  - {{name: slit, group: garamut, volume: 100, pan: 56, expression: 104, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Slit Drum")}}}
  - {{name: sea, group: sea, volume: 96, pan: 64, expression: 100, is_drum: true, {vcsl("Membranophones/Other Membranophones/Ocean Drum")}}}
  - {{name: bongos, group: kundu, volume: 100, pan: 72, expression: 104, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Bongos")}}}
  - {{name: frame, group: frame, volume: 100, pan: 64, expression: 104, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
parts:
{part("didge_part", "didge", didge)}
{part("choir_f_part", "choir_f", choir_f)}
{part("choir_m_part", "choir_m", choir_m)}
{part("marimba_part", "marimba", marimba)}
{part("marimba_low_part", "marimba_low", marimba_low)}
{part("kalimba_part", "kalimba", kalimba)}
{part("claves_part", "claves", claves)}
{part("slit_part", "slit", slit)}
{part("sea_part", "sea", sea)}
{part("bongos_part", "bongos", bongos)}
{part("frame_part", "frame", frame)}
processing:
  groups:
    didge:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 2.5, attack_ms: 30.0, release_ms: 200.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 9.0}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 0.0}}
    marimba:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: -0.1}}
    marimba_low:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: lowpass, cutoff_hz: 3000}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 0.0}}
    kalimba:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: 0.3}}
    sticks:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 14.0}}
    garamut:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 8.0}}
    sea:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 9.0}}
    kundu:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: compressor, threshold_db: -18.0, ratio: 2.0, attack_ms: 12.0, release_ms: 90.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 0.0}}
    frame:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 0.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      # The marimba, kalimba and hand drums make a high crest. A fast limiter takes their
      # attack peaks down a few dB, so the cue normalizes near the other History cues.
      - {{processor: gain, gain_db: 3.0}}
      - processor: pedalboard
        effects:
          - {{effect: limiter, threshold_db: -6.0, release_ms: 60.0}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  # Exploring plays everything; the tune layer can drop out under dialogue.
  layers:
    bed: [didge, choir, marimba_low, sea]
    drums: [sticks, garamut, kundu, frame]
    tune: [marimba, kalimba]
  sections:
    - {{id: song, form: [{", ".join(f[0] for f in FORM)}], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

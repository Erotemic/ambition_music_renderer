"""Over the Land Bridge: the Americas floor of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_americas_land_bridge.py scores/active/history_americas_land_bridge.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different
locations in the history dimension." Each region floor of the History grid
gets its own cue; this one plays on every room of the Americas floor, from
Beringia (the land bridge from Asia, 20,000 years ago: ice, mammoths and
sabre-tooth cats) east to First Maize (Mesoamerica, where people made maize
from teosinte). It is exploration music under dialogue and light fighting.

The sound starts cold and wide and grows warm. Clay vessel flutes are among
the oldest instruments of the Americas, so a clay ocarina has the tune and a
small ocarina sings above it. A two-tone slit drum (in the role of the
teponaztli), a frame drum and a shaker keep the walk; wine glasses, mark
trees and an ocean drum are the ice and the wind; low strings and a low
choir are the cold.

A minor at 88 BPM, 4/4, and A major (with the Mixolydian G) for the maize:
  - THE CROSSING THEME: long notes that climb a fourth and fall back, like a
    walk into the wind: E D | E G A | G E D | E.
  - THE MAIZE THEME: a short dance figure that grows each time it returns:
    A C# E F# E C#.

Form, 64 bars, about 2:55. The file loops as a whole: bar 65 is bar 1.
  ice_wind     1-8    wind, glasses, an open fifth in the basses; the
                      ocarina calls from far off; a walking heartbeat.
  crossing     9-16   the crossing theme on the ocarina, Am G Em Am F G Am.
  mammoth      17-24  heavy steps in the low strings and drums, a stern
                      variant of the theme over Dm Am Dm E; a cat hisses.
  thaw         25-32  the ice melts: C G D A F C G A; the small ocarina
                      flickers; the theme's tail turns to A major.
  first_maize  33-40  the maize theme over A G D A; the slit drum and the
                      shaker dance.
  teosinte     41-48  the small ocarina grows a seed of two notes into a
                      phrase; wordless voices swell under it.
  harvest      49-56  the crossing theme in A major, an octave up on the
                      small ocarina; the ocarina holds a counter-line.
  return       57-64  the maize figure in minor and slow; the wind comes
                      back; E major leads to A minor at bar 1.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 88
OUT = Path(sys.argv[1])
rng = random.Random(20000)  # years since the crossing

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
ocarina = Clip(0.006, 3, 69, 86)        # VCSL Ocarina, Typical - Sus: A4-D6
ocarina_small = Clip(0.006, 3, 81, 97)  # VCSL Ocarina, Small - Sustain: A5-C#7
glasses = Clip(0.004, 2, 74, 87)        # VCSL Wine Glasses - Slow: D5-D#6
chimes = Clip(0.0, 0, 60, 65)           # VCSL Mark Trees: six gestures
wind = Clip(0.0, 0, 60, 62)             # VCSL Ocean Drum: three long sustains
celli = Clip(0.006, 3, 36, 73)
basses = Clip(0.006, 3, 24, 60)
choir_m = Clip(0.008, 2, 43, 66)
choir_f = Clip(0.008, 2, 67, 84)
slit = Clip(0.008, 4, 60, 61)           # VCSL Slit Drum: 60 the high tongue, 61 the low tongue
frame = Clip(0.008, 4, 60, 65)          # VCSL Frame Drum
shaker = Clip(0.006, 4, 60, 67)         # VCSL Shaker, Small
harmony: dict[int, str] = {}

# Unpitched trigger keys.
SLIT_HI, SLIT_LO = 60, 61
FR_LOW_HAND, FR_LOW_HIT, FR_LOW_MUTE, FR_SMALL_HAND, FR_SMALL_HIT, FR_SMALL_MUTE = 60, 61, 62, 63, 64, 65
SH_SLAP, SH_DOUBLE_DOWN, SH_DOUBLE_UP, SH_HIGH_UP, SH_LOW_DOWN, SH_LOW_UP = 61, 62, 63, 65, 66, 67
CH_ASC, CH_DESC, CH_FAST_ASC, CH_RANDOM, CH_SLOW_ASC, CH_SLOW_DESC = 60, 61, 62, 63, 64, 65
WIND_1, WIND_2, WIND_3 = 60, 61, 62

# ---- Harmony ------------------------------------------------------------------------------
#: chord -> (bass root in the basses' octave, celli voicing, low choir voicing)
CHORD = {
    "Am": ("A1", ["A2", "E3"], ["A2", "E3", "C4"]),
    "G": ("G1", ["G2", "D3"], ["G2", "D3", "B3"]),
    "Em": ("E1", ["E2", "B2"], ["B2", "E3", "G3"]),
    "F": ("F1", ["F2", "C3"], ["A2", "C3", "F3"]),
    "Fmaj7": ("F1", ["F2", "C3"], ["A2", "E3", "C4"]),
    "Dm": ("D2", ["D2", "A2"], ["A2", "D3", "F3"]),
    "E": ("E1", ["E2", "B2"], ["B2", "E3", "G#3"]),
    "Esus4": ("E1", ["E2", "B2"], ["B2", "E3", "A3"]),
    "C": ("C2", ["C2", "G2"], ["G2", "C3", "E3"]),
    "D": ("D2", ["D2", "A2"], ["A2", "D3", "F#3"]),
    "A": ("A1", ["A2", "E3"], ["A2", "E3", "C#4"]),
    "Asus4": ("A1", ["A2", "E3"], ["A2", "D3", "E3"]),
    "F#m": ("F#1", ["F#2", "C#3"], ["A2", "C#3", "F#3"]),
}
#: the third of each chord, for the warm sections where the celli add it
THIRD = {"Am": "C3", "G": "B2", "Em": "G2", "F": "A2", "Fmaj7": "A2", "Dm": "F3", "E": "G#2", "Esus4": "A2",
         "C": "E3", "D": "F#3", "A": "C#3", "Asus4": "D3", "F#m": "A2"}


def low_bed(n: int, chord: str, bass_vel: int, cello_vel: int, warm=False, dur=3.92):
    """One bar of the low strings: the basses on the root, the celli on an open fifth (and the third when warm)."""
    harmony[n] = chord
    root, fifth, _ = CHORD[chord]
    basses.note(T(n), dur, root, bass_vel)
    celli.note(T(n), dur, fifth + ([THIRD[chord]] if warm else []), cello_vel)


def hum(n: int, chord: str, vel: int, bars: int = 1):
    choir_m.note(T(n), 4 * bars - 0.1, CHORD[chord][2], vel)


def sing(clip: Clip, n0: int, phrase, vel=92, octave=0):
    """A phrase, one list of (beat, duration, note) per bar."""
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            long = dur >= 1.5
            clip.note(T(n0 + k) + at, dur * (0.97 if long else 0.9), midi(name) + 12 * octave, vel + (4 if long else 0))


# ---- Percussion ---------------------------------------------------------------------------
def heartbeat(n: int, vel=58):
    """The walk: a soft low hit on one and three (the open hand, key 60, is near silent)."""
    frame.note(T(n), 0.5, FR_LOW_HIT, vel)
    frame.note(T(n) + 2, 0.5, FR_LOW_MUTE, vel - 6)


def walking(n: int, vel=70):
    frame.note(T(n), 0.5, FR_LOW_HIT, vel)
    frame.note(T(n) + 1, 0.3, FR_SMALL_MUTE, vel - 26)
    frame.note(T(n) + 2, 0.5, FR_LOW_MUTE, vel - 8)
    frame.note(T(n) + 3.5, 0.3, FR_SMALL_MUTE, vel - 30)


def stomp(n: int, vel=92):
    """The mammoth: two heavy steps and a light pickup."""
    frame.note(T(n), 0.8, FR_LOW_HIT, vel)
    frame.note(T(n) + 2, 0.8, FR_LOW_HIT, vel - 8)
    slit.note(T(n), 0.8, SLIT_LO, vel - 14)
    slit.note(T(n) + 3.5, 0.4, SLIT_HI, vel - 30)


def teponaztli(n: int, vel=80, full=True):
    """The two-tone slit drum dance: high, low low, high low (and a pickup in full bars)."""
    t = T(n)
    slit.note(t, 0.4, SLIT_HI, vel)
    if full:
        slit.note(t + 1, 0.4, SLIT_LO, vel - 10)
    slit.note(t + 1.5, 0.4, SLIT_LO, vel - 18)
    slit.note(t + 2.5, 0.4, SLIT_HI, vel - 6)
    slit.note(t + 3, 0.4, SLIT_LO, vel - 12)
    if full and n % 4 == 0:
        slit.note(t + 3.5, 0.3, SLIT_HI, vel - 20)


def rattle(n: int, vel=56):
    """Eighth notes on the shaker, low shakes, down on the beat and up off it."""
    for i in range(8):
        shaker.note(T(n) + 0.5 * i, 0.45, SH_LOW_DOWN if i % 2 == 0 else SH_LOW_UP, vel + (8 if i % 4 == 0 else 0))


# ---- Melodies (beat in bar, duration, note) -------------------------------------------------
CALL = [  # ice_wind 5-8: the ocarina calls from far off
    [(1.0, 2.0, "E5"), (3.0, 1.0, "A5")],
    [(0.0, 2.0, "G5"), (2.0, 1.5, "D5")],
    [(0.0, 3.0, "E5")],
    [],
]
CROSSING = [  # over Am G Em Am | F G Am Am
    [(0.0, 3.0, "E5"), (3.0, 1.0, "D5")],
    [(0.0, 1.0, "E5"), (1.0, 1.0, "G5"), (2.0, 2.0, "A5")],
    [(0.0, 1.5, "G5"), (1.5, 0.5, "E5"), (2.0, 2.0, "D5")],
    [(0.0, 3.5, "E5")],
    [(0.0, 2.0, "C5"), (2.0, 1.0, "D5"), (3.0, 1.0, "E5")],
    [(0.0, 3.0, "B4"), (3.0, 1.0, "D5")],
    [(0.0, 1.0, "C5"), (1.0, 1.0, "B4"), (2.0, 2.0, "A4")],
    [(0.0, 3.0, "A4")],
]
STERN = [  # mammoth, over Dm Am Dm E | Dm Am F E
    [(0.0, 1.5, "A4"), (1.5, 0.5, "C5"), (2.0, 2.0, "D5")],
    [(0.0, 1.0, "E5"), (1.0, 1.0, "C5"), (2.0, 2.0, "A4")],
    [(0.0, 1.5, "A4"), (1.5, 0.5, "C5"), (2.0, 1.0, "D5"), (3.0, 1.0, "F5")],
    [(0.0, 3.5, "E5")],
    [(0.0, 1.0, "F5"), (1.0, 1.0, "E5"), (2.0, 2.0, "D5")],
    [(0.0, 1.0, "C5"), (1.0, 1.0, "E5"), (2.0, 2.0, "A5")],
    [(0.0, 1.5, "G5"), (1.5, 0.5, "F5"), (2.0, 2.0, "C5")],
    [(0.0, 3.0, "B4")],
]
FLICKER = [  # thaw 25-28, the small ocarina over C G D Asus4
    [(1.0, 1.0, "E6"), (2.0, 2.0, "G6")],
    [(0.0, 3.0, "D6")],
    [(0.0, 1.0, "F#6"), (1.0, 1.0, "E6"), (2.0, 2.0, "D6")],
    [(0.0, 3.0, "E6")],
]
THAW_TAIL = [  # thaw 29-32, over F C G A: the crossing theme's tail, ending on the major third
    [(0.0, 2.0, "C5"), (2.0, 1.0, "D5"), (3.0, 1.0, "E5")],
    [(0.0, 3.0, "G5"), (3.0, 1.0, "E5")],
    [(0.0, 1.0, "D5"), (1.0, 1.0, "B4"), (2.0, 2.0, "D5")],
    [(0.0, 3.5, "C#5")],
]
MAIZE = [  # over A G D A | F#m G E A
    [(0.0, 0.5, "A4"), (0.5, 0.5, "C#5"), (1.0, 1.0, "E5"), (2.0, 0.5, "F#5"), (2.5, 0.5, "E5"), (3.0, 1.0, "C#5")],
    [(0.0, 0.5, "B4"), (0.5, 0.5, "D5"), (1.0, 1.5, "G5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "D5")],
    [(0.0, 0.5, "F#5"), (0.5, 0.5, "E5"), (1.0, 0.5, "D5"), (1.5, 0.5, "E5"), (2.0, 1.0, "F#5"), (3.0, 1.0, "A5")],
    [(0.0, 3.0, "E5")],
    [(0.0, 0.5, "A4"), (0.5, 0.5, "C#5"), (1.0, 0.5, "E5"), (1.5, 0.5, "F#5"), (2.0, 1.0, "A5"), (3.0, 1.0, "F#5")],
    [(0.0, 0.5, "G5"), (0.5, 0.5, "F#5"), (1.0, 1.0, "D5"), (2.0, 0.5, "E5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "G5")],
    [(0.0, 1.5, "B5"), (1.5, 0.5, "A5"), (2.0, 1.0, "G#5"), (3.0, 1.0, "B5")],
    [(0.0, 3.0, "A5")],
]
SEED = [  # teosinte, the small ocarina over D A E F#m | D A G E: two notes grow into a phrase
    [(0.0, 1.0, "A5"), (1.0, 2.5, "D6")],
    [(0.0, 1.0, "A5"), (1.0, 1.0, "B5"), (2.0, 1.5, "E6")],
    [(0.0, 1.0, "B5"), (1.0, 0.5, "C#6"), (1.5, 0.5, "D6"), (2.0, 1.5, "E6")],
    [(0.0, 1.0, "A5"), (1.0, 0.5, "B5"), (1.5, 0.5, "C#6"), (2.0, 1.0, "E6"), (3.0, 1.0, "F#6")],
    [(0.0, 3.0, "F#6"), (3.0, 1.0, "E6")],
    [(0.0, 1.0, "C#6"), (1.0, 1.0, "E6"), (2.0, 2.0, "A6")],
    [(0.0, 1.5, "G6"), (1.5, 0.5, "F#6"), (2.0, 1.0, "D6"), (3.0, 1.0, "B5")],
    [(0.0, 3.0, "B5")],
]
HARVEST = [  # the crossing theme in A major, an octave up, over A G D A | F#m E A A
    [(0.0, 3.0, "E6"), (3.0, 1.0, "D6")],
    [(0.0, 1.0, "E6"), (1.0, 1.0, "G6"), (2.0, 2.0, "A6")],
    [(0.0, 1.5, "G6"), (1.5, 0.5, "E6"), (2.0, 2.0, "D6")],
    [(0.0, 3.5, "E6")],
    [(0.0, 2.0, "C#6"), (2.0, 1.0, "D6"), (3.0, 1.0, "E6")],
    [(0.0, 3.0, "B5"), (3.0, 1.0, "D6")],
    [(0.0, 1.0, "C#6"), (1.0, 1.0, "B5"), (2.0, 2.0, "A5")],
    [(0.0, 3.0, "A5")],
]
COUNTER = [  # harvest: the ocarina holds a slow line under the small ocarina
    [(0.0, 3.0, "C#5"), (3.0, 1.0, "E5")],
    [(0.0, 4.0, "B4")],
    [(0.0, 2.0, "A4"), (2.0, 2.0, "F#5")],
    [(0.0, 2.0, "E5"), (2.0, 2.0, "C#5")],
    [(0.0, 4.0, "F#5")],
    [(0.0, 2.0, "E5"), (2.0, 2.0, "B4")],
    [(0.0, 2.0, "E5"), (2.0, 2.0, "C#5")],
    [(0.0, 3.0, "A4")],
]
MEMORY = [  # return, over F G Am Am | F G Esus4 E: the maize figure in minor, slow
    [(0.0, 1.0, "A4"), (1.0, 1.0, "C5"), (2.0, 1.0, "E5"), (3.0, 1.0, "F5")],
    [(0.0, 3.0, "D5")],
    [(0.0, 1.0, "E5"), (1.0, 1.0, "C5"), (2.0, 2.0, "A4")],
    [],
    [(1.0, 3.0, "C5")],
    [(0.0, 2.0, "D5"), (2.0, 2.0, "B4")],
    [(0.0, 3.0, "A4")],
    [],
]

# ---- ice_wind, 1-8 --------------------------------------------------------------------------
ICE = ["Am", "Am", "Am", "Am", "Am", "G", "Em", "Am"]
for k, chord in enumerate(ICE):
    n = 1 + k
    low_bed(n, chord, 54 + 2 * k, 46 + 2 * k)
    if n >= 5:
        heartbeat(n, 50 + 2 * (n - 5))
hum(3, "Am", 48, bars=2)
for n in range(5, 9):
    hum(n, ICE[n - 1], 54)
wind.note(T(1), 15.5, WIND_1, 70)
wind.note(T(5), 15.5, WIND_3, 62)
chimes.note(T(1) + 1, 7.0, CH_RANDOM, 58)
chimes.note(T(5), 5.0, CH_SLOW_DESC, 52)
glasses.note(T(2), 7.5, "A5", 48)
glasses.note(T(4), 3.5, "E5", 44)
glasses.note(T(6), 3.8, "D5", 44)
glasses.note(T(7), 3.8, "E5", 46)
sing(ocarina, 5, CALL, vel=78)

# ---- crossing, 9-16 -------------------------------------------------------------------------
CROSS_CH = ["Am", "G", "Em", "Am", "F", "G", "Am", "Am"]
for k, chord in enumerate(CROSS_CH):
    n = 9 + k
    low_bed(n, chord, 66, 58)
    walking(n, 70)
    if k >= 4:
        hum(n, chord, 52)
    if k % 2 == 1:
        shaker.note(T(n) + 3, 0.8, SH_DOUBLE_DOWN, 46)
sing(ocarina, 9, CROSSING, vel=94)
glasses.note(T(9), 7.5, "E5", 42)
glasses.note(T(13), 3.8, "A5", 42)
chimes.note(T(12) + 2, 4.0, CH_SLOW_ASC, 46)

# ---- mammoth, 17-24 -------------------------------------------------------------------------
MAMMOTH_CH = ["Dm", "Am", "Dm", "E", "Dm", "Am", "F", "E"]
for k, chord in enumerate(MAMMOTH_CH):
    n = 17 + k
    harmony[n] = chord
    root, fifth, _ = CHORD[chord]
    for at, v in ((0, 84), (2, 76)):  # two heavy steps a bar
        basses.note(T(n) + at, 1.7, [midi(root), midi(root) + 12], v)
        celli.note(T(n) + at, 1.7, fifth, v - 6)
    stomp(n, 92 if k % 4 == 0 else 86)
    hum(n, chord, 60)
for n in (20, 24):  # the sabre-tooth cat hisses, once in each half
    shaker.note(T(n) + 3.0, 0.9, SH_HIGH_UP, 38)
sing(ocarina, 17, STERN, vel=96)

# ---- thaw, 25-32 --------------------------------------------------------------------------
THAW_CH = ["C", "G", "D", "Asus4", "F", "C", "G", "A"]
GLASS = {"C": ["E5", "G5"], "G": ["D5", "G5"], "D": ["D5", "A5"], "Asus4": ["D5", "A5"], "F": ["F5", "A5"],
         "A": ["E5", "A5"]}
for k, chord in enumerate(THAW_CH):
    n = 25 + k
    low_bed(n, chord, 60, 54, warm=True)
    heartbeat(n, 54)
    if k < 4:
        glasses.note(T(n), 3.8, GLASS[chord], 46)
    else:
        hum(n, chord, 50)
    if k >= 4:
        rattle(n, 40 + 3 * (k - 4))
chimes.note(T(25), 5.0, CH_SLOW_ASC, 50)
chimes.note(T(29) + 2, 4.0, CH_DESC, 44)
sing(ocarina_small, 25, FLICKER, vel=80)
sing(ocarina, 29, THAW_TAIL, vel=90)

# ---- first_maize, 33-40 ---------------------------------------------------------------------
MAIZE_CH = ["A", "G", "D", "A", "F#m", "G", "E", "A"]
for k, chord in enumerate(MAIZE_CH):
    n = 33 + k
    harmony[n] = chord
    root, fifth, _ = CHORD[chord]
    basses.note(T(n), 1.9, root, 74)
    basses.note(T(n) + 2, 1.9, midi(root) + 7, 66)
    celli.note(T(n), 3.92, fifth + [THIRD[chord]], 58)
    teponaztli(n, 82)
    rattle(n, 56)
    frame.note(T(n), 0.5, FR_LOW_HIT, 66)
    frame.note(T(n) + 2, 0.4, FR_SMALL_HIT, 52)
    if k >= 4:
        hum(n, chord, 52)
sing(ocarina, 33, MAIZE, vel=96)

# ---- teosinte, 41-48 ------------------------------------------------------------------------
TEO_CH = ["D", "A", "E", "F#m", "D", "A", "G", "E"]
SWELL = {"D": ["A4", "D5", "F#5"], "A": ["A4", "C#5", "E5"], "E": ["G#4", "B4", "E5"], "F#m": ["A4", "C#5", "F#5"],
         "G": ["G4", "B4", "D5"]}
for k, chord in enumerate(TEO_CH):
    n = 41 + k
    harmony[n] = chord
    root, fifth, _ = CHORD[chord]
    basses.note(T(n), 3.92, root, 66)
    celli.note(T(n), 3.92, fifth, 54)
    choir_f.note(T(n), 3.9, SWELL[chord], 54 + (6 if k in (3, 5) else 0))
    teponaztli(n, 70, full=False)
    rattle(n, 48)
    frame.note(T(n), 0.5, FR_LOW_MUTE, 58)
sing(ocarina_small, 41, SEED, vel=86)
chimes.note(T(48) + 1, 3.0, CH_FAST_ASC, 44)

# ---- harvest, 49-56 -------------------------------------------------------------------------
HARV_CH = ["A", "G", "D", "A", "F#m", "E", "A", "A"]
for k, chord in enumerate(HARV_CH):
    n = 49 + k
    harmony[n] = chord
    root, fifth, _ = CHORD[chord]
    basses.note(T(n), 1.9, root, 78)
    basses.note(T(n) + 2, 1.9, midi(root) + 7, 70)
    celli.note(T(n), 3.92, fifth + [THIRD[chord]], 62)
    hum(n, chord, 58)
    teponaztli(n, 86)
    rattle(n, 60)
    frame.note(T(n), 0.5, FR_LOW_HIT, 74)
    frame.note(T(n) + 2, 0.4, FR_SMALL_HIT, 58)
    frame.note(T(n) + 3, 0.3, FR_SMALL_MUTE, 46)
sing(ocarina_small, 49, HARVEST, vel=92)
sing(ocarina, 49, COUNTER, vel=76)

# ---- return, 57-64 --------------------------------------------------------------------------
RET_CH = ["F", "G", "Am", "Am", "F", "G", "Esus4", "E"]
for k, chord in enumerate(RET_CH):
    n = 57 + k
    if n == 64:  # the last bar stops on beat 3, so nothing rings across the loop seam
        low_bed(n, chord, 50, 44, warm=True, dur=2.6)
        choir_m.note(T(n), 2.6, CHORD[chord][2], 44)
    else:
        low_bed(n, chord, 60 - k, 52 - k, warm=chord in ("E",))
        hum(n, chord, 50 - k)
    if n <= 62:
        heartbeat(n, 56 - 2 * k)
for n in (57, 58):
    rattle(n, 44 - 6 * (n - 57))
slit.note(T(57), 0.4, SLIT_HI, 64)
slit.note(T(59), 0.4, SLIT_LO, 58)
wind.note(T(59), 8.0, WIND_2, 58)
chimes.note(T(61), 4.0, CH_SLOW_DESC, 46)
glasses.note(T(57), 3.8, ["A5", "C6"], 42)
glasses.note(T(59), 7.5, "E5", 40)
sing(ocarina, 57, MEMORY, vel=82)

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
    ("ice_wind", 1, "Ice wind: wind, glasses and a far call", 0.3, 0.3),
    ("crossing", 9, "Crossing: the theme into the wind", 0.5, 0.5),
    ("mammoth", 17, "Mammoth: heavy steps, a stern variant", 0.65, 0.6),
    ("thaw", 25, "Thaw: the ice melts toward A major", 0.45, 0.45),
    ("first_maize", 33, "First Maize: the maize dance", 0.7, 0.7),
    ("teosinte", 41, "Teosinte: a seed grows into a phrase", 0.6, 0.6),
    ("harvest", 49, "Harvest: the crossing theme in A major", 0.8, 0.8),
    ("return", 57, "Return: the wind again, back to A minor", 0.35, 0.35),
]
form_lines = []
for i, (fid, start, label, energy, density) in enumerate(FORM):
    end = FORM[i + 1][1] if i + 1 < len(FORM) else END_BAR
    form_lines.append(f"  - {{id: {fid}, label: '{label}', from: {{bar: {start}, beat: 1}}, to: {{bar: {end}, beat: 1}}, "
                      f"energy: {energy}, density: {density}, role: loop_component, loopable: true}}")
form_text = "\n".join(form_lines)

score = f"""schema: ambition.musicir.v3
id: history_americas_land_bridge
title: Over the Land Bridge
description: >-
  The Americas floor of the History dimension, from Beringia (the land
  bridge from Asia, 20,000 years ago) to First Maize in Mesoamerica. A minor
  turning to A major at 88 BPM. A clay ocarina has the tune: a crossing
  theme of long notes that climb into the wind, then a maize dance figure
  that grows each time it returns. Wine glasses, mark trees and an ocean
  drum are the ice and wind; low strings and a low choir are the cold; a
  two-tone slit drum (in the role of the teponaztli), a frame drum and a
  shaker keep the walk and the dance. Generated by
  dev/compose_history_americas_land_bridge.py: edit that, not this file.
notes:
  - 'Jon, 2026-11-03: "I also think we will want new music for different locations in the history dimension." One cue for each region floor; this one plays on every room of the Americas floor.'
  - 'The file loops as a whole: bar 65 is bar 1. The last bar (E major) stops on beat 3 and leads to A minor.'
  - 'All melodies are original. The VCSL instruments are explicit sfz_glob programs because they are not in the instrument catalog; the percussion, chimes and ocean drum are trigger keys, so they are is_drum.'
seed: 20000
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: A minor
end: {{bar: {END_BAR}, beat: 1}}
form:
{form_text}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: ocarina, group: ocarina, program: ocarina, volume: 110, pan: 60, expression: 112, {vcsl("Aerophones/Edge-blown Aerophones/Ocarina, Typical - Sus")}}}
  - {{name: ocarina_small, group: ocarina_small, program: ocarina, volume: 104, pan: 72, expression: 108, {vcsl("Aerophones/Edge-blown Aerophones/Ocarina, Small - Sustain")}}}
  - {{name: glasses, group: ice, program: pad_choir, volume: 96, pan: 84, expression: 100, {vcsl("Idiophones/Friction Idiophones/Wine Glasses - Slow")}}}
  - {{name: chimes, group: ice, volume: 96, pan: 40, expression: 100, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Mark Trees")}}}
  - {{name: wind, group: wind, volume: 96, pan: 64, expression: 100, is_drum: true, {vcsl("Membranophones/Other Membranophones/Ocean Drum")}}}
  - {{name: celli, group: strings, program: cello, volume: 100, pan: 56, expression: 104, {sfz("strings.celli")}}}
  - {{name: basses, group: strings, program: contrabass, volume: 100, pan: 68, expression: 104, {sfz("strings.basses")}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 96, pan: 60, expression: 100, {sfz("vpo.choir_male")}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 96, pan: 70, expression: 100, {sfz("vpo.choir")}}}
  - {{name: slit, group: slit, volume: 100, pan: 52, expression: 104, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Slit Drum")}}}
  - {{name: frame, group: frame, volume: 100, pan: 64, expression: 104, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
  - {{name: shaker, group: shaker, volume: 100, pan: 80, expression: 104, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Shaker, Small")}}}
parts:
{part("ocarina_part", "ocarina", ocarina)}
{part("ocarina_small_part", "ocarina_small", ocarina_small)}
{part("glasses_part", "glasses", glasses)}
{part("chimes_part", "chimes", chimes)}
{part("wind_part", "wind", wind)}
{part("celli_part", "celli", celli)}
{part("basses_part", "basses", basses)}
{part("choir_m_part", "choir_m", choir_m)}
{part("choir_f_part", "choir_f", choir_f)}
{part("slit_part", "slit", slit)}
{part("frame_part", "frame", frame)}
{part("shaker_part", "shaker", shaker)}
processing:
  groups:
    ocarina:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 12.0, release_ms: 120.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 3.0}}
    ocarina_small:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 10000}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 1.0}}
    ice:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: reverb, wet: 0.35, decay_seconds: 3.2}}
        - {{processor: gain, gain_db: 7.0}}
    wind:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 7.0}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -3.0}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: -2.0}}
    slit:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 7.0}}
    frame:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: compressor, threshold_db: -18.0, ratio: 2.0, attack_ms: 15.0, release_ms: 90.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 1.0}}
    shaker:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: lowpass, cutoff_hz: 12000}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 11.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  # Exploring plays everything; the tune layer can drop out under dialogue.
  layers:
    bed: [strings, choir, wind, ice]
    drums: [slit, frame, shaker]
    tune: [ocarina, ocarina_small]
  sections:
    - {{id: song, form: [{", ".join(f[0] for f in FORM)}], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

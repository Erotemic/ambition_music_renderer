"""Between the Rivers: the History dimension's floor of the Mediterranean and
the Fertile Crescent. Writes its MusicIR v3 score:

    python3 dev/compose_history_crescent_between_the_rivers.py scores/active/history_crescent_between_the_rivers.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different locations
in the history dimension." Each region floor of the History grid gets its own
cue. This floor runs west to east, oldest to newest: the Levant (the first step
out of Africa), the Fertile Crescent (the first farmers, wheat and barley, the
first villages), Uruk (the first cities and the first writing; Enheduanna, the
first named author) and the Classical Shore (Greece and Rome on the sea). One
cue plays across all of these rooms, so it must suit the whole span and loop
for a long time. It is exploration music: mid energy, under dialogue.

D Dorian at 84 BPM, 4/4. The sound is people inventing cities, counting grain
and writing it down:
  - THE LYRE (the voice of the floor, the Lyre of Ur): a plucked folk harp. It
    opens alone over a drone and it is present in every section.
  - THE REED (the aulos role): a solo oboe that has the field song and the
    city hymn.
  - THE DRONE: basses and celli on open fifths; a bowed psaltery shimmers high.
  - THE HANDS: frame drum, darbuka, finger cymbals; a tambourine on the shore.
  - THE TEMPLE: a male choir, used lightly, for the hymn in Uruk.
Melodies (all original):
  - THE LYRE CALL: a free solo line; one Phrygian E flat turns it home.
  - THE FIELD SONG (theme A): falls from D5, climbs through the Dorian B, and
    comes home on D. The second time the lyre has it an octave up and its
    half cadence goes to A major (the Hijaz colour, F against C sharp).
  - THE COUNT: the lyre counts grain on the Hijaz tetrachord of A (A Bb C# D):
    one; one two; one two three... and the psaltery writes each count down.
  - THE CITY HYMN (theme B): square, one chord a bar, Dm F C G | Dm Bb C A.
  - THE SHORE: the field song a fourth up in G Dorian, then a new broad tune
    that walks back down to A, the dominant of bar 1's D.

Form, 4/4 at 84 BPM, 72 bars (about 3:26), the whole cue loops (bar 72 thins
to the drone and the lyre's last notes; bar 1 is the lone lyre and drone):
  levant    1-8    the lyre call alone over a D drone
  fields    9-24   the field song: oboe, then lyre up an octave; frame drum, darbuka
  counting  25-32  the count on A Hijaz; darbuka answers, the oboe's Hijaz phrase
  uruk      33-48  the city hymn: strings, procession drums; choir sings it at 41
  shore     49-64  the field song in G Dorian, tallest; the shore tune back to A
  return    65-72  lyre and drone again, the oboe answers, thinning to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 84
OUT = Path(sys.argv[1])
rng = random.Random(3200)  # about when Uruk began to write

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name) -> int:
    if isinstance(name, int):
        return name
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.drift = drift
        self.vel_jitter = vel_jitter
        #: (cc, [(bar, value), ...]) step curves, for a patch whose dynamics follow a controller
        self.controllers: list[tuple[int, list[tuple[int, int]]]] = []

    def note(self, at, dur, pitches, vel):
        at = F(at).limit_denominator(960)
        if self.drift and at > 0:
            at += F(rng.uniform(-self.drift, self.drift)).limit_denominator(960)
        at = max(F(0), at)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if not isinstance(pitches, (list, tuple)):
            pitches = [pitches]
        self.events.append((at, F(dur).limit_denominator(960), [midi(p) for p in pitches], vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}"]
        if self.controllers:
            lines.append(f"{indent}  automation:")
            for cc, points in self.controllers:
                pts = ", ".join(f"[{{beats: {T(bar):g}}}, {value}]" for bar, value in points)
                lines.append(f"{indent}    - {{id: {clip_id}_cc{cc}, cc: {cc}, interpolation: step, resolution: 1/4, points: [{pts}]}}")
        lines.append(f"{indent}  events:")
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


def T(n: int) -> float:
    """The first beat of bar n, in beats."""
    return (n - 1) * 4.0


lyre = Clip(0.006, 4)
psaltery = Clip(0.004, 3)  # plucked: the stylus
shimmer = Clip(0.0, 2)  # bowed psaltery, long bow
oboe = Clip(0.005, 3)
violins = Clip(0.006, 3)
violas = Clip(0.006, 3)
celli = Clip(0.006, 3)
basses = Clip(0.004, 2)
choir = Clip(0.008, 2)
frame = Clip(0.008, 4)
darbuka = Clip(0.008, 4)
zils = Clip(0.004, 3)  # finger cymbals
tamb = Clip(0.008, 4)
ocean = Clip()
harmony: dict[int, str] = {}

# ---- Harmony ---------------------------------------------------------------------------
#: root pitch class and the semitones of the third and fifth over it
CHORD = {
    "Dm": ("D", 3, 7), "C": ("C", 4, 7), "Am": ("A", 3, 7), "A": ("A", 4, 7), "F": ("F", 4, 7),
    "G": ("G", 4, 7), "Gm": ("G", 3, 7), "Bb": ("Bb", 4, 7),
}


def root_in(chord: str, low: int) -> int:
    """The chord's root in the octave that starts at `low`."""
    pc = NOTE[CHORD[chord][0]]
    return low + (pc - low) % 12


def third(chord: str) -> int:
    return CHORD[chord][1]


# ---- Tunes: (beat, duration, note), one list per bar ------------------------------------
LYRE_CALL = [
    [(0.0, 1.0, "D4"), (1.0, 0.5, "A4"), (1.5, 0.5, "G4"), (2.0, 2.0, "A4")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "B4"), (1.0, 1.0, "A4"), (2.0, 1.0, "G4"), (3.0, 1.0, "E4")],
    [(0.0, 1.5, "F4"), (1.5, 0.5, "G4"), (2.0, 0.5, "A4"), (2.5, 0.5, "G4"), (3.0, 1.0, "F4")],
    [(0.0, 1.0, "E4"), (1.0, 1.0, "D4"), (2.0, 2.0, "A3")],
    [(0.0, 1.0, "D4"), (1.0, 0.5, "F4"), (1.5, 0.5, "A4"), (2.0, 1.0, "D5"), (3.0, 0.5, "C5"), (3.5, 0.5, "A4")],
    [(0.0, 2.0, "B4"), (2.0, 0.5, "A4"), (2.5, 0.5, "G4"), (3.0, 1.0, "A4")],
    [(0.0, 0.5, "G4"), (0.5, 0.5, "F4"), (1.0, 0.5, "Eb4"), (1.5, 0.5, "F4"), (2.0, 2.0, "D4")],
    [(0.0, 1.0, "A3"), (1.0, 1.0, "D4"), (2.0, 1.0, "E4"), (3.0, 1.0, "A4")],
]
#: The field song (theme A), in D Dorian, over FIELD_CH.
FIELD = [
    [(0.0, 1.5, "D5"), (1.5, 0.5, "C5"), (2.0, 1.0, "A4"), (3.0, 1.0, "G4")],
    [(0.0, 0.5, "F4"), (0.5, 0.5, "G4"), (1.0, 2.0, "A4"), (3.0, 1.0, "B4")],
    [(0.0, 1.0, "C5"), (1.0, 0.5, "B4"), (1.5, 0.5, "A4"), (2.0, 2.0, "G4")],
    [(0.0, 1.0, "A4"), (1.0, 1.0, "F4"), (2.0, 2.0, "E4")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "E5"), (2.0, 1.0, "F5"), (3.0, 1.0, "E5")],
    [(0.0, 1.0, "D5"), (1.0, 0.5, "C5"), (1.5, 0.5, "B4"), (2.0, 2.0, "A4")],
    [(0.0, 0.5, "G4"), (0.5, 0.5, "A4"), (1.0, 1.0, "B4"), (2.0, 0.5, "A4"), (2.5, 0.5, "G4"), (3.0, 1.0, "F4")],
    [(0.0, 1.0, "E4"), (1.0, 0.5, "F4"), (1.5, 0.5, "E4"), (2.0, 2.0, "D4")],
]
FIELD_CH = ["Dm", "Dm", "C", "Am", "Dm", "F", "G", "Dm"]
#: The second time the half cadence is A major: F against C sharp, the Hijaz colour.
FIELD_CH_2 = ["Dm", "Dm", "C", "A", "Dm", "F", "G", "Dm"]
#: The oboe's slow counter-line under the lyre's field song (bars 17-24).
FIELD_COUNTER = [
    [(0.0, 2.0, "F4"), (2.0, 2.0, "A4")], [(0.0, 4.0, "D5")], [(0.0, 2.0, "E5"), (2.0, 2.0, "C5")],
    [(0.0, 4.0, "C#5")], [(0.0, 2.0, "A4"), (2.0, 2.0, "D5")], [(0.0, 4.0, "C5")],
    [(0.0, 2.0, "B4"), (2.0, 2.0, "D5")], [(0.0, 2.0, "G4"), (2.0, 1.8, "F4")],
]
#: The oboe's Hijaz phrase over the A pedal (bars 29-32); the last eighth leads to the hymn's F4.
HIJAZ_PHRASE = [
    [(0.0, 2.0, "E5"), (2.0, 0.5, "F5"), (2.5, 0.5, "E5"), (3.0, 1.0, "D5")],
    [(0.0, 1.0, "C#5"), (1.0, 1.0, "Bb4"), (2.0, 2.0, "A4")],
    [(0.0, 0.5, "Bb4"), (0.5, 0.5, "C#5"), (1.0, 1.0, "D5"), (2.0, 1.0, "E5"), (3.0, 1.0, "G5")],
    [(0.0, 1.0, "F5"), (1.0, 1.0, "E5"), (2.0, 0.5, "D5"), (2.5, 0.5, "C#5"), (3.0, 0.5, "A4"), (3.5, 0.5, "E4")],
]
#: The city hymn (theme B): square, one chord a bar.
HYMN = [
    [(0.0, 2.0, "F4"), (2.0, 1.0, "A4"), (3.0, 1.0, "D5")],
    [(0.0, 2.0, "C5"), (2.0, 2.0, "A4")],
    [(0.0, 1.0, "G4"), (1.0, 1.0, "C5"), (2.0, 1.0, "E5"), (3.0, 1.0, "D5")],
    [(0.0, 3.0, "D5"), (3.0, 1.0, "B4")],
    [(0.0, 2.0, "A4"), (2.0, 1.0, "D5"), (3.0, 1.0, "F5")],
    [(0.0, 2.0, "F5"), (2.0, 1.0, "D5"), (3.0, 1.0, "Bb4")],
    [(0.0, 1.0, "C5"), (1.0, 1.0, "E5"), (2.0, 1.0, "G5"), (3.0, 1.0, "E5")],
    [(0.0, 1.0, "E5"), (1.0, 1.0, "C#5"), (2.0, 2.0, "A4")],
]
HYMN_CH = ["Dm", "F", "C", "G", "Dm", "Bb", "C", "A"]
#: The shore tune (bars 57-64): broad steps that walk back to A.
SHORE = [
    [(0.0, 1.0, "F5"), (1.0, 1.0, "D5"), (2.0, 1.5, "Bb4"), (3.5, 0.5, "C5")],
    [(0.0, 1.0, "E5"), (1.0, 1.0, "C5"), (2.0, 1.5, "G4"), (3.5, 0.5, "A4")],
    [(0.0, 1.0, "D5"), (1.0, 1.0, "F5"), (2.0, 1.0, "A5"), (3.0, 1.0, "G5")],
    [(0.0, 2.0, "G5"), (2.0, 1.0, "D5"), (3.0, 1.0, "B4")],
    [(0.0, 1.0, "Bb4"), (1.0, 1.0, "D5"), (2.0, 1.5, "G5"), (3.5, 0.5, "F5")],
    [(0.0, 1.0, "E5"), (1.0, 1.0, "G5"), (2.0, 2.0, "C5")],
    [(0.0, 1.0, "D5"), (1.0, 1.0, "C5"), (2.0, 1.0, "Bb4"), (3.0, 1.0, "A4")],
    [(0.0, 2.0, "E5"), (2.0, 2.0, "C#5")],
]
SHORE_CH = ["Bb", "C", "Dm", "G", "Gm", "C", "Bb", "A"]


def sing(clip: Clip, n0: int, phrase, vel=90, shift=0, legato=0.95):
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            held = dur >= 1.0
            clip.note(T(n0 + k) + at, dur * (legato if held else 0.9), midi(name) + shift, vel + (5 if held else 0))


def pluck(clip: Clip, n0: int, phrase, vel=84, shift=0):
    """A plucked line: the string rings, so the written length is only the damping point."""
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            clip.note(T(n0 + k) + at, max(dur, 0.5), midi(name) + shift, vel + (4 if at == 0 else 0))


# ---- Beds ------------------------------------------------------------------------------
def lyre_eighths(n: int, chord: str, vel: int):
    """Eighths in 3+3+2: an open fifth on each group's first eighth, the octave and tenth between."""
    r = root_in(chord, 45)
    fifth, octave, tenth = r + 7, r + 12, r + 12 + third(chord)
    for i, p in enumerate([[r, fifth], octave, tenth, [r, fifth], octave, tenth, [r, fifth], octave]):
        lyre.note(T(n) + 0.5 * i, 0.5, p, vel + (8 if i in (0, 3, 6) else 0))


def lyre_quarters(n: int, chord: str, vel: int):
    """Quarters, low: the fifth on the beat, then octave, fifth, tenth. The ordered city pulse."""
    r = root_in(chord, 43)
    for i, p in enumerate([[r, r + 7], r + 12, r + 7, r + 12 + third(chord)]):
        lyre.note(T(n) + i, 1.0, p, vel + (6 if i == 0 else 0))


def lyre_hijaz(n: int, vel: int):
    """An A major arpeggio with the B flat neighbour: the Hijaz colour under the oboe."""
    for i, p in enumerate(["A2", "E3", "A3", "C#4", "Bb3", "A3", "E3", "C#4"]):
        lyre.note(T(n) + 0.5 * i, 0.5, p, vel + (8 if i == 0 else 0))


def strings_bar(n: int, chord: str, vel: int, bars: int = 1, violins_on: bool = False, violas_on: bool = True):
    r = root_in(chord, 36)
    dur = 4.0 * bars - 0.1
    basses.note(T(n), dur, r, vel - 4)
    celli.note(T(n), dur, r + 7 if r + 7 < 50 else r - 5, vel)
    v = root_in(chord, 55)
    if violas_on:
        violas.note(T(n), dur, [v, v + third(chord)], vel - 6)
    if violins_on:
        top = root_in(chord, 67)
        violins.note(T(n), dur, [top + third(chord), top + 7], vel - 8)


def drone(n: int, bars: int, low: str, fifth: str | None, vel: int, end_early: float = 0.1):
    basses.note(T(n), 4.0 * bars - end_early, midi(low), vel)
    if fifth:
        celli.note(T(n), 4.0 * bars - end_early, midi(fifth), vel - 4)


def choir_chord(n: int, chord: str, vel: int):
    r = root_in(chord, 45)
    choir.note(T(n) + 0.05, 3.8, [r, r + 7], vel)


# Percussion keys (VCSL): frame drum 61 large open, 62 large muted, 64 small open, 65 small muted;
# darbuka 60 doum (low), 61 tek, 62 ka; tambourine 60 hit, 61 roll, 62 shake.
# Every VCSL drum here switches to a soft layer (about 20 dB quieter) under velocity 84.
F_LOW, F_LOW_M, F_HI, F_HI_M = 61, 62, 64, 65
DOUM, TEK, KA = 60, 61, 62


def frame_bar(n: int, style: str):
    t = T(n)
    if style == "fields":
        frame.note(t, 0.5, F_LOW, 100)
        frame.note(t + 1.5, 0.4, F_HI, 92)
        frame.note(t + 3.0, 0.4, F_LOW_M, 94)
    elif style == "count":
        frame.note(t, 0.6, F_LOW, 96)
    elif style == "procession":
        frame.note(t, 0.5, F_LOW, 104)
        frame.note(t + 1.0, 0.3, F_HI_M, 90)
        frame.note(t + 2.0, 0.5, F_LOW, 96)
        frame.note(t + 3.0, 0.3, F_HI_M, 90)
    elif style == "shore":
        frame.note(t, 0.5, F_LOW, 106)
        frame.note(t + 1.5, 0.3, F_LOW_M, 88)
        frame.note(t + 2.0, 0.5, F_HI, 98)
        frame.note(t + 3.5, 0.3, F_LOW_M, 88)


def darbuka_bar(n: int, style: str, fill: bool = False):
    t = T(n)
    if style == "fields":
        for at, key, v in ((0, DOUM, 98), (1.5, TEK, 92), (2.5, DOUM, 90), (3.0, TEK, 94), (3.5, KA, 86)):
            darbuka.note(t + at, 0.25, key, v)
    elif style == "procession":
        darbuka.note(t, 0.25, DOUM, 100)
        darbuka.note(t + 2.0, 0.25, DOUM, 92)
        for at in (0.5, 1.5, 2.5, 3.5):
            darbuka.note(t + at, 0.2, TEK, 86)
    elif style == "shore":
        for at, key, v in ((0, DOUM, 102), (1.0, TEK, 92), (1.5, KA, 86), (2.0, DOUM, 96), (3.0, TEK, 94),
                           (3.5, KA, 88)):
            darbuka.note(t + at, 0.25, key, v)
    if fill:
        for i in range(8):
            darbuka.note(t + 2.0 + 0.25 * i, 0.15, TEK if i % 2 == 0 else KA, 86 + i * 2)


# ---- levant, 1-8: the lyre call alone over a D drone ---------------------------------------
for n in range(1, 9):
    harmony[n] = "Dm"
pluck(lyre, 1, LYRE_CALL, vel=82)
for n in (1, 3, 5):
    lyre.note(T(n), 1.0, ["D3", "A3"], 74)
lyre.note(T(7), 1.0, ["G2", "D3"], 70)
drone(1, 2, "D2", None, 66)
for n in (3, 5, 7):
    drone(n, 2, "D2", "A2", 68)


# ---- fields, 9-24: the field song ----------------------------------------------------------
for k, chord in enumerate(FIELD_CH):
    n = 9 + k
    harmony[n] = chord
    lyre_eighths(n, chord, 56)
    frame_bar(n, "fields")
sing(oboe, 9, FIELD, vel=92)
for n in (9, 11, 13, 15):
    drone(n, 2, "D2", "A2", 70)
for k, chord in enumerate(FIELD_CH_2):
    n = 17 + k
    harmony[n] = chord
    lyre_quarters(n, chord, 66)
    frame_bar(n, "fields")
    darbuka_bar(n, "fields", fill=k == 7)
pluck(lyre, 17, FIELD, vel=88, shift=12)
sing(oboe, 17, FIELD_COUNTER, vel=82)
for n in (17, 19, 21, 23):
    drone(n, 2, "D2", "A2", 72)
for n, note in ((17, "D5"), (19, "E5"), (21, "D5"), (23, "A4")):
    shimmer.note(T(n) + 0.1, 7.6, note, 64)
for n in (9, 13, 17, 21):
    zils.note(T(n), 1.0, 60, 90)


# ---- counting, 25-32: the count on A Hijaz -------------------------------------------------
for n in range(25, 33):
    harmony[n] = "A"
#: one; one two; one two three; ... each count is an eighth, the darbuka answers in the gaps.
COUNTS = [
    (25, 0.0, 1), (25, 2.0, 2),
    (26, 0.0, 3), (26, 2.0, 4),
    (27, 0.0, 5),
]
HIJAZ = ["A4", "Bb4", "C#5", "D5", "E5"]
for n, at, count in COUNTS:
    for i in range(count):
        lyre.note(T(n) + at + 0.5 * i, 0.5, HIJAZ[i], 86 + 2 * i)
        # the psaltery writes the same count down an octave up, one beat behind
        psaltery.note(T(n) + at + 1.0 + 0.25 * i, 0.4, midi(HIJAZ[i]) + 12, 78)
# bar 28: the tally read back, down and up again
for i, name in enumerate(["E5", "D5", "C#5", "Bb4", "A4", "Bb4", "C#5", "A4"]):
    lyre.note(T(28) + 0.5 * i, 0.5, name, 88 - (4 if i % 2 else 0))
# the darbuka's answers sit in the gaps of the count
for n, ats in ((25, (1.0, 3.0, 3.5)), (26, (1.5, 3.5)), (27, (2.5, 3.0, 3.5)), (28, ())):
    darbuka.note(T(n), 0.25, DOUM, 96)
    for at in ats:
        darbuka.note(T(n) + at, 0.2, TEK if at % 1 == 0 else KA, 92)
for n in range(25, 33):
    frame_bar(n, "count")
for n in (29, 30, 31, 32):
    lyre_hijaz(n, 58)
    darbuka_bar(n, "fields", fill=n == 32)
sing(oboe, 29, HIJAZ_PHRASE, vel=96)
for n in (25, 27, 29, 31):
    drone(n, 2, "A1", "E2", 70)
shimmer.note(T(25) + 0.1, 7.6, "A4", 62)
shimmer.note(T(27) + 0.1, 7.6, "E5", 60)
zils.note(T(25), 1.0, 60, 92)
zils.note(T(29), 1.0, 60, 88)


# ---- uruk, 33-48: the city hymn --------------------------------------------------------------
for half in (0, 1):
    for k, chord in enumerate(HYMN_CH):
        n = 33 + 8 * half + k
        harmony[n] = chord
        strings_bar(n, chord, 70 + 6 * half)
        frame_bar(n, "procession")
        darbuka_bar(n, "procession", fill=(half == 1 and k == 7))
        if half == 0:
            lyre_quarters(n, chord, 72)
        if half == 1 and k >= 4:
            choir_chord(n, chord, 66)
        if k % 2 == 0:
            zils.note(T(n), 1.0, 60, 86)
sing(oboe, 33, HYMN, vel=96)
# the stylus: three short strokes high on the psaltery at the end of the hymn's even bars
for n, notes in ((34, ("A5", "C6", "F6")), (36, ("B5", "D6", "G6")), (38, ("Bb5", "D6", "F6")),
                 (40, ("E6", "C#6", "A5"))):
    for i, name in enumerate(notes):
        psaltery.note(T(n) + 3.0 + 0.25 * i, 0.4, name, 80 + 3 * i)
# the hymn sung: the male choir has the tune an octave down (41-44), the lyre doubles it
sing(choir, 41, HYMN[:4], vel=80, shift=-12, legato=0.98)
pluck(lyre, 41, HYMN, vel=88)
for k, chord in enumerate(HYMN_CH):  # the lyre keeps the low fifth under its own tune
    lyre.note(T(41 + k), 1.0, [root_in(chord, 43), root_in(chord, 43) + 7], 70)
sing(oboe, 45, HYMN[4:], vel=100)


# ---- shore, 49-64: the field song in G Dorian, then the shore tune ---------------------------
SHORE_FIELD_CH = ["Gm", "Gm", "F", "Dm", "Gm", "Bb", "C", "Gm"]
for k, chord in enumerate(SHORE_FIELD_CH):
    n = 49 + k
    harmony[n] = chord
    strings_bar(n, chord, 78, violas_on=False)
    lyre_eighths(n, chord, 64)
    frame_bar(n, "shore")
    darbuka_bar(n, "shore", fill=k == 7)
    tamb.note(T(n) + 1.0, 0.3, 60, 92)
    tamb.note(T(n) + 3.0, 0.3, 60, 96)
    if k < 3:  # in bar 52 the violins' B flat would rub on the choir's A
        choir_chord(n, chord, 70)
sing(oboe, 49, FIELD, vel=104, shift=5)
pluck(lyre, 49, FIELD, vel=78, shift=5)
# The violins double the tune an octave down and the violas rest: a held pad in the tune's register
# makes seconds against its passing notes.
sing(violins, 49, FIELD, vel=78, shift=5 - 12)
for k, chord in enumerate(SHORE_CH):
    n = 57 + k
    harmony[n] = chord
    strings_bar(n, chord, 80, violins_on=True, violas_on=False)
    lyre_eighths(n, chord, 66)
    frame_bar(n, "shore")
    darbuka_bar(n, "shore", fill=k == 7)
    tamb.note(T(n) + 1.0, 0.3, 60, 92)
    tamb.note(T(n) + 3.0, 0.3, 60, 96)
tamb.note(T(56) + 3.0, 1.0, 61, 90)
tamb.note(T(64) + 2.0, 1.5, 61, 86)
sing(oboe, 57, SHORE, vel=104)
sing(violins, 57, SHORE, vel=80, shift=-12)
ocean.note(T(49), 12.0, 61, 74)
ocean.note(T(57), 12.0, 62, 66)
for n in (49, 53, 57, 61):
    zils.note(T(n), 1.0, 60, 88)


# ---- return, 65-72: lyre and drone, thinning to bar 1 ----------------------------------------
for n in range(65, 73):
    harmony[n] = "Dm"
RETURN_LYRE = {
    65: FIELD[0], 66: FIELD[1],
    67: [(0.0, 1.0, "D4"), (2.0, 1.0, "A3")],
    68: [(0.0, 1.0, "C4"), (2.0, 1.0, "G3")],
    69: LYRE_CALL[4],
    70: [(0.0, 1.0, "C5"), (1.0, 1.0, "A4"), (2.0, 0.5, "G4"), (2.5, 0.5, "F4"), (3.0, 1.0, "E4")],
    71: [(0.0, 0.5, "F4"), (0.5, 0.5, "Eb4"), (1.0, 1.0, "D4"), (2.0, 1.0, "A3")],
}
for n, notes in RETURN_LYRE.items():
    pluck(lyre, n, [notes], vel=80 - (n - 65))
for n in (65, 69):
    lyre.note(T(n), 1.0, ["D3", "A3"], 70)
# the oboe answers twice, softly
sing(oboe, 67, [[(0.0, 2.0, "C5"), (2.0, 2.0, "A4")], [(0.0, 1.0, "G4"), (1.0, 1.0, "F4"), (2.0, 1.8, "E4")]], vel=82)
frame.note(T(65), 0.6, F_LOW, 90)
drone(65, 2, "D2", "A2", 68)
drone(67, 2, "D2", "A2", 64)
drone(69, 2, "D2", "A2", 60)
drone(71, 2, "D2", None, 56, end_early=0.6)
shimmer.note(T(65) + 0.1, 7.6, "D5", 58)

END_BAR = 73
progression = [harmony[n] for n in range(1, END_BAR)]
# The VPO performance oboe's dynamics follow CC1, not velocity. 118 is the top (the VPO violin held a
# note for ever at 122 or more).
oboe.controllers.append((1, [(1, 90), (9, 104), (17, 80), (25, 84), (29, 100), (33, 100), (41, 100), (45, 104),
                             (49, 106), (57, 108), (65, 88)]))


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


PARTS = [("lyre", lyre), ("psaltery", psaltery), ("shimmer", shimmer), ("oboe", oboe), ("violins", violins),
         ("violas", violas), ("celli", celli), ("basses", basses), ("choir", choir), ("frame", frame),
         ("darbuka", darbuka), ("zils", zils), ("tamb", tamb), ("ocean", ocean)]
form_rows = [
    ("levant", 1, 9, 0.25, 0.25, "the lyre call alone over a D drone"),
    ("fields", 9, 25, 0.5, 0.5, "the field song: oboe, then lyre up an octave; frame drum, darbuka"),
    ("counting", 25, 33, 0.55, 0.5, "the count on A Hijaz; the darbuka answers, then the oboe sings a Hijaz phrase"),
    ("uruk", 33, 49, 0.7, 0.7, "the city hymn: strings, procession drums; the choir sings it at bar 41"),
    ("shore", 49, 65, 0.8, 0.8, "the field song in G Dorian, then the shore tune back to A"),
    ("return", 65, END_BAR, 0.3, 0.3, "lyre and drone again, thinning to bar 1"),
]
form_yaml = "\n".join(
    f"  - {{id: {fid}, from: {{bar: {a}, beat: 1}}, to: {{bar: {b}, beat: 1}}, energy: {e}, density: {d}, "
    f"loopable: true, role: '{role}'}}" for fid, a, b, e, d, role in form_rows)
form_ids = ", ".join(r[0] for r in form_rows)

score = f"""schema: ambition.musicir.v3
id: history_crescent_between_the_rivers
title: Between the Rivers
description: >-
  The History dimension's floor of the Mediterranean and the Fertile Crescent
  (the Levant, the Fertile Crescent, Uruk, the Classical Shore). D Dorian at
  84 BPM. A plucked lyre (the Lyre of Ur) opens alone over a drone; an oboe in
  the aulos role sings the field song; the lyre counts grain on the Hijaz
  tetrachord of A while a psaltery writes the count down; the city hymn stands
  square over strings and procession drums, and a male choir sings it once;
  the shore takes the field song up a fourth into G Dorian with tambourine and
  a sea wash, then walks back to A for bar 1. The whole cue loops. Generated by
  dev/compose_history_crescent_between_the_rivers.py: edit that, not this file.
notes:
  - 'Form: levant 1-8, fields 9-24, counting 25-32, uruk 33-48, shore 49-64, return 65-72; bar 72 is the drone alone and hands to the lone lyre at bar 1.'
  - 'Layered for a room: bed (lyre, strings, shimmer), drums (hand drums, sea), tune (oboe, psaltery), power (choir).'
seed: 3200
timebase: {{ppq: 960}}
meter: 4/4
tempo:
  bpm: {BPM}
key: D dorian
end: {{bar: {END_BAR}, beat: 1}}
form:
{form_yaml}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  # The Lyre of Ur's voice: the VCSL folk harp (catalog folk.harp is a concert harp).
  - {{name: lyre, group: lyre, program: orchestral_harp, volume: 104, pan: 64, expression: 108, {vcsl("Chordophones/Composite Chordophones/Folk Harp")}}}
  - {{name: psaltery, group: psaltery, program: dulcimer, volume: 100, pan: 64, expression: 104, {vcsl("Chordophones/Zithers/Psaltery, Bowed and Plucked - Pluck")}}}
  - {{name: shimmer, group: shimmer, program: string_ensemble_2, volume: 100, pan: 64, expression: 104, {vcsl("Chordophones/Zithers/Psaltery, Bowed and Plucked - LongBow")}}}
  - {{name: oboe, group: oboe, program: oboe, volume: 106, pan: 64, expression: 110, controls: {{1: 90}}, {sfz("vpo.oboe_solo_perf")}}}
  - {{name: violins, group: strings, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1")}}}
  - {{name: violas, group: strings, program: viola, volume: 100, pan: 64, expression: 104, {sfz("strings.violas")}}}
  - {{name: celli, group: strings, program: cello, volume: 102, pan: 64, expression: 106, {sfz("strings.celli")}}}
  - {{name: basses, group: strings, program: contrabass, volume: 104, pan: 64, expression: 108, {sfz("strings.basses")}}}
  - {{name: choir, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {sfz("vpo.choir_male")}}}
  - {{name: frame, group: drums, volume: 110, pan: 64, expression: 112, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
  - {{name: darbuka, group: drums, volume: 104, pan: 64, expression: 108, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Darbuka")}}}
  - {{name: zils, group: drums, volume: 96, pan: 64, expression: 100, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Finger Cymbals")}}}
  - {{name: tamb, group: drums, volume: 96, pan: 64, expression: 100, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Tambourine 1")}}}
  - {{name: ocean, group: sea, volume: 96, pan: 64, expression: 100, is_drum: true, {vcsl("Membranophones/Other Membranophones/Ocean Drum")}}}
parts:
{chr(10).join(part(f"{name}_part", name, clip) for name, clip in PARTS)}
processing:
  groups:
    lyre:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 2.0, attack_ms: 8.0, release_ms: 120.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: -0.15}}
    psaltery:
      chain:
        - {{processor: highpass, cutoff_hz: 250}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 10.0}}
        - {{processor: balance, position: 0.35}}
    shimmer:
      chain:
        - {{processor: highpass, cutoff_hz: 250}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: reverb, wet: 0.35, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.2}}
    oboe:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 12.0, release_ms: 120.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: 0.1}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -2.0}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 3.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 45}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.0, attack_ms: 15.0, release_ms: 90.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: -2.0}}
    sea:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: gain, gain_db: -2.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.1}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [lyre, strings, shimmer]
    drums: [drums, sea]
    tune: [oboe, psaltery]
    power: [choir]
  sections:
    - {{id: song, form: [{form_ids}], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

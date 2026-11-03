"""Solstice Stones: the Europe floor of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_europe_solstice_stones.py scores/active/history_europe_solstice_stones.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different locations
in the history dimension." Each region floor of the History dimension gets its
own cue, and one cue plays in all rooms of its floor. The player walks east
through the ages: Ice Age Europe (mammoth hunters, the painted caves, bone
flutes), the first farmers, the megalith builders (stones aligned to the
solstice sunrise), the Celtic frontier (hill forts, Rome at the border) and
the Viking north (ships, sagas, cold sea).

E Dorian in 6/8 at a dotted quarter of about 61 (92 quarter notes a minute).
Cold air, stone and fire: patient and a little mysterious at the start, warmer
in the folk ages. The oldest known instruments are European bone flutes, so a
breathy recorder is the main voice ("the bone flute"). Every tune is original.

  - THE CALL: the bone-flute theme, four bars that climb a fourth to E and come
    back down; its answer touches the Dorian C sharp, the warm colour of the
    mode. The theme comes back in every age.
  - THE SUNRISE: in the stones the bass climbs one step each two bars,
    E F# G A B C# D E, and the descant climbs over it to a held G sharp on an
    E major chord: the light comes in between the stones.
  - THE HILL-FORT DANCE: a lilting 6/8 tune over a harp, for the Celtic age.
  - THE OARS: plucked tagelharpa and a men's chant in open intervals over
    E Aeolian (C natural): the cold sea of the north.

Form, 6/8, two dotted-quarter beats a bar, 92 bars, about 3:00. The whole file
loops: bar 92 is a D chord that goes back to the E drone of bar 1.
  bar    section    content
  1-12   cave       a hummed open fifth, a heartbeat drum; the bone flute calls.
  13-28  furrow     a walking drum and plucks; the full theme, then a second strain.
  29-44  stones     the sunrise: the bass climbs a step each two bars to E major.
  45-60  hillfort   harp in 6/8, the dance tune on recorder, then on ocarina.
  61-76  longship   E Aeolian: tagelharpa oars, a men's chant, a cold descant.
  77-92  embers     the theme with everyone, the ocarina answers, then the cave again.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 92  # quarter notes; a 6/8 bar is three of them
OUT = Path(sys.argv[1])
rng = random.Random(3200)  # about 3200 BC: the first great stone circles

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
    """The quarter-note time of eighth `eighth` (0 to 5) of 6/8 bar `n`."""
    return (n - 1) * 3.0 + 0.5 * eighth


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.drift = drift
        self.vel_jitter = vel_jitter

    def note(self, start, dur, pitches, vel):
        start = F(start).limit_denominator(960)
        if self.drift and start > 0:
            start += F(rng.uniform(-self.drift, self.drift)).limit_denominator(960)
        start = max(F(0), start)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        self.events.append((start, F(dur).limit_denominator(960), [p if isinstance(p, int) else midi(p) for p in pitches], vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for start, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(start)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


flute = Clip(0.006, 3)      # the bone flute: a tenor recorder
descant = Clip(0.006, 3)    # an alto recorder, for the high lines
ocarina = Clip(0.006, 3)
choir = Clip(0.01, 2)       # men's voices: a hum, then a chant
celli = Clip(0.01, 2)
harp = Clip(0.004, 4)
pluck = Clip(0.004, 4)      # the bass tagelharpa, plucked
drum = Clip(0.004, 4)       # the frame drum
harmony: dict[int, str] = {}

END_BAR = 93

# ---- Harmony ---------------------------------------------------------------------------
#: the chord root in the low octave (E2 to D3), and the chord's third above the root
ROOT = {"Em": "E2", "G": "G2", "D": "D3", "A": "A2", "Bm": "B2", "C": "C3", "Am": "A2", "E": "E2",
        "D/F#": "D3", "A/C#": "A2", "A/E": "A2"}
THIRD = {"Em": 3, "G": 4, "D": 4, "A": 4, "Bm": 3, "C": 4, "Am": 3, "E": 4, "D/F#": 4, "A/C#": 4, "A/E": 4}
#: the bass note when it is not the root
BASS = {"D/F#": "F#2", "A/C#": "C#3", "A/E": "E2"}
#: the men's hum, three voices in G2..F#4 (the choir patch plays 43..66). The A chord has no
#: C sharp: the tune leans on D5 over it, and a C#4 under that is a minor ninth.
HUM = {
    "Em": ["E3", "G3", "B3"], "G": ["D3", "G3", "B3"], "D": ["D3", "F#3", "A3"], "A": ["E3", "A3", "E4"],
    "Bm": ["D3", "F#3", "B3"], "C": ["E3", "G3", "C4"], "Am": ["E3", "A3", "C4"], "E": ["G#3", "B3", "E4"],
    "D/F#": ["F#3", "A3", "D4"], "A/C#": ["A3", "C#4", "E4"], "A/E": ["E3", "A3", "C#4"],
}


def bass_of(chord: str) -> int:
    return midi(BASS.get(chord, ROOT[chord]))


def fifth_of(chord: str) -> int:
    return midi(ROOT[chord]) + 7


# ---- Tunes: each bar is a list of (eighth, length in eighths, note) ------------------------
CALL = [
    [(0, 3, "B4"), (3, 1, "A4"), (4, 2, "B4")],
    [(0, 2, "D5"), (2, 1, "E5"), (3, 3, "B4")],
    [(0, 1, "A4"), (1, 1, "G4"), (2, 1, "A4"), (3, 3, "E4")],
    [(0, 5, "E4")],
]
#: the answer touches the Dorian C sharp and stays open on B
ANSWER_OPEN = [
    [(0, 3, "B4"), (3, 1, "A4"), (4, 2, "B4")],
    [(0, 2, "D5"), (2, 1, "E5"), (3, 2, "F#5"), (5, 1, "E5")],
    [(0, 3, "D5"), (3, 1, "C#5"), (4, 2, "A4")],
    [(0, 5, "B4")],
]
#: the answer that closes on E
ANSWER_HOME = ANSWER_OPEN[:2] + [
    [(0, 2, "D5"), (2, 1, "C#5"), (3, 2, "A4"), (5, 1, "G4")],
    [(0, 5, "E4")],
]
#: the second strain of the farmers, over G A Em Em G Em Bm D
STRAIN = [
    [(0, 3, "D5"), (3, 2, "B4"), (5, 1, "D5")],
    [(0, 3, "E5"), (3, 2, "C#5"), (5, 1, "A4")],
    [(0, 2, "B4"), (2, 1, "G4"), (3, 3, "E4")],
    [(0, 3, "G4"), (3, 3, "B4")],
    [(0, 3, "D5"), (3, 2, "E5"), (5, 1, "F#5")],
    [(0, 3, "G5"), (3, 2, "F#5"), (5, 1, "E5")],
    [(0, 3, "F#5"), (3, 2, "D5"), (5, 1, "B4")],
    [(0, 5, "A4")],
]
#: the sunrise line, two bars on each chord of the climb
SUNRISE = [
    [(0, 9, "B4"), (9, 3, "A4")],
    [(0, 6, "A4"), (6, 6, "D5")],
    [(0, 9, "D5"), (9, 3, "E5")],
    [(0, 6, "E5"), (6, 3, "C#5"), (9, 3, "E5")],
    [(0, 9, "F#5"), (9, 3, "D5")],
    [(0, 6, "E5"), (6, 6, "A5")],
    [(0, 9, "F#5"), (9, 3, "A5")],
    [(0, 11, "G#5")],
]
SUNRISE_CH = ["Em", "D/F#", "G", "A", "Bm", "A/C#", "D", "E"]
#: the hill-fort dance, sixteen bars
DANCE = [
    [(0, 2, "E5"), (2, 1, "B4"), (3, 1, "E5"), (4, 1, "F#5"), (5, 1, "G5")],
    [(0, 2, "F#5"), (2, 1, "E5"), (3, 3, "B4")],
    [(0, 2, "A4"), (2, 1, "D5"), (3, 1, "F#5"), (4, 1, "E5"), (5, 1, "D5")],
    [(0, 2, "D5"), (2, 1, "A4"), (3, 3, "F#4")],
    [(0, 2, "E5"), (2, 1, "B4"), (3, 1, "E5"), (4, 1, "F#5"), (5, 1, "G5")],
    [(0, 2, "A5"), (2, 1, "G5"), (3, 2, "F#5"), (5, 1, "E5")],
    [(0, 2, "C#5"), (2, 1, "E5"), (3, 1, "A5"), (4, 1, "G5"), (5, 1, "F#5")],
    [(0, 5, "E5")],
    [(0, 2, "D5"), (2, 1, "B4"), (3, 1, "D5"), (4, 1, "E5"), (5, 1, "F#5")],
    [(0, 2, "G5"), (2, 1, "F#5"), (3, 3, "D5")],
    [(0, 2, "F#5"), (2, 1, "E5"), (3, 1, "D5"), (4, 1, "A4"), (5, 1, "D5")],
    [(0, 3, "F#5"), (3, 3, "A5")],
    [(0, 2, "G5"), (2, 1, "F#5"), (3, 2, "E5"), (5, 1, "D5")],
    [(0, 2, "C#5"), (2, 1, "D5"), (3, 2, "E5"), (5, 1, "C#5")],
    [(0, 2, "B4"), (2, 1, "A4"), (3, 3, "B4")],
    [(0, 5, "E5")],
]
DANCE_CH = ["Em", "Em", "D", "D", "Em", "Em", "A", "A", "G", "G", "D", "D", "Em", "A", "Em", "Em"]
#: the oars: two bars on each chord, E Aeolian
OARS_CH = ["Em", "C", "D", "Em", "Am", "C", "D", "D"]
#: the men's chant over the oars, two bars on each chord
CHANT = [
    [(0, 6, "B3"), (6, 3, "A3"), (9, 3, "G3")],
    [(0, 9, "E3"), (9, 3, "G3")],
    [(0, 6, "A3"), (6, 3, "F#3"), (9, 3, "A3")],
    [(0, 11, "B3")],
    [(0, 6, "C4"), (6, 3, "B3"), (9, 3, "A3")],
    [(0, 6, "G3"), (6, 6, "E3")],
    [(0, 6, "F#3"), (6, 6, "A3")],
    [(0, 11, "A3")],
]
#: the cold descant over the second half of the oars
COLD = [
    [(0, 6, "E5"), (6, 3, "C5"), (9, 3, "B4")],
    [(0, 6, "G5"), (6, 3, "E5"), (9, 3, "G5")],
    [(0, 6, "A5"), (6, 3, "F#5"), (9, 3, "E5")],
    [(0, 11, "D5")],
]
#: the ocarina's answer in the embers, all above its lowest note A4
ECHO = [
    [(0, 3, "B4"), (3, 1, "A4"), (4, 2, "B4")],
    [(0, 2, "D5"), (2, 1, "E5"), (3, 2, "F#5"), (5, 1, "E5")],
    [(0, 3, "E5"), (3, 3, "C#5")],
    [(0, 5, "B4")],
]


def sing(clip: Clip, n0: int, phrase, vel: int, gate: float = 0.92, transpose: int = 0):
    """Play a phrase whose bars start at bar n0. A long note gets a little more weight."""
    for k, notes in enumerate(phrase):
        for e, length, name in notes:
            clip.note(at(n0 + k, e), 0.5 * length * gate, midi(name) + transpose, vel + (4 if length >= 3 else 0))


def chords(n0: int, names: list[str], bars_each: int = 1):
    for k, name in enumerate(names):
        for b in range(bars_each):
            harmony[n0 + k * bars_each + b] = name


# ---- Bed writers ------------------------------------------------------------------------
def hum(n: int, chord: str, bars: int, vel: int, voices=None):
    """The men hum a chord; the last eighth stays free for a breath."""
    notes = [midi(x) for x in (voices or HUM[chord])]
    choir.note(at(n), 3.0 * bars - 0.4, notes, vel)


def upper_fifth(chord: str) -> int:
    """The fifth of the chord, above its bass note."""
    fifth = fifth_of(chord)
    return fifth if fifth > bass_of(chord) else fifth + 12


def drone(n: int, chord: str, bars: int, vel: int, low_octave: bool = False):
    """The celli hold the bass note and the fifth of the chord."""
    drop = 12 if low_octave and bass_of(chord) > 45 else 0
    celli.note(at(n), 3.0 * bars - 0.3, [bass_of(chord) - drop, upper_fifth(chord) - drop], vel)


def plucks(n: int, chord: str, style: str, vel: int):
    root = bass_of(chord)    # E2..D3, the deep register of the tagelharpa
    fifth = upper_fifth(chord)
    if style == "walk":      # a dotted-quarter pulse: bass, fifth
        pluck.note(at(n, 0), 1.4, root, vel)
        pluck.note(at(n, 3), 1.4, fifth, vel - 10)
    elif style == "oars":    # the oars: a hard stroke, a pull, the fifth, a return
        pluck.note(at(n, 0), 0.9, root, vel)
        pluck.note(at(n, 2), 0.45, root, vel - 26)
        pluck.note(at(n, 3), 0.9, fifth, vel - 8)
        # the octave over E and A; over C and D the fifth, because C4 and D4 sample out of tune
        pluck.note(at(n, 5), 0.45, root + 12 if root + 12 <= 57 else fifth, vel - 22)
    elif style == "dance":   # one deep note under the harp
        pluck.note(at(n, 0), 2.6, root, vel)


def arpeggio(n: int, chord: str, vel: int, style: str = "full"):
    """The harp in 6/8: root, fifth, octave, tenth, twelfth, octave."""
    r = midi(ROOT[chord])
    if r > 51:
        r -= 12
    t = THIRD[chord]
    if style == "full":
        steps = [0, 7, 12, 12 + t, 19, 12]
    else:  # "light": three notes, one each dotted quarter and a pickup
        steps = [0, None, None, 12 + t, None, 19]
    for i, s in enumerate(steps):
        if s is None:
            continue
        harp.note(at(n, i), 1.2, r + s, vel + (8 if i == 0 else 0))


# frame-drum keys of the VCSL frame drum: the large drum is 60 hand, 61 hit, 62 muted;
# the small drum is 63 hand, 64 hit, 65 muted
L_HAND, L_HIT, L_MUTE, S_HAND, S_HIT, S_MUTE = 60, 61, 62, 63, 64, 65


def beat(n: int, style: str, vel: int = 0):
    t = lambda e: at(n, e)
    if style == "heart":
        drum.note(t(0), 0.4, L_HIT, 64 + vel)
        drum.note(t(1), 0.4, L_HAND, 44 + vel)
    elif style == "walk":
        drum.note(t(0), 0.4, L_HIT, 82 + vel)
        drum.note(t(2), 0.3, S_MUTE, 46 + vel)
        drum.note(t(3), 0.4, S_HIT, 68 + vel)
        drum.note(t(5), 0.3, S_MUTE, 44 + vel)
    elif style == "stone":
        drum.note(t(0), 0.6, L_HIT, 76 + vel)
    elif style == "dance":
        drum.note(t(0), 0.4, L_HIT, 90 + vel)
        drum.note(t(1), 0.3, S_MUTE, 44 + vel)
        drum.note(t(2), 0.3, S_MUTE, 54 + vel)
        drum.note(t(3), 0.4, S_HIT, 80 + vel)
        drum.note(t(4), 0.3, S_MUTE, 44 + vel)
        drum.note(t(5), 0.3, S_HAND, 58 + vel)
    elif style == "oars":
        drum.note(t(0), 0.5, L_HIT, 100 + vel)
        drum.note(t(2), 0.3, L_MUTE, 58 + vel)
        drum.note(t(3), 0.5, L_HIT, 88 + vel)
        drum.note(t(5), 0.3, S_MUTE, 50 + vel)
    elif style == "roll":    # six even strokes that grow
        for e in range(6):
            drum.note(t(e), 0.3, S_HIT if e % 3 else L_HIT, 56 + 6 * e + vel)


# ---- cave, 1-12: cold air ----------------------------------------------------------------
chords(1, ["Em"] * 10 + ["A/E", "Em"])
for n in (1, 3, 5, 7, 9):
    hum(n, "Em", 2, 46, voices=["E3", "B3"])
    celli.note(at(n), 5.7, midi("E2"), 52)
hum(11, "A/E", 1, 46, voices=["E3", "A3"])  # open: the flute's D5 falls to C sharp over it
hum(12, "Em", 1, 46, voices=["E3", "B3"])
celli.note(at(11), 5.7, midi("E2"), 52)
for n in range(1, 13):
    beat(n, "heart", vel=-6 if n < 5 else 0)
sing(flute, 5, CALL, 76)
sing(flute, 9, ANSWER_OPEN, 78)

# ---- furrow, 13-28: farming arrives -------------------------------------------------------
FURROW_A = ["Em", "G", "D", "Em", "Em", "D", "A", "Em"]
FURROW_B = ["G", "A", "Em", "Em", "G", "Em", "Bm", "D"]
chords(13, FURROW_A + FURROW_B)
for k, ch in enumerate(FURROW_A + FURROW_B):
    n = 13 + k
    plucks(n, ch, "walk", 84)
    beat(n, "walk", vel=-6 if n < 17 else 0)
    hum(n, ch, 1, 44 if n < 21 else 50)
    drone(n, ch, 1, 50)
sing(flute, 13, CALL, 84)
sing(flute, 17, ANSWER_HOME, 86)
sing(flute, 21, STRAIN, 86)
for k, n in enumerate(range(21, 29)):  # the harp joins lightly for the second strain
    arpeggio(n, FURROW_B[k], 52, style="light")

# ---- stones, 29-44: the sunrise ------------------------------------------------------------
chords(29, SUNRISE_CH, bars_each=2)
for k, ch in enumerate(SUNRISE_CH):
    n = 29 + 2 * k
    rising = k / 7.0
    hum(n, ch, 2, int(42 + 22 * rising), voices=["E3", "B3"] if k == 0 else None)
    drone(n, ch, 2, int(48 + 22 * rising))
    if k < 4:
        beat(n, "stone", vel=-10)       # one stone footfall each two bars
    elif k < 6:
        beat(n, "stone")
        beat(n + 1, "stone", vel=-12)
    if k >= 4:
        plucks(n, ch, "dance", 66 + 4 * k)
        plucks(n + 1, ch, "walk", 62 + 4 * k)
for k in range(8):
    sing(descant, 29 + 2 * k, [SUNRISE[k]], 72 + 3 * k, gate=0.96)
# the harp: stars at first, then rising ripples
STARS = {29: ("B5", 3), 30: ("E6", 0), 31: ("A5", 3), 32: ("F#5", 0), 33: ("D6", 3), 34: ("B5", 0), 35: ("C#6", 3), 36: ("E6", 0)}
for n, (name, e) in STARS.items():
    harp.note(at(n, e), 2.0, midi(name), 50)
for k in range(4, 8):
    n = 29 + 2 * k
    arpeggio(n, SUNRISE_CH[k], 56 + 4 * k)
    arpeggio(n + 1, SUNRISE_CH[k], 52 + 4 * k)
beat(41, "roll", vel=-4)
beat(42, "roll", vel=8)
beat(43, "dance", vel=6)
beat(44, "walk")

# ---- hillfort, 45-60: the Celtic dance ------------------------------------------------------
chords(45, DANCE_CH)
for k, ch in enumerate(DANCE_CH):
    n = 45 + k
    arpeggio(n, ch, 66)
    plucks(n, ch, "dance", 78)
    beat(n, "dance", vel=-4 if k < 8 else 0)
    if k % 2 == 0:           # one held drone per chord, at most two bars long
        drone(n, ch, 2 if DANCE_CH[k + 1] == ch else 1, 46)
    elif DANCE_CH[k - 1] != ch:
        drone(n, ch, 1, 46)
sing(flute, 45, DANCE[:8], 88, gate=0.85)
sing(ocarina, 53, DANCE[8:], 86, gate=0.85)
for n, e, length, name in ((53, 0, 12, "B4"), (55, 0, 12, "A4"), (57, 0, 6, "G4"), (58, 0, 6, "A4"),
                           (59, 0, 6, "B4"), (60, 0, 5, "G4")):
    flute.note(at(n, e), 0.5 * length * 0.95, midi(name), 66)

# ---- longship, 61-76: the cold sea ----------------------------------------------------------
chords(61, OARS_CH, bars_each=2)
LOW_CHANT = {"Em": "E3", "C": "C3", "D": "D3", "Am": "A2"}
for k, ch in enumerate(OARS_CH):
    n = 61 + 2 * k
    sing(choir, n, [CHANT[k]], 74 + (6 if k >= 4 else 0), gate=0.95)
    choir.note(at(n), 5.6, midi(LOW_CHANT[ch]), 54 + (6 if k >= 4 else 0))
    drone(n, ch, 2, 48, low_octave=True)
    for b in (0, 1):
        plucks(n + b, ch, "oars", 100)
        beat(n + b, "oars", vel=-6 if k < 2 else 0)
for k in range(4):
    sing(descant, 69 + 2 * k, [COLD[k]], 78, gate=0.96)

# ---- embers, 77-92: the warm return, then the cave again --------------------------------------
EMBERS_A = FURROW_A
EMBERS_B = ["Em", "D", "A", "Em"]
chords(77, EMBERS_A + EMBERS_B + ["Em", "Em", "D", "D"])
for k, ch in enumerate(EMBERS_A + EMBERS_B):
    n = 77 + k
    arpeggio(n, ch, 60 if k < 8 else 54, style="full" if k < 8 else "light")
    plucks(n, ch, "walk", 86 if k < 8 else 76)
    beat(n, "walk", vel=0 if k < 8 else -8)
    hum(n, ch, 1, 45 if k < 8 else 42)  # under the returning theme, softer than in the furrow
    drone(n, ch, 1, 47 if k < 8 else 44)
sing(flute, 77, CALL, 88)
sing(flute, 81, ANSWER_HOME, 90)
sing(ocarina, 85, ECHO, 80, gate=0.9)
# the last four bars thin out to the cave: the open fifth, the heartbeat, a last call
hum(89, "Em", 2, 44, voices=["E3", "B3"])
celli.note(at(89), 5.7, midi("E2"), 48)
hum(91, "D", 2, 42, voices=["D3", "A3"])
celli.note(at(91), 5.6, midi("D2"), 46)
for n in range(89, 93):
    beat(n, "heart", vel=-4)
sing(flute, 89, [[(0, 3, "B4"), (3, 1, "A4"), (4, 2, "B4")], [(0, 5, "E4")]], 74)
sing(flute, 91, [[(0, 3, "A4"), (3, 1, "G4"), (4, 2, "A4")], [(0, 4, "D4")]], 70)

progression = [harmony[n] for n in range(1, END_BAR)]
assert len(progression) == END_BAR - 1

# The playable range of each sample; a note outside it would be silent or folded.
RANGES = {"flute": (60, 86, flute), "descant": (65, 91, descant), "ocarina": (69, 86, ocarina),
          "choir": (43, 66, choir), "celli": (36, 73, celli), "harp": (36, 93, harp), "pluck": (38, 65, pluck),
          "drum": (60, 65, drum)}
for label, (lo, hi, clip) in RANGES.items():
    for start, dur, pitches, _ in clip.events:
        for p in pitches:
            assert lo <= p <= hi, f"{label}: pitch {p} at {start} is out of {lo}..{hi}"
        # nothing rings over the loop seam
        assert start + dur <= at(END_BAR) + F(1, 960), f"{label}: a note at {start} rings past the end"


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', required: true, settings: {{fold_to_range: false}}}}"


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}, required: true}}"


#: tuning correction in cents for each tagelharpa note of this score (see the instrument entry)
PLUCK_TUNING = {"E2": -31, "G2": 45, "A2": 21, "B2": 5, "C3": 41, "C#3": 70, "D3": -9, "E3": -56, "F#3": -30,
                "G3": 3, "A3": -14}
used = {p for _, _, pitches, _ in pluck.events for p in pitches}
assert used <= {midi(k) for k in PLUCK_TUNING}, sorted(used - {midi(k) for k in PLUCK_TUNING})

SECONDS = (END_BAR - 1) * 3 * 60 / BPM
score = f"""schema: ambition.musicir.v3
id: history_europe_solstice_stones
title: Solstice Stones
description: >-
  The Europe floor of the History dimension, one cue for all its rooms, from
  the Ice Age caves to the Viking north. E Dorian in 6/8 at a dotted quarter
  of about 61. Cold air, stone and fire: a breathy recorder is the bone flute
  and calls over a hummed open fifth and a frame-drum heartbeat; the farmers
  bring a walking drum and plucks; between the stones the bass climbs a step
  each two bars to an E major sunrise; a harp and an ocarina dance in the hill
  forts; plucked tagelharpa oars and a men's chant cross a cold E Aeolian sea;
  the theme comes home warm and thins back to the cave. Original melodies.
  Generated by dev/compose_history_europe_solstice_stones.py: edit that, not
  this file.
notes:
  - 'Jon, 2026-11-03: "I also think we will want new music for different locations in the history dimension." One cue per region floor; this is Europe.'
  - 'Form: cave 1-12, furrow 13-28, stones 29-44, hillfort 45-60, longship 61-76, embers 77-92. The whole file loops: bar 92 is a D chord that goes back to the E drone of bar 1.'
  - 'The tagelharpa is Karoryfer Horse Pulse, a bass tagelharpa played pizzicato; this score uses its single-articulation pluck program, not the keyswitch program, where velocity selects the articulation.'
  - 'Layered for a room: bed (celli, choir, tagelharpa, harp), drums (frame drum), tune (bone flute, descant, ocarina).'
seed: 3200
timebase: {{ppq: 960}}
meter: 6/8
tempo: {BPM}
key: E dorian
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: cave, label: 'Cave: the bone flute calls', from: {{bar: 1, beat: 1}}, to: {{bar: 13, beat: 1}}, role: loop_component, loopable: true, energy: 0.25, density: 0.25}}
  - {{id: furrow, label: 'Furrow: the farmers walk', from: {{bar: 13, beat: 1}}, to: {{bar: 29, beat: 1}}, role: loop_component, loopable: true, energy: 0.5, density: 0.5}}
  - {{id: stones, label: 'Stones: the solstice sunrise', from: {{bar: 29, beat: 1}}, to: {{bar: 45, beat: 1}}, role: loop_component, loopable: true, energy: 0.6, density: 0.55}}
  - {{id: hillfort, label: 'Hill fort: the dance', from: {{bar: 45, beat: 1}}, to: {{bar: 61, beat: 1}}, role: loop_component, loopable: true, energy: 0.75, density: 0.75}}
  - {{id: longship, label: 'Longship: the oars', from: {{bar: 61, beat: 1}}, to: {{bar: 77, beat: 1}}, role: loop_component, loopable: true, energy: 0.8, density: 0.7}}
  - {{id: embers, label: 'Embers: the theme comes home', from: {{bar: 77, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, role: loop_component, loopable: true, energy: 0.55, density: 0.55}}
render:
  backend: pretty-midi
  sample_rate: 48000
  ogg_quality: 7
  metadata_markers:
    - {{bar: 1, id: m1, label: Cave}}
    - {{bar: 13, id: m13, label: Furrow}}
    - {{bar: 29, id: m29, label: Stones}}
    - {{bar: 45, id: m45, label: Hill fort}}
    - {{bar: 61, id: m61, label: Longship}}
    - {{bar: 77, id: m77, label: Embers}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: flute, group: flute, program: recorder, volume: 104, pan: 64, expression: 108, {vcsl("Aerophones/Edge-blown Aerophones/Baroque Tenor Recorder - Sustain")}}}
  - {{name: descant, group: descant, program: recorder, volume: 100, pan: 64, expression: 104, {vcsl("Aerophones/Edge-blown Aerophones/Baroque Alto Recorder - Sustain")}}}
  - {{name: ocarina, group: ocarina, program: ocarina, volume: 100, pan: 64, expression: 104, {vcsl("Aerophones/Edge-blown Aerophones/Ocarina, Typical - Sus")}}}
  - {{name: choir, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {sfz("vpo.choir_male")}}}
  - {{name: celli, group: celli, program: cello, volume: 100, pan: 64, expression: 104, {sfz("strings.celli")}}}
  - {{name: harp, group: harp, program: orchestral_harp, volume: 104, pan: 64, expression: 108, {sfz("folk.harp")}}}
  # Not the catalog's keyswitch program: in it velocity selects scrape, pluck or nail. 03-pluck plays one articulation.
  # The tagelharpa samples are tuned note by note, from about -70 to +56 cents. The curve starts from the
  # negative of the median pitch of the six round robins of each note (autocorrelation, 0.2 s to 0.7 s into
  # each sample). G2, C3 and C#3 are then set from the pitch measured in a render with the first curve.
  - name: pluck
    group: pluck
    program: acoustic_bass
    volume: 104
    pan: 64
    expression: 108
    tuning_correction:
      mode: curve
      interpolation: linear
      max_abs_cents: 80
      points: {{{", ".join(f"{k}: {v}" for k, v in PLUCK_TUNING.items())}}}
    instrument_backend: {{kind: sfz, sfz_glob: '**/Karoryfer/HorsePulse/Programs/03-pluck.sfz', required: true, settings: {{fold_to_range: false}}}}
  - {{name: drum, group: drum, program: taiko_drum, volume: 104, pan: 64, expression: 108, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
parts:
{part("flute_part", "flute", flute)}
{part("descant_part", "descant", descant)}
{part("ocarina_part", "ocarina", ocarina)}
{part("choir_part", "choir", choir)}
{part("celli_part", "celli", celli)}
{part("harp_part", "harp", harp)}
{part("pluck_part", "pluck", pluck)}
{part("drum_part", "drum", drum)}
processing:
  groups:
    # The VCSL recorder and ocarina samples are about 3 dB louder on the right; the balance corrects it.
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 2.0, attack_ms: 15.0, release_ms: 140.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 7.0}}
        - {{processor: balance, position: -0.25}}
    descant:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.34, decay_seconds: 3.2}}
        - {{processor: gain, gain_db: 7.0}}
        - {{processor: balance, position: 0.0}}
    ocarina:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 7.0}}
        - {{processor: balance, position: 0.05}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: reverb, wet: 0.36, decay_seconds: 3.4}}
        - {{processor: gain, gain_db: 0.0}}
    celli:
      chain:
        - {{processor: highpass, cutoff_hz: 45}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: -0.15}}
    harp:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: 0.25}}
    pluck:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 4000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.4, attack_ms: 10.0, release_ms: 110.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 2.0}}
    drum:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: compressor, threshold_db: -18.0, ratio: 2.0, attack_ms: 15.0, release_ms: 90.0}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 0.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 150.0, makeup_db: 1.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [celli, choir, pluck, harp]
    drums: [drum]
    tune: [flute, descant, ocarina]
  sections:
    - {{id: song, form: [cave, furrow, stones, hillfort, longship, embers], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {SECONDS:.0f} s")

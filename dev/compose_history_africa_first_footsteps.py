"""First Footsteps: the Africa floor of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_africa_first_footsteps.py scores/active/history_africa_first_footsteps.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different locations
in the history dimension." The History dimension is a grid of rooms: each
column is an age, each floor is a region. Africa is the bottom floor, where
the whole dimension starts. Its rooms, west (oldest) to east: the Cradle (the
Great Rift Valley, the first nomads, the first fire; the player starts here),
the Southern Coast (shell beads, ochre, the walk out of Africa by the coast),
the Green Sahara (herders, rock art, lakes), the Nile Valley, Aksum and Kush,
and the Timbuktu coast (Mali, trade, scholars). One cue plays on all of them.

The feeling is the long walk that every person descends from: warm, open, at
a walking pace. G Mixolydian (the flat seventh F is the open, unresolved
colour) at 88 BPM, 4/4, and every beat is divided in three: each bar is a
cycle of 12 pulses, felt as 4 x 3 (the frame drum, the shaker, the claps) and
as 3 x 4 (the bass, the congas, the long notes of the tunes) at the same time.

  - THE CYCLE: the harmony is a ring of four bars, not a progression that
    resolves: G Am F C at home, Em D C D in the Green Sahara, C G/B Am F for
    the kingdoms. The last chord of each ring leads round to its first.
  - THE INTERLOCK: the mbira dzaVadzimu plays one hand on the beat and one
    hand between; the nyunga nyunga fills the pulses the mbira leaves, so the
    two together make the full 12-pulse stream that neither plays alone.
  - THE CALL AND THE ANSWER: a two-bar call and a two-bar answer on each
    ring. In the walk the kalimba calls and the balafon answers; in the river
    they change places; in the kingdoms the kalimba and the balafon call in
    octaves and the wordless choir answers. The long notes of the call cross
    the beat in groups of four pulses: the 3 x 4 feel in the tune.

Form, 4/4 at 88 BPM, 64 bars (16 rings of four), about 2:55. The whole file
loops: the return thins to the mbira and the frame drum, and bar 64 ends with
the mbira alone, as bar 1 starts.
  embers    1-8    the mbira alone; the frame drum heartbeat from bar 5    (Cradle)
  walk      9-20   the nyunga interlock, the bass, the shaker; the kalimba
                   calls and the balafon answers                          (Coast)
  green     21-32  Em D C D: the balafon runs in fours, congas, a slit
                   drum answers the kalimba                               (Sahara)
  river     33-44  home again: the balafon calls, the kalimba answers,
                   the choir holds the chords quietly                     (Nile)
  kingdoms  45-56  C G/B Am F: bells, claps, congas; the kalimba and the
                   balafon call in octaves, the choir answers             (Aksum, Kush, Timbuktu)
  return    57-64  home: the call once more with no answer; then the mbira
                   and the frame drum alone                               (back to the Cradle)
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 88
OUT = Path(sys.argv[1])
rng = random.Random(1974)  # the year "Lucy" was found in the Afar

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: one pulse is a third of a beat; a bar has 12
P = F(1, 3)
#: the written length of a plucked tine (mbira, nyunga, kalimba): five pulses
RING = 5 * P

#: Measured sounding offset, in cents, of the VCSL samples against 12-TET (each region's
#: sample pitch plus its `tune` opcode; the method reads a VCSL marimba within 5 cents).
#: The renderer corrects each note by the opposite amount with pitch bend. The bend holds
#: only while the note is written as on, so the tines are written RING long (the mbira and the
#: nyunga stop at the bar line). A key not listed
#: takes the value of the nearest listed key; the listed zeros hold the keys within 8 cents at 0.
TUNING = {
    "mbira": {50: 22, 51: 22, 52: -17, 53: -17, 54: -10, 55: -10, 56: 0, 57: -19, 58: -19, 59: -30, 60: -30,
              61: 8, 62: 8, 63: -12, 64: 0, 75: 0, 76: 30, 77: 30, 78: 6, 79: 6, 80: 0, 81: -14, 82: -14,
              83: -17, 84: -17},
    "nyunga": {53: -26, 54: -26, 55: -26, 56: 8, 57: 8, 58: -22, 59: -22, 60: 0, 64: 0, 65: 10, 66: 10, 67: 0, 68: 0,
               69: 0, 70: 6, 71: 6, 72: 0, 76: 0, 77: -13, 78: -13},
    "kalimba": {59: 9, 60: 9, 61: 10, 62: 10, 63: 0, 72: 0, 73: -19, 74: -19, 75: -27, 76: -27, 77: 0, 84: 0},
    "balafon": {60: -11, 61: -11, 62: -11, 63: -11, 64: -17, 65: -17, 66: -17, 67: -17, 68: -17, 69: 0, 86: 0,
                87: 14, 88: 14, 89: 14, 90: 14, 91: 14},
}


def midi(name: str) -> int:
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

    def note(self, at, dur, pitches, vel):
        at = F(at).limit_denominator(960)
        if self.drift and at > 0:
            at += F(rng.uniform(-self.drift, self.drift)).limit_denominator(960)
        at = max(F(0), at)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        self.events.append((at, F(dur), [p if isinstance(p, int) else midi(p) for p in pitches], vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


def T(n: int) -> F:
    """The first beat of bar n, in beats."""
    return F((n - 1) * 4)


def at(n: int, pulse) -> F:
    """Pulse `pulse` (0 to 11) of bar n, in beats."""
    return T(n) + F(pulse) * P


mbira = Clip(0.012, 5)
nyunga = Clip(0.012, 5)
kalimba = Clip(0.008, 4)
balafon = Clip(0.008, 4)
bass = Clip(0.006, 4)
choir_f = Clip(0.01, 2)
choir_m = Clip(0.01, 2)
frame = Clip(0.006, 5)
shaker = Clip(0.008, 6)
conga = Clip(0.006, 5)
claps = Clip(0.01, 5)
bell = Clip(0.004, 4)
slit = Clip(0.006, 4)
harmony: dict[int, str] = {}

# ---- Harmony ---------------------------------------------------------------------------
#: pitch classes of each chord, root first
CHORD = {
    "G": ["G", "B", "D"], "Am": ["A", "C", "E"], "F": ["F", "A", "C"], "C": ["C", "E", "G"],
    "Em": ["E", "G", "B"], "D": ["D", "F#", "A"], "G/B": ["G", "B", "D"],
}
#: the bass note of each chord
ROOT = {"G": "G2", "Am": "A2", "F": "F2", "C": "C2", "Em": "E2", "D": "D2", "G/B": "B1"}
#: the bass's second note, a chord tone above the bass note (the fifth, but D over the B of G/B)
FIFTH = {"G/B": "D2"}
HOME = ["G", "Am", "F", "C"]
GREEN = ["Em", "D", "C", "D"]
KING = ["C", "G/B", "Am", "F"]


def ladder(chord: str, lo: int, hi: int) -> list[int]:
    """The chord tones from lo up to hi (both included), low to high."""
    pcs = {NOTE[x] for x in CHORD[chord]}
    return [p for p in range(lo, hi + 1) if p % 12 in pcs]


# ---- The interlock ---------------------------------------------------------------------
#: The mbira's two hands, as {pulse: (hand, rung)}. The left hand ("L") reads a low ladder,
#: the right hand ("H") a high ladder. The left hand is on the beat (4 x 3); the right hand
#: comes between.
MBIRA_HOME = {0: ("L", 0), 2: ("H", 3), 3: ("L", 2), 4: ("H", 2), 6: ("L", 1), 8: ("H", 4), 9: ("L", 2), 10: ("H", 2)}
#: The second shape: the right hand falls in groups of four pulses (3 x 4) for the later rings.
MBIRA_WIDE = {0: ("L", 0), 1: ("H", 4), 3: ("L", 1), 4: ("H", 3), 6: ("L", 0), 7: ("H", 2), 8: ("H", 4), 9: ("L", 2),
              10: ("H", 3)}
#: The last bar of the file: the full pattern up to pulse 9, so the pulse goes on to the seam.
MBIRA_LAST = {0: ("L", 0), 2: ("H", 3), 3: ("L", 2), 4: ("H", 2), 6: ("L", 1), 8: ("H", 4), 9: ("L", 2)}
#: The nyunga nyunga fills pulses the mbira leaves: {pulse: rung of its ladder}.
NYUNGA_HOME = {1: 2, 5: 1, 7: 3, 11: 2}
NYUNGA_WIDE = {2: 3, 5: 2, 11: 1}


def mbira_bar(n: int, chord: str, shape: dict, vel: int):
    low, high = ladder(chord, 50, 62), ladder(chord, 64, 81)
    for pulse, (hand, rung) in shape.items():
        rungs = low if hand == "L" else high
        accent = 8 if pulse in (0, 6) else (4 if hand == "L" else 0)
        # The sample rings for seconds after note-off, so the written length changes only how long
        # the tuning bend of this note holds (see TUNING below).
        # A note stops at the bar line, so it does not sound into the next chord as written.
        mbira.note(at(n, pulse), min(RING, (12 - pulse) * P), rungs[min(rung, len(rungs) - 1)], vel + accent)


def nyunga_bar(n: int, chord: str, shape: dict, vel: int):
    rungs = ladder(chord, 57, 76)
    for pulse, rung in shape.items():
        nyunga.note(at(n, pulse), min(RING, (12 - pulse) * P), rungs[min(rung, len(rungs) - 1)], vel)


# ---- The tunes -------------------------------------------------------------------------
#: (pulse, length in pulses, note), one list per bar of the ring.
#: The home call (bars 1-2 of a ring over G Am): up the valley, then three long falling
#: notes in groups of four pulses.
CALL_HOME = [
    [(0, 2, "G4"), (2, 1, "A4"), (3, 3, "B4"), (6, 2, "D5"), (8, 1, "B4"), (9, 3, "D5")],
    [(0, 4, "E5"), (4, 4, "C5"), (8, 4, "A4")],
]
#: The call on the last ring of a section: the long notes climb instead.
CALL_HOME_UP = [
    [(0, 2, "G4"), (2, 1, "A4"), (3, 3, "B4"), (6, 2, "D5"), (8, 1, "E5"), (9, 3, "G5")],
    [(0, 4, "E5"), (4, 4, "G5"), (8, 4, "A5")],
]
#: The home answer (bars 3-4 over F C): it starts off the beat and comes down to G.
ANSWER_HOME = [
    [(2, 1, "C5"), (3, 2, "A4"), (5, 1, "C5"), (6, 3, "D5"), (9, 3, "C5")],
    [(0, 2, "A4"), (2, 1, "G4"), (3, 3, "A4"), (6, 5, "G4")],
]
#: The answer to the climbing call: it comes down from F5.
ANSWER_HOME_DOWN = [
    [(0, 3, "F5"), (3, 2, "C5"), (5, 1, "A4"), (6, 3, "D5"), (9, 3, "C5")],
    [(0, 2, "A4"), (2, 1, "G4"), (3, 3, "A4"), (6, 5, "G4")],
]
#: The Green Sahara tune, all four bars on the kalimba (Em D C D); the slit drum answers.
GREEN_TUNE = [
    [(0, 2, "E5"), (2, 1, "D5"), (3, 3, "B4"), (6, 2, "G4"), (8, 1, "A4"), (9, 3, "B4")],
    [(0, 6, "A4"), (6, 3, "F#4"), (9, 2, "A4")],
    [(0, 2, "G4"), (2, 1, "A4"), (3, 3, "C5"), (6, 2, "E5"), (8, 1, "C5"), (9, 3, "D5")],
    [(0, 4, "A4"), (4, 4, "F#4"), (8, 4, "A4")],
]
#: The kingdoms call (C G/B), in octaves on the kalimba and the balafon.
CALL_KING = [
    [(0, 3, "G5"), (3, 2, "E5"), (5, 1, "G5"), (6, 3, "A5"), (9, 3, "G5")],
    [(0, 4, "D5"), (4, 4, "B4"), (8, 4, "D5")],
]
CALL_KING_UP = [
    [(0, 3, "G5"), (3, 2, "E5"), (5, 1, "G5"), (6, 3, "A5"), (9, 3, "C6")],
    [(0, 4, "B5"), (4, 4, "G5"), (8, 4, "D5")],
]
#: The choir's answer in the kingdoms (Am F): long notes, sung without words.
ANSWER_KING = [
    [(0, 6, "E5"), (6, 6, "C5")],
    [(0, 4, "D5"), (4, 4, "C5"), (8, 3, "A4")],
]


def sing(clip: Clip, n0: int, bars, vel: int, octave: int = 0, legato: float = 0.92, floor: int = 0,
         ring: bool = False):
    """Play a tune. A note under `floor` goes up one octave, so it stays in the sampled range.
    With `ring`, a note that TUNING corrects is written at least RING long, so its bend holds."""
    for k, notes in enumerate(bars):
        for pulse, length, name in notes:
            held = length >= 3
            pitch = midi(name) + 12 * octave
            if pitch < floor:
                pitch += 12
            dur = length * P * legato
            if ring and TUNING["kalimba"].get(pitch):
                dur = max(dur, RING)
            clip.note(at(n0 + k, pulse), dur, pitch, vel + (5 if held else 0))


# ---- The beds --------------------------------------------------------------------------
def bass_bar(n: int, chord: str, style: str, vel: int):
    """The upright bass, plucked. "three": root, fifth, octave on pulses 0, 4, 8 (3 x 4 over the
    4 x 3 drum). "step": root and fifth with a step to the next ring. "long": one held root."""
    root = midi(ROOT[chord])
    fifth = midi(FIFTH[chord]) if chord in FIFTH else root + 7
    if style == "three":
        for pulse, p, v in ((0, root, vel + 8), (4, fifth, vel), (8, root + 12, vel - 4)):
            bass.note(at(n, pulse), 3.5 * P, p, v)
    elif style == "green":
        for pulse, p, v in ((0, root, vel + 8), (6, fifth, vel), (9, root, vel - 4)):
            bass.note(at(n, pulse), 2.5 * P, p, v)
    elif style == "walk":
        for pulse, p, v in ((0, root, vel + 8), (4, fifth, vel), (8, root + 12, vel - 2), (10, fifth, vel - 8)):
            bass.note(at(n, pulse), 1.8 * P, p, v)
    elif style == "long":
        bass.note(T(n), 3.6, root, vel)


def balafon_run(n: int, chord: str, vel: int):
    """Groups of four pulses, three to a bar: the balafon's 3 x 4 against the drum's 4 x 3."""
    rungs = ladder(chord, 64, 84)
    shape = (0, 2, 1, 3)
    for g in range(3):
        for i, rung in enumerate(shape):
            pulse = 4 * g + i
            balafon.note(at(n, pulse), P * 0.9, rungs[min(rung + (1 if g == 1 else 0), len(rungs) - 1)],
                         vel + (8 if i == 0 else 0))


def choir_bar(n: int, chord: str, vel: int, bars: int = 1):
    """A quiet held chord: two voices in the female choir (from G4), two in the male choir."""
    top = ladder(chord, 67, 79)[:2]
    low = ladder(chord, 48, 62)[-2:]
    length = 4.0 * bars - 0.25
    choir_f.note(T(n) + F(1, 20), length, top, vel)
    choir_m.note(T(n) + F(1, 20), length, low, vel - 4)


# VCSL frame drum keys: 60 large hand, 61 large hit, 62 large muted, 63 small hand, 64 small hit,
# 65 small muted. Congas: 60 conga muted, 61 conga open, 62 quinto muted, 63 quinto open,
# 64 tumba muted, 65 tumba open. Slit drum: 60 high, 61 low. Agogo: 60 high, 61 low.
# Small shaker: 64 and 65 are the high quick shakes down and up.
F_HAND, F_HIT, F_MUTE, F_SHAND, F_SHIT, F_SMUTE = 60, 61, 62, 63, 64, 65
C_MUTE, C_OPEN, Q_MUTE, Q_OPEN, T_MUTE, T_OPEN = 60, 61, 62, 63, 64, 65


def frame_bar(n: int, style: str, vel: int):
    if style == "heart":
        frame.note(at(n, 0), P, F_HIT, vel + 8)
        frame.note(at(n, 6), P, F_HAND, vel - 6)
        frame.note(at(n, 9), P, F_SMUTE, vel - 18)
    elif style == "walk":
        frame.note(at(n, 0), P, F_HIT, vel + 8)
        frame.note(at(n, 3), P, F_SHAND, vel - 14)
        frame.note(at(n, 6), P, F_HAND, vel - 2)
        frame.note(at(n, 9), P, F_SMUTE, vel - 12)
        frame.note(at(n, 11), P, F_SMUTE, vel - 20)
    elif style == "full":
        frame.note(at(n, 0), P, F_HIT, vel + 8)
        frame.note(at(n, 3), P, F_SHIT, vel - 8)
        frame.note(at(n, 6), P, F_HIT, vel)
        frame.note(at(n, 8), P, F_SMUTE, vel - 18)
        frame.note(at(n, 9), P, F_SHIT, vel - 8)
        frame.note(at(n, 11), P, F_SMUTE, vel - 16)


def shaker_bar(n: int, vel: int):
    """The long-short swing on every beat: pulses 0 and 2 of each three."""
    for beat in range(4):
        shaker.note(at(n, 3 * beat), P, 64, vel + (8 if beat % 2 == 0 else 0))
        shaker.note(at(n, 3 * beat + 2), P, 65, vel - 10)


def conga_bar(n: int, vel: int, busy: bool):
    """The congas speak in fours (3 x 4): the tumba on 0, the conga on 4 and 8."""
    conga.note(at(n, 0), P, T_OPEN, vel + 6)
    conga.note(at(n, 4), P, C_OPEN, vel)
    conga.note(at(n, 8), P, C_OPEN, vel - 4)
    conga.note(at(n, 7), P, Q_MUTE, vel - 16)
    if busy:
        conga.note(at(n, 10), P, Q_OPEN, vel - 8)
        conga.note(at(n, 11), P, Q_MUTE, vel - 18)


def slit_answer(n: int, vel: int):
    """The slit drum's two-tone answer at the end of a bar: high, high, low."""
    slit.note(at(n, 6), P, 60, vel)
    slit.note(at(n, 8), P, 60, vel - 10)
    slit.note(at(n, 9), 2 * P, 61, vel + 4)


#: The bell's line over the 12 pulses, seven strokes (the low bell on the first).
BELL = (0, 2, 4, 5, 7, 9, 11)


def bell_bar(n: int, vel: int):
    for pulse in BELL:
        bell.note(at(n, pulse), P, 61 if pulse == 0 else 60, vel + (6 if pulse == 0 else 0))


def claps_bar(n: int, vel: int):
    """Claps on beats 2 and 4, a soft solo clap before beat 4."""
    claps.note(at(n, 3), P, 60, vel)
    claps.note(at(n, 9), P, 60, vel + 4)
    claps.note(at(n, 8), P, 61, vel - 22)


# ---- embers, 1-8: the mbira alone; the frame drum heartbeat from bar 5 ----------------------
for k in range(8):
    n = 1 + k
    chord = HOME[k % 4]
    harmony[n] = chord
    mbira_bar(n, chord, MBIRA_HOME, 70 + 2 * k)
    if k >= 4:
        frame_bar(n, "heart", 72 + 2 * (k - 4))
    if k >= 6:
        nyunga_bar(n, chord, {1: 2, 7: 3}, 58)  # two pulses of the interlock lead in to the walk

# ---- walk, 9-20: the interlock, the bass, the shaker; the kalimba calls, the balafon answers --
for k in range(12):
    n = 9 + k
    chord = HOME[k % 4]
    harmony[n] = chord
    mbira_bar(n, chord, MBIRA_HOME, 80)
    nyunga_bar(n, chord, NYUNGA_HOME, 70)
    bass_bar(n, chord, "three", 84)
    frame_bar(n, "walk", 80)
    shaker_bar(n, 50 + (8 if k >= 4 else 0))
for ring in range(3):
    n0 = 9 + 4 * ring
    last = ring == 2
    sing(kalimba, n0, CALL_HOME_UP if last else CALL_HOME, 88, ring=True)
    sing(balafon, n0 + 2, ANSWER_HOME_DOWN if last else ANSWER_HOME, 84)

# ---- green, 21-32: Em D C D; the balafon runs in fours, congas, the slit drum answers --------
for k in range(12):
    n = 21 + k
    chord = GREEN[k % 4]
    harmony[n] = chord
    mbira_bar(n, chord, MBIRA_WIDE, 78)
    nyunga_bar(n, chord, NYUNGA_WIDE, 68)
    bass_bar(n, chord, "green", 84)
    balafon_run(n, chord, 58 + (6 if k >= 4 else 0))
    frame_bar(n, "heart", 76)
    shaker_bar(n, 48)
    if k >= 4:
        conga_bar(n, 80, busy=k >= 8)
    if k % 2 == 1:
        slit_answer(n, 82)
for ring in range(3):
    sing(kalimba, 21 + 4 * ring, GREEN_TUNE, 86, ring=True)

# ---- river, 33-44: home; the balafon calls, the kalimba answers, the choir holds the chords ---
for k in range(12):
    n = 33 + k
    chord = HOME[k % 4]
    harmony[n] = chord
    mbira_bar(n, chord, MBIRA_HOME if k % 8 < 4 else MBIRA_WIDE, 82)
    nyunga_bar(n, chord, NYUNGA_HOME, 72)
    bass_bar(n, chord, "walk", 86)
    frame_bar(n, "walk", 82)
    shaker_bar(n, 56)
    if k % 2 == 0:
        choir_bar(n, chord, 56 + (6 if k >= 4 else 0), bars=1)
    else:
        choir_bar(n, chord, 54 + (6 if k >= 4 else 0), bars=1)
for ring in range(3):
    n0 = 33 + 4 * ring
    last = ring == 2
    sing(balafon, n0, CALL_HOME_UP if last else CALL_HOME, 92)
    sing(kalimba, n0 + 2, ANSWER_HOME_DOWN if last else ANSWER_HOME, 90, ring=True)

# ---- kingdoms, 45-56: C G/B Am F; bells, claps, congas; the call in octaves, the choir answers -
for k in range(12):
    n = 45 + k
    chord = KING[k % 4]
    harmony[n] = chord
    mbira_bar(n, chord, MBIRA_WIDE, 84)
    nyunga_bar(n, chord, NYUNGA_HOME, 74)
    bass_bar(n, chord, "walk", 90)
    frame_bar(n, "full", 84)
    shaker_bar(n, 58)
    conga_bar(n, 84, busy=True)
    bell_bar(n, 58 + (6 if k >= 4 else 0))
    if k >= 4:
        claps_bar(n, 74)
    if k % 4 == 1:
        slit_answer(n, 80)
    if k % 4 in (0, 1):
        choir_bar(n, chord, 50)  # quiet under the call, so the answer stands out
for ring in range(3):
    n0 = 45 + 4 * ring
    last = ring == 2
    call = CALL_KING_UP if last else CALL_KING
    sing(kalimba, n0, call, 92, ring=True)
    sing(balafon, n0, call, 84, octave=-1, floor=midi("C4"))  # the balafon is sampled from C4
    sing(choir_f, n0 + 2, ANSWER_KING, 72, legato=0.97)
    for j in (2, 3):  # the male choir holds the root and fifth under the answer
        low = ladder(KING[j], 48, 62)[-2:]
        choir_m.note(T(n0 + j) + F(1, 20), 3.75, low, 60)

# ---- return, 57-64: the call with no answer; then the mbira and the frame drum alone ----------
for k in range(8):
    n = 57 + k
    chord = HOME[k % 4]
    harmony[n] = chord
    if n == 64:
        mbira_bar(n, chord, MBIRA_LAST, 70)
    else:
        mbira_bar(n, chord, MBIRA_HOME, 80 - 2 * k)
    if k < 4:
        nyunga_bar(n, chord, NYUNGA_HOME, 68 - 3 * k)
        bass_bar(n, chord, "three" if k < 3 else "long", 82 - 4 * k)
        shaker_bar(n, 50 - 4 * k)
        frame_bar(n, "walk", 78)
    elif n < 64:
        frame_bar(n, "heart", 76 - 3 * (k - 4))
sing(kalimba, 57, CALL_HOME, 84, ring=True)

END_BAR = 65
progression = [harmony[n] for n in range(1, END_BAR)]

# No note is written across the loop seam: a tine of the last bar stops at the bar line.
for clip in (mbira, nyunga, kalimba, balafon, bass, choir_f, choir_m, frame, shaker, conga, claps, bell, slit):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


#: group gains in dB, set from the section levels that dev/measure_stems.py reads. The plucks and the
#: hand drums also go through a fast compressor: their attacks set the peak, and the master limiter
#: normalizes to that peak.
GAIN = {"mbira": 0.0, "nyunga": 5.0, "kalimba": 8.0, "balafon": 12.0, "bass": -3.0, "choir": -9.0, "frame": -2.0,
        "shaker": 11.0, "conga": -3.0, "claps": 5.0, "bell": 7.0, "slit": 4.0}


def tuning(name: str) -> str:
    points = ", ".join(f"{k}: {v}" for k, v in sorted(TUNING[name].items()))
    return f"tuning_correction: {{mode: curve, interpolation: nearest, max_abs_cents: 40, points: {{{points}}}}}"


PLUCKED = "Idiophones/Plucked Idiophones"
STRUCK = "Idiophones/Struck Idiophones"
DRUMS = "Membranophones/Struck Membranophones"
score = f"""schema: ambition.musicir.v3
id: history_africa_first_footsteps
title: First Footsteps
description: >-
  The Africa floor of the History dimension, from the Cradle in the Rift
  Valley to the Timbuktu coast: the long walk that every person descends
  from. G Mixolydian at 88 BPM, every beat in three, so each bar is 12
  pulses felt as four beats and as three long steps at once. A ring of four
  chords (G Am F C) turns instead of resolving. An mbira dzaVadzimu and a
  nyunga nyunga interlock; a kalimba and a balafon call and answer; the
  Green Sahara turns to Em D C D with congas and a slit drum; the kingdoms
  ring C G/B Am F with a bell, claps, and a wordless choir that answers. The
  whole song loops back to the mbira alone. Generated by
  dev/compose_history_africa_first_footsteps.py: edit that, not this file.
notes:
  - 'Form: embers 1-8, walk 9-20, green 21-32, river 33-44, kingdoms 45-56, return 57-64; bar 64 is the left hand of the mbira only and hands to bar 1.'
  - 'Rhythm: 4/4 with the beat in three (12 pulses a bar). The frame drum, the shaker and the claps keep 4 x 3; the bass, the congas, the balafon run and the long notes of the tunes move in groups of four pulses (3 x 4).'
  - 'Every melody here is original. The bell line is a seven-stroke 12-pulse timeline, a rhythm and not a tune.'
  - 'Layered for a room: bed (mbira, nyunga, bass), drums (frame, shaker, congas, claps, bell, slit drum), tune (kalimba, balafon), voices (choir).'
seed: 1974
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: G mixolydian
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: embers, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.25, density: 0.25, loopable: true, role: 'the mbira alone, then the frame drum heartbeat'}}
  - {{id: walk, from: {{bar: 9, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.5, density: 0.55, loopable: true, role: 'the interlock; the kalimba calls, the balafon answers'}}
  - {{id: green, from: {{bar: 21, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.6, density: 0.65, loopable: true, role: 'Em D C D: the balafon runs in fours, congas, a slit drum answers'}}
  - {{id: river, from: {{bar: 33, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.65, density: 0.7, loopable: true, role: 'the balafon calls, the kalimba answers, the choir holds the chords'}}
  - {{id: kingdoms, from: {{bar: 45, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.8, density: 0.85, loopable: true, role: 'C G/B Am F: bells, claps, the call in octaves, the choir answers'}}
  - {{id: return, from: {{bar: 57, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'the call with no answer; the mbira and the frame drum, back to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: mbira, group: mbira, program: kalimba, volume: 104, pan: 64, expression: 108, {tuning("mbira")}, {vcsl(PLUCKED + "/Mbira dzaVadzimu Nyamaropa, Zimbabwe, Low B")}}}
  - {{name: nyunga, group: nyunga, program: kalimba, volume: 100, pan: 64, expression: 104, {tuning("nyunga")}, {vcsl(PLUCKED + "/Nyunga Nyunga, Mozambique, Low F")}}}
  - {{name: kalimba, group: kalimba, program: kalimba, volume: 104, pan: 64, expression: 108, {tuning("kalimba")}, {vcsl(PLUCKED + "/Kalimba, Kenya")}}}
  - {{name: balafon, group: balafon, program: marimba, volume: 102, pan: 64, expression: 106, {tuning("balafon")}, {vcsl(STRUCK + "/Balafon - Soft Mallet")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 110, pan: 64, expression: 112, {sfz("bass.upright")}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 96, pan: 64, expression: 100, {sfz("vpo.choir")}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 98, pan: 64, expression: 102, {sfz("vpo.choir_male")}}}
  - {{name: frame, group: frame, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl(DRUMS + "/Frame Drum")}}}
  - {{name: shaker, group: shaker, volume: 100, pan: 64, expression: 100, is_drum: true, {vcsl(STRUCK + "/Shaker, Small")}}}
  - {{name: conga, group: conga, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl(DRUMS + "/Conga")}}}
  - {{name: claps, group: claps, volume: 100, pan: 64, expression: 100, is_drum: true, {vcsl(STRUCK + "/Claps")}}}
  - {{name: bell, group: bell, volume: 100, pan: 64, expression: 100, is_drum: true, {vcsl(STRUCK + "/Agogo Bells")}}}
  - {{name: slit, group: slit, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl(STRUCK + "/Slit Drum")}}}
parts:
{part("mbira_part", "mbira", mbira)}
{part("nyunga_part", "nyunga", nyunga)}
{part("kalimba_part", "kalimba", kalimba)}
{part("balafon_part", "balafon", balafon)}
{part("bass_part", "bass", bass)}
{part("choir_f_part", "choir_f", choir_f)}
{part("choir_m_part", "choir_m", choir_m)}
{part("frame_part", "frame", frame)}
{part("shaker_part", "shaker", shaker)}
{part("conga_part", "conga", conga)}
{part("claps_part", "claps", claps)}
{part("bell_part", "bell", bell)}
{part("slit_part", "slit", slit)}
processing:
  groups:
    mbira:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: compressor, threshold_db: -28.0, ratio: 2.5, attack_ms: 3.0, release_ms: 90.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: {GAIN["mbira"]}}}
        - {{processor: balance, position: -0.2}}
    nyunga:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: {GAIN["nyunga"]}}}
        - {{processor: balance, position: 0.25}}
    kalimba:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: compressor, threshold_db: -28.0, ratio: 2.5, attack_ms: 3.0, release_ms: 90.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: {GAIN["kalimba"]}}}
        - {{processor: balance, position: 0.1}}
    balafon:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: {GAIN["balafon"]}}}
        - {{processor: balance, position: -0.1}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3000}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 15.0, release_ms: 120.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 110}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: {GAIN["choir"]}}}
    frame:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: compressor, threshold_db: -26.0, ratio: 3.0, attack_ms: 2.0, release_ms: 80.0, makeup_db: 0.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["frame"]}}}
    shaker:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: {GAIN["shaker"]}}}
        - {{processor: balance, position: 0.35}}
    conga:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: compressor, threshold_db: -26.0, ratio: 3.0, attack_ms: 2.0, release_ms: 80.0, makeup_db: 0.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["conga"]}}}
        - {{processor: balance, position: -0.3}}
    claps:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {GAIN["claps"]}}}
    bell:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["bell"]}}}
        - {{processor: balance, position: 0.4}}
    slit:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {GAIN["slit"]}}}
        - {{processor: balance, position: -0.35}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      # The plucks and the hand drums make a crest of 22 dB (the sustained History cues: 17 to 19).
      # A fast limiter takes the few attack peaks down about 3 dB, so the cue normalizes near the
      # others (-18.6 LUFS against -20.9 without it, measured with dev/remix_from_stems.py).
      - {{processor: gain, gain_db: 2.0}}
      - processor: pedalboard
        effects:
          - {{effect: limiter, threshold_db: -5.0, release_ms: 60.0}}
      # -2.2, not the usual -1.5: the limited attacks come out of the Ogg encoder 0.7 dB higher,
      # over the -1 dBTP ceiling of `audit levels`.
      - {{processor: limiter, target_peak_db: -2.2, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [mbira, nyunga, bass]
    drums: [frame, shaker, conga, claps, bell, slit]
    tune: [kalimba, balafon]
    voices: [choir]
  sections:
    - {{id: song, form: [embers, walk, green, river, kingdoms, return], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

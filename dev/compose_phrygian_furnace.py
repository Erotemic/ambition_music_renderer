"""The Phrygian Furnace: fast heavy metal in D Phrygian dominant, with twin
lead guitars. Writes its MusicIR v3 score:

    python3 dev/compose_phrygian_furnace.py scores/active/phrygian_furnace.music.yaml

Jon, 2026-10-19, after The Tritone Decree: "I want you to write another
heavy metal song. The first one was great." So this one is its own thing:
where the Decree is a Locrian gallop with strings and choir, this is thrash
at 168 BPM in D Phrygian dominant (D Eb F# G A Bb C), whose flat second and
augmented second (Eb to F#) give it its heat, sung by two lead guitars a
third apart, with low horns under the chorus.

Only D, Eb, G and C carry a perfect fifth in the mode, so only they are
power chords; the other degrees are octaves.

Form, 4/4 at 168 BPM:
  intro       1-8    one guitar sings the chorus slowly over a horn drone,
                      then the band hits D and Eb.
  verse       9-24   the skank-beat riff on D.                   (loop start)
  climb       25-32  half time: G, C, Eb, D, rising to the chorus.
  chorus      33-48  twin leads in thirds, horns an octave under, double kick.
  grind       49-56  a syncopated breakdown on D with Eb stabs.
  solo        57-72  a lead solo through the mode's augmented second.
  chorus2     73-80  the second half of the chorus.
  turnaround  81-84  the riff and the Eb-D hits back into the verse.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 168
OUT = Path(sys.argv[1])
rng = random.Random(1968)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


MODE = [midi(n) % 12 for n in ("D4", "Eb4", "F#4", "G4", "A4", "Bb4", "C5")]


def third_below(pitch: int) -> int:
    """The mode's note a third (two degrees) below `pitch`."""
    candidates = [p for p in range(pitch - 5, pitch - 2) if p % 12 in MODE]
    return candidates[-1] if pitch % 12 in MODE else pitch - 3


#: Jon hears high lead guitar as piercing: no lead note above A5.
TOP = midi("A5")


def step(pitch: int, direction: int) -> int:
    """The next note of the mode up (+1) or down (-1) from `pitch`."""
    pitch += direction
    while pitch % 12 not in MODE:
        pitch += direction
    return pitch


#: The pitch classes of each chord the harmony names.
CHORD_PCS = {
    "D": {2, 6, 9}, "Gm": {7, 10, 2}, "Eb": {3, 7, 10}, "Cm": {0, 3, 7},
}


def twin_under(pitch: int, chord: str, held: bool) -> int:
    """The twin's note under the lead: on a held note, the nearest tone of the
    chord below it (a third below can be a semitone off the chord: Bb under D
    over D); on a passing note, the mode's third below."""
    if held:
        for below in range(pitch - 3, pitch - 10, -1):
            if below % 12 in CHORD_PCS[chord]:
                return below
    return third_below(pitch)


def frac(beats) -> str:
    """Beats as a fraction of a whole note, on whole ticks of ppq 960. Always
    a fraction: a bare integer is a tick offset."""
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


class Clip:
    """Exact events of one clip, in beats from bar 1."""

    def __init__(self, jitter_ms: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.jitter = jitter_ms / 1000.0 * BPM / 60.0
        self.vel_jitter = vel_jitter

    def note(self, at, dur, pitches, vel):
        at = F(at).limit_denominator(960)
        if self.jitter and at > 0:
            at += F(rng.uniform(-self.jitter, self.jitter)).limit_denominator(960)
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


def bar(n: int) -> float:
    """The beat score bar `n` (1-based) starts on."""
    return (n - 1) * 4.0


D2, Eb2, Fs2, G2, A2, Bb2, C3 = (midi(n) for n in ("D2", "Eb2", "F#2", "G2", "A2", "Bb2", "C3"))
FIFTHS = {D2 % 12, Eb2 % 12, G2 % 12, C3 % 12}


def chord(root: int) -> list[int]:
    """A power chord where the mode has the fifth; an octave where it does not."""
    return [root, root + 7, root + 12] if root % 12 in FIFTHS else [root, root + 12]


def mute(root: int) -> list[int]:
    """The two low strings of a palm-muted chug."""
    return [root, root + 7] if root % 12 in FIFTHS else [root, root + 12]


rhythm_l = Clip(jitter_ms=4, vel_jitter=4)
rhythm_r = Clip(jitter_ms=4, vel_jitter=4)
bass = Clip(jitter_ms=3, vel_jitter=3)
kit = Clip(jitter_ms=2, vel_jitter=4)
lead = Clip(jitter_ms=2, vel_jitter=3)
twin = Clip(jitter_ms=3, vel_jitter=3)
horns = Clip()
rhythms = (rhythm_l, rhythm_r)


def both(at, dur, pitches, vel):
    for r in rhythms:
        r.note(at, dur, pitches, vel)


# ---- Drums (GM keys of the Muldjord kit) -----------------------------------
KICK, SNARE, HAT, OPEN_HAT, CRASH, CHINA, RIDE, RIDE_BELL, FLOOR, MID, HIGH = 36, 38, 42, 46, 49, 52, 51, 53, 41, 45, 48


def drums(n: int, style: str, crash=False):
    t = bar(n)
    if style == "skank":  # thrash: kick on the beat, snare on the off-beat
        for beat in range(4):
            kit.note(t + beat, 0.1, KICK, 110)
            kit.note(t + beat + 0.5, 0.1, SNARE, 108 if beat % 2 else 100)
            kit.note(t + beat, 0.1, RIDE, 80)
            kit.note(t + beat + 0.5, 0.1, RIDE, 64)
    elif style == "half":  # half time, the kick doubled in eighths
        for i in range(8):
            kit.note(t + 0.5 * i, 0.08, KICK, 104 if i % 2 == 0 else 92)
            kit.note(t + 0.5 * i, 0.07, HAT, 76 if i % 2 == 0 else 58)
        kit.note(t + 2, 0.14, SNARE, 122)
    elif style == "double":  # chorus: double kick sixteenths, snare on 2 and 4
        for i in range(16):
            kit.note(t + 0.25 * i, 0.07, KICK, 100 if i % 2 == 0 else 88)
        for beat in range(4):
            kit.note(t + beat, 0.1, RIDE_BELL if beat % 2 == 0 else RIDE, 82)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 120)
    elif style == "grind":  # breakdown: the kick with the chug, china on one
        for o in (0, 0.75, 1.5, 2.5, 3.0):
            kit.note(t + o, 0.1, KICK, 114)
        kit.note(t + 1, 0.14, SNARE, 118)
        kit.note(t + 3, 0.14, SNARE, 118)
        kit.note(t, 0.3, CHINA, 104)
        for beat in (1, 2, 3):
            kit.note(t + beat, 0.1, RIDE_BELL, 78)
    elif style == "gallop":
        for beat in range(4):
            for o, v in ((0, 110), (0.5, 96), (0.75, 100)):
                kit.note(t + beat + o, 0.1, KICK, v)
            kit.note(t + beat, 0.1, RIDE, 80)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 118)
    elif style == "toms":
        for beat in range(4):
            kit.note(t + beat, 0.2, FLOOR, 100 + 4 * beat)
    if crash:
        kit.note(t, 0.6, CRASH, 118)
        kit.note(t, 0.12, KICK, 122)


def fill(n: int, start=2.0):
    t = bar(n)
    toms = [SNARE, SNARE, HIGH, HIGH, MID, MID, FLOOR, FLOOR]
    count = int((4 - start) / 0.25)
    for i in range(count):
        kit.note(t + start + 0.25 * i, 0.1, toms[min(7, i * 8 // count)], 96 + 3 * i)
        if i % 2 == 0:
            kit.note(t + start + 0.25 * i, 0.08, KICK, 100)


# ---- Shred vocabulary ------------------------------------------------------------
def play(clip: Clip, at: float, notes: list[int], sub: float, vel: int = 100, twin_too: bool = False) -> float:
    """`notes` one after another, `sub` beats each; with `twin_too` the twin
    plays them a third below. Returns the beat after the last note."""
    for i, pitch in enumerate(notes):
        pitch = min(pitch, TOP)
        accent = 8 if i % 4 == 0 else 0
        clip.note(at + i * sub, sub * 0.9, pitch, vel + accent)
        if twin_too:
            twin.note(at + i * sub, sub * 0.9, third_below(pitch), vel - 6 + accent)
    return at + len(notes) * sub


def scale_run(start: str, count: int, direction: int) -> list[int]:
    """`count` notes of the mode from `start`, up or down."""
    notes = [midi(start)]
    for _ in range(count - 1):
        notes.append(step(notes[-1], direction))
    return notes


def fours_down(top: str, groups: int) -> list[int]:
    """The shred sequence: four notes down the mode, each group a step lower."""
    out, head = [], midi(top)
    for _ in range(groups):
        group = [head]
        for _ in range(3):
            group.append(step(group[-1], -1))
        out += group
        head = step(head, -1)
    return out


def threes_up(bottom: str, groups: int) -> list[int]:
    """Three notes up the mode, each group a step higher (for sixteenth triplets)."""
    out, head = [], midi(bottom)
    for _ in range(groups):
        out += [head, step(head, 1), step(step(head, 1), 1)]
        head = step(head, 1)
    return out


def pedal(anchor: str, line: list[str]) -> list[int]:
    """A pedal-point lick: the line, each note answered by the anchor."""
    out = []
    for name in line:
        out += [midi(name), midi(anchor)]
    return out


def sweep(chord_notes: list[str]) -> list[int]:
    """A sweep: up the arpeggio and back down."""
    up = [midi(n) for n in chord_notes]
    return up + up[-2::-1]


# ---- The verse riff ---------------------------------------------------------
def riff(n: int, variant: str, vel=100):
    """Two bars of the furnace riff: palm-muted D eighths with the flat second
    pushing at them, and an answer that climbs the mode."""
    t = bar(n)
    first = [D2, D2, Eb2, D2, D2, D2, Fs2, G2]
    for i, root in enumerate(first):
        accent = root != D2
        both(t + 0.5 * i, 0.42 if accent else 0.16, chord(root) if accent else mute(root), vel + (12 if accent else 0))
        bass.note(t + 0.5 * i, 0.45, root, 96 + (10 if accent else 0))
    t += 4
    if variant == "a":
        hits = [(0, D2, 0.5, False), (0.5, D2, 0.5, False), (1.0, Eb2, 0.5, False), (1.5, D2, 0.5, False),
                (2.0, G2, 0.75, True), (2.75, Fs2, 0.25, True), (3.0, Eb2, 0.5, True), (3.5, C3, 0.5, True)]
    else:
        hits = [(0, D2, 0.5, False), (0.5, D2, 0.5, False), (1.0, Eb2, 0.5, False), (1.5, D2, 0.5, False),
                (2.0, C3, 0.5, True), (2.5, Bb2, 0.5, True), (3.0, A2, 0.5, True), (3.5, Eb2, 0.5, True)]
    for o, root, dur, accent in hits:
        both(t + o, dur - 0.08 if accent else 0.16, chord(root) if accent else mute(root), vel + (14 if accent else 0))
        bass.note(t + o, dur - 0.05, root, 98 + (10 if accent else 0))


# ---- The chorus: twin leads ----------------------------------------------------
CHORUS = [
    [("D4", 2), ("Eb4", 1), ("F#4", 1)],
    [("G4", 2), ("F#4", 1), ("Eb4", 1)],
    [("D4", 1), ("C4", 1), ("Bb3", 1), ("C4", 1)],
    [("D4", 4)],
    [("A4", 2), ("G4", 1), ("F#4", 1)],
    [("G4", 1.5), ("A4", 0.5), ("Bb4", 2)],
    [("A4", 1), ("G4", 1), ("F#4", 1), ("Eb4", 1)],
    [("D4", 3)],
    [("F#4", 2), ("G4", 1), ("A4", 1)],
    [("Bb4", 2), ("A4", 1), ("G4", 1)],
    [("F#4", 1), ("G4", 1), ("A4", 1), ("Bb4", 1)],
    [("C5", 4)],
    [("Bb4", 2), ("A4", 1), ("G4", 1)],
    [("A4", 2), ("G4", 1), ("F#4", 1)],
    [("Eb4", 1), ("F#4", 1), ("Eb4", 1), ("C4", 1)],
    [("D4", 4)],
]
CHORUS_ROOTS = [D2, G2, Eb2, D2, D2, G2, C3, D2, D2, G2, D2, C3, G2, D2, Eb2, D2]
CHORUS_CHORDS = ["D", "Gm", "Eb", "D", "D", "Gm", "Cm", "D", "D", "Gm", "D", "Cm", "Gm", "D", "Eb", "D"]


def chorus(n: int, bars=range(16), vel=100, octave=0, slow=1):
    """The chorus melody on the lead guitar, a third below on the twin, and the
    horns an octave under the lead. `slow`: each bar of melody takes this many
    bars (the intro sings it at half speed)."""
    for k, i in enumerate(bars):
        beat = 0.0
        for name, dur in CHORUS[i]:
            at = bar(n) + (k * 4 + beat) * slow
            pitch = midi(name) + 12 * octave
            accent = 8 if beat == 0 else 0
            length = dur * slow * 0.96
            lead.note(at, length, pitch, vel + accent)
            if slow == 1:
                twin.note(at, length, twin_under(pitch, CHORUS_CHORDS[i], dur >= 1), vel - 6 + accent)
                horns.note(at, length, pitch - 12, vel - 18 + accent)
            beat += dur


def chug_bar(n: int, root: int, vel=96, style="eighths"):
    t = bar(n)
    if style == "eighths":
        for i in range(8):
            accent = i in (0, 3, 6)
            both(t + 0.5 * i, 0.4 if accent else 0.16, chord(root) if accent else mute(root), vel - 8 + (14 if accent else 0))
            bass.note(t + 0.5 * i, 0.45, root, 92 + (8 if accent else 0))
    elif style == "whole":
        both(t, 3.9, chord(root), vel + 10)
        bass.note(t, 3.9, root, 106)
        for o in (2.5, 3.0, 3.5):
            both(t + o, 0.16, mute(root), vel - 12)


harmony: dict[int, str] = {}

# Intro, bars 1-8.
chorus(1, bars=range(2), vel=88, octave=0, slow=2)  # one guitar, the first two bars of the chorus at half speed
horns.note(bar(1), 15.8, [midi("D3"), midi("A3")], 66)
bass.note(bar(1), 15.8, D2, 74)
for n in range(1, 5):
    kit.note(bar(n), 0.4, FLOOR, 92 + 4 * n)
    kit.note(bar(n) + 2, 0.4, FLOOR, 84 + 4 * n)
    harmony[n] = "D"
kit.note(bar(1), 2.0, CRASH, 90)
for k, n in enumerate(range(5, 9)):
    root = (D2, Eb2, D2, Eb2)[k]
    both(bar(n), 1.4, chord(root), 118)
    both(bar(n) + 1.5, 0.4, chord(root), 112)
    both(bar(n) + 2.5, 1.3, chord(root), 116)
    bass.note(bar(n), 1.4, root, 112)
    bass.note(bar(n) + 1.5, 0.4, root, 104)
    bass.note(bar(n) + 2.5, 1.3, root, 110)
    horns.note(bar(n), 1.4, root + 24, 96)
    drums(n, "half", crash=True)
    harmony[n] = ("D", "Eb", "D", "Eb")[k]
    # Over each hit, the lead tears down the mode into it (bar 8 has its own run).
    if n < 8:
        play(lead, bar(n) + 2.5, fours_down(("A5", "G5", "A5", "A5")[k], 1) + scale_run(("F#5", "Eb5", "F#5", "G5")[k], 2, -1), 0.25, 100)
play(lead, bar(8), threes_up("D4", 4) + threes_up("A4", 1) + [midi("D5")], 0.25, 98)
fill(8, 2.0)

# Verse, bars 9-24 (the loop starts here).
for n, v in ((9, "a"), (11, "b"), (13, "a"), (15, "b"), (17, "a"), (19, "b"), (21, "a"), (23, "b")):
    riff(n, v)
    harmony.update({n: "D", n + 1: "D"})
for n in range(9, 25):
    drums(n, "skank", crash=n in (9, 17))
# A lead fill in the gap at the end of each four bars of the riff.
VERSE_FILLS = {
    12: fours_down("A5", 2),
    16: scale_run("D4", 8, 1),
    20: pedal("D5", ["A4", "Bb4", "C5", "Bb4"]),
    24: fours_down("G5", 1) + scale_run("D5", 4, -1),
}
for n, notes in VERSE_FILLS.items():
    play(lead, bar(n) + 2.0, notes, 0.25, 98)
fill(24, 3.0)

# Climb, bars 25-32: half time on G, C, Eb, D, twice; the horns swell.
CLIMB = [G2, C3, Eb2, D2] * 2
CLIMB_CHORDS = ["Gm", "Cm", "Eb", "D"] * 2
for k in range(8):
    n = 25 + k
    chug_bar(n, CLIMB[k], vel=100, style="whole")
    horns.note(bar(n), 3.8, [CLIMB[k] + 12, CLIMB[k] + 19] if CLIMB[k] % 12 in FIFTHS else [CLIMB[k] + 12], 78 + 3 * k)
    drums(n, "half", crash=k % 2 == 0)
    harmony[n] = CLIMB_CHORDS[k]
fill(32, 2.0)

# Chorus, bars 33-48.
for k in range(16):
    n = 33 + k
    chug_bar(n, CHORUS_ROOTS[k], vel=98)
    drums(n, "double", crash=k % 4 == 0)
    harmony[n] = CHORUS_CHORDS[k]
chorus(33, vel=100)
fill(48, 3.0)

# Grind, bars 49-56: syncopated chugs on D, Eb stabs, then the climb back.
for k in range(8):
    n = 49 + k
    t = bar(n)
    for o in (0, 0.75, 1.5, 2.5, 3.0):
        root = Eb2 if (o == 3.0 and k % 2) else D2
        both(t + o, 0.5 if o in (0, 1.5) else 0.2, chord(root) if o in (0, 1.5) or root == Eb2 else mute(root), 116)
        bass.note(t + o, 0.5 if o in (0, 1.5) else 0.2, root, 110)
    if k >= 4:
        # D held under the chug; the Eb stab of the odd bars is the horns' too.
        horns.note(t, 2.9 if k % 2 else 3.8, [midi("D3"), midi("A3")], 90)
        if k % 2:
            horns.note(t + 3.0, 0.9, [midi("Eb3"), midi("Bb3")], 98)
    drums(n, "grind", crash=k in (0, 4))
    harmony[n] = "D"
fill(56, 2.0)

# Solo, bars 57-72, over D, Eb, D, C: the shred.
SOLO_ROOTS = [D2, Eb2, D2, C3] * 4
SOLO_CHORDS = ["D", "Eb", "D", "Cm"] * 4
for k in range(16):
    n = 57 + k
    chug_bar(n, SOLO_ROOTS[k], vel=92)
    drums(n, "gallop" if k < 8 else "double", crash=k % 4 == 0)
    harmony[n] = SOLO_CHORDS[k]
# 57-60: up the neck, a held note, then down in fours.
t = play(lead, bar(57), scale_run("D4", 8, 1), 0.25)
lead.note(t, 1.9, midi("F#5"), 108)
play(lead, bar(58), fours_down("F#5", 4), 0.25)
t = play(lead, bar(59), pedal("D5", ["A4", "Bb4", "C5", "Bb4", "A4", "G4", "F#4", "G4"]), 0.25)
play(lead, bar(60), sweep(["D4", "F#4", "A4", "D5", "F#5", "A5"]), 1 / 6)
play(lead, bar(60) + 2.0, scale_run("G5", 6, -1), 1 / 3)
# 61-64: sixteenth-note triplet climbs and the augmented second.
play(lead, bar(61), threes_up("D4", 8), 1 / 6)
play(lead, bar(62), pedal("Eb5", ["F#4", "G4", "A4", "Bb4", "C5", "Bb4", "A4", "G4"]), 0.25)
play(lead, bar(63), fours_down("A5", 4), 0.25)
play(lead, bar(64), sweep(["C4", "Eb4", "G4", "C5", "Eb5", "G5"]), 1 / 6)
play(lead, bar(64) + 11 / 6, scale_run("F#5", 6, -1), 1 / 3)
# 65-68: the trade: the lead takes two beats, the twin answers.
for k, n in enumerate(range(65, 69)):
    play(lead, bar(n), fours_down(("A5", "G5", "A5", "F#5")[k], 2), 0.25)
    play(twin, bar(n) + 2.0, scale_run(("D4", "Eb4", "F#4", "A4")[k], 8, 1), 0.25, 98)
# 69-72: both guitars in thirds, flat out.
play(lead, bar(69), fours_down("A5", 4), 0.25, twin_too=True)
play(lead, bar(70), threes_up("D5", 4) + threes_up("G4", 4), 1 / 6, twin_too=True)
play(lead, bar(71), pedal("D5", ["A4", "Bb4", "C5", "Bb4", "A4", "G4", "F#4", "G4"]), 0.25, twin_too=True)
t = play(lead, bar(72), scale_run("D4", 8, 1), 0.25, twin_too=True)
lead.note(t, 1.9, midi("D5"), 110)
twin.note(t, 1.9, midi("Bb4"), 104)
fill(72, 3.0)

# Chorus 2, bars 73-80: the chorus's second half, everything.
for k in range(8):
    n = 73 + k
    chug_bar(n, CHORUS_ROOTS[8 + k], vel=102)
    drums(n, "double", crash=k % 2 == 0)
    harmony[n] = CHORUS_CHORDS[8 + k]
chorus(73, bars=range(8, 16), vel=104)
fill(80, 3.0)

# Turnaround, bars 81-84: the riff, then Eb and D hits back into the verse.
riff(81, "a", vel=104)
harmony.update({81: "D", 82: "D"})
drums(81, "skank", crash=True)
drums(82, "skank")
for k, n in enumerate((83, 84)):
    for o, root in ((0, Eb2), (1.5, Eb2), (3.0, D2)) if k == 0 else ((0, Eb2), (0.75, Eb2), (1.5, D2)):
        both(bar(n) + o, 1.2, chord(root), 120)
        bass.note(bar(n) + o, 1.2, root, 112)
        horns.note(bar(n) + o, 1.2, root + 24, 100)
        kit.note(bar(n) + o, 0.4, CRASH if o == 0 else CHINA, 112)
        kit.note(bar(n) + o, 0.12, KICK, 120)
    harmony[n] = "Eb"
fill(84, 2.0)

END_BAR = 85
progression = [harmony.get(n, "D") for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


HIGH_GAIN = """        - processor: pedalboard
          effects:
            - {effect: gain, gain_db: %(pre)s}
            - {effect: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 6.0, release_ms: 90.0}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gxts9#ts9sim
          binary: lv2apply
          channel_mode: dual_mono
          wet_mix: 0.62
          params: {fslider0_: -3.0, fslider1_: 720.0, fslider2_: 0.8, BYPASS: 1.0}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.66
          params: {P6v: 0.82, Middle: 0.56, Bass: 0.56, Treble: 0.6, WET_DRY: 66.0, GAIN: -1.0}"""

RHYTHM_TAIL = """        - {{processor: highpass, cutoff_hz: 85}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 330, q: 1.0, db: -2.5}}
            - {{type: peak, hz: 1500, q: 0.9, db: 1.5}}
            - {{type: peak, hz: 3400, q: 1.2, db: -3.0}}
            - {{type: peak, hz: 4900, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 6800}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 2.5, attack_ms: 6.0, release_ms: 80.0}}
        - {{processor: balance, position: {pos}}}"""

LEAD_TAIL = """        - {{processor: highpass, cutoff_hz: 120}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 700, q: 0.8, db: 1.5}}
            - {{type: peak, hz: 3000, q: 0.8, db: -3.5}}
            - {{type: peak, hz: 4130, q: 3.0, db: -3.0}}
            - {{type: peak, hz: 4920, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 5600}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 7.0, release_ms: 90.0}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: 268, feedback: 0.2, mix: 0.14}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {gain}}}
        - {{processor: balance, position: {pos}}}"""

GUITAR = "instrument_backend: {kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {fold_to_range: false}}"

score = f"""schema: ambition.musicir.v3
id: phrygian_furnace
title: The Phrygian Furnace
description: >-
  Thrash metal in D Phrygian dominant at 168 BPM: a skank-beat riff on D with
  the flat second pushing at it, a half-time climb, a chorus for two lead
  guitars a third apart over low horns and double kick, a syncopated
  breakdown, and a solo through the mode's augmented second. Composed from
  first principles (Jon, 2026-10-19: "write another heavy metal song").
  Generated by dev/compose_phrygian_furnace.py: edit that, not this file.
notes:
  - 'D Phrygian dominant: D Eb F# G A Bb C. Only D, Eb, G and C carry a perfect fifth, so only they are power chords.'
  - 'The intro plays once; the loop is bars 9-84, and its turnaround hits Eb and D back into the verse riff.'
  - 'Rhythm guitars are two takes of one part, panned hard left and right; the lead and its twin are panned a little apart.'
seed: 1968
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: {{tonic: D, mode: phrygian}}
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.6, density: 0.4, role: 'one guitar sings the chorus slowly over a horn drone; the band hits D and Eb'}}
  - {{id: verse, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.85, density: 0.8, loopable: true, role: 'the skank-beat riff'}}
  - {{id: climb, from: {{bar: 25, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.8, density: 0.6, loopable: true, role: 'half time, rising to the chorus'}}
  - {{id: chorus, from: {{bar: 33, beat: 1}}, to: {{bar: 49, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'twin leads, horns, double kick'}}
  - {{id: grind, from: {{bar: 49, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.9, density: 0.6, loopable: true, role: 'the breakdown'}}
  - {{id: solo, from: {{bar: 57, beat: 1}}, to: {{bar: 73, beat: 1}}, energy: 0.95, density: 0.85, loopable: true, role: 'the lead solo; the twin joins at the end'}}
  - {{id: chorus2, from: {{bar: 73, beat: 1}}, to: {{bar: 81, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the chorus again, everything'}}
  - {{id: turnaround, from: {{bar: 81, beat: 1}}, to: {{bar: 85, beat: 1}}, energy: 0.9, density: 0.8, loopable: true, role: 'the riff and the Eb-D hits back into the verse'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: rhythm_l, group: rhythm_l, program: distortion_guitar, volume: 110, pan: 64, expression: 112, {GUITAR}}}
  - {{name: rhythm_r, group: rhythm_r, program: distortion_guitar, volume: 110, pan: 64, expression: 112, {GUITAR}}}
  - {{name: lead, group: lead, program: distortion_guitar, volume: 104, pan: 64, expression: 112, {GUITAR}}}
  - {{name: twin, group: twin, program: distortion_guitar, volume: 104, pan: 64, expression: 112, controls: {{111: 0, 114: 52, 116: 20}}, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndGreenGuitars/Programs/02-black_keyswitch.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: bass, group: bass, program: picked_bass, volume: 116, pan: 64, expression: 116, mix_gain_db: 6.0, instrument_backend: {{kind: sfz, library_ref: bass.growly}}}}
  - {{name: horns, group: horns, program: french_horn, volume: 104, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.horns_sustain}}}}
  - {{name: kit, group: drums, volume: 124, pan: 64, expression: 120, is_drum: true, mix_gain_db: 1.0, instrument_backend: {{kind: sfz, library_ref: drums.muldjord}}}}
parts:
{part("rhythm_l_part", "rhythm_l", rhythm_l)}
{part("rhythm_r_part", "rhythm_r", rhythm_r)}
{part("lead_part", "lead", lead)}
{part("twin_part", "twin", twin)}
{part("bass_part", "bass", bass)}
{part("horns_part", "horns", horns)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    rhythm_l:
      chain:
{HIGH_GAIN % {"pre": "14.0"}}
{RHYTHM_TAIL.format(pos=-0.85)}
    rhythm_r:
      chain:
{HIGH_GAIN % {"pre": "14.0"}}
{RHYTHM_TAIL.format(pos=0.85)}
    lead:
      chain:
{HIGH_GAIN % {"pre": "12.0"}}
{LEAD_TAIL.format(gain=3.0, pos=-0.3)}
    twin:
      chain:
{HIGH_GAIN % {"pre": "12.0"}}
{LEAD_TAIL.format(gain=1.0, pos=0.3)}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 32}}
        - processor: pedalboard
          effects:
            - {{effect: distortion, drive_db: 4.0}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 80, q: 0.8, db: 2.0}}
            - {{type: peak, hz: 250, q: 0.9, db: -1.5}}
            - {{type: peak, hz: 900, q: 1.0, db: 1.0}}
        - {{processor: lowpass, cutoff_hz: 3200}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 15.0, release_ms: 110.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -2.0}}
    horns:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 4.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 70, q: 1.0, db: 2.0}}
            - {{type: peak, hz: 400, q: 1.0, db: -2.0}}
            - {{type: peak, hz: 3500, q: 1.0, db: 1.5}}
        - {{processor: lowpass, cutoff_hz: 12500}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.4, attack_ms: 12.0, release_ms: 80.0, makeup_db: 1.5}}
        - {{processor: gain, gain_db: -2.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 34}}
      - processor: parametric_eq
        bands:
          - {{type: peak, hz: 380, q: 0.8, db: -1.5}}
      - {{processor: compressor, threshold_db: -17.0, ratio: 3.0, attack_ms: 10.0, release_ms: 90.0, makeup_db: 2.0, knee_db: 6.0}}
      - {{processor: reverb, wet: 0.04, decay_seconds: 1.3}}
      - {{processor: stereo_width, amount: 0.06}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.92, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    band: [rhythm_l, rhythm_r, bass, drums]
    horns: [horns]
    lead: [lead, twin]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [verse, climb, chorus, grind, solo, chorus2, turnaround], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

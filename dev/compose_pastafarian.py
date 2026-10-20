"""Pastafarian: reggae for the Noodle dimension, with a noodly lead guitar.
Writes its MusicIR v3 score:

    python3 dev/compose_pastafarian.py scores/active/pastafarian.music.yaml

A double-time feel (the skank on every off-beat, the one drop on two and four)
was tried as an A/B on 2026-10-20; Jon: "A is better. B feels too fast."

Jon, 2026-10-20: "a new tune for the Noodle dimension, which has a Reggae vibe.
"Pastafarian". It also has a noodly guitar vibe too, and depending on the tune
it can incorporate choirs for a holy vibe, but for this song exclude that, as
that is only for when the FSM is around or invoked." So: NO CHOIR here.

The reggae, from the inside out:
  - The one drop: in the verses the kick and a cross-stick land together on
    beat THREE, beat one is empty, and the hats shuffle. The hook goes to
    "steppers", a kick on every beat, for lift.
  - The skank: a short, bright chop of the chord on two and four, now and
    then doubled.
  - The organ bubble: the chord on every off-beat eighth, a soft low note on
    the sixteenth before it.
  - The bass is the song's spine: deep, round, melodic, and it leaves holes.
  - The dub break strips to bass and drums, and the skank comes back through
    a long echo.
The noodle: the lead guitar sings the tune with slides into its long notes
(pitch bends from below), hammered grace notes and quick runs, and noodles in
every gap the horns leave. Held lead notes stay at or below A5 (Jon hears high
lead guitar as piercing).

Form, 4/4 at 76 BPM, G major:
  intro   1-4    a drum roll, then skank, organ and the lead's opening noodle.
  verse   5-20   one drop; the lead plays the tune over G C D C, twice.   (loop start)
  hook    21-28  steppers; horns take the hook over G D Em C, the lead answers.
  dub     29-36  bass and drums; the skank through a long echo; the lead throws single notes.
  solo    37-44  the lead noodles over Em C Am D.
  hook    45-52  the hook again, horns and lead together.
  outro   53-56  the verse turnaround, the run up, home to D for the loop.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 76
OUT = Path(sys.argv[1])

rng = random.Random(1717)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: The second eighth of each beat lands this far into it. Straight: Jon heard
#: the first draft's shuffle (the eighths late, the sixteenths not) as a groove
#: that was "trying to be classic reggae, but missing".
SHUFFLE = 0.5
#: Pitch-bend units a cent: the Shiny guitar bends 200 cents.
BEND_PER_CENT = 8192 / 200


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def sh(beat: float) -> float:
    """``beat`` on the shuffled eighth grid."""
    whole, rest = divmod(beat, 1.0)
    if abs(rest - 0.5) < 1e-6:
        rest = SHUFFLE
    return whole + rest


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.bends: list[tuple] = []
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
        return at

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        if self.bends:
            lines.append(f"{indent}  automation:")
            seen = {}
            for when, value in sorted(self.bends):
                seen[frac(when)] = value  # a later point at the same tick wins
            for i, (when, value) in enumerate(seen.items()):
                lines.append(f"{indent}    - {{id: {clip_id}_bend_{i:04d}, at: {when}, pitch_bend: {value}}}")
        return "\n".join(lines)


def bar(n: int) -> float:
    return (n - 1) * 4.0


lead = Clip(drift=0.004, vel_jitter=4)
horns_tp = Clip(drift=0.01, vel_jitter=3)
horns_tb = Clip(drift=0.01, vel_jitter=3)
horns_sx = Clip(drift=0.01, vel_jitter=3)
skank = Clip(drift=0.002, vel_jitter=4)
dub = Clip(drift=0.006, vel_jitter=4)
organ = Clip(drift=0.002, vel_jitter=4)
bass = Clip(drift=0.003, vel_jitter=3)
kit = Clip(drift=0.003, vel_jitter=4)
hats = Clip(drift=0.004, vel_jitter=6)

# ---- Harmony ------------------------------------------------------------------------
TRIAD = {"G": ["G", "B", "D"], "C": ["C", "E", "G"], "D": ["D", "F#", "A"], "Em": ["E", "G", "B"], "Am": ["A", "C", "E"]}
#: The skank's bright upper voicing, and the organ's middle one.
SKANK = {"G": ["B3", "D4", "G4"], "C": ["C4", "E4", "G4"], "D": ["A3", "D4", "F#4"], "Em": ["B3", "E4", "G4"], "Am": ["A3", "C4", "E4"]}
ORGAN = {"G": ["G3", "B3", "D4"], "C": ["G3", "C4", "E4"], "D": ["F#3", "A3", "D4"], "Em": ["G3", "B3", "E4"], "Am": ["A3", "C4", "E4"]}
ROOT = {"G": "G1", "C": "C2", "D": "D2", "Em": "E2", "Am": "A1"}
VERSE = ["G", "C", "D", "C"]
HOOK = ["G", "D", "Em", "C"]
SOLO = ["Em", "C", "Am", "D"]
harmony: dict[int, str] = {}


def skank_bar(n: int, name: str, vel=74, double=False, clip=None):
    """The chop on two and four, short and bright; `double` adds the 'chk-chk'
    sixteenth after four."""
    clip = clip or skank
    t = bar(n)
    for o in (1.0, 3.0):
        clip.note(t + o, 0.16, SKANK[name], vel)
    if double:
        clip.note(t + 3.25, 0.12, SKANK[name], vel - 14)


def bubble(n: int, name: str, vel=60):
    """The organ bubble: between every two beats, the chord on the 'and' and
    again, softer, on the 'a' -- the double hit that bubbles."""
    t = bar(n)
    for k in range(4):
        organ.note(t + k + 0.5, 0.2, ORGAN[name], vel)
        organ.note(t + k + 0.75, 0.16, ORGAN[name], vel - 14)


def bassline(n: int, name: str, nxt: str, figure: int, vel=92):
    """The spine: deep and round, with holes. Figure 0 waits out beat one; figure
    1 lands on it; figure 2 is the dub's, a few long notes and silence."""
    t = bar(n)
    r = midi(ROOT[name])
    tones = [midi(x + "2") % 12 for x in TRIAD[name]]
    third = r + (tones[1] - tones[0]) % 12
    fifth = r + 7
    nxt_root = midi(ROOT[nxt])
    # the step into the next root from the scale tone below it (G major)
    approach = nxt_root - (1 if nxt_root % 12 in (7, 0) else 2)
    if figure == 0:  # one drop: beat one empty, the weight on three with the drop
        bass.note(t + 0.5, 0.45, r, vel - 6)
        bass.note(t + 1.0, 0.9, r, vel)
        bass.note(t + 2.0, 1.0, fifth if name in ("C", "D") else r + 12, vel + 2)
        bass.note(t + 3.0, 0.45, third, vel - 8)
        bass.note(t + 3.5, 0.45, approach, vel - 10)
    elif figure == 1:  # steppers: on the beat, the root driving
        bass.note(t, 0.9, r, vel + 2)
        bass.note(t + 1.0, 0.45, r, vel - 6)
        bass.note(t + 1.5, 0.45, third, vel - 8)
        bass.note(t + 2.0, 0.9, fifth, vel - 2)
        bass.note(t + 3.0, 0.45, r + 12, vel - 6)
        bass.note(t + 3.5, 0.45, approach, vel - 10)
    else:
        bass.note(t + 1.0, 1.4, r, vel + 2)
        bass.note(t + 2.5, 0.45, fifth, vel - 6)
        bass.note(t + 3.0, 0.9, r, vel - 2)


KICK, SNARE, XSTICK, HAT, OPEN_HAT, PEDAL_HAT, HI_TOM, MID_TOM, FLOOR_TOM, CRASH, RIDE = 36, 38, 37, 42, 46, 44, 50, 47, 41, 49, 51


def drums(n: int, style: str):
    """One drop (kick and cross-stick together on three, beat one empty),
    steppers (a kick on every beat), or the dub (one drop, sparse hats)."""
    t = bar(n)
    if style in ("one_drop", "dub"):
        kit.note(t + 2.0, 0.2, KICK, 104)
        kit.note(t + 2.0, 0.2, XSTICK, 92)
    elif style == "steppers":
        for k in range(4):
            kit.note(t + k, 0.2, KICK, 98 if k % 2 == 0 else 90)
        kit.note(t + 2.0, 0.2, XSTICK, 94)
        kit.note(t + 2.0, 0.2, SNARE, 62)
    # the hats: a shuffled eighth, the off-beat lighter; an open hat every other bar
    for k in range(4):
        if style == "dub" and k in (0, 2):
            hats.note(t + k, 0.1, PEDAL_HAT, 50)
            continue
        hats.note(t + k, 0.1, HAT, 64)
        hats.note(t + sh(k + 0.5), 0.1, OPEN_HAT if (k == 3 and n % 2 == 0 and style != "dub") else HAT, 44)
        if style == "steppers" and k in (1, 3):
            hats.note(t + k + 0.75, 0.06, HAT, 30)


def fill(n: int, kind: str):
    """The last two beats of a bar: a snare roll into the next section."""
    t = bar(n) + 2.0
    if kind == "roll":
        for i in range(8):
            kit.note(t + i * 0.25, 0.1, SNARE, 50 + 6 * i)
    elif kind == "toms":
        for i, drum in enumerate((HI_TOM, HI_TOM, MID_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM)):
            kit.note(t + i / 3, 0.15, drum, 78 + 4 * i)
    elif kind == "flam":
        kit.note(t + 1.0, 0.1, SNARE, 70)
        kit.note(t + 1.5, 0.1, SNARE, 84)
        kit.note(t + 1.75, 0.1, SNARE, 96)


# ---- The lead guitar: the tune, with slides and noodles ------------------------------
# A note is (beat, length, name) or (beat, length, name, ornament): "s" slides in
# from a whole step below, "h" is hammered from a half step below (a grace note),
# "v" is a slide in from a half step.

def slide(at: float, cents: float, over: float = 0.18):
    """Bend from `cents` below up to the note over `over` beats."""
    start = round(-cents * BEND_PER_CENT)
    lead.bends.append((F(at).limit_denominator(960) - F(1, 64), max(-8191, start)))
    for i in (1, 2, 3):
        lead.bends.append((F(at + over * i / 3).limit_denominator(960), round(start * (1 - i / 3))))


def sing(clip: Clip, n: int, phrase, vel=86, octave=0, length=0.95):
    for k, notes in enumerate(phrase):
        for note in notes:
            at, dur, name = note[:3]
            orn = note[3] if len(note) > 3 else ""
            when = bar(n + k) + sh(at)
            pitch = midi(name) + 12 * octave
            assert clip is not lead or pitch <= midi("A5"), f"lead note {name} above A5"
            if orn == "h":
                clip.note(when - 0.08, 0.08, pitch - 1, vel - 16)
            clip.note(when, dur * length, pitch, vel + (6 if at in (0.0, 1.0, 2.0, 3.0) else 0))
            if clip is lead and orn in ("s", "v"):
                slide(when, 200 if orn == "s" else 100)


TUNE = [
    [(0.5, 0.5, "B4"), (1.0, 0.5, "D5"), (1.5, 1.0, "E5", "s"), (2.5, 0.25, "D5"), (2.75, 0.25, "B4"), (3.0, 1.0, "D5", "h")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "E5"), (1.0, 1.5, "G5", "s"), (2.75, 0.25, "E5"), (3.0, 0.5, "D5"), (3.5, 0.5, "C5")],
    [(0.5, 0.25, "A4"), (0.75, 0.25, "B4"), (1.0, 0.5, "D5"), (1.5, 0.5, "F#5"), (2.0, 1.0, "A5", "s"), (3.0, 0.5, "F#5"), (3.5, 0.5, "E5")],
    [(0.0, 1.0, "D5", "v"), (1.0, 0.25, "E5"), (1.25, 0.25, "D5"), (1.5, 0.25, "C5"), (1.75, 0.25, "A4"), (2.0, 1.5, "G4", "s")],
    [(0.5, 0.5, "B4"), (1.0, 0.5, "D5"), (1.5, 1.0, "E5", "s"), (2.5, 0.25, "D5"), (2.75, 0.25, "B4"), (3.0, 1.0, "D5", "h")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "E5"), (1.0, 0.5, "G5"), (1.5, 0.25, "A5"), (1.75, 0.25, "G5"), (2.0, 1.0, "E5", "s"), (3.0, 0.5, "G5"), (3.5, 0.5, "E5")],
    [(0.0, 0.5, "F#5"), (0.5, 0.5, "E5"), (1.0, 0.5, "D5"), (1.5, 0.5, "B4"), (2.0, 0.5, "A4"), (2.5, 0.25, "B4"), (2.75, 0.25, "A4"), (3.0, 1.0, "F#4", "s")],
    [(0.5, 0.25, "G4"), (0.75, 0.25, "A4"), (1.0, 0.25, "B4"), (1.25, 0.25, "C5"), (1.5, 0.25, "D5"), (1.75, 0.25, "E5"), (2.0, 1.5, "G5", "s")],
]
#: The hook, on the horns: trumpets and sax in unison, trombones an octave down.
HOOK_TUNE = [
    [(0.0, 0.5, "D5"), (0.5, 0.5, "D5"), (1.0, 1.0, "B4"), (2.0, 0.5, "G4"), (2.5, 1.25, "A4")],
    [(0.0, 0.5, "A4"), (0.5, 0.5, "B4"), (1.0, 0.5, "A4"), (1.5, 1.0, "F#4"), (3.0, 0.5, "D4"), (3.5, 0.5, "E4")],
    [(0.0, 0.5, "G4"), (0.5, 0.5, "G4"), (1.0, 1.0, "E5"), (2.0, 0.5, "D5"), (2.5, 1.25, "B4")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "B4"), (1.0, 0.5, "A4"), (1.5, 1.0, "G4"), (2.5, 0.5, "A4"), (3.0, 1.0, "C5")],
    [(0.0, 0.5, "D5"), (0.5, 0.5, "D5"), (1.0, 1.0, "B4"), (2.0, 0.5, "G4"), (2.5, 1.25, "A4")],
    [(0.0, 0.5, "A4"), (0.5, 0.5, "B4"), (1.0, 0.5, "A4"), (1.5, 1.0, "F#4"), (3.0, 0.5, "D4"), (3.5, 0.5, "E4")],
    [(0.0, 0.5, "G4"), (0.5, 0.5, "B4"), (1.0, 1.0, "E5"), (2.0, 0.5, "F#5"), (2.5, 1.25, "G5")],
    [(0.0, 1.0, "E5"), (1.0, 0.5, "D5"), (1.5, 0.5, "C5"), (2.0, 1.0, "G4"), (3.0, 1.0, "A4")],
]
#: The lead's answers in the hook's gaps: quick noodles at the end of each bar.
ANSWERS = [
    [(3.75, 0.25, "B4", "h")],
    [(2.0, 0.25, "D5"), (2.25, 0.25, "E5"), (2.5, 0.5, "F#5", "v")],
    [(3.75, 0.25, "G5")],
    [(3.5, 0.25, "D5"), (3.75, 0.25, "E5")],
    [(3.75, 0.25, "B4", "h")],
    [(2.0, 0.25, "A5"), (2.25, 0.25, "F#5"), (2.5, 0.5, "E5", "s")],
    [(3.75, 0.25, "A5")],
    [(3.5, 0.25, "D5"), (3.75, 0.25, "E5")],
]
#: The solo: noodling through E minor pentatonic and G major, slides on the peaks.
SOLO_LINE = [
    [(0.5, 0.25, "E5"), (0.75, 0.25, "G5"), (1.0, 1.0, "A5", "s"), (2.0, 0.25, "G5"), (2.25, 0.25, "E5"), (2.5, 0.25, "D5"), (2.75, 0.25, "B4"), (3.0, 1.0, "D5", "v")],
    [(0.0, 0.25, "E5"), (0.25, 0.25, "D5"), (0.5, 0.25, "C5"), (0.75, 0.25, "B4"), (1.0, 0.5, "G4"), (1.5, 0.5, "A4", "h"), (2.0, 1.5, "C5", "s")],
    [(0.5, 0.33, "A4"), (0.83, 0.33, "B4"), (1.17, 0.33, "C5"), (1.5, 0.5, "E5"), (2.0, 0.25, "D5"), (2.25, 0.25, "C5"), (2.5, 0.25, "A4"), (2.75, 0.25, "G4"), (3.0, 1.0, "A4", "s")],
    [(0.0, 0.25, "F#4"), (0.25, 0.25, "A4"), (0.5, 0.25, "D5"), (0.75, 0.25, "F#5"), (1.0, 1.5, "A5", "s"), (2.5, 0.25, "G5"), (2.75, 0.25, "F#5"), (3.0, 0.5, "E5"), (3.5, 0.5, "D5")],
    [(0.0, 1.0, "B4", "v"), (1.0, 0.25, "E5"), (1.25, 0.25, "D5"), (1.5, 0.25, "B4"), (1.75, 0.25, "D5"), (2.0, 0.25, "E5"), (2.25, 0.25, "G5"), (2.5, 1.0, "E5", "s"), (3.5, 0.5, "D5")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "E5"), (1.0, 0.25, "G5"), (1.25, 0.25, "E5"), (1.5, 0.25, "G5"), (1.75, 0.25, "A5"), (2.0, 1.5, "G5", "s"), (3.5, 0.5, "E5")],
    [(0.0, 0.33, "C5"), (0.33, 0.33, "B4"), (0.67, 0.33, "A4"), (1.0, 0.5, "E4"), (1.5, 0.5, "G4", "h"), (2.0, 0.5, "A4"), (2.5, 0.5, "C5"), (3.0, 1.0, "E5", "s")],
    [(0.0, 0.25, "D5"), (0.25, 0.25, "E5"), (0.5, 0.25, "F#5"), (0.75, 0.25, "A5"), (1.0, 0.5, "F#5"), (1.5, 0.5, "D5"), (2.0, 0.25, "C5"), (2.25, 0.25, "B4"), (2.5, 0.25, "A4"), (2.75, 0.25, "F#4"), (3.0, 1.0, "D4", "s")],
]
#: The dub: single notes thrown into the echo, and long silences.
THROWS = [[(1.5, 0.75, "D5", "s")], [], [(3.0, 0.75, "A4", "v")], [], [(1.5, 0.5, "G5")], [], [(2.0, 0.5, "F#5", "s")], [(3.5, 0.25, "E5")]]
#: The intro's opening noodle.
OPENING = [[], [], [(1.5, 0.25, "D5"), (1.75, 0.25, "E5"), (2.0, 0.25, "G5"), (2.25, 0.25, "E5"), (2.5, 1.0, "D5", "s")],
           [(0.5, 0.25, "B4"), (0.75, 0.25, "A4"), (1.0, 0.5, "G4"), (1.5, 0.25, "A4"), (1.75, 0.25, "B4"), (2.0, 1.5, "D5", "v")]]


def horn_line(n: int, phrase, vel=84, stab=False):
    sing(horns_tp, n, phrase, vel=vel, length=0.6 if stab else 0.9)
    sing(horns_sx, n, phrase, vel=vel - 4, length=0.6 if stab else 0.9)
    sing(horns_tb, n, phrase, vel=vel - 2, octave=-1, length=0.6 if stab else 0.9)


def section(n0: int, chords, bars: int, *, drum_style: str, bass_figure, organ_on=True, skank_on=True, double_every=0):
    for k in range(bars):
        n = n0 + k
        name = chords[k % len(chords)]
        nxt = chords[(k + 1) % len(chords)]
        harmony[n] = name
        if skank_on:
            skank_bar(n, name, double=bool(double_every) and k % double_every == double_every - 1)
        if organ_on:
            bubble(n, name)
        bassline(n, name, nxt, bass_figure(k))
        drums(n, drum_style)


# Intro, bars 1-4: a roll, then the band; the lead's opening noodle.
for k in range(4):
    n = 1 + k
    name = VERSE[k]
    harmony[n] = name
    if k >= 1:
        skank_bar(n, name)
        bubble(n, name, vel=50)
        drums(n, "one_drop")
fill(1, "roll")
kit.note(0.0, 0.2, CRASH, 70)
sing(lead, 1, OPENING, vel=80)
bass.note(bar(4) + 2.0, 0.45, midi("D2"), 84)
bass.note(bar(4) + sh(2.5), 0.45, midi("E2"), 80)
bass.note(bar(4) + 3.0, 0.9, midi("F#2"), 86)

# Verse, bars 5-20: one drop; the lead sings the tune twice.
section(5, VERSE, 16, drum_style="one_drop", bass_figure=lambda k: 0, double_every=4)
sing(lead, 5, TUNE, vel=86)
sing(lead, 13, TUNE, vel=90)
fill(20, "toms")

# Hook, bars 21-28: steppers; the horns' hook; the lead answers.
kit.note(bar(21), 0.3, CRASH, 96)
section(21, HOOK, 8, drum_style="steppers", bass_figure=lambda k: 1, double_every=2)
horn_line(21, HOOK_TUNE, vel=86)
sing(lead, 21, ANSWERS, vel=82)
fill(28, "flam")

# Dub, bars 29-36: bass and drums; the skank through the echo; the lead throws.
for k in range(8):
    n = 29 + k
    name = HOOK[k % 4]
    harmony[n] = name
    bassline(n, name, HOOK[(k + 1) % 4], 2 if k % 2 == 0 else 0, vel=98)
    drums(n, "dub")
    if k % 2 == 1:
        dub.note(bar(n) + 3.0, 0.16, SKANK[name], 82)
    if k in (3, 7):
        organ.note(bar(n) + 2.5, 1.4, ORGAN[name], 46)
sing(lead, 29, THROWS, vel=84)
fill(36, "roll")

# Solo, bars 37-44: the lead noodles over Em C Am D.
kit.note(bar(37), 0.3, CRASH, 90)
section(37, SOLO, 8, drum_style="one_drop", bass_figure=lambda k: k % 2, double_every=2)
sing(lead, 37, SOLO_LINE, vel=88)
fill(44, "toms")

# Hook, bars 45-52: horns and lead together.
kit.note(bar(45), 0.3, CRASH, 100)
section(45, HOOK, 8, drum_style="steppers", bass_figure=lambda k: 1, double_every=2)
horn_line(45, HOOK_TUNE, vel=90)
sing(lead, 45, HOOK_TUNE[:4], vel=80, octave=0)
sing(lead, 49, ANSWERS[4:], vel=84)
fill(52, "flam")

# Outro, bars 53-56: the verse turnaround and the run up, home to D for the loop.
section(53, ["G", "C", "D", "D"], 4, drum_style="one_drop", bass_figure=lambda k: 0)
sing(lead, 53, [TUNE[0], TUNE[5], TUNE[6], TUNE[7][:6]], vel=84)
fill(56, "roll")

END_BAR = 57
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


NAKED = "instrument_backend: {kind: sfz, library_ref: drums.naked, settings: {render_timeout_s: 900}}"
SHINY = "controls: {100: 0, 107: 0}, instrument_backend: {kind: sfz, sfz_glob: '**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz', settings: {fold_to_range: false}}"
TENOR = "instrument_backend: {kind: sfz, sfz_glob: '**/Reed Aerophones/Tenor Saxophone - Vibrato.sfz'}"
DUB_DELAY = round(60000 / BPM * 0.75)  # a dotted eighth

score = f"""schema: ambition.musicir.v3
id: pastafarian
title: Pastafarian
description: >-
  Reggae for the Noodle dimension: G major at 76 BPM, a one-drop groove that
  goes to steppers for the hook, a skank on two and four, an organ bubble, a
  deep melodic bass, a horn hook, and a noodly lead guitar that slides into
  its long notes and noodles in every gap. A dub break strips it to bass and
  drums with the skank in a long echo. No choir: the holy choir belongs to the
  Flying Spaghetti Monster's own music (Jon, 2026-10-20). Generated by
  dev/compose_pastafarian.py: edit that, not this file.
notes:
  - 'Verses are one drop (kick and cross-stick on three, beat one empty); the hooks are steppers (a kick on every beat).'
  - 'The intro plays once; the loop is bars 5-56, ending on D, which leads back to G at bar 5.'
  - 'The lead guitar slides with pitch bends (the Shiny guitar bends 200 cents); no held lead note above A5.'
seed: 1717
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: G major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.4, density: 0.35, role: 'a roll, the band, the opening noodle'}}
  - {{id: verse, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'one drop; the lead sings the tune'}}
  - {{id: hook, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.75, density: 0.7, loopable: true, role: 'steppers; the horn hook'}}
  - {{id: dub, from: {{bar: 29, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.45, density: 0.35, loopable: true, role: 'bass and drums; echoes'}}
  - {{id: solo, from: {{bar: 37, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.65, density: 0.6, loopable: true, role: 'the lead noodles'}}
  - {{id: hook_2, from: {{bar: 45, beat: 1}}, to: {{bar: 53, beat: 1}}, energy: 0.8, density: 0.75, loopable: true, role: 'the hook, horns and lead together'}}
  - {{id: outro, from: {{bar: 53, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.6, density: 0.55, loopable: true, role: 'the turnaround, home to D'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: lead, group: lead, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
  - {{name: skank, group: skank, program: clean_guitar, volume: 100, pan: 64, expression: 108, {SHINY}}}
  - {{name: dub, group: dub, program: clean_guitar, volume: 100, pan: 64, expression: 108, {SHINY}}}
  - {{name: organ, group: organ, program: drawbar_organ, volume: 92, pan: 64, expression: 100}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 112, pan: 64, expression: 114, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndBlueBasses/Programs/04-babyblue_warm.sfz'}}}}
  - {{name: trumpets, group: horns, program: trumpet, volume: 100, pan: 64, expression: 106, instrument_backend: {{kind: sfz, library_ref: orchestra.trumpets_sustain}}}}
  - {{name: trombones, group: horns, program: trombone, volume: 100, pan: 64, expression: 106, instrument_backend: {{kind: sfz, library_ref: orchestra.trombones_sustain}}}}
  - {{name: sax, group: horns, program: tenor_sax, volume: 96, pan: 64, expression: 104, {TENOR}}}
  - {{name: kit, group: drums, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: hats, group: hats, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
parts:
{part("lead_part", "lead", lead)}
{part("skank_part", "skank", skank)}
{part("dub_part", "dub", dub)}
{part("organ_part", "organ", organ)}
{part("bass_part", "bass", bass)}
{part("trumpets_part", "trumpets", horns_tp)}
{part("trombones_part", "trombones", horns_tb)}
{part("sax_part", "sax", horns_sx)}
{part("kit_part", "kit", kit)}
{part("hats_part", "hats", hats)}
processing:
  groups:
    lead:
      chain:
        - processor: pedalboard
          effects:
            - {{effect: gain, gain_db: 8.0}}
            - {{effect: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 8.0, release_ms: 110.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gxts9#ts9sim
          binary: lv2apply
          channel_mode: dual_mono
          wet_mix: 0.4
          params: {{fslider0_: -6.0, fslider1_: 620.0, fslider2_: 0.6, BYPASS: 1.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.5
          params: {{P6v: 0.7, Middle: 0.7, Bass: 0.5, Treble: 0.56, WET_DRY: 55.0, GAIN: -4.0}}
        - {{processor: highpass, cutoff_hz: 110}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 800, q: 0.8, db: 1.5}}
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
            - {{type: peak, hz: 4920, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 5600}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 7.0, release_ms: 90.0}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {DUB_DELAY}, feedback: 0.22, mix: 0.16}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: 0.15}}
    skank:
      chain:
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_redeye#chump
          binary: lv2apply
          channel_mode: dual_mono
          params: {{Gain: 0.3, Tone: 0.7, Volume: 0.5}}
        - {{processor: highpass, cutoff_hz: 260}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 2400, q: 1.0, db: 3.0}}
        - {{processor: lowpass, cutoff_hz: 6500}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.5, attack_ms: 4.0, release_ms: 80.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 0.9}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: -0.45}}
    dub:
      chain:
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_redeye#chump
          binary: lv2apply
          channel_mode: dual_mono
          params: {{Gain: 0.3, Tone: 0.7, Volume: 0.5}}
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: lowpass, cutoff_hz: 4500}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {DUB_DELAY}, feedback: 0.55, mix: 0.5}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 2.5}}
        - {{processor: balance, position: 0.35}}
    organ:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - processor: pedalboard
          effects:
            - {{effect: chorus, rate_hz: 5.5, depth: 0.12, mix: 0.3}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.4}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: lowpass, cutoff_hz: 800}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 90, q: 0.8, db: 3.0}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 25.0, release_ms: 140.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -3.0}}
    horns:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 1400, q: 0.9, db: 1.5}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.2, attack_ms: 12.0, release_ms: 110.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: -3.0}}
        - {{processor: balance, position: -0.15}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 65, q: 1.0, db: 2.5}}
            - {{type: peak, hz: 3500, q: 1.0, db: -2.0}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.0, attack_ms: 12.0, release_ms: 90.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: 5.0}}
    hats:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: gain, gain_db: 19.0}}
        - {{processor: balance, position: 0.3}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 20.0, release_ms: 150.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.1}}
      - {{processor: limiter, target_peak_db: -2.0, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    rhythm: [skank, dub, organ, bass, drums, hats]
    tune: [lead, horns]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [verse, hook, dub, solo, hook_2, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

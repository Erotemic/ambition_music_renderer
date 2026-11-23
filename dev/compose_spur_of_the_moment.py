"""Spur of the Moment: a western in A harmonic minor, in three flavours of one
theme. Writes its MusicIR v3 score:

    python3 dev/compose_spur_of_the_moment.py scores/active/spur_of_the_moment.music.yaml

The request (Jon, 2026-11-21): another cowboy western around Am, E major and
F major, mostly Am, in several flavours: a background for a town, a more
intense action cue, and an extreme one for a boss fight, where metal guitar
blends with the country western. Nothing is taken from another tune, ours
included; the boss borrows the Iron Toccata's manner (a pedal-point riff in
sixteenths, a twin lead under the tune, a duel), not its notes.

Am, E and F are A harmonic minor's own chords (A B C D E F G#). Its two
colours are the raised seventh, G#, which pulls every phrase home, and the
augmented second between F and G#, which this theme says over the E chord.

THE MATERIAL (original):
  the spur (a one-bar riff): A A C A G# A E, the root kicked twice, the third,
      the leading note and down to the fifth. Over F and E it moves with the
      root (F F A F E F C, E E G# E D E B).
  the call (8 bars): A A E D C | B C B A E | G# B E B | C B A A |
      A A E F E | C D C A F | G# F G# B G# | A.
      Its seventh bar is the theme's mark: G#, F, G# over E, the augmented
      second and back.
  the answer (8 bars): it climbs to A5 over Am, sinks through F, leans on F
      over E (a flat ninth), and ends on G#, the way back to the call.

One cue, one tempo (148), three playback sections the game moves between:

  main_street  1-40   the town: a two-beat on the archtop, an upright, brushes,
                      a bowed drone; the call on the twang guitar at half
                      speed, the answer on the fiddle; the spur in the tail. (loop)
  pursuit     41-80   the chase: a train beat, a strummed guitar, the spur on
                      the twang; the call and the answer on fiddle and
                      trumpet, then with staccato strings and trumpet stabs. (loop)
  showdown    81-128  the boss: the spur as a pedal-point riff in sixteenths
                      under double kick; the call on the lead guitar with a
                      twin under it and the fiddle on the tune; the answer;
                      the fiddle and the guitar duel; a half-time hoedown
                      where the twang and the banjo trade over the chugs; the
                      call with everything.                               (loop)
"""

from __future__ import annotations

import math
import random
import sys
from fractions import Fraction as F
from pathlib import Path

OUT = Path(sys.argv[1])
BPM = 148
SEED = 1872

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


#: A harmonic minor.
MODE = [9, 11, 0, 2, 4, 5, 8]
#: Jon hears high lead guitar as piercing: no lead or fiddle note above A5.
TOP = midi("A5")

CHORD = {"Am": ["A", "C", "E"], "E": ["E", "G#", "B"], "F": ["F", "A", "C"]}
CHORD_PCS = {name: {NOTE[n] for n in notes} for name, notes in CHORD.items()}
ROOT_PC = {"Am": 9, "E": 4, "F": 5}


def step(pitch: int, direction: int) -> int:
    pitch += direction
    while pitch % 12 not in MODE:
        pitch += direction
    return pitch


def degrees(pitch: int, n: int) -> int:
    for _ in range(abs(n)):
        pitch = step(pitch, 1 if n > 0 else -1)
    return pitch


def tones(chord: str, octave: int) -> list[int]:
    out = []
    for name in CHORD[chord]:
        p = midi(f"{name}{octave}")
        while out and p <= out[-1]:
            p += 12
        out.append(p)
    return out


def root(chord: str, low: int) -> int:
    """The chord's root at or above `low`."""
    p = low
    while p % 12 != ROOT_PC[chord]:
        p += 1
    return p


def under(pitch: int, chord: str, held: bool) -> int:
    """A harmony note below `pitch`: a chord tone under a held note, else the
    scale's third below."""
    if held:
        for below in range(pitch - 3, pitch - 10, -1):
            if below % 12 in CHORD_PCS[chord]:
                return below
    return degrees(pitch, -2)


# The longest group reverb here decays within this, so a gap of it holds a ring.
RING_SECONDS = 2.5


class Cue:
    def __init__(self, segments):
        self.rng = random.Random(SEED)
        gap = max(1, math.ceil(RING_SECONDS * BPM / 240))
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
        self.jitter = jitter_ms / 1000.0 * BPM / 60.0
        self.vel_jitter = vel_jitter

    def form_region(self, beat):
        return next((sid for sid, first, last, start in self.cue.segments
                     if (start - 1) * 4 <= beat < (start + last - first) * 4), None)

    def note(self, at, dur, pitches, vel):
        rng = self.cue.rng
        at = F(at).limit_denominator(960)
        owner = self.form_region(at)
        if self.jitter and at > 0:
            at += F(rng.uniform(-self.jitter, self.jitter)).limit_denominator(960)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        pitches = [p if isinstance(p, int) else midi(p) for p in pitches]
        self.events.append((at, F(dur).limit_denominator(960), pitches, vel, owner if owner != self.form_region(at) else None))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel, owner in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            if owner is None:
                lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
            else:
                field = "pitch" if len(pitches) == 1 else "pitches"
                lines.append(f"{indent}    - {{at: {frac(at)}, dur: {frac(dur)}, {field}: {pitch}, velocity: {vel}, form_region: {owner}}}")
        return "\n".join(lines)


# ---- The theme --------------------------------------------------------------
CALL = [
    [("A4", 0.5), ("A4", 0.5), ("E5", 1.5), ("D5", 0.5), ("C5", 1.0)],
    [("B4", 0.5), ("C5", 0.5), ("B4", 0.5), ("A4", 0.5), ("E4", 2.0)],
    [("G#4", 1.5), ("B4", 0.5), ("E5", 1.0), ("B4", 1.0)],
    [("C5", 1.0), ("B4", 0.5), ("A4", 0.5), ("A4", 2.0)],
    [("A4", 0.5), ("A4", 0.5), ("E5", 1.5), ("F5", 0.5), ("E5", 1.0)],
    [("C5", 0.5), ("D5", 0.5), ("C5", 0.5), ("A4", 0.5), ("F4", 2.0)],
    [("G#4", 1.0), ("F4", 0.5), ("G#4", 0.5), ("B4", 1.0), ("G#4", 1.0)],
    [("A4", 3.0), (None, 1.0)],
]
CALL_HARMONY = ["Am", "Am", "E", "Am", "Am", "F", "E", "Am"]
ANSWER = [
    [("E5", 1.0), ("E5", 0.5), ("D5", 0.5), ("C5", 1.0), ("E5", 1.0)],
    [("A5", 1.5), ("E5", 0.5), ("C5", 1.0), ("A4", 1.0)],
    [("F5", 1.5), ("E5", 0.5), ("D5", 0.5), ("C5", 0.5), ("A4", 1.0)],
    [("C5", 1.0), ("D5", 0.5), ("C5", 0.5), ("A4", 2.0)],
    [("B4", 0.5), ("G#4", 0.5), ("B4", 0.5), ("D5", 0.5), ("F5", 1.0), ("E5", 1.0)],
    [("D5", 1.0), ("B4", 1.0), ("G#4", 1.0), ("E4", 1.0)],
    [("A4", 0.5), ("C5", 0.5), ("E5", 1.0), ("D5", 0.5), ("C5", 0.5), ("B4", 1.0)],
    [("G#4", 3.0), (None, 1.0)],
]
ANSWER_HARMONY = ["Am", "Am", "F", "F", "E", "E", "Am", "E"]
for _bar in CALL + ANSWER:
    assert sum(beats for _, beats in _bar) == 4, _bar


def spur(chord: str, base: int) -> list[tuple[int, float]]:
    """The spur from the chord's root `base`: (pitch, beats)."""
    third = base + (3 if chord == "Am" else 4)
    return [(base, 0.75), (base, 0.25), (third, 0.5), (base, 0.5), (step(base, -1), 0.5), (base, 0.5),
            (base - 5, 1.0)]


# GM drum keys (the Naked, Big Rusty and Muldjord kits map like GM).
KICK, SNARE, SIDESTICK, HAT, HAT_OPEN, CRASH, CHINA, RIDE, RIDE_BELL, FLOOR, MID, HIGH = (
    36, 38, 37, 42, 46, 49, 52, 51, 53, 41, 45, 48)

cue = Cue([("main_street", 1, 40), ("pursuit", 41, 80), ("showdown", 81, 128)])
t = cue.t

# Town and chase.
archtop = cue.clip("archtop", 6, 6)
upright = cue.clip("upright", 5, 5)
brushes = cue.clip("brushes", 4, 5)
drone = cue.clip("drone", 6, 3)
twang = cue.clip("twang", 5, 5)
fiddle = cue.clip("fiddle", 7, 5)
trumpet = cue.clip("trumpet", 6, 4)
train = cue.clip("train", 3, 5)
staccato = cue.clip("staccato", 3, 5)
stabs = cue.clip("stabs", 4, 4)
# The showdown.
rhythm_l = cue.clip("rhythm_l", 4, 4)
rhythm_r = cue.clip("rhythm_r", 4, 4)
lead = cue.clip("lead", 2, 3)
twin = cue.clip("twin", 3, 3)
growl = cue.clip("growl", 3, 3)
kit = cue.clip("kit", 2, 4)
hot_fiddle = cue.clip("hot_fiddle", 3, 4)
banjo = cue.clip("banjo", 4, 5)
brass = cue.clip("brass", 5, 4)


def melody(clip: Clip, bar: int, bars, vel: int, *, stretch: int = 1, transpose: int = 0, legato: float = 0.92,
           harmony=None, harmony_clip: Clip | None = None, cap: int = TOP, under_only: bool = False) -> None:
    """Play `bars` of (note, beats) from logical `bar`; `stretch` 2 is half speed.
    With `harmony_clip`, that clip plays `under` each note; with `under_only`,
    `clip` itself plays only the line under the tune."""
    for k, notes in enumerate(bars):
        at = t(bar) + 4 * stretch * k
        for i, (name, beats) in enumerate(notes):
            if name is not None:
                pitch = min(midi(name) + transpose, cap)
                accent = 6 if i == 0 else 0
                if under_only:
                    pitch = under(pitch, harmony[k], True)
                clip.note(at, beats * stretch * legato, pitch, vel + accent)
                if harmony_clip is not None:
                    harmony_clip.note(at, beats * stretch * legato, under(pitch, harmony[k], beats >= 1),
                                      vel - 8 + accent)
            at += beats * stretch


def figure(clip: Clip, at: float, notes: list[int], sub: float, vel: int, *, cap: int = TOP,
           harmony: str | None = None, legato: float = 0.9) -> float:
    """`notes` one after another, `sub` beats each; with `harmony` the twin
    plays a third under. Returns the beat after the last note."""
    for i, pitch in enumerate(notes):
        pitch = min(pitch, cap)
        accent = 8 if i % 4 == 0 else 0
        clip.note(at + i * sub, sub * legato, pitch, vel + accent)
        if harmony:
            twin.note(at + i * sub, sub * legato, under(pitch, harmony, False), vel - 6 + accent)
    return at + len(notes) * sub


def run(start: str, count: int, direction: int) -> list[int]:
    notes = [midi(start)]
    for _ in range(count - 1):
        notes.append(step(notes[-1], direction))
    return notes


def fours_down(top: str, groups: int) -> list[int]:
    out, head = [], midi(top)
    for _ in range(groups):
        group = [head]
        for _ in range(3):
            group.append(step(group[-1], -1))
        out += group
        head = step(head, -1)
    return out


def stretched(harmony: list[str], factor: int) -> list[str]:
    return [chord for chord in harmony for _ in range(factor)]


# ===========================================================================
# MAIN STREET (1-40): the town
# ===========================================================================
TOWN = stretched(CALL_HARMONY, 2) + stretched(ANSWER_HARMONY, 2) + ["Am", "Am", "Am", "Am", "F", "F", "E", "E"]
for i, chord in enumerate(TOWN):
    bar = 1 + i
    cue.harmony[bar] = chord
    # The two-beat: the root on 1, the chord on 2, the fifth on 3, the chord on 4.
    low = root(chord, midi("E2"))
    upper = [p for p in tones(chord, 3) if p > low + 4][:3]
    fifth = low + 7 if low + 7 <= midi("C3") else low - 5
    archtop.note(t(bar), 0.95, low, 80)
    archtop.note(t(bar, 1), 0.5, upper, 66)
    archtop.note(t(bar, 2), 0.95, fifth, 74)
    archtop.note(t(bar, 3), 0.5, upper, 64)
    if i % 4 == 3:
        archtop.note(t(bar, 3.5), 0.4, upper, 54)
    b = root(chord, midi("E1"))
    upright.note(t(bar), 0.95, b, 86)
    upright.note(t(bar, 2), 0.95, b + 7 if b + 7 <= midi("D2") else b - 5, 76)
    # Brushes: a soft kick on 1 and 3, the brush on 2 and 4, a shaker in eighths.
    brushes.note(t(bar), 0.3, KICK, 58)
    brushes.note(t(bar, 2), 0.3, KICK, 50)
    brushes.note(t(bar, 1), 0.3, SNARE, 44)
    brushes.note(t(bar, 3), 0.3, SNARE, 46)
    for k in range(8):
        brushes.note(t(bar, 0.5 * k), 0.15, HAT, 30 if k % 2 else 40)
    # The drone: a bowed fifth on A that holds through every Am, the root elsewhere.
    if i % 2 == 0:
        if chord == "Am":
            drone.note(t(bar), 7.6, [midi("A2"), midi("E3")], 50)
        else:
            drone.note(t(bar), 7.6, root(chord, midi("A2")), 48)
# The call on the twang, an octave down, at half speed; then the answer on the
# fiddle. The twang answers the fiddle's long notes with the spur.
melody(twang, 1, CALL, 82, stretch=2, transpose=-12, legato=0.9)
melody(fiddle, 17, ANSWER, 80, stretch=2, legato=0.96)
for bar, chord in ((20, "Am"), (24, "F"), (28, "E"), (32, "E")):
    at = t(bar)
    for pitch, beats in spur(chord, root(chord, midi("E3"))):
        twang.note(at, beats * 0.85, pitch, 70)
        at += beats
# The tail: the spur on the twang over the drone, the fiddle holding above,
# then F and E back to the call.
for k, chord in enumerate(["Am", "Am", "Am", "Am", "F", "F", "E", "E"]):
    bar = 33 + k
    if k in (0, 2, 4, 6):
        at = t(bar)
        for pitch, beats in spur(chord, root(chord, midi("E3"))):
            twang.note(at, beats * 0.85, pitch, 78)
            at += beats
fiddle.note(t(34), 7.5, midi("E5"), 66)
fiddle.note(t(36), 3.5, midi("C5"), 64)
fiddle.note(t(37), 7.5, midi("C5"), 66)
fiddle.note(t(39), 3.5, midi("B4"), 64)
fiddle.note(t(40), 2.5, midi("G#4"), 62)
fiddle.note(t(40, 2.5), 1.4, midi("B4"), 60)

# ===========================================================================
# PURSUIT (41-80): the chase
# ===========================================================================
CHASE = (["Am", "Am", "Am", "E"] + CALL_HARMONY + ANSWER_HARMONY + CALL_HARMONY + ANSWER_HARMONY
         + ["Am", "Am", "F", "E"])
for i, chord in enumerate(CHASE):
    bar = 41 + i
    cue.harmony[bar] = chord
    late = bar >= 61
    # The train beat: the snare in eighths, accents on 2 and 4, the kick on 1 and 3.
    for k in range(8):
        accent = k in (2, 6)
        train.note(t(bar, 0.5 * k), 0.15, SNARE, 104 if accent else 56 + (6 if k % 2 == 0 else 0))
    train.note(t(bar), 0.3, KICK, 104)
    train.note(t(bar, 2), 0.3, KICK, 96)
    if late:
        train.note(t(bar, 1.5), 0.3, KICK, 84)
        for k in range(4):
            train.note(t(bar, k + 0.5), 0.2, HAT_OPEN if k == 3 else HAT, 60)
    if bar in (41, 45, 53, 61, 69, 77):
        train.note(t(bar), 1.0, CRASH, 100)
    # The strum: down on the beat, up on the off-beat, the chord in the middle.
    # In the tail it only hits the bar: the spur has the floor.
    voicing = [p for p in tones(chord, 3) + tones(chord, 4) if midi("E3") <= p <= midi("E5")][:4]
    if bar >= 77:
        archtop.note(t(bar), 1.5, voicing, 72)
    else:
        for k in range(8):
            archtop.note(t(bar, 0.5 * k), 0.4, voicing if k % 2 == 0 else voicing[1:], 60 if k % 2 == 0 else 46)
    # The upright drives eighths on the root, the spur's kick in the last bar of four.
    b = root(chord, midi("E1"))
    if i % 4 == 3:
        at = t(bar)
        for pitch, beats in spur(chord, b + 12 if b + 12 <= midi("B2") else b):
            upright.note(at, beats * 0.85, pitch, 84)
            at += beats
    else:
        for k in range(8):
            upright.note(t(bar, 0.5 * k), 0.42, b if k % 4 != 3 else b + 7, 80 if k % 2 == 0 else 68)
    if late:
        # Staccato strings in eighths on the chord's tones, and a trumpet stab
        # on the off-beat of 2 and on 4.
        # Under the tune, and never the E under its F: E7 without its root.
        arp = {"Am": ["A3", "C4", "E4"], "F": ["A3", "C4", "F4"], "E": ["G#3", "B3", "D4"]}[chord]
        arp = [midi(x) for x in arp]
        for k in range(8):
            staccato.note(t(bar, 0.5 * k), 0.3, arp[[0, 1, 2, 1, 0, 1, 2, 1][k]] if k % 2 else arp[0], 74)
        stabs.note(t(bar, 1.5), 0.4, tones(chord, 4), 86)
        stabs.note(t(bar, 3), 0.6, tones(chord, 4), 90)
# The intro: the spur on the twang, four times, to the E.
for k, chord in enumerate(["Am", "Am", "Am", "E"]):
    at = t(41 + k)
    for pitch, beats in spur(chord, root(chord, midi("E3"))):
        twang.note(at, beats * 0.8, pitch, 92)
        at += beats
# The call on the fiddle, the trumpet joins it for the answer a third under;
# then both an octave apart with the stabs, and the twang on the spur in the tail.
melody(fiddle, 45, CALL, 92, legato=0.92)
melody(fiddle, 53, ANSWER, 92, legato=0.92)
melody(trumpet, 53, ANSWER, 86, legato=0.9, harmony=ANSWER_HARMONY, under_only=True)
melody(trumpet, 61, CALL, 94, legato=0.9)
melody(fiddle, 61, CALL, 88, legato=0.9, harmony=CALL_HARMONY, under_only=True)
melody(fiddle, 69, ANSWER, 96, legato=0.9)
melody(trumpet, 69, ANSWER, 88, legato=0.9, harmony=ANSWER_HARMONY, under_only=True)
# The twang answers the call's held notes with the spur's tail.
for bar in (46, 48, 62, 64):
    figure(twang, t(bar, 2), [midi("E4"), midi("G#4"), midi("A4"), midi("C5")], 0.5, 84)
for k, chord in enumerate(["Am", "Am", "F", "E"]):
    at = t(77 + k)
    for pitch, beats in spur(chord, root(chord, midi("E3"))):
        twang.note(at, beats * 0.8, pitch, 96)
        stabs.note(at, beats * 0.6, [pitch + 12, pitch + 24], 84)
        at += beats
for k in range(8):
    train.note(t(80, 2 + 0.25 * k), 0.1, SNARE, 70 + 6 * k)


# ===========================================================================
# SHOWDOWN (81-128): the boss
# ===========================================================================
FIFTHS = {9, 4, 5, 11, 2, 0}  # A, E, F, B, D, C carry a perfect fifth in A harmonic minor


def power(r: int) -> list[int]:
    return [r, r + 7, r + 12] if r % 12 in FIFTHS else [r, r + 12]


def both(at, dur, pitches, vel):
    for clip in (rhythm_l, rhythm_r):
        clip.note(at, dur, pitches, vel)


def drums(bar: int, style: str, crash=False):
    at = t(bar)
    if style == "double":
        for i in range(16):
            kit.note(at + 0.25 * i, 0.07, KICK, 100 if i % 2 == 0 else 86)
        for beat in range(4):
            kit.note(at + beat, 0.1, RIDE_BELL if beat % 2 == 0 else RIDE, 82)
            kit.note(at + beat + 0.5, 0.08, RIDE, 62)
        for beat in (1, 3):
            kit.note(at + beat, 0.12, SNARE, 120)
    elif style == "half":
        for o in (0, 1.5, 2.5):
            kit.note(at + o, 0.1, KICK, 112)
        kit.note(at + 2, 0.14, SNARE, 122)
        for i in range(8):
            kit.note(at + 0.5 * i, 0.07, HAT, 78 if i % 2 == 0 else 58)
    elif style == "anthem":
        for i in range(8):
            kit.note(at + 0.5 * i, 0.08, KICK, 106 if i % 2 == 0 else 92)
        for beat in range(4):
            kit.note(at + beat, 0.2, RIDE, 84)
        for beat in (1, 3):
            kit.note(at + beat, 0.12, SNARE, 120)
    elif style == "skank":
        for beat in range(4):
            kit.note(at + beat, 0.1, KICK, 110)
            kit.note(at + beat + 0.5, 0.1, SNARE, 104)
            kit.note(at + beat, 0.1, RIDE, 80)
    if crash:
        kit.note(at, 0.6, CRASH, 118)
        kit.note(at, 0.12, KICK, 122)


def fill(bar: int, start=2.0):
    at = t(bar)
    toms = [SNARE, SNARE, HIGH, HIGH, MID, MID, FLOOR, FLOOR]
    count = int((4 - start) / 0.25)
    for i in range(count):
        kit.note(at + start + 0.25 * i, 0.1, toms[min(7, i * 8 // count)], 96 + 3 * i)
        if i % 2 == 0:
            kit.note(at + start + 0.25 * i, 0.08, KICK, 100)


def pedal(bar: int, chord: str, vel=98, fiddle_too=False):
    """Two bars of sixteenths: the open root against a line in the scale over
    it, the line on the off-sixteenth. The line rises to the sixth and falls,
    twice; it stays a third or more over the root, so the low strings never
    rub a second against the bass."""
    r = root(chord, midi("E2"))
    line = [degrees(r + 12, d) for d in (4, 5, 4, 2, 4, 5, 6, 5, 4, 5, 4, 2, 6, 5, 4, 2)]
    for b in (0, 1):
        at = t(bar + b)
        for i in range(8):
            both(at + 0.5 * i, 0.2, [r], vel - 14)
            low = line[8 * b + i] - 12
            both(at + 0.5 * i + 0.25, 0.2, [low if low > r else low + 12], vel)
            growl.note(at + 0.5 * i, 0.45, r, 96 if i % 2 == 0 else 86)
            if fiddle_too:
                # A double shuffle: the open string on the beat, the line an
                # octave over the guitars' on the off-sixteenth.
                hot_fiddle.note(at + 0.5 * i, 0.22, r + 24, 74)
                hot_fiddle.note(at + 0.5 * i + 0.25, 0.22, line[8 * b + i] + 12, 90)


def chugs(bar: int, chord: str, accents=(0, 4), vel=104):
    r = root(chord, midi("E2"))
    at = t(bar)
    for j in range(8):
        accent = j in accents
        both(at + 0.5 * j, 0.4 if accent else 0.18, power(r) if accent else power(r)[:2], vel if accent else vel - 12)
        growl.note(at + 0.5 * j, 0.45, r, 100 if accent else 90)


# The riff (81-88): the spur as a pedal point, Am Am F E; the fiddle joins it.
for k, chord in enumerate(["Am", "Am", "F", "E"]):
    bar = 81 + 2 * k
    pedal(bar, chord, fiddle_too=k >= 2)
    cue.harmony.update({bar: chord, bar + 1: chord})
for bar in range(81, 89):
    drums(bar, "double", crash=bar in (81, 85))
figure(lead, t(84, 2), fours_down("A5", 2), 0.25, 100)
figure(lead, t(88, 2), run("G#4", 8, 1), 0.25, 100)
fill(88, 3.0)

# The call (89-96) on the lead with the twin under it, the fiddle on the tune;
# the answer (97-104) with the brass holding the chord.
for k, chord in enumerate(CALL_HARMONY + ANSWER_HARMONY):
    bar = 89 + k
    cue.harmony[bar] = chord
    chugs(bar, chord)
    drums(bar, "anthem" if k < 8 else "double", crash=k % 4 == 0)
    if k >= 8:
        brass.note(t(bar), 3.8, [p - 12 for p in tones(chord, 4)[:2]] + [tones(chord, 4)[0]], 78)
melody(lead, 89, CALL, 100, legato=0.96, harmony=CALL_HARMONY, harmony_clip=twin)
melody(hot_fiddle, 89, CALL, 90, legato=0.9)
melody(lead, 97, ANSWER, 102, legato=0.96, harmony=ANSWER_HARMONY, harmony_clip=twin)
melody(hot_fiddle, 97, ANSWER, 90, legato=0.9)
fill(104, 3.0)

# The duel (105-112) over Am E F E: the fiddle states each chord in sextuplets,
# the guitar answers down the scale; then both at once, an octave apart; then
# the twin joins the guitar in thirds.
DUEL = ["Am", "E", "F", "E"] * 2
ARPS = {"Am": ["A4", "C5", "E5", "A5", "E5", "C5"], "E": ["E4", "G#4", "B4", "E5", "B4", "G#4"],
        "F": ["F4", "A4", "C5", "F5", "C5", "A4"]}
for k, chord in enumerate(DUEL):
    bar = 105 + k
    cue.harmony[bar] = chord
    chugs(bar, chord, accents=(0, 3, 6), vel=100)
    drums(bar, "skank" if k < 4 else "double", crash=k % 4 == 0)
    if k < 4:
        figure(hot_fiddle, t(bar), [midi(x) for x in ARPS[chord]] * 2, 1 / 6, 92)
        figure(lead, t(bar, 2), fours_down(("A5", "G#5", "F5", "G#5")[k], 2), 0.25, 100)
    elif k < 6:
        top = ("A4", "G#4")[k - 4]
        figure(lead, t(bar), run(top, 8, 1) + run(("A5", "G#5")[k - 4], 8, -1), 0.25, 100)
        figure(hot_fiddle, t(bar), [p - 12 for p in run(top, 8, 1) + run(("A5", "G#5")[k - 4], 8, -1)], 0.25, 86)
    else:
        figure(lead, t(bar), fours_down(("A5", "G#5")[k - 6], 4), 0.25, 100, harmony=chord)
        figure(hot_fiddle, t(bar), [midi(x) for x in ARPS[chord]] * 4, 1 / 6, 84)
fill(112, 2.0)

# The hoedown (113-120): half time; the guitars hit and hold, the twang and
# the banjo trade over them.
HOEDOWN = ["Am", "Am", "Am", "Am", "F", "F", "E", "E"]
for k, chord in enumerate(HOEDOWN):
    bar = 113 + k
    cue.harmony[bar] = chord
    r = root(chord, midi("E2"))
    for o, dur in ((0, 1.4), (1.5, 0.4), (2.5, 1.4)):
        both(t(bar, o), dur, power(r), 114)
        growl.note(t(bar, o), dur, r, 106)
    drums(bar, "half", crash=k % 4 == 0)
    up = tones(chord, 3) + [tones(chord, 3)[0] + 12]
    if k % 2 == 0:
        # The banjo's roll in sixteenths: forward, through the chord.
        for j in range(16):
            banjo.note(t(bar, 0.25 * j), 0.3, up[[0, 1, 2, 3, 1, 2, 3, 0][j % 8]], 80 if j % 4 == 0 else 66)
    else:
        # The twang answers: the spur in double stops, snapped.
        at = t(bar)
        for pitch, beats in spur(chord, root(chord, midi("A3"))):
            twang.note(at, beats * 0.55, [pitch, under(pitch + 12, chord, True)], 98)
            at += beats
figure(lead, t(120, 2), run("E4", 8, 1), 0.25, 102)
fill(120, 3.0)

# The call with everything (121-128): lead and twin, the fiddle an octave
# under, the brass on the tune; the run home to the riff.
for k, chord in enumerate(CALL_HARMONY):
    bar = 121 + k
    cue.harmony[bar] = chord
    chugs(bar, chord, vel=108)
    drums(bar, "double", crash=k % 2 == 0)
melody(lead, 121, CALL, 104, legato=0.96, harmony=CALL_HARMONY, harmony_clip=twin)
melody(hot_fiddle, 121, CALL, 90, legato=0.9)
melody(brass, 121, CALL, 88, legato=0.92, transpose=-12)
figure(lead, t(128, 3), [midi("E4"), midi("G#4"), midi("B4"), midi("D5")], 0.25, 102)
fill(128, 3.0)


# ---- Write ------------------------------------------------------------------
def form_and_playback(shapes: dict) -> tuple[str, str]:
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
        fields = [f"id: {sid}", f"form: [{sid}]", "loop: true"]
        if i > 0:
            fields.append(f"lead_in: before_{sid}")
        fields.append(f"tail: before_{cue.segments[i + 1][0]}" if i + 1 < len(cue.segments) else "tail: after_all")
        play.append("    - {" + ", ".join(fields) + "}")
    return "\n".join(rows), "\n".join(play)


def parts_yaml() -> str:
    out = []
    for name, clip in cue.clips.items():
        out.append("\n".join([f"  - id: {name}_part", f"    instrument: {name}", "    voices:", f"      - id: {name}_main",
                              "        clips:", clip.yaml(f"{name}_all", "          ")]))
    return "\n".join(out)


def sfz(ref: str, controls: str = "") -> str:
    return f"{controls}instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def glob(pattern: str, controls: str = "") -> str:
    return f"{controls}instrument_backend: {{kind: sfz, optional: false, sfz_glob: '{pattern}', settings: {{fold_to_range: false}}}}"


EMILY = glob("**/Emilyguitar/Emilyguitar/emily_basic.sfz")
TWIN = glob("**/BlackAndGreenGuitars/Programs/02-black_keyswitch.sfz", "controls: {111: 0, 114: 52, 116: 20}, ")
TWANG = glob("**/BlackAndGreenGuitars/Programs/04-green_twang.sfz")
TRUMPET_SOLO = glob("**/Virtual-Playing-Orchestra3/Brass/trumpet-SOLO-PERF.sfz", "controls: {1: 100}, ")

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
            - {{effect: delay, delay_ms: 304, feedback: 0.2, mix: 0.14}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {gain}}}
        - {{processor: balance, position: {pos}}}"""


def simple(*, hp: int, wet: float, decay: float, gain: float, pos: float = 0.0, lp: int | None = None) -> str:
    lines = ["      chain:", f"        - {{processor: highpass, cutoff_hz: {hp}}}"]
    if lp:
        lines.append(f"        - {{processor: lowpass, cutoff_hz: {lp}}}")
    lines.append(f"        - {{processor: reverb, wet: {wet}, decay_seconds: {decay}}}")
    lines.append(f"        - {{processor: gain, gain_db: {gain}}}")
    if pos:
        lines.append(f"        - {{processor: balance, position: {pos}}}")
    return "\n".join(lines)


shapes = {
    "main_street": "energy: 0.3, density: 0.4, loopable: true, role: 'the town: a two-beat, a bowed drone, the call on the twang at half speed, the answer on the fiddle'",
    "pursuit": "energy: 0.7, density: 0.7, loopable: true, role: 'the chase: a train beat, the spur on the twang, the theme on fiddle and trumpet'",
    "showdown": "energy: 0.95, density: 0.9, loopable: true, role: 'the boss: a pedal-point riff, twin leads with the fiddle, a duel, a hoedown'",
}
form, playback = form_and_playback(shapes)
def logical(score_bar: int) -> int | None:
    for _, first, last, at in cue.segments:
        if at <= score_bar <= at + last - first:
            return first + score_bar - at
    return None


progression = ", ".join(cue.harmony.get(logical(b), "Am") for b in range(1, cue.end_bar))

score = f"""schema: ambition.musicir.v3
id: spur_of_the_moment
title: Spur of the Moment
description: >-
  A western in A harmonic minor on Am, E and F, in three flavours of one
  theme: a town on an archtop two-beat with the call on a twang guitar and
  the answer on the fiddle; a chase on a train beat with fiddle and trumpet;
  and a boss fight where neoclassical metal (a pedal-point riff, twin leads,
  a fiddle-against-guitar duel) meets a half-time hoedown. Composed from first
  principles. Generated by dev/compose_spur_of_the_moment.py: edit that, not
  this file.
notes:
  - 'Jon, 2026-11-21: a cowboy western on Am, E major and F major with a heavy focus on Am; a town background, an intense action cue, and an extreme boss cue blending metal guitar with the country western. Original material; the boss borrows the Iron Toccata manner, not its notes.'
  - 'The spur: A A C A G# A E. The call: its seventh bar is G# F G# over E, the augmented second. The answer climbs to A5 and ends on G#.'
  - 'One tempo (148) for all three sections, so the game can move between them on a bar line: main_street (town), pursuit (action), showdown (boss).'
seed: {SEED}
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: {{tonic: A, mode: harmonic_minor}}
end: {{bar: {cue.end_bar}, beat: 1}}
form:
{form}
harmony:
  every_bars: 1
  cycle: false
  progression: [{progression}]
instruments:
  - {{name: archtop, group: archtop, program: steel_guitar, volume: 100, pan: 64, expression: 104, {sfz("guitar.acoustic", "controls: {100: 126}, ")}}}
  - {{name: upright, group: upright, program: acoustic_bass, volume: 106, pan: 64, expression: 108, {sfz("bass.upright")}}}
  - {{name: brushes, group: brushes, volume: 110, pan: 64, expression: 110, is_drum: true, {sfz("drums.naked")}}}
  - {{name: drone, group: drone, program: cello, volume: 100, pan: 64, expression: 100, {sfz("folk.bass_tagelharpa")}}}
  - {{name: twang, group: twang, program: clean_guitar, volume: 104, pan: 64, expression: 110, {TWANG}}}
  - {{name: fiddle, group: fiddle, program: violin, volume: 100, pan: 64, expression: 104, {sfz("strings.violin_solo")}}}
  - {{name: trumpet, group: trumpet, program: trumpet, volume: 100, pan: 64, expression: 106, {TRUMPET_SOLO}}}
  - {{name: train, group: train, volume: 114, pan: 64, expression: 114, is_drum: true, {sfz("drums.big_rusty")}}}
  - {{name: staccato, group: staccato, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1_staccato")}}}
  - {{name: stabs, group: stabs, program: trumpet, volume: 100, pan: 64, expression: 106, {sfz("orchestra.trumpets_staccato")}}}
  - {{name: rhythm_l, group: rhythm_l, program: distortion_guitar, volume: 110, pan: 64, expression: 112, {EMILY}}}
  - {{name: rhythm_r, group: rhythm_r, program: distortion_guitar, volume: 110, pan: 64, expression: 112, {EMILY}}}
  - {{name: lead, group: lead, program: distortion_guitar, volume: 104, pan: 64, expression: 112, {EMILY}}}
  - {{name: twin, group: twin, program: distortion_guitar, volume: 104, pan: 64, expression: 112, {TWIN}}}
  - {{name: growl, group: growl, program: picked_bass, volume: 116, pan: 64, expression: 116, mix_gain_db: 6.0, {sfz("bass.growly")}}}
  - {{name: kit, group: kit, volume: 124, pan: 64, expression: 120, is_drum: true, mix_gain_db: 1.0, {sfz("drums.muldjord")}}}
  - {{name: hot_fiddle, group: hot_fiddle, program: violin, volume: 104, pan: 64, expression: 110, {sfz("strings.violin_solo_marcato")}}}
  - {{name: banjo, group: banjo, program: banjo, volume: 100, pan: 64, expression: 104, {sfz("folk.banjo")}}}
  - {{name: brass, group: brass, program: trumpet, volume: 104, pan: 64, expression: 108, {sfz("orchestra.trumpets_sustain")}}}
parts:
{parts_yaml()}
processing:
  groups:
    archtop:
{simple(hp=80, wet=0.16, decay=1.6, gain=4.0, pos=-0.3)}
    upright:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3500}}
        - {{processor: gain, gain_db: 5.0}}
    brushes:
{simple(hp=40, wet=0.12, decay=1.2, gain=10.0)}
    drone:
{simple(hp=50, lp=5000, wet=0.3, decay=2.6, gain=14.0, pos=-0.15)}
    twang:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: 135, feedback: 0.12, mix: 0.12}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 15.0}}
        - {{processor: balance, position: 0.3}}
    fiddle:
{simple(hp=180, wet=0.22, decay=1.8, gain=15.0, pos=0.2)}
    trumpet:
{simple(hp=150, wet=0.3, decay=2.6, gain=6.0, pos=-0.1)}
    train:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.2, attack_ms: 10.0, release_ms: 90.0}}
        - {{processor: gain, gain_db: 4.0}}
    staccato:
{simple(hp=120, lp=9000, wet=0.18, decay=1.6, gain=4.0, pos=-0.25)}
    stabs:
{simple(hp=120, lp=8000, wet=0.2, decay=1.8, gain=8.0, pos=0.15)}
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
{LEAD_TAIL.format(gain=3.0, pos=-0.2)}
    twin:
      chain:
{HIGH_GAIN % {"pre": "12.0"}}
{LEAD_TAIL.format(gain=1.0, pos=0.3)}
    growl:
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
    kit:
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
    hot_fiddle:
{simple(hp=200, lp=9000, wet=0.16, decay=1.4, gain=10.0, pos=0.4)}
    banjo:
{simple(hp=150, wet=0.12, decay=1.4, gain=13.0, pos=-0.35)}
    brass:
{simple(hp=100, lp=7000, wet=0.22, decay=2.0, gain=8.0, pos=-0.1)}
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
  full: true
  sections:
{playback}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {cue.end_bar - 1} bars, {(cue.end_bar - 1) * 4 * 60 / BPM:.0f} s")

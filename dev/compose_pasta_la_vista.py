"""Pasta la Vista: upbeat ska for exploring, fighting and puzzling in the Noodle dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_pasta_la_vista.py scores/active/pasta_la_vista.music.yaml

Jon, 2026-10-20: "something more upbeat, let's lean more into ska ... Still
noodle dimension. But let's feel pumped while exploring / fighting / solving
puzzles with this one." The title is mine.

What sets it apart from its reggae siblings (Pastafarian, It Was Revealed to Me
in a Dream, AI Dente):
  - Ska, not reggae: B-flat major at 168 BPM, the guitar chop on EVERY
    off-beat, a walking bass in quarters, the snare on two and four.
  - A horn section sings the head: trumpet and tenor sax in octaves, the
    trombone under them.
  - The noodly guitar trades calls with the horns, then takes a solo.
  - A stop-time break before the last head.

Built for a level, in LAYERS the game mixes (the `playback` block):
  bed     skank, organ, bass                       always
  drums   ska drums                                exploring
  tune    the horn section, the noodly guitar      exploring
  combat  a ska-punk beat (kick on the beat, snare on the off-beat),
          palm-muted crunch in eighths, horn stabs
Every layer runs through every bar of the loop, so a fight can bring the
combat layer up anywhere and take it away again.

Form, 4/4 at 168 BPM:
  intro    1-4    a horn fanfare over band hits, then the band kicks in.
  head     5-20   the horns sing the head; the guitar fills.         (loop start)
  calls    21-36  the guitar calls, the horns answer; C to F builds into the solo.
  solo     37-52  the guitar solos; the horns hold backgrounds.
  break    53-56  stop time: hits, guitar licks in the holes, a fill.
  head_2   57-72  the head again, the horns in harmony, four on the floor; on F.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 168
OUT = Path(sys.argv[1])
rng = random.Random(5150)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: Pitch-bend units a cent: the Shiny guitar bends 200 cents.
BEND_PER_CENT = 8192 / 200
#: B-flat major, as pitch classes.
SCALE = (10, 0, 2, 3, 5, 7, 9)


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

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        if self.bends:
            lines.append(f"{indent}  automation:")
            seen = {}
            for when, value in sorted(self.bends):
                seen[frac(when)] = value
            for i, (when, value) in enumerate(seen.items()):
                lines.append(f"{indent}    - {{id: {clip_id}_bend_{i:04d}, at: {when}, pitch_bend: {value}}}")
        return "\n".join(lines)


def bar(n: int) -> float:
    return (n - 1) * 4.0


trumpet = Clip(drift=0.003, vel_jitter=3)
sax = Clip(drift=0.004, vel_jitter=3)
trombone = Clip(drift=0.004, vel_jitter=3)
guitar = Clip(drift=0.004, vel_jitter=4)
skank = Clip(drift=0.002, vel_jitter=4)
organ = Clip(drift=0.002, vel_jitter=4)
bass = Clip(drift=0.003, vel_jitter=3)
kit = Clip(drift=0.003, vel_jitter=4)
hats = Clip(drift=0.004, vel_jitter=6)
war_kit = Clip(drift=0.003, vel_jitter=4)
crunch = Clip(drift=0.002, vel_jitter=4)
stab_trumpets = Clip(drift=0.003, vel_jitter=3)
stab_trombones = Clip(drift=0.003, vel_jitter=3)

# ---- Harmony ------------------------------------------------------------------------
SKANK = {"Bb": ["D4", "F4", "Bb4"], "Gm": ["D4", "G4", "Bb4"], "Eb": ["Eb4", "G4", "Bb4"], "F": ["C4", "F4", "A4"],
         "Cm": ["C4", "Eb4", "G4"], "C": ["C4", "E4", "G4"]}
ORGAN = {"Bb": ["F3", "Bb3", "D4"], "Gm": ["G3", "Bb3", "D4"], "Eb": ["G3", "Bb3", "Eb4"], "F": ["F3", "A3", "C4"],
         "Cm": ["G3", "C4", "Eb4"], "C": ["G3", "C4", "E4"]}
ROOT = {"Bb": "Bb1", "Gm": "G1", "Eb": "Eb2", "F": "F1", "Cm": "C2", "C": "C2"}
MINOR = {"Gm", "Cm"}
HEAD = ["Bb", "Gm", "Eb", "F", "Bb", "Gm", "Cm", "F"] * 2
CALLS = ["Eb", "Eb", "Bb", "Bb", "Eb", "Eb", "F", "F", "Gm", "Gm", "Eb", "Eb", "C", "C", "F", "F"]
SOLO = ["Bb", "Eb", "Bb", "F"] * 4
BREAK = ["Bb", "Bb", "F", "F"]
harmony: dict[int, str] = {}


def skank_bar(n, name, vel=70):
    """The ska chop: a short upstroke on every off-beat."""
    t = bar(n)
    for k in range(4):
        skank.note(t + k + 0.5, 0.14, SKANK[name], vel - (6 if k % 2 == 0 else 0))
        organ.note(t + k + 0.5, 0.2, ORGAN[name], 54)


def walking(n, name, nxt, vel=96, push=False):
    """Quarters: the root, the third, the fifth, then a B-flat-major step into
    the next root; `push` doubles each into eighths for the last head."""
    t = bar(n)
    r = midi(ROOT[name])
    third = r + (3 if name in MINOR else 4)
    fifth = r + 7
    nxt_r = midi(ROOT[nxt])
    step = 1 if nxt_r < r else -1
    approach = nxt_r + step
    while approach % 12 not in SCALE or (name == "C" and approach % 12 == 3):
        approach += step
    line = [r, third, fifth, approach] if n % 2 else [r, r + 12, fifth, approach]
    line = [p + 12 if p < midi("E1") else p for p in line]  # the bass's lowest sample is E1
    for k, p in enumerate(line):
        if push:
            bass.note(t + k, 0.45, p, vel - (0 if k % 2 == 0 else 6))
            bass.note(t + k + 0.5, 0.4, p, vel - 14)
        else:
            bass.note(t + k, 0.85, p, vel - (0 if k % 2 == 0 else 6))


KICK, SNARE, XSTICK, HAT, OPEN_HAT, HI_TOM, MID_TOM, FLOOR_TOM, CRASH, RIDE = 36, 38, 37, 42, 46, 50, 47, 41, 49, 51


def fill(clip, n, vel=70):
    t = bar(n)
    for i in range(8):
        clip.note(t + 2.0 + i * 0.25, 0.1, SNARE if i < 4 else (HI_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM)[i - 4], vel + 5 * i)


def ska_drums(n, four=False, crash=False, last_of_phrase=False):
    """The kick on one and three (every beat when `four`), the snare on two and
    four, the hat open on the off-beats with the chop."""
    t = bar(n)
    if crash:
        kit.note(t, 0.4, CRASH, 96)
    for k in range(4):
        if four or k % 2 == 0:
            kit.note(t + k, 0.2, KICK, 100 if k % 2 == 0 else 92)
        hats.note(t + k, 0.1, HAT, 46)
        hats.note(t + k + 0.5, 0.12, OPEN_HAT if k == 3 and n % 2 == 0 else HAT, 70)
    if last_of_phrase:
        kit.note(t + 1.0, 0.2, SNARE, 100)
        fill(kit, n)
    else:
        kit.note(t + 1.0, 0.2, SNARE, 100)
        kit.note(t + 3.0, 0.2, SNARE, 104)


def punk_drums(n, crash=False, last_of_phrase=False):
    """Ska-punk: the kick on every beat, the snare on every off-beat, a ride on top."""
    t = bar(n)
    if crash:
        war_kit.note(t, 0.4, CRASH, 104)
    span = 2 if last_of_phrase else 4
    for k in range(span):
        war_kit.note(t + k, 0.2, KICK, 108 if k % 2 == 0 else 100)
        war_kit.note(t + k + 0.5, 0.2, SNARE, 98 if k % 2 else 92)
        war_kit.note(t + k, 0.1, RIDE, 70)
        war_kit.note(t + k + 0.5, 0.1, RIDE, 54)
    if last_of_phrase:
        fill(war_kit, n, vel=80)


def combat_bar(n, name):
    """Palm-muted power chords in eighths and horn stabs on the off-beats of two and four."""
    t = bar(n)
    r = midi(ROOT[name]) + 12
    if r < midi("E2"):
        r += 12
    power = [r, r + 7, r + 12]
    for e in range(8):
        crunch.note(t + e * 0.5, 0.2, power, 98 if e % 2 == 0 else 84)
    for o in (1.5, 3.5):
        STABS.append((t + o, name))


#: (when, chord) of each combat stab, written once the tune is (see `emit_stabs`).
STABS: list[tuple[float, str]] = []


def emit_stabs():
    """The stabs leave out any chord tone a semitone or a tritone from a horn note sounding with them."""
    tune = [(at, at + dur, p) for clip in (trumpet, sax, trombone) for at, dur, ps, _ in clip.events for p in ps]
    for when, name in STABS:
        sounding = {p % 12 for a, b, p in tune if a <= when + 0.01 and b > when}
        def keep(p):
            return all(min((p - q) % 12, (q - p) % 12) not in (1, 6) for q in sounding)
        stab = [midi(x) + 12 for x in SKANK[name]]
        stab_trumpets.note(when, 0.25, [p for p in stab if keep(p)] or stab[:1], 100)
        stab_trombones.note(when, 0.25, [p - 12 for p in stab if keep(p)] or [stab[0] - 12], 96)


def section(n0, chords, *, phrase=8, four=False, push=False):
    for k, name in enumerate(chords):
        n = n0 + k
        nxt = chords[(k + 1) % len(chords)]
        harmony[n] = name
        skank_bar(n, name)
        walking(n, name, nxt, push=push)
        last = k % phrase == phrase - 1
        ska_drums(n, four=four, crash=k % phrase == 0, last_of_phrase=last)
        punk_drums(n, crash=k % phrase == 0, last_of_phrase=k % 4 == 3)
        combat_bar(n, name)


# ---- The tune ------------------------------------------------------------------------
def slide(clip: Clip, at: float, cents: float, over: float = 0.18):
    start = round(-cents * BEND_PER_CENT)
    clip.bends.append((F(at).limit_denominator(960) - F(1, 64), max(-8191, start)))
    for i in (1, 2, 3):
        clip.bends.append((F(at + over * i / 3).limit_denominator(960), round(start * (1 - i / 3))))


def sing(clip: Clip, n: int, phrase, vel=84, octave=0, length=0.95):
    for k, notes in enumerate(phrase):
        for note in notes:
            at, dur, name = note[:3]
            orn = note[3] if len(note) > 3 else ""
            when = bar(n + k) + at
            pitch = midi(name) + 12 * octave
            assert clip is not guitar or pitch <= midi("A5"), f"guitar note {name} above A5"
            if orn == "h":
                clip.note(when - 0.08, 0.08, pitch - 1, vel - 16)
            clip.note(when, dur * length, pitch, vel + (5 if at in (0.0, 1.0, 2.0, 3.0) else 0))
            if clip is guitar and orn in ("s", "v"):
                slide(clip, when, 200 if orn == "s" else 100)


def harmony_below(name: str, chord: str) -> int:
    """The nearest tone of `chord` at least a minor third below `name`."""
    tones = {midi(x) % 12 for x in SKANK[chord]}
    q = midi(name) - 3
    while q % 12 not in tones:
        q -= 1
    return q


def horns(n, phrase, vel=104, harmony_line=False):
    """The section: trumpet on top, the tenor an octave below; the trombone
    doubles the tenor, or takes a third under it in the last head."""
    sing(trumpet, n, phrase, vel=vel, length=0.9)
    sing(sax, n, phrase, vel=vel - 6, octave=-1, length=0.9)
    if not harmony_line:
        sing(trombone, n, phrase, vel=vel - 8, octave=-1, length=0.9)
        return
    for k, notes in enumerate(phrase):
        for note in notes:
            at, dur, name = note[:3]
            trombone.note(bar(n + k) + at, dur * 0.9, harmony_below(name, harmony[n + k]) - 12, vel - 8)


HEAD_TUNE = [
    [(0.0, 0.5, "F4"), (0.5, 0.5, "Bb4"), (1.0, 0.5, "D5"), (1.5, 1.0, "F5"), (3.0, 0.5, "Eb5"), (3.5, 0.5, "D5")],
    [(0.0, 1.0, "D5"), (1.0, 0.5, "Bb4"), (1.5, 1.5, "G4"), (3.5, 0.5, "D5")],
    [(0.0, 0.5, "Bb4"), (0.5, 0.5, "Eb5"), (1.0, 0.5, "G5"), (1.5, 1.0, "F5"), (2.5, 0.5, "Eb5"), (3.0, 1.0, "G5")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "A4"), (1.0, 0.5, "F4"), (1.5, 0.5, "A4"), (2.0, 0.5, "C5"), (2.5, 1.5, "Eb5")],
    [(0.0, 0.5, "F4"), (0.5, 0.5, "Bb4"), (1.0, 0.5, "D5"), (1.5, 1.0, "F5"), (3.0, 0.5, "Eb5"), (3.5, 0.5, "D5")],
    [(0.0, 0.5, "D5"), (0.5, 0.5, "G5"), (1.0, 1.0, "F5"), (2.0, 0.5, "D5"), (2.5, 1.0, "Bb4"), (3.5, 0.5, "D5")],
    [(0.0, 0.5, "Eb5"), (0.5, 0.5, "C5"), (1.0, 0.5, "G4"), (1.5, 0.5, "C5"), (2.0, 1.0, "Eb5"), (3.0, 0.5, "D5"), (3.5, 0.5, "C5")],
    [(0.0, 1.0, "A4"), (1.0, 0.5, "C5"), (1.5, 0.5, "F5"), (2.0, 2.0, "F5")],
]
#: The head's second ending climbs, into the calls (and, in the last head, round to the top).
HEAD_END = [(0.0, 0.5, "F5"), (0.5, 0.5, "F5"), (1.0, 0.5, "G5"), (1.5, 0.5, "A5"), (2.0, 2.0, "C6")]
#: The guitar's fills in the head, where the horns hold.
HEAD_FILLS = [
    [], [(2.0, 0.25, "Bb4"), (2.25, 0.25, "C5"), (2.5, 0.5, "D5", "s"), (3.0, 0.5, "G4")], [], [],
    [], [], [], [(2.5, 0.25, "C5"), (2.75, 0.25, "D5"), (3.0, 0.25, "Eb5"), (3.25, 0.25, "F5"), (3.5, 0.5, "A5", "s")],
]
#: Two bars of guitar, two bars of horns; four times.
CALL = [
    [[(0.0, 0.5, "G4"), (0.5, 0.5, "Bb4"), (1.0, 1.0, "Eb5", "s"), (2.0, 0.25, "F5"), (2.25, 0.25, "Eb5"), (2.5, 0.5, "C5"), (3.0, 1.0, "Bb4", "v")],
     [(0.0, 0.5, "G4"), (0.5, 0.5, "Bb4"), (1.0, 2.0, "C5", "s")]],
    [[(0.0, 0.25, "Bb4"), (0.25, 0.25, "C5"), (0.5, 0.5, "Eb5"), (1.0, 0.5, "G5", "s"), (1.5, 0.5, "F5"), (2.0, 1.0, "Eb5", "v"), (3.0, 0.5, "C5"), (3.5, 0.5, "Bb4")],
     [(0.0, 2.0, "G4", "s"), (2.5, 0.5, "Bb4")]],
    [[(0.0, 0.5, "D5"), (0.5, 0.5, "F5"), (1.0, 1.0, "G5", "s"), (2.0, 0.25, "F5"), (2.25, 0.25, "D5"), (2.5, 0.5, "Bb4"), (3.0, 1.0, "D5", "v")],
     [(0.0, 0.5, "C5"), (0.5, 0.5, "Bb4"), (1.0, 2.0, "G4", "s")]],
    [[(0.0, 0.5, "C5"), (0.5, 0.5, "E5"), (1.0, 1.0, "G5", "s"), (2.0, 0.5, "E5"), (2.5, 0.5, "C5"), (3.0, 1.0, "D5", "v")],
     [(0.0, 0.5, "E5"), (0.5, 0.5, "G5"), (1.0, 2.0, "A5", "s")]],
]
ANSWER = [
    [[(0.0, 0.5, "D5"), (0.5, 0.5, "D5"), (1.0, 0.5, "F5"), (1.5, 1.0, "D5"), (3.0, 0.5, "C5"), (3.5, 0.5, "Bb4")],
     [(0.0, 1.5, "Bb4"), (2.0, 0.5, "F4"), (2.5, 0.5, "Bb4")]],
    [[(0.0, 0.5, "C5"), (0.5, 0.5, "C5"), (1.0, 0.5, "F5"), (1.5, 1.0, "Eb5"), (3.0, 0.5, "D5"), (3.5, 0.5, "C5")],
     [(0.0, 1.0, "A4"), (1.0, 0.5, "C5"), (1.5, 1.5, "F5")]],
    [[(0.0, 0.5, "Eb5"), (0.5, 0.5, "Eb5"), (1.0, 0.5, "G5"), (1.5, 1.0, "Eb5"), (3.0, 0.5, "D5"), (3.5, 0.5, "C5")],
     [(0.0, 1.5, "Bb4"), (2.0, 0.5, "G4"), (2.5, 0.5, "Bb4")]],
    [[(0.0, 0.5, "F4"), (0.5, 0.5, "A4"), (1.0, 0.5, "C5"), (1.5, 0.5, "Eb5"), (2.0, 0.5, "F5"), (2.5, 0.5, "Eb5"), (3.0, 0.5, "C5"), (3.5, 0.5, "A4")],
     [(0.0, 0.5, "C5"), (0.5, 0.5, "Eb5"), (1.0, 0.5, "F5"), (1.5, 0.5, "G5"), (2.0, 2.0, "A5")]],
]
SOLO_LINE = [
    [(0.0, 0.5, "F4"), (0.5, 0.5, "Bb4"), (1.0, 0.5, "C5"), (1.5, 0.5, "D5"), (2.0, 1.0, "F5", "s"), (3.0, 0.5, "D5"), (3.5, 0.5, "C5")],
    [(0.0, 1.5, "Bb4", "v"), (1.5, 0.5, "G4"), (2.0, 0.5, "Bb4"), (2.5, 0.5, "C5"), (3.0, 1.0, "Eb5", "s")],
    [(0.0, 0.25, "F5"), (0.25, 0.25, "G5"), (0.5, 0.5, "F5"), (1.0, 0.5, "D5"), (1.5, 0.5, "F5"), (2.0, 1.0, "G5", "s"), (3.0, 1.0, "F5", "v")],
    [(0.0, 0.5, "Eb5"), (0.5, 0.5, "C5"), (1.0, 0.5, "A4"), (1.5, 0.5, "C5"), (2.0, 2.0, "F5", "s")],
    [(0.5, 0.25, "Bb4"), (0.75, 0.25, "C5"), (1.0, 0.25, "D5"), (1.25, 0.25, "F5"), (1.5, 0.5, "G5"), (2.0, 0.5, "F5"), (2.5, 0.5, "D5"), (3.0, 1.0, "F5", "v")],
    [(0.0, 0.5, "G5"), (0.5, 0.5, "F5"), (1.0, 0.5, "Eb5"), (1.5, 0.5, "C5"), (2.0, 1.0, "Bb4", "s"), (3.0, 0.5, "G4"), (3.5, 0.5, "Bb4")],
    [(0.0, 1.0, "D5", "h"), (1.0, 0.5, "F5"), (1.5, 0.5, "D5"), (2.0, 0.5, "C5"), (2.5, 0.5, "Bb4"), (3.0, 1.0, "G4", "s")],
    [(0.0, 0.5, "A4"), (0.5, 0.5, "C5"), (1.0, 0.5, "Eb5"), (1.5, 0.5, "F5"), (2.0, 1.0, "A5", "s"), (3.0, 0.5, "G5"), (3.5, 0.5, "F5")],
    [(0.0, 0.25, "Bb4"), (0.25, 0.25, "C5"), (0.5, 0.25, "D5"), (0.75, 0.25, "F5"), (1.0, 0.25, "G5"), (1.25, 0.25, "F5"), (1.5, 0.25, "D5"), (1.75, 0.25, "C5"), (2.0, 1.0, "D5", "s"), (3.0, 1.0, "F5", "v")],
    [(0.0, 0.25, "G5"), (0.25, 0.25, "F5"), (0.5, 0.25, "Eb5"), (0.75, 0.25, "C5"), (1.0, 0.5, "Bb4"), (1.5, 0.5, "C5"), (2.0, 1.0, "Eb5", "s"), (3.0, 0.5, "G5"), (3.5, 0.5, "Eb5")],
    [(0.0, 1.5, "F5", "v"), (1.5, 0.25, "D5"), (1.75, 0.25, "F5"), (2.0, 0.5, "G5"), (2.5, 0.5, "F5"), (3.0, 1.0, "D5", "s")],
    [(0.0, 0.5, "C5"), (0.5, 0.5, "A4"), (1.0, 0.5, "C5"), (1.5, 0.5, "Eb5", "h"), (2.0, 1.0, "F5", "s"), (3.0, 1.0, "A5", "s")],
    [(0.0, 0.25, "G5"), (0.25, 0.25, "F5"), (0.5, 0.25, "D5"), (0.75, 0.25, "C5"), (1.0, 0.25, "D5"), (1.25, 0.25, "C5"), (1.5, 0.25, "Bb4"), (1.75, 0.25, "G4"), (2.0, 2.0, "Bb4", "v")],
    [(0.0, 1.0, "G5", "s"), (1.0, 0.5, "F5"), (1.5, 0.5, "Eb5"), (2.0, 0.5, "C5"), (2.5, 0.5, "Eb5"), (3.0, 1.0, "G5", "v")],
    [(0.0, 0.5, "F5"), (0.5, 0.5, "D5"), (1.0, 0.5, "Bb4"), (1.5, 0.5, "D5"), (2.0, 0.5, "F5"), (2.5, 0.5, "G5"), (3.0, 1.0, "F5", "s")],
    [(0.0, 0.25, "C5"), (0.25, 0.25, "D5"), (0.5, 0.25, "Eb5"), (0.75, 0.25, "F5"), (1.0, 0.5, "G5"), (1.5, 0.5, "A5"), (2.0, 2.0, "A5", "v")],
]
#: Under the solo the horns hold the chord's third and punch the and of four.
BACKING_TOP = {"Bb": "D5", "Eb": "G4", "F": "A4"}
#: The guitar's licks in the break's holes.
BREAK_LICKS = [
    [(1.0, 0.25, "Bb4"), (1.25, 0.25, "C5"), (1.5, 0.25, "D5"), (1.75, 0.25, "F5"), (3.0, 0.5, "G5", "s"), (3.5, 0.5, "F5")],
    [(1.0, 0.25, "D5"), (1.25, 0.25, "F5"), (1.5, 0.25, "G5"), (1.75, 0.25, "F5"), (3.0, 1.0, "D5", "v")],
    [(1.0, 0.25, "C5"), (1.25, 0.25, "Eb5"), (1.5, 0.5, "F5", "s"), (2.0, 0.25, "Eb5"), (2.25, 0.25, "C5"), (2.5, 0.5, "A4"), (3.0, 1.0, "C5", "s")],
    [],
]

# Intro, bars 1-4: a fanfare over hits, then the band.
INTRO = ["Bb", "F", "Bb", "F"]
for k, name in enumerate(INTRO):
    harmony[1 + k] = name
for n, name in ((1, "Bb"), (2, "F")):
    t = bar(n)
    kit.note(t, 0.4, CRASH, 100)
    kit.note(t, 0.2, KICK, 104)
    bass.note(t, 0.8, midi(ROOT[name]), 100)
    skank.note(t, 0.3, SKANK[name], 90)
    organ.note(t, 1.5, ORGAN[name], 70)
horns(1, [[(0.0, 0.5, "F4"), (0.5, 0.5, "Bb4"), (1.0, 0.5, "D5"), (1.5, 1.0, "F5"), (3.0, 0.5, "F5"), (3.5, 0.5, "F5")],
          [(0.0, 1.0, "F5"), (1.0, 0.5, "Eb5"), (1.5, 0.5, "C5"), (2.0, 2.0, "A4")]], vel=110)
fill(kit, 2, vel=74)
for k, name in enumerate(INTRO[2:]):
    n = 3 + k
    skank_bar(n, name)
    walking(n, name, "Bb" if k else "F")
    ska_drums(n, crash=k == 0, last_of_phrase=k == 1)

section(5, HEAD)
horns(5, HEAD_TUNE + HEAD_TUNE[:7] + [HEAD_END])
sing(guitar, 5, HEAD_FILLS + HEAD_FILLS[:7], vel=80)

section(21, CALLS)
for i in range(4):
    sing(guitar, 21 + 4 * i, CALL[i], vel=88)
    horns(23 + 4 * i, ANSWER[i], vel=104 + 2 * i)

section(37, SOLO)
sing(guitar, 37, SOLO_LINE, vel=90)
for k, name in enumerate(SOLO):
    t = bar(37 + k)
    top = midi(BACKING_TOP[name])
    trumpet.note(t, 2.6, top, 78)
    sax.note(t, 2.6, top - 12, 74)
    trombone.note(t, 2.6, midi(ROOT[name]) + 24 if name != "Eb" else midi(ROOT[name]) + 12, 72)
    for clip, p in ((trumpet, top), (sax, top - 12)):
        clip.note(t + 3.5, 0.3, p, 96)

# Break, bars 53-56: stop time.
for k, name in enumerate(BREAK):
    n = 53 + k
    harmony[n] = name
    t = bar(n)
    hits = (0.0,) if k == 3 else (0.0, 2.5)
    for o in hits:
        skank.note(t + o, 0.3, SKANK[name], 96)
        organ.note(t + o, 0.4, ORGAN[name], 72)
        bass.note(t + o, 0.4, midi(ROOT[name]), 104)
        kit.note(t + o, 0.2, KICK, 106)
        kit.note(t + o, 0.4, CRASH, 92)
        war_kit.note(t + o, 0.2, KICK, 110)
        war_kit.note(t + o, 0.4, CRASH, 100)
        crunch.note(t + o, 0.35, [midi(ROOT[name]) + 24, midi(ROOT[name]) + 31], 104)
        stab_trumpets.note(t + o, 0.3, [midi(x) + 12 for x in SKANK[name]], 108)
        stab_trombones.note(t + o, 0.3, [midi(x) for x in SKANK[name]], 104)
    for o in hits:
        trumpet.note(t + o, 0.3, midi(SKANK[name][2]) + 12, 110)
        sax.note(t + o, 0.3, midi(SKANK[name][1]), 104)
        trombone.note(t + o, 0.3, midi(SKANK[name][0]) - 12, 102)
sing(guitar, 53, BREAK_LICKS, vel=92)
fill(kit, 56, vel=76)
fill(war_kit, 56, vel=84)
for i in range(4):  # the trumpet climbs under the fill, F to B-flat
    trumpet.note(bar(56) + 1.0 + i * 0.25, 0.22, midi(("F5", "G5", "A5", "Bb5")[i]), 96 + 4 * i)

section(57, HEAD, four=True, push=True)
horns(57, HEAD_TUNE + HEAD_TUNE[:7] + [[(0.0, 0.5, "F5"), (0.5, 0.5, "F5"), (1.0, 0.5, "G5"), (1.5, 0.5, "A5"), (2.0, 2.0, "C6")]],
      vel=108, harmony_line=True)
sing(guitar, 57, HEAD_TUNE[:4], vel=80, octave=-1)
sing(guitar, 61, HEAD_FILLS[4:], vel=84)
sing(guitar, 65, HEAD_TUNE[:4], vel=82, octave=-1)
sing(guitar, 69, HEAD_FILLS[4:7], vel=84)

emit_stabs()

END_BAR = 73
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


NAKED = "instrument_backend: {kind: sfz, library_ref: drums.naked, settings: {render_timeout_s: 900}}"
SHINY = "controls: {100: 0, 107: 0}, instrument_backend: {kind: sfz, sfz_glob: '**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz', settings: {fold_to_range: false}}"
EMILY = "instrument_backend: {kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {fold_to_range: false}}"
VPO = "controls: {1: 100}, instrument_backend: {kind: sfz, sfz_glob: '**/Virtual-Playing-Orchestra3/Brass/%s', settings: {fold_to_range: false}}"
TENOR = "instrument_backend: {kind: sfz, sfz_glob: '**/Reed Aerophones/Tenor Saxophone - Non-Vibrato.sfz', settings: {fold_to_range: false}}"
ECHO = round(60000 / BPM * 0.75)  # a dotted eighth
score = f"""schema: ambition.musicir.v3
id: pasta_la_vista
title: Pasta la Vista
description: >-
  Upbeat ska for exploring, fighting and puzzling in the Noodle dimension:
  B-flat major at 168 BPM, the guitar chop and the organ on every off-beat, a
  walking bass, the snare on two and four. A horn section (trumpet and tenor
  sax in octaves, trombone) sings the head; the noodly guitar trades calls
  with it and takes a solo; a stop-time break leads to the last head in
  harmony. Fights bring in the combat layer: a ska-punk beat, palm-muted
  crunch in eighths and horn stabs (Jon, 2026-10-20; the title is mine).
  Generated by dev/compose_pasta_la_vista.py: edit that, not this file.
notes:
  - 'The intro plays once; the loop is bars 5-72, ending on F, back to B-flat at bar 5.'
  - 'Layered for a level: bed, drums, tune and combat; the combat layer runs through every bar of the loop.'
  - 'No choir, celesta or harp: those belong to the holy tune.'
  - 'No held guitar note above A5.'
seed: 5150
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: Bb major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.6, density: 0.4, role: 'a horn fanfare over hits, then the band'}}
  - {{id: head, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.75, density: 0.7, loopable: true, role: 'the horns sing the head; the guitar fills'}}
  - {{id: calls, from: {{bar: 21, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.75, density: 0.65, loopable: true, role: 'the guitar calls, the horns answer'}}
  - {{id: solo, from: {{bar: 37, beat: 1}}, to: {{bar: 53, beat: 1}}, energy: 0.8, density: 0.65, loopable: true, role: 'the guitar solos over horn backgrounds'}}
  - {{id: break, from: {{bar: 53, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.7, density: 0.35, loopable: true, role: 'stop time; guitar licks in the holes; a fill'}}
  - {{id: head_2, from: {{bar: 57, beat: 1}}, to: {{bar: 73, beat: 1}}, energy: 0.9, density: 0.8, loopable: true, role: 'the head in harmony, four on the floor; on F'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: trumpet, group: horns, program: trumpet, volume: 104, pan: 64, expression: 110, {VPO % "trumpet-SOLO-PERF.sfz"}}}
  - {{name: sax, group: horns, program: tenor_sax, volume: 100, pan: 64, expression: 106, {TENOR}}}
  - {{name: trombone, group: horns, program: trombone, volume: 100, pan: 64, expression: 106, {VPO % "trombone-SOLO-PERF.sfz"}}}
  - {{name: guitar, group: guitar, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
  - {{name: skank, group: skank, program: clean_guitar, volume: 100, pan: 64, expression: 108, {SHINY}}}
  - {{name: organ, group: organ, program: drawbar_organ, volume: 92, pan: 64, expression: 100}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 112, pan: 64, expression: 114, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndBlueBasses/Programs/04-babyblue_warm.sfz'}}}}
  - {{name: kit, group: drums, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: hats, group: hats, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: war_kit, group: war_drums, volume: 120, pan: 64, expression: 118, is_drum: true, {NAKED}}}
  - {{name: crunch, group: crunch, program: distortion_guitar, volume: 108, pan: 64, expression: 112, {EMILY}}}
  - {{name: stab_trumpets, group: stabs, program: trumpet, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trumpets_staccato}}}}
  - {{name: stab_trombones, group: stabs, program: trombone, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trombones_staccato}}}}
parts:
{part("trumpet_part", "trumpet", trumpet)}
{part("sax_part", "sax", sax)}
{part("trombone_part", "trombone", trombone)}
{part("guitar_part", "guitar", guitar)}
{part("skank_part", "skank", skank)}
{part("organ_part", "organ", organ)}
{part("bass_part", "bass", bass)}
{part("kit_part", "kit", kit)}
{part("hats_part", "hats", hats)}
{part("war_kit_part", "war_kit", war_kit)}
{part("crunch_part", "crunch", crunch)}
{part("stab_trumpets_part", "stab_trumpets", stab_trumpets)}
{part("stab_trombones_part", "stab_trombones", stab_trombones)}
processing:
  groups:
    horns:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 1400, q: 0.9, db: 2.0}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.4, attack_ms: 6.0, release_ms: 90.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.3}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: 0.1}}
    guitar:
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
        - {{processor: lowpass, cutoff_hz: 5600}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.22, mix: 0.16}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: -0.2}}
    skank:
      chain:
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_redeye#chump
          binary: lv2apply
          channel_mode: dual_mono
          params: {{Gain: 0.3, Tone: 0.7, Volume: 0.5}}
        - {{processor: highpass, cutoff_hz: 200}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 2800, q: 1.0, db: -4.0}}
            - {{type: peak, hz: 600, q: 0.9, db: 1.5}}
        - {{processor: lowpass, cutoff_hz: 3800}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.5, attack_ms: 4.0, release_ms: 80.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 0.9}}
        - {{processor: gain, gain_db: 1.5}}
        - {{processor: balance, position: -0.45}}
    organ:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - processor: pedalboard
          effects:
            - {{effect: chorus, rate_hz: 5.5, depth: 0.12, mix: 0.3}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 0.9}}
        - {{processor: gain, gain_db: 4.0}}
        - {{processor: balance, position: 0.45}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: lowpass, cutoff_hz: 1200}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 90, q: 0.8, db: 2.0}}
            - {{type: peak, hz: 700, q: 1.0, db: 2.0}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 15.0, release_ms: 110.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -3.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 65, q: 1.0, db: 2.0}}
            - {{type: peak, hz: 200, q: 1.2, db: 1.5}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.0, attack_ms: 10.0, release_ms: 80.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 0.9}}
        - {{processor: gain, gain_db: 4.0}}
    hats:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: gain, gain_db: 17.0}}
        - {{processor: balance, position: 0.3}}
    war_drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 60, q: 1.0, db: 3.0}}
            - {{type: peak, hz: 3500, q: 1.0, db: -1.5}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.5, attack_ms: 10.0, release_ms: 80.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: -1.0}}
    crunch:
      chain:
        - processor: pedalboard
          effects:
            - {{effect: gain, gain_db: 10.0}}
            - {{effect: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 8.0, release_ms: 110.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gxts9#ts9sim
          binary: lv2apply
          channel_mode: dual_mono
          wet_mix: 0.5
          params: {{fslider0_: -4.0, fslider1_: 680.0, fslider2_: 0.66, BYPASS: 1.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.6
          params: {{P6v: 0.74, Middle: 0.66, Bass: 0.5, Treble: 0.58, WET_DRY: 60.0, GAIN: -2.0}}
        - {{processor: highpass, cutoff_hz: 100}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
            - {{type: peak, hz: 4920, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: gain, gain_db: -9.5}}
        - {{processor: balance, position: 0.55}}
    stabs:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 1600, q: 0.9, db: 1.5}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.4, attack_ms: 5.0, release_ms: 80.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: -0.3}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 20.0, release_ms: 150.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.1}}
      - {{processor: limiter, target_peak_db: -2.0, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  # Exploring plays bed, drums and tune; a fight brings in combat (each layer
  # runs through every bar of the loop).
  layers:
    bed: [skank, organ, bass]
    drums: [drums, hats]
    tune: [horns, guitar]
    combat: [war_drums, crunch, stabs]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [head, calls, solo, break, head_2], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

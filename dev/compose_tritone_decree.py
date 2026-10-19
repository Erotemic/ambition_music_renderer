"""The Tritone Decree: a heavy metal theme in E Locrian for the Evil
dimension (Castle Godwin). Writes its MusicIR v3 score:

    python3 dev/compose_tritone_decree.py scores/active/tritone_decree.music.yaml

Composed from first principles (Jon, 2026-10-19: "come up with your own
composition for a heavy metal Locrian evil theme").

E Locrian: E F G A Bb C D. The home chord is diminished (E G Bb): the
tonic has no perfect fifth, and its fifth is the tritone Bb. The riff
gallops on E and leans on F (the flat second) and Bb (the flat fifth); the
cadence lands on an E-Bb dyad, a home that never settles.

Form, 4/4 at 140 BPM:
  intro       1-8    bells toll E and Bb, the male choir hums the tritone,
                      the guitar swells; then the riff with floor toms.
  decree      9-16   the riff, the full band.                 (loop start)
  theme       17-32  the theme on strings and choir, the guitars chug.
  descent     33-40  half time: hits, chant, bells; then a climbing build.
  solo        41-56  the lead guitar; the last four bars in harmony.
  proclamation 57-64 the theme's second half, everything at once.
  turnaround  65-72  the riff, a break, and back to the decree.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 140
OUT = Path(sys.argv[1])
rng = random.Random(1933)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


LOCRIAN = [midi(n) % 12 for n in ("E4", "F4", "G4", "A4", "Bb4", "C5", "D5")]


def scale_step(pitch: int, steps: int) -> int:
    """`pitch` moved `steps` degrees along E Locrian."""
    octave, pc = divmod(pitch, 12)
    idx = LOCRIAN.index(pc)
    idx += steps
    octave += idx // 7
    return octave * 12 + LOCRIAN[idx % 7]


def frac(beats) -> str:
    """Beats as a fraction of a whole note, on whole ticks of ppq 960."""
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    # Always a fraction: a bare integer is a tick offset.
    return f"{value.numerator}/{value.denominator}"


class Clip:
    """Exact events of one clip, in beats from its start."""

    def __init__(self, bar: int, jitter_ms: float = 0.0, vel_jitter: int = 0):
        self.bar = bar
        self.events: list[tuple] = []
        self.jitter = jitter_ms / 1000.0 * BPM / 60.0  # beats
        self.vel_jitter = vel_jitter

    def note(self, at, dur, pitches, vel):
        at = F(at).limit_denominator(960)
        if self.jitter and at > 0:
            at += F(rng.uniform(-self.jitter, self.jitter)).limit_denominator(960)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        pitches = [p if isinstance(p, int) else midi(p) for p in pitches]
        self.events.append((at, F(dur), pitches, vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: {self.bar}, beat: 1}}", f"{indent}  events:"]
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


# ---- The guitar riff ------------------------------------------------------
E2, F2, G2, A2, Bb2, C3, D3 = (midi(n) for n in ("E2", "F2", "G2", "A2", "Bb2", "C3", "D3"))


def power(root: int, tritone: bool = False) -> list[int]:
    """A power chord on `root`: root, fifth, octave. On E, Locrian has no
    fifth: the octave alone, or the tritone when `tritone`."""
    if root % 12 == 4:
        return [root, root + 6] if tritone else [root, root + 12]
    return [root, root + 7, root + 12]


def gallop(clip: Clip, bar: int, beat: float, root: int, vel=96):
    """Palm-muted gallop on one beat: an eighth and two sixteenths."""
    off = bar * 4 + beat
    clip.note(off, 0.18, [root, root + 12] if root % 12 == 4 else [root, root + 7], vel)
    clip.note(off + 0.5, 0.12, [root, root + 12] if root % 12 == 4 else [root, root + 7], vel - 14)
    clip.note(off + 0.75, 0.12, [root, root + 12] if root % 12 == 4 else [root, root + 7], vel - 10)


def riff(clip: Clip, bar: int, variant: str, bass: Clip | None = None):
    """Two bars of the decree. `variant`: 'a' lands on the E-Bb dyad, 'b'
    walks the power chords down into the next E."""
    for b in (0, 1):
        for beat in (0, 1):
            gallop(clip, bar + b, beat, E2, 100 if beat == 0 else 92)
            if bass:
                bass.note((bar + b) * 4 + beat, 0.45, E2, 100)
                bass.note((bar + b) * 4 + beat + 0.5, 0.2, E2, 86)
                bass.note((bar + b) * 4 + beat + 0.75, 0.2, E2, 90)
    t = bar * 4
    clip.note(t + 2.0, 0.42, power(F2), 112)
    clip.note(t + 2.5, 0.12, [E2, E2 + 12], 90)
    clip.note(t + 2.75, 0.12, [E2, E2 + 12], 94)
    clip.note(t + 3.0, 0.95, power(Bb2), 114)
    if bass:
        bass.note(t + 2.0, 0.45, F2, 104)
        bass.note(t + 2.5, 0.2, E2, 88)
        bass.note(t + 2.75, 0.2, E2, 90)
        bass.note(t + 3.0, 0.95, Bb2, 106)
    t = (bar + 1) * 4
    if variant == "a":
        clip.note(t + 2.0, 0.42, power(G2), 112)
        clip.note(t + 2.5, 0.42, power(F2), 108)
        clip.note(t + 3.0, 0.98, power(E2, tritone=True), 118)
        if bass:
            bass.note(t + 2.0, 0.45, G2, 104)
            bass.note(t + 2.5, 0.45, F2, 100)
            bass.note(t + 3.0, 0.98, E2, 110)
    else:
        for i, root in enumerate((C3, Bb2, A2, F2)):
            clip.note(t + 2.0 + 0.5 * i, 0.42, power(root), 112 - 2 * i)
            if bass:
                bass.note(t + 2.0 + 0.5 * i, 0.45, root, 104)


# ---- The theme ------------------------------------------------------------
THEME = [
    # Statement: the tonic, the flat second, up to the flat fifth and home.
    [("E4", 2), ("F4", 1), ("E4", 1)],
    [("G4", 3), ("F4", 1)],
    [("Bb4", 1), ("A4", 1), ("G4", 1), ("F4", 1)],
    [("E4", 4)],
    # Again, reaching a step higher.
    [("E4", 2), ("F4", 1), ("G4", 1)],
    [("C5", 3), ("Bb4", 1)],
    [("A4", 1), ("G4", 1), ("F4", 1), ("G4", 1)],
    [("Bb4", 2), ("A4", 1), ("F4", 1)],
    # The answer, on the flat fifth: it climbs to the top and hangs there.
    [("Bb4", 2), ("C5", 1), ("Bb4", 1)],
    [("D5", 3), ("C5", 1)],
    [("Bb4", 1), ("A4", 1), ("G4", 1), ("A4", 1)],
    [("Bb4", 4)],
    # The decree: down through the flat second to the home it cannot rest on.
    [("G4", 2), ("A4", 1), ("Bb4", 1)],
    [("F4", 3), ("G4", 1)],
    [("F4", 1), ("E4", 1), ("F4", 1), ("D4", 1)],
    [("E4", 4)],
]
THEME_ROOTS = [E2, G2, Bb2, E2, E2, C3, F2, Bb2, Bb2, D3, G2, E2, G2, F2, D3, E2]
THEME_CHORDS = ["Edim", "Gm", "Bb", "Edim", "Edim", "C", "F", "Bb", "Bb", "Dm", "Gm", "Edim", "Gm", "F", "Dm", "Edim"]
CHORD_TONES = {
    "Edim": ["E3", "G3", "Bb3"], "Gm": ["G3", "Bb3", "D4"], "Bb": ["F3", "Bb3", "D4"], "C": ["E3", "G3", "C4"],
    "F": ["F3", "A3", "C4"], "Dm": ["F3", "A3", "D4"], "Am": ["E3", "A3", "C4"],
}


def theme(clip: Clip, bar: int, bars=range(16), octave=0, vel=96):
    for k, i in enumerate(bars):
        beat = 0.0
        for name, dur in THEME[i]:
            accent = 8 if beat == 0 else 0
            clip.note((bar + k) * 4 + beat, dur * 0.97, midi(name) + 12 * octave, vel + accent)
            beat += dur


def chug_bar(clip: Clip, bar: int, root: int, vel=94, bass: Clip | None = None):
    """Eighth-note chugs with a gallop to the next bar; accents on 1 and 3."""
    t = bar * 4
    chord = power(root)
    for i in range(7):
        accent = 14 if i in (0, 4) else 0
        clip.note(t + 0.5 * i, 0.4 if accent else 0.16, chord if accent else chord[:2], vel - 8 + accent)
        if bass:
            bass.note(t + 0.5 * i, 0.45, root, 92 + accent // 2)
    clip.note(t + 3.5, 0.12, chord[:2], vel - 10)
    clip.note(t + 3.75, 0.12, chord[:2], vel - 6)
    if bass:
        bass.note(t + 3.5, 0.2, root, 88)
        bass.note(t + 3.75, 0.2, root, 90)


# ---- Drums (GM keys of the Muldjord kit) -----------------------------------
KICK, SNARE, HAT, OPEN_HAT, CRASH, CHINA, RIDE, RIDE_BELL, FLOOR, MID, HIGH = 36, 38, 42, 46, 49, 52, 51, 53, 41, 45, 48


def drum_groove(kit: Clip, bar: int, style: str, crash=False):
    t = bar * 4
    if style == "gallop":
        for beat in range(4):
            for o, v in ((0, 112), (0.5, 98), (0.75, 102)):
                kit.note(t + beat + o, 0.1, KICK, v)
            kit.note(t + beat, 0.1, RIDE if beat % 2 else RIDE_BELL, 84)
            kit.note(t + beat + 0.5, 0.1, RIDE, 66)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 118)
    elif style == "drive":
        for i in range(16):
            kit.note(t + 0.25 * i, 0.08, KICK, 104 if i % 2 == 0 else 92)
        for i in range(8):
            kit.note(t + 0.5 * i, 0.07, HAT, 78 if i % 2 == 0 else 62)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 118)
    elif style == "march":
        for i in range(8):
            kit.note(t + 0.5 * i, 0.1, KICK, 106 if i % 2 == 0 else 88)
            kit.note(t + 0.5 * i, 0.07, HAT, 80 if i % 2 == 0 else 60)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 116)
        kit.note(t + 3.75, 0.08, SNARE, 70)
    elif style == "half":
        kit.note(t + 0, 0.12, KICK, 120)
        kit.note(t + 0.75, 0.1, KICK, 100)
        kit.note(t + 1.5, 0.1, KICK, 104)
        kit.note(t + 2, 0.14, SNARE, 122)
        for beat in range(4):
            kit.note(t + beat, 0.1, CHINA if beat == 0 else RIDE_BELL, 96 if beat == 0 else 80)
    elif style == "toms":
        for beat in range(4):
            kit.note(t + beat, 0.15, FLOOR, 108)
            kit.note(t + beat + 0.5, 0.1, FLOOR, 88)
            kit.note(t + beat + 0.75, 0.1, FLOOR, 92)
        kit.note(t + 3.5, 0.1, MID, 96)
    if crash:
        kit.note(t, 0.6, CRASH, 116)
        kit.note(t, 0.12, KICK, 122)


def fill(kit: Clip, bar: int, start=2.0):
    """A tom run down the kit over the last beats of `bar`."""
    t = bar * 4
    toms = [HIGH, HIGH, MID, MID, FLOOR, FLOOR, FLOOR, SNARE]
    n = int((4 - start) / 0.25)
    for i in range(n):
        kit.note(t + start + 0.25 * i, 0.1, toms[min(len(toms) - 1, i * len(toms) // n)], 96 + 3 * i)
        if i % 2 == 0:
            kit.note(t + start + 0.25 * i, 0.08, KICK, 100)


def snare_roll(kit: Clip, bar: int, bars: int):
    t = bar * 4
    n = bars * 16
    for i in range(n):
        kit.note(t + 0.25 * i, 0.08, SNARE, 50 + int(70 * i / n))
    for i in range(bars * 4):
        kit.note(t + i, 0.1, KICK, 104)


# ---- Build the score --------------------------------------------------------
rhythm_l = Clip(1, jitter_ms=4, vel_jitter=4)
rhythm_r = Clip(1, jitter_ms=4, vel_jitter=4)
bass = Clip(1, jitter_ms=3, vel_jitter=3)
kit = Clip(1, jitter_ms=2, vel_jitter=4)
strings = Clip(1)
cello = Clip(1)
choir_m = Clip(1)
choir_f = Clip(1)
bells = Clip(1)
timpani = Clip(1)
lead = Clip(1)
harm = Clip(1)

rhythms = (rhythm_l, rhythm_r)


def both(fn, *args, **kw):
    """Play a rhythm part on both guitars; only the left one drives the bass."""
    fn(rhythm_l, *args, bass=kw.pop("bass", None), **kw)
    fn(rhythm_r, *args, bass=None, **kw)


#: The keys each choir sings (VPO: male G2-F#4, female G4-C6).
RANGE = {"choir_m": (43, 66), "choir_f": (67, 84)}


def pad(clip: Clip, bar: int, chord: str, vel=72, octave=0, beats=4.0):
    lo, hi = RANGE["choir_f" if clip is choir_f else "choir_m"]
    for name in CHORD_TONES[chord]:
        pitch = midi(name) + 12 * octave
        while pitch > hi:
            pitch -= 12
        while pitch < lo:
            pitch += 12
        clip.note(bar * 4, beats - 0.15, pitch, vel)


def bar_of(n: int) -> int:
    """Score bar `n` (1-based) as a 0-based bar offset from the clips at bar 1."""
    return n - 1


harmony_bars: dict[int, str] = {}

# Intro, bars 1-8.
for b in range(1, 5):
    bells.note(bar_of(b) * 4, 3.8, "E4", 92 if b == 1 else 80)
    if b % 2 == 0:
        bells.note(bar_of(b) * 4 + 2, 1.8, "Bb4", 74)
    harmony_bars[b] = "Edim"
choir_m.note(bar_of(1) * 4, 7.8, ["E3"], 58)
choir_m.note(bar_of(3) * 4, 7.8, ["E3", "Bb3"], 70)
for i in range(16):  # a timpani roll swelling into the riff
    timpani.note(bar_of(4) * 4 + 0.25 * i, 0.2, midi("E3"), 44 + 4 * i)
for r in rhythms:  # the guitar swells on the tritone, then lets go
    r.note(bar_of(3) * 4, 7.6, [E2, E2 + 6, E2 + 12], 84)
bass.note(bar_of(3) * 4, 7.6, E2, 80)
for b in (5, 7):
    both(riff, bar_of(b), "a" if b == 5 else "b", bass=bass)
    harmony_bars.update({b: "Edim", b + 1: "Edim"})
for b in (5, 6):
    drum_groove(kit, bar_of(b), "toms", crash=(b == 5))
drum_groove(kit, bar_of(7), "gallop", crash=True)
drum_groove(kit, bar_of(8), "gallop")
fill(kit, bar_of(8), 3.0)

# The decree, bars 9-16 (the loop starts here).
for b, v in ((9, "a"), (11, "a"), (13, "b"), (15, "a")):
    both(riff, bar_of(b), v, bass=bass)
    harmony_bars.update({b: "Edim", b + 1: "Edim"})
for b in range(9, 17):
    drum_groove(kit, bar_of(b), "gallop", crash=b in (9, 13))
fill(kit, bar_of(16), 3.0)
for b in (9, 13):
    bells.note(bar_of(b) * 4, 3.8, "E4", 84)
    pad(choir_m, bar_of(b), "Edim", 66, beats=8.0)

# The theme, bars 17-32.
for k in range(16):
    b = 17 + k
    both(chug_bar, bar_of(b), THEME_ROOTS[k], bass=bass)
    harmony_bars[b] = THEME_CHORDS[k]
    pad(choir_m, bar_of(b), THEME_CHORDS[k], 70 if k < 8 else 78)
    drum_groove(kit, bar_of(b), "march" if k < 8 else "drive", crash=k in (0, 4, 8, 12))
theme(strings, bar_of(17), vel=92)
theme(cello, bar_of(17), octave=-1, vel=88)
theme(lead, bar_of(25), bars=range(8, 16), octave=0, vel=78)  # the guitar joins for the answer
fill(kit, bar_of(32), 2.0)

# The descent, bars 33-40.
DESCENT = ["Edim", "Edim", "F", "Edim", "Edim", "F", "Gm", "Bb"]
for k in range(4):
    b = 33 + k
    t = bar_of(b) * 4
    root = F2 if DESCENT[k] == "F" else E2
    for r in rhythms:
        r.note(t, 1.4, power(root, tritone=True) if root == E2 else power(root), 120)
        r.note(t + 1.5, 0.2, [root, root + 12], 100)
        r.note(t + 1.75, 0.2, [root, root + 12], 104)
        r.note(t + 2.5, 1.4, power(Bb2), 116)
    bass.note(t, 1.4, root, 112)
    bass.note(t + 1.5, 0.2, root, 96)
    bass.note(t + 1.75, 0.2, root, 100)
    bass.note(t + 2.5, 1.4, Bb2, 110)
    bells.note(t, 3.8, "E4" if k % 2 == 0 else "Bb4", 88)
    timpani.note(t, 0.9, midi("E3"), 110)
    timpani.note(t + 2.5, 0.9, midi("Bb2"), 104)
    choir_m.note(t, 3.85, ["E3", "Bb3"], 92)
    drum_groove(kit, bar_of(b), "half", crash=(k == 0))
    harmony_bars[b] = DESCENT[k]
for k in range(4):  # the climb: tremolo on E, F, G, then Bb, and a snare roll
    b = 37 + k
    t = bar_of(b) * 4
    root = (E2, F2, G2, Bb2)[k]
    for r in rhythms:
        for i in range(16):
            r.note(t + 0.25 * i, 0.2, power(root)[:2], 84 + 2 * k + i)
    for i in range(8):
        bass.note(t + 0.5 * i, 0.45, root, 96 + 2 * k)
    strings.note(t, 3.9, midi(("E4", "F4", "G4", "Bb4")[k]), 80 + 6 * k)
    cello.note(t, 3.9, midi(("E3", "F3", "G3", "Bb3")[k]), 80 + 6 * k)
    pad(choir_m, bar_of(b), DESCENT[4 + k], 80 + 4 * k)
    harmony_bars[b] = DESCENT[4 + k]
snare_roll(kit, bar_of(37), 4)
kit.note(bar_of(37) * 4, 0.6, CRASH, 110)

# The solo, bars 41-56, over E, F, G, F.
SOLO = [
    [("E4", .5), ("F4", .5), ("G4", .5), ("Bb4", .5), ("A4", 1), ("G4", 1)],
    [("F4", .75), ("G4", .25), ("F4", .5), ("E4", .5), ("F4", 2)],
    [("G4", .5), ("Bb4", .5), ("C5", .5), ("D5", .5), ("C5", .5), ("Bb4", .5), ("G4", 1)],
    [("Bb4", .5), ("A4", .5), ("G4", .5), ("F4", .5), ("E4", 2)],
    [("Bb4", .25), ("C5", .25), ("D5", .5), ("E5", 1), ("D5", .5), ("C5", .5), ("Bb4", 1)],
    [("C5", .5), ("D5", .5), ("F5", 1.5), ("E5", .5), ("D5", 1)],
    [("E5", .25), ("F5", .25), ("E5", .25), ("D5", .25), ("C5", .5), ("Bb4", .5), ("A4", .5), ("G4", .5), ("F4", 1)],
    [("G4", .5), ("A4", .5), ("Bb4", 1), ("E4", 2)],
    [(n, .25) for n in ("G5", "F5", "E5", "D5", "F5", "E5", "D5", "C5", "E5", "D5", "C5", "Bb4", "D5", "C5", "Bb4", "A4")],
    [(n, .25) for n in ("C5", "Bb4", "A4", "G4", "Bb4", "A4", "G4", "F4")] + [("G4", 1), ("F4", .5), ("G4", .5)],
    [(n, .25) for n in ("G4", "Bb4", "D5", "G5", "F5", "D5", "Bb4", "F4", "A4", "C5", "F5", "A5")] + [("G5", 1)],
    [("E5", 2), ("D5", .5), ("C5", .5), ("Bb4", 1)],
    [("E5", 1), ("F5", 1), ("G5", 2)],
    [("F5", 1), ("E5", 1), ("D5", .5), ("C5", .5), ("Bb4", 1)],
    [("C5", .5), ("D5", .5), ("E5", .5), ("F5", .5), ("G5", 1), ("A5", 1)],
    [("E5", 3)],
]
SOLO_ROOTS = [E2, F2, G2, F2] * 4
SOLO_CHORDS = ["Edim", "F", "Gm", "F"] * 4
for k in range(16):
    b = 41 + k
    both(chug_bar, bar_of(b), SOLO_ROOTS[k], vel=90, bass=bass)
    drum_groove(kit, bar_of(b), "gallop" if k < 8 else "drive", crash=k in (0, 4, 8, 12))
    harmony_bars[b] = SOLO_CHORDS[k]
    beat = 0.0
    for name, dur in SOLO[k]:
        lead.note(bar_of(b) * 4 + beat, dur * (0.96 if dur >= 1 else 0.9), midi(name), 100 + (6 if beat == 0 else 0))
        if k >= 12:  # the second guitar a third below, in the mode
            harm.note(bar_of(b) * 4 + beat, dur * (0.96 if dur >= 1 else 0.9), scale_step(midi(name), -2), 94)
        beat += dur
    if k >= 12:
        pad(choir_f, bar_of(b), SOLO_CHORDS[k], 64, octave=2)
fill(kit, bar_of(56), 3.0)

# The proclamation, bars 57-64: the theme's second half, everything.
for k in range(8):
    b = 57 + k
    both(chug_bar, bar_of(b), THEME_ROOTS[8 + k], vel=100, bass=bass)
    harmony_bars[b] = THEME_CHORDS[8 + k]
    pad(choir_m, bar_of(b), THEME_CHORDS[8 + k], 86)
    pad(choir_f, bar_of(b), THEME_CHORDS[8 + k], 72, octave=2)
    drum_groove(kit, bar_of(b), "drive", crash=k in (0, 2, 4, 6))
    if k in (0, 4):
        bells.note(bar_of(b) * 4, 3.8, "Bb4" if k == 0 else "E4", 90)
theme(strings, bar_of(57), bars=range(8, 16), vel=100)
theme(cello, bar_of(57), bars=range(8, 16), octave=-1, vel=96)
theme(lead, bar_of(57), bars=range(8, 16), vel=90)
fill(kit, bar_of(64), 2.0)

# The turnaround, bars 65-72, back into the decree.
for b, v in ((65, "a"), (67, "b"), (69, "a")):
    both(riff, bar_of(b), v, bass=bass)
    harmony_bars.update({b: "Edim", b + 1: "Edim"})
for b in range(65, 71):
    drum_groove(kit, bar_of(b), "gallop", crash=b in (65, 69))
# The break: one gallop, a stop, and the band hits E, F, G, Bb up into bar 9.
t = bar_of(71) * 4
for r in rhythms:
    gallop(r, bar_of(71), 0, E2, 104)
    r.note(t + 1.0, 0.9, power(E2, tritone=True), 118)
bass.note(t, 0.45, E2, 104)
bass.note(t + 1.0, 0.9, E2, 110)
kit.note(t, 0.6, CRASH, 116)
kit.note(t, 0.12, KICK, 120)
kit.note(t + 1.0, 0.6, CHINA, 110)
kit.note(t + 1.0, 0.12, KICK, 118)
harmony_bars[71] = "Edim"
t = bar_of(72) * 4
for i, root in enumerate((E2, F2, G2, Bb2)):
    for r in rhythms:
        r.note(t + i, 0.6, power(root), 108 + 3 * i)
    bass.note(t + i, 0.6, root, 104 + 2 * i)
fill(kit, bar_of(72), 0.0)
harmony_bars[72] = "Edim"

END_BAR = 73

# ---- Write -------------------------------------------------------------------
progression = [harmony_bars.get(b, "Edim") for b in range(1, END_BAR)]


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

score = f"""schema: ambition.musicir.v3
id: tritone_decree
title: The Tritone Decree
description: >-
  Heavy metal in E Locrian for the Evil dimension (Castle Godwin). A
  galloping riff on E that leans on the flat second and the flat fifth, a
  theme for strings and male choir, a half-time descent with bells and
  chant, a guitar solo that ends in two-part harmony, and a proclamation of
  the theme with everything. Composed from first principles (Jon,
  2026-10-19; he shipped draft 1 the same day). Generated by
  dev/compose_tritone_decree.py: edit that, not this file.
notes:
  - 'E Locrian: E F G A Bb C D. The home chord is diminished; the riff and the theme both cadence on an E-Bb tritone.'
  - 'The intro plays once; the loop is bars 9-72 and its turnaround climbs E F G Bb back into the decree.'
  - 'Rhythm guitars are two takes of the same part (small timing and velocity differences), panned hard left and right.'
seed: 1933
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: {{tonic: E, mode: locrian}}
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.55, density: 0.4, role: 'bells toll E and Bb; the riff with floor toms'}}
  - {{id: decree, from: {{bar: 9, beat: 1}}, to: {{bar: 17, beat: 1}}, energy: 0.85, density: 0.8, loopable: true, role: 'the riff, full band'}}
  - {{id: theme, from: {{bar: 17, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.8, density: 0.7, loopable: true, role: 'the theme on strings and choir'}}
  - {{id: descent, from: {{bar: 33, beat: 1}}, to: {{bar: 41, beat: 1}}, energy: 0.9, density: 0.6, loopable: true, role: 'half time, chant and bells; the climb'}}
  - {{id: solo, from: {{bar: 41, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.95, density: 0.85, loopable: true, role: 'the lead guitar, then two guitars'}}
  - {{id: proclamation, from: {{bar: 57, beat: 1}}, to: {{bar: 65, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the theme, everything'}}
  - {{id: turnaround, from: {{bar: 65, beat: 1}}, to: {{bar: 73, beat: 1}}, energy: 0.9, density: 0.8, loopable: true, role: 'the riff and the break back to the decree'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: rhythm_l, group: rhythm_l, program: distortion_guitar, volume: 110, pan: 64, expression: 112, instrument_backend: {{kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: rhythm_r, group: rhythm_r, program: distortion_guitar, volume: 110, pan: 64, expression: 112, instrument_backend: {{kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: lead, group: lead, program: distortion_guitar, volume: 104, pan: 64, expression: 112, instrument_backend: {{kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: harm, group: harm, program: distortion_guitar, volume: 104, pan: 64, expression: 112, controls: {{111: 0, 114: 52, 116: 20}}, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndGreenGuitars/Programs/02-black_keyswitch.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: bass, group: bass, program: picked_bass, volume: 116, pan: 64, expression: 116, mix_gain_db: 6.0, instrument_backend: {{kind: sfz, library_ref: bass.growly}}}}
  - {{name: strings, group: strings, program: string_ensemble_1, volume: 104, pan: 64, expression: 110, instrument_backend: {{kind: sfz, library_ref: strings.violins_1}}}}
  - {{name: cello, group: strings, program: cello, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: strings.cello}}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, library_ref: vpo.choir_male}}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 96, pan: 64, expression: 100, instrument_backend: {{kind: sfz, library_ref: vpo.choir}}}}
  - {{name: bells, group: bells, program: tubular_bells, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, sfz_glob: '**/Virtual-Playing-Orchestra3/Percussion/tubular-bells.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: timpani, group: timpani, volume: 110, pan: 64, expression: 112, is_drum: true, instrument_backend: {{kind: sfz, library_ref: orchestra.timpani}}}}
  - {{name: kit, group: drums, volume: 124, pan: 64, expression: 120, is_drum: true, mix_gain_db: 1.0, instrument_backend: {{kind: sfz, library_ref: drums.muldjord}}}}
parts:
{part("rhythm_l_part", "rhythm_l", rhythm_l)}
{part("rhythm_r_part", "rhythm_r", rhythm_r)}
{part("lead_part", "lead", lead)}
{part("harm_part", "harm", harm)}
{part("bass_part", "bass", bass)}
{part("strings_part", "strings", strings)}
{part("cello_part", "cello", cello)}
{part("choir_m_part", "choir_m", choir_m)}
{part("choir_f_part", "choir_f", choir_f)}
{part("bells_part", "bells", bells)}
{part("timpani_part", "timpani", timpani)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    rhythm_l:
      chain:
{HIGH_GAIN % {"pre": "14.0"}}
        - {{processor: highpass, cutoff_hz: 85}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 330, q: 1.0, db: -2.5}}
            - {{type: peak, hz: 1500, q: 0.9, db: 1.5}}
            - {{type: peak, hz: 3400, q: 1.2, db: -3.0}}
            - {{type: peak, hz: 4900, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 6800}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 2.5, attack_ms: 6.0, release_ms: 80.0}}
        - {{processor: balance, position: -0.85}}
    rhythm_r:
      chain:
{HIGH_GAIN % {"pre": "14.0"}}
        - {{processor: highpass, cutoff_hz: 85}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 330, q: 1.0, db: -2.5}}
            - {{type: peak, hz: 1500, q: 0.9, db: 1.5}}
            - {{type: peak, hz: 3400, q: 1.2, db: -3.0}}
            - {{type: peak, hz: 4900, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 6800}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 2.5, attack_ms: 6.0, release_ms: 80.0}}
        - {{processor: balance, position: 0.85}}
    lead:
      chain:
{HIGH_GAIN % {"pre": "12.0"}}
        - {{processor: highpass, cutoff_hz: 120}}
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
            - {{effect: delay, delay_ms: 321, feedback: 0.22, mix: 0.16}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 1.5}}
        - {{processor: balance, position: -0.12}}
    harm:
      chain:
{HIGH_GAIN % {"pre": "12.0"}}
        - {{processor: highpass, cutoff_hz: 120}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
            - {{type: peak, hz: 4130, q: 3.0, db: -3.0}}
            - {{type: peak, hz: 6200, q: 3.5, db: -4.0}}
        - {{processor: lowpass, cutoff_hz: 5600}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 7.0, release_ms: 90.0}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: 321, feedback: 0.2, mix: 0.14}}
        - {{processor: gain, gain_db: 1.0}}
        - {{processor: balance, position: 0.35}}
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
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 8.0}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 3.0}}
    bells:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 8.0}}
    timpani:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 2.0}}
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
    orchestra: [strings, choir, bells, timpani]
    lead: [lead, harm]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [decree, theme, descent, solo, proclamation, turnaround], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

"""Hobford Goblins: level 1's music, every part of it built on the goblin
motif of the first goblin tune (scores/active/first_goblin_tune_v2). Writes
its MusicIR v3 score:

    python3 dev/compose_hobford_goblins.py scores/active/hobford_goblins.music.yaml

Jon, 2026-11-17: goblin-motif variants for Hobford in place of "A possible
morning": foreboding ones for the valley, and music for the break-in and the
lab raid.

THE MOTIF. Two cells, both on D. The tune: D F E C# D G# G F (a minor third
up, a step down, the leading note, and the tritone G# leaning on G). The
answer, low: D D C F G F D A.

One cue, one tempo (120), six playback sections the game moves between:

  lurking     1-32   the valley by day: a fingerpicked guitar and a fiddle
                      tune that begins as the motif without its tritone; the
                      celli say the real motif under it, twice.      (loop)
  shadowed   33-56   the woods, the clearing and the fell: a drone, a harp
                      ostinato with the tritone in it, the motif slowed on
                      flute, a heartbeat on the timpani.            (loop)
  break_in   57-64   the knock at the barn door: three knocks, a pause,
                      impatient knocks, the motif in the horns, a snare roll
                      and a climb to the door giving way.       (one time)
  raid       65-80   the lab raid: a goblin march. Staccato strings, snare,
                      the motif in the horns and the answer in the trombones.
                                                                    (loop)
  brute      81-96   the brute's wave: the motif slowed in the low brass, a
                      stomp, male choir.                            (loop)
  aftermath  97-110  the raid's end and the Creator's last words: the motif
                      as a lament on a solo cello.               (one time)
"""

from __future__ import annotations

import math
import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 120
OUT = Path(sys.argv[1])
rng = random.Random(1117)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    """Beats as a fraction of a whole note, on whole ticks of ppq 960."""
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


class Clip:
    """Exact events of one part, in beats from bar 1."""

    def __init__(self, jitter_ms: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.jitter = jitter_ms / 1000.0 * BPM / 60.0
        self.vel_jitter = vel_jitter

    def form_region(self, beat):
        return next((sid for sid, first, last, start in SEGMENTS
                     if (start - 1) * 4 <= beat < (start + last - first) * 4), None)

    def note(self, at, dur, pitches, vel):
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


# The music is written in logical bars 1-110, section after section. In the
# score each section has two silent bars before it and after it: the ring a
# section's notes and reverb sound into, which a loop adds back onto its head
# (its tail), and the early starts of a loop's first notes, which it adds onto
# its end (its lead-in).
# The longest group reverb here decays within this, so a gap of it holds a ring.
RING_SECONDS = 2.5
_GAP = max(1, math.ceil(RING_SECONDS * BPM / 240))
_LOGICAL = [  # (id, first logical bar, last logical bar)
    ("lurking", 1, 32),
    ("shadowed", 33, 56),
    ("break_in", 57, 64),
    ("raid", 65, 80),
    ("brute", 81, 96),
    ("aftermath", 97, 110),
]
# (id, first, last, first score bar). The first section starts the score: a
# silent opening is dead air in the radio mix and the inspector's preview.
# Between sections, a gap long enough for the ring (the tail of the one
# before, the lead-in of the one after). The aftermath ends the cue.
SEGMENTS = []
_at = 1
for _sid, _first, _last in _LOGICAL:
    SEGMENTS.append((_sid, _first, _last, _at))
    _at += _last - _first + 1 + _GAP
END_BAR = SEGMENTS[-1][3] + SEGMENTS[-1][2] - SEGMENTS[-1][1] + 1


def score_bar(bar: int) -> int:
    """The score bar of logical bar `bar`."""
    for _, first, last, at in SEGMENTS:
        if first <= bar <= last:
            return at + bar - first
    raise ValueError(f"logical bar {bar} is in no section")


def t(bar: int, beat: float = 0.0) -> float:
    """Beats from the start to `beat` (0-based) of logical bar `bar` (1-based)."""
    return (score_bar(bar) - 1) * 4 + beat


# ---- The motif ----------------------------------------------------------
TUNE = [0, 3, 2, -1, 0, 6, 5, 3]
TUNE_RHYTHM = [0.5, 0.5, 0.5, 0.5, 0.75, 0.25, 0.5, 0.5]
ANSWER = [0, 0, -2, 3, 5, 3, 0, -5]
ANSWER_RHYTHM = [0.5, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 0.5]
# The tune as a valley tune: the leading note and the tritone smoothed into
# the mode (D dorian), so it is the motif's shape without its threat.
INNOCENT = [0, 3, 2, 0, -2, 0, 5, 3]


def cell(clip: Clip, start: float, root: int, intervals, rhythm, vel: int, *, stretch: float = 1.0,
         legato: float = 0.92, accent_first: int = 6, shape=None):
    """One statement of a motif cell from `start`: each note `legato` of its
    span, the first a little accented. `shape` maps a note's index to a
    velocity change (a swell or a fall)."""
    at = start
    for i, (step, span) in enumerate(zip(intervals, rhythm)):
        span *= stretch
        v = vel + (accent_first if i == 0 else 0) + (shape(i) if shape else 0)
        clip.note(at, span * legato, root + step, v)
        at += span
    return at


# ---- Harmony -------------------------------------------------------------
CHORD = {
    "Dm": ["D", "F", "A"], "Bb": ["Bb", "D", "F"], "F": ["F", "A", "C"], "C": ["C", "E", "G"],
    "Gm": ["G", "Bb", "D"], "A": ["A", "C#", "E"], "A7": ["A", "C#", "E", "G"], "Eb": ["Eb", "G", "Bb"],
    "Gm6": ["G", "Bb", "D", "E"], "Dm9": ["D", "F", "A", "E"], "Bbmaj7": ["Bb", "D", "F", "A"],
}
harmony_bars: dict[int, str] = {}


def tones(chord: str, octave: int) -> list[int]:
    """The chord's tones from its root in `octave`, each above the last."""
    out = []
    for name in CHORD[chord]:
        p = midi(f"{name}{octave}")
        while out and p <= out[-1]:
            p += 12
        out.append(p)
    return out


def root(chord: str, octave: int) -> int:
    return midi(f"{CHORD[chord][0]}{octave}")


def tim(pitch: int) -> int:
    """`pitch` folded into the sampled range of the timpani the catalog
    resolves (VCSL Timpani 1, F2 to G3): a note outside it is silent."""
    while pitch < midi("F2"):
        pitch += 12
    while pitch > midi("G3"):
        pitch -= 12
    return pitch


guitar = Clip(6, 6)
fiddle = Clip(8, 5)
flute = Clip(6, 4)
clarinet = Clip(6, 4)
violins = Clip(4, 3)
violins_st = Clip(4, 5)
celli = Clip(4, 3)
celli_st = Clip(4, 5)
cello_solo = Clip(8, 4)
bass = Clip(5, 5)
harp = Clip(5, 5)
horns = Clip(5, 4)
trombones = Clip(5, 4)
tuba = Clip(5, 3)
choir = Clip(4, 3)
timpani = Clip(3, 4)
snare = Clip(3, 7)
bass_drum = Clip(3, 4)

SNARE, SNARE_LOW, SIDESTICK = 62, 64, 60
BASS_DRUM = 60

# ---- LURKING (1-32): the valley by day -----------------------------------
LURK = ["Dm", "Dm", "Bb", "Bb", "F", "F", "C", "C", "Dm", "Dm", "Gm", "Gm", "Bb", "Bb", "A", "A"]
for half in (0, 16):
    for i, chord in enumerate(LURK):
        bar = 1 + half + i
        harmony_bars[bar] = chord
        # Fingerpicked: root, fifth, the tenth, the octave above, in eighths.
        # The guitar's lowest string is E2: a lower root goes up an octave.
        r = root(chord, 2)
        if r < midi("E2"):
            r += 12
        third = tones(chord, 3)[1]
        fifth = r + 7
        pattern = [r, fifth, r + 12, third + 12 if third + 12 < midi("G4") else third, fifth + 12, third + 12 if third + 12 < midi("G4") else third, r + 12, fifth]
        for k, p in enumerate(pattern):
            guitar.note(t(bar, 0.5 * k), 0.9 if k == 0 else 0.6, p, 80 if k == 0 else (68 if k % 2 else 72))
        # The upright, plucked, on the half bar.
        bass.note(t(bar), 1.6, r if r < midi("A2") else r - 12, 86)
        if i % 2 == 1:
            bass.note(t(bar, 2), 1.4, fifth - 12 if fifth - 12 > midi("E1") else fifth, 76)

# The fiddle's tune: the innocent motif, then its answer turned up, twice.
for start_bar, r in ((5, midi("D5")), (9, midi("D5")), (21, midi("D5"))):
    end = cell(fiddle, t(start_bar), r, INNOCENT, TUNE_RHYTHM, 86, stretch=2.0, legato=0.96,
               shape=lambda i: (6 if i in (2, 6) else 0))
fiddle.note(t(13), 3.6, midi("A4"), 82)
fiddle.note(t(14), 3.6, midi("F4"), 78)
fiddle.note(t(25), 3.6, midi("C5"), 82)
fiddle.note(t(26), 3.6, midi("A4"), 78)
# The flute answers it in the second half, an octave over.
cell(flute, t(17), midi("A5"), [0, -2, -4, -2, 0, 3, 2, 0], TUNE_RHYTHM, 82, stretch=2.0, legato=0.95)
flute.note(t(27), 3.5, midi("D5"), 76)
flute.note(t(28), 3.5, midi("Bb4"), 74)
# Under it, the real motif, low and quiet: the threat in the valley.
for bar in (13, 29):
    cell(celli, t(bar), midi("D3"), TUNE, TUNE_RHYTHM, 82, stretch=2.0, legato=0.98,
         shape=lambda i: 8 if i == 5 else 0)
    timpani.note(t(bar), 1.0, tim(midi("D2")), 54)
    timpani.note(t(bar + 2), 1.0, tim(midi("A1")), 58)
    timpani.note(t(bar + 3, 2), 1.0, tim(midi("A1")), 62)
    harp.note(t(bar + 1, 2), 3.0, [midi("D3"), midi("G#3")], 76)
# A harp grace at the head of each phrase.
for bar in (1, 9, 17, 25):
    chord = harmony_bars[bar]
    for k, p in enumerate(tones(chord, 4) + [tones(chord, 4)[0] + 12]):
        harp.note(t(bar, 0.25 * k), 2.5, p, 74 + 3 * k)

# ---- SHADOWED (33-56): the woods, the clearing, the fell ----------------
SHADE = ["Dm", "Dm", "Eb", "Dm", "Gm", "Gm", "A", "A"]
for block in range(3):
    for i, chord in enumerate(SHADE):
        bar = 33 + 8 * block + i
        harmony_bars[bar] = chord
        # The drone: celli on D and A under everything.
        celli.note(t(bar), 3.9, [midi("D2"), midi("A2")], 46 + 4 * block)
        # High strings, pianissimo, the chord's upper tones.
        up = tones(chord, 5)
        violins.note(t(bar), 3.9, up[1:] if len(up) > 2 else up, 38 + 4 * block)
        # The harp ostinato: D A F, then the chord's own colour, with the
        # tritone G# every other bar.
        colour = midi("G#4") if i % 2 == 1 else tones(chord, 4)[1]
        for k, p in enumerate([midi("D4"), midi("A4"), midi("F4"), colour, midi("A4"), midi("F4"), midi("D4"), midi("A3")]):
            harp.note(t(bar, 0.5 * k), 0.9, p, 80 if k == 0 else 70)
# The motif slowed on the flute; the answer on the clarinet.
cell(flute, t(37), midi("D5"), TUNE, TUNE_RHYTHM, 80, stretch=2.0, legato=0.97, shape=lambda i: 6 if i == 5 else 0)
cell(clarinet, t(41), midi("D4"), ANSWER, ANSWER_RHYTHM, 84, stretch=2.0, legato=0.95)
cell(flute, t(45), midi("D5"), TUNE, TUNE_RHYTHM, 84, stretch=2.0, legato=0.97, shape=lambda i: 6 if i == 5 else 0)
cell(clarinet, t(49), midi("D4"), TUNE, TUNE_RHYTHM, 86, stretch=2.0, legato=0.95)
clarinet.note(t(53), 7.6, midi("D4"), 80)
flute.note(t(53, 2), 5.6, midi("G#5"), 74)
flute.note(t(55), 7.4, midi("A5"), 72)
# The heartbeat: lub-dub on the timpani, nearer each block.
for bar in range(41, 57):
    v = 50 + (bar - 41) * 2
    timpani.note(t(bar), 0.6, tim(midi("D2")), v)
    timpani.note(t(bar, 0.5), 0.6, tim(midi("D2")), v - 10)
    if bar % 4 == 0:
        bass_drum.note(t(bar, 2), 1.0, BASS_DRUM, 46 + (bar - 41))

# ---- BREAK-IN (57-64): the knock at the barn door -----------------------
for bar in range(57, 65):
    harmony_bars[bar] = "Dm" if bar < 63 else "A"
# Three knocks.
for beat in (0, 1, 2):
    bass_drum.note(t(57, beat), 0.8, BASS_DRUM, 108)
    timpani.note(t(57, beat), 0.8, tim(midi("D2")), 100)
# The strings hold their breath.
violins.note(t(57, 3), 4.8, [midi("D5"), midi("Eb5")], 40)
celli.note(t(57, 3), 4.8, [midi("D2"), midi("A2")], 52)
# Impatient knocks.
for beat in (0, 0.5, 1.0, 2.0):
    bass_drum.note(t(59, beat), 0.6, BASS_DRUM, 112)
    timpani.note(t(59, beat), 0.6, tim(midi("D2")), 104)
# The horns say who it is.
cell(horns, t(60), midi("D3"), TUNE, TUNE_RHYTHM, 92, legato=0.9)
cell(trombones, t(61), midi("D3"), ANSWER, ANSWER_RHYTHM, 92, legato=0.9)
cell(horns, t(62), midi("A3"), TUNE, TUNE_RHYTHM, 100, legato=0.9)
# A snare roll and a climb to the door giving way.
for k in range(56):
    snare.note(t(61, 0.25 * k), 0.12, SNARE, int(40 + 1.4 * k))
# D harmonic minor, up from D4 to the leading note under the A chord.
HARMONIC_MINOR = [0, 2, 3, 5, 7, 8, 11]
for k in range(14):
    pitch = midi("D4") + 12 * (k // 7) + HARMONIC_MINOR[k % 7]
    violins_st.note(t(63, 0.5 * k), 0.4, pitch, 70 + 3 * k)
    celli_st.note(t(63, 0.5 * k), 0.4, pitch - 24, 70 + 3 * k)
# The door gives way: everything on A, and a breath before the march.
for clip, pitches, v in (
    (violins, [midi("A4"), midi("C#5"), midi("E5"), midi("A5")], 110),
    (celli, [midi("A2"), midi("E3")], 110),
    (horns, [midi("A3"), midi("C#4"), midi("E4")], 112),
    (trombones, [midi("A2"), midi("E3")], 112),
    (tuba, [midi("A1")], 110),
):
    clip.note(t(64, 3), 0.9, pitches, v)
bass_drum.note(t(64, 3), 1.0, BASS_DRUM, 124)
timpani.note(t(64, 3), 1.0, tim(midi("A1")), 120)
snare.note(t(64, 3), 0.2, SNARE, 118)

# ---- RAID (65-80): the goblin march --------------------------------------
RAID = ["Dm", "Dm", "Bb", "A", "Dm", "Dm", "Gm", "A", "Gm", "Gm", "Dm", "Dm", "Bb", "C", "A", "A"]


def march_bar(bar: int, chord: str, heavy: bool = False):
    """One bar of the march: snare, bass drum, timpani, staccato strings."""
    for beat, v in ((0, 104), (0.5, 76), (0.75, 70), (1, 88), (1.5, 74), (2, 100), (2.5, 76), (2.75, 70),
                    (3, 88), (3.5, 74), (3.75, 80)):
        snare.note(t(bar, beat), 0.1, SNARE if beat not in (0.75, 2.75) else SNARE_LOW, v + (8 if heavy else 0))
    bass_drum.note(t(bar), 0.6, BASS_DRUM, 100)
    bass_drum.note(t(bar, 2), 0.6, BASS_DRUM, 92)
    r = root(chord, 2)
    if r > midi("A2"):
        r -= 12
    timpani.note(t(bar), 0.7, tim(r), 96)
    timpani.note(t(bar, 2), 0.7, tim(r + 7), 86)
    # The ostinato: the motif's turn, around the chord's root.
    hi = root(chord, 4)
    if hi > midi("G4"):
        hi -= 12
    third = tones(chord, 4)[1] - tones(chord, 4)[0]
    for k, step in enumerate([0, 0, third, 0, 2, 0, -1, 0]):
        violins_st.note(t(bar, 0.5 * k), 0.3, hi + step, 92 if k % 2 == 0 else 78)
    lo = root(chord, 3)
    if lo > midi("G3"):
        lo -= 12
    for k in range(8):
        celli_st.note(t(bar, 0.5 * k), 0.3, lo + (7 if k in (3, 7) else 0), 92 if k % 2 == 0 else 80)
    tuba.note(t(bar), 1.8, lo - 12, 92)
    tuba.note(t(bar, 2), 1.8, lo - 12 + 7 if lo - 12 + 7 < midi("D2") else lo - 12, 84)


for i, chord in enumerate(RAID):
    bar = 65 + i
    harmony_bars[bar] = chord
    march_bar(bar, chord)
# The call and the answer.
for bar in (65, 69):
    cell(horns, t(bar), midi("D4"), TUNE, TUNE_RHYTHM, 100)
    cell(trombones, t(bar + 1), midi("D3"), ANSWER, ANSWER_RHYTHM, 100)
cell(horns, t(67), midi("Bb3"), [0, 4, 2, 0, -1, 0, 2, 4], TUNE_RHYTHM, 96)
cell(horns, t(68), midi("A3"), [0, 4, 7, 4, 0, -1, 0, 4], TUNE_RHYTHM, 98)
cell(horns, t(71), midi("G3"), TUNE, TUNE_RHYTHM, 100)
cell(horns, t(72), midi("A3"), [0, 4, 7, 10, 7, 4, 0, -1], TUNE_RHYTHM, 102)
# Up high: flute and fiddle double the tune, the horns hold under it.
for bar, r in ((73, midi("G5")), (74, midi("G5")), (75, midi("D5")), (76, midi("D5"))):
    cell(flute, t(bar), r, TUNE, TUNE_RHYTHM, 92, legato=0.85)
    cell(fiddle, t(bar), r - 12, TUNE, TUNE_RHYTHM, 88, legato=0.85)
    horns.note(t(bar), 3.8, tones(harmony_bars[bar], 3), 84)
# The turnaround: the tune in everyone, then the answer down to A.
cell(horns, t(77), midi("Bb3"), [0, 4, 2, 0, -1, 0, 2, 4], TUNE_RHYTHM, 106)
cell(trombones, t(77), midi("Bb2"), [0, 4, 2, 0, -1, 0, 2, 4], TUNE_RHYTHM, 104)
cell(horns, t(78), midi("C4"), [0, 4, 2, 0, -1, 0, 2, 4], TUNE_RHYTHM, 106)
cell(trombones, t(78), midi("C3"), [0, 4, 2, 0, -1, 0, 2, 4], TUNE_RHYTHM, 104)
cell(horns, t(79), midi("A3"), ANSWER, ANSWER_RHYTHM, 108)
cell(trombones, t(79), midi("A2"), ANSWER, ANSWER_RHYTHM, 106)
horns.note(t(80), 3.6, [midi("A3"), midi("C#4"), midi("E4")], 104)
trombones.note(t(80), 3.6, [midi("A2"), midi("E3")], 102)
for k in range(8):
    snare.note(t(80, 2 + 0.25 * k), 0.1, SNARE, 80 + 4 * k)

# ---- BRUTE (81-96): the brute's wave ------------------------------------
BRUTE = ["Dm", "Dm", "Bb", "Bb", "Gm", "Gm", "A", "A"]
for half in (0, 8):
    for i, chord in enumerate(BRUTE):
        bar = 81 + half + i
        harmony_bars[bar] = chord
        # The stomp: bass drum and timpani together, then the snare cracks.
        for beat, v in ((0, 120), (1, 96), (2, 116), (2.5, 92)):
            bass_drum.note(t(bar, beat), 0.7, BASS_DRUM, v)
        r = root(chord, 2)
        if r > midi("A2"):
            r -= 12
        timpani.note(t(bar), 0.9, tim(r), 112)
        timpani.note(t(bar, 2), 0.9, tim(r), 104)
        for beat in (1, 3):
            snare.note(t(bar, beat), 0.15, SNARE, 112)
        snare.note(t(bar, 3.75), 0.1, SNARE_LOW, 78)
        # The strings saw at the chord in sixteenths.
        hi = tones(chord, 4)
        for k in range(16):
            violins_st.note(t(bar, 0.25 * k), 0.18, hi[0] + 12 if k % 4 == 0 else hi[0], 92 if k % 4 == 0 else 72)
        celli.note(t(bar), 3.9, [r + 12, r + 19], 96)
        tuba.note(t(bar), 3.8, r, 104)
        # Male choir on the chord, two bars at a time.
        # The brass has the root: the choir sings the third, the fifth and
        # the octave, where its samples are in tune (its D3 and G3 measure
        # 39 and 21 cents off) and in its range (to F#4).
        if i % 2 == 0:
            low = tones(chord, 3)
            voices = [p for p in low[1:] + [low[0] + 12] if p <= midi("F#4")]
            choir.note(t(bar), 7.8, voices, 92 + (8 if half else 0))
# The motif slowed in the low brass.
for bar, r in ((81, midi("D3")), (85, midi("G2")), (89, midi("D3"))):
    cell(trombones, t(bar), r, TUNE, TUNE_RHYTHM, 108, stretch=2.0, legato=0.95, shape=lambda i: 10 if i == 5 else 0)
# A canon on top in the second half: horns a bar behind the trombones.
cell(horns, t(90), midi("D4"), TUNE, TUNE_RHYTHM, 104, stretch=2.0, legato=0.9)
cell(trombones, t(93), midi("A2"), ANSWER, ANSWER_RHYTHM, 110, stretch=2.0, legato=0.9)
cell(horns, t(95), midi("A3"), [0, 4, 7, 4, 0, -1, 0, 4], TUNE_RHYTHM, 108)
horns.note(t(96), 3.5, [midi("A3"), midi("C#4"), midi("E4")], 104)

# ---- AFTERMATH (97-110): the lament -------------------------------------
LAMENT = ["Dm", "Dm", "Bb", "Bb", "Gm", "Gm", "A", "A", "Dm", "Bbmaj7", "Gm6", "A", "Dm9", "Dm9"]
for i, chord in enumerate(LAMENT):
    bar = 97 + i
    harmony_bars[bar] = chord
    v = 46 if bar < 109 else 40
    violins.note(t(bar), 3.95, tones(chord, 4)[1:], v)
    celli.note(t(bar), 3.95, [root(chord, 2) if root(chord, 2) >= midi("C2") else root(chord, 2) + 12], v + 4)
    if bar < 109:
        for k, p in enumerate(tones(chord, 3) + [tones(chord, 3)[0] + 12, tones(chord, 3)[1] + 12]):
            harp.note(t(bar, 0.5 * k), 2.5, p, 70)
# The cello sings the motif slowly, and where the tritone was it falls to
# the fifth: D F E C# D, A G F E D.
cell(cello_solo, t(97), midi("D3"), [0, 3, 2, -1, 0], [2, 2, 1.5, 0.5, 2], 84, legato=0.98)
cell(cello_solo, t(99), midi("D3"), [7, 5, 3, 2, 0], [2, 1.5, 0.5, 2, 2], 82, legato=0.98)
cell(cello_solo, t(101), midi("A2"), [0, 3, 5, 3, 1, 0], [1.5, 0.5, 2, 1.5, 0.5, 2], 80, legato=0.98)
cell(cello_solo, t(103), midi("D3"), [0, 3, 2, -1, 0], [2, 2, 1.5, 0.5, 2], 82, legato=0.98)
# The last phrase falls to the leading note and home.
cell(cello_solo, t(105), midi("D3"), [7, 5, 3, 2, 0, -1, 0], [2, 1.5, 0.5, 4, 4, 4, 8], 78, legato=0.98)
# The flute, last, on the fifth: something left to build on.
flute.note(t(108), 3.8, midi("A5"), 54)
flute.note(t(109), 7.5, midi("A5"), 48)

score_harmony = {score_bar(b): chord for b, chord in harmony_bars.items()}
progression = [score_harmony.get(b, "Dm") for b in range(1, END_BAR)]


def form_rows() -> str:
    rows = []
    shapes = {
        "lurking": "energy: 0.3, density: 0.4, loopable: true, role: 'the valley by day: guitar and fiddle, the motif low under them'",
        "shadowed": "energy: 0.35, density: 0.35, loopable: true, role: 'the woods: drone, harp ostinato, the motif slowed, a heartbeat'",
        "break_in": "energy: 0.7, density: 0.5, role: 'knocks, the motif in the horns, the door gives way'",
        "raid": "energy: 0.85, density: 0.8, loopable: true, role: 'the goblin march'",
        "brute": "energy: 0.95, density: 0.85, loopable: true, role: 'the brute: the motif slowed in the low brass, a stomp, male choir'",
        "aftermath": "energy: 0.25, density: 0.3, role: 'the lament on a solo cello'",
    }
    previous_end = 1
    for sid, first, last, at in SEGMENTS:
        if at > previous_end:
            rows.append(f"  - {{id: before_{sid}, from: {{bar: {previous_end}, beat: 1}}, to: {{bar: {at}, beat: 1}}, energy: 0.1, density: 0.0, role: 'silence: a ring and a lead-in'}}")
        end = at + last - first + 1
        rows.append(f"  - {{id: {sid}, from: {{bar: {at}, beat: 1}}, to: {{bar: {end}, beat: 1}}, {shapes[sid]}}}")
        previous_end = end
    return "\n".join(rows)


def playback_rows() -> str:
    rows = []
    for i, (sid, *_rest) in enumerate(SEGMENTS):
        fields = [f"id: {sid}", f"form: [{sid}]"]
        if sid in ("lurking", "shadowed", "raid", "brute"):
            fields.append("loop: true")
            if i > 0:
                fields.append(f"lead_in: before_{sid}")
        if i + 1 < len(SEGMENTS):
            fields.append(f"tail: before_{SEGMENTS[i + 1][0]}")
        rows.append("    - {" + ", ".join(fields) + "}")
    return "\n".join(rows)



def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, optional: false, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


PARTS = [
    ("guitar", guitar), ("fiddle", fiddle), ("flute", flute), ("clarinet", clarinet), ("violins", violins),
    ("violins_st", violins_st), ("celli", celli), ("celli_st", celli_st), ("cello_solo", cello_solo),
    ("bass", bass), ("harp", harp), ("horns", horns), ("trombones", trombones), ("tuba", tuba),
    ("choir", choir), ("timpani", timpani), ("snare", snare), ("bass_drum", bass_drum),
]

SNARE_PATH = "Membranophones/Struck Membranophones/Snare Drum, Rope Tension"
BASS_DRUM_PATH = "Membranophones/Struck Membranophones/Bass Drum 1"

score = f"""schema: ambition.musicir.v3
id: hobford_goblins
title: Hobford Goblins
description: >-
  Level 1's music on the goblin motif of the first goblin tune: the valley by
  day with the motif under a fiddle tune, the woods with the motif slowed over
  a drone, the knock at the barn door, the lab raid as a goblin march, the
  brute's wave, and a lament for the Creator. Generated by
  dev/compose_hobford_goblins.py: edit that, not this file.
notes:
  - 'Jon, 2026-11-17: goblin-motif variants for Hobford in place of A possible morning; foreboding ones, and music for the break-in and the lab raid.'
  - 'The motif: D F E C# D G# G F, answered low by D D C F G F D A. The valley tune is the motif with its leading note and tritone smoothed into D dorian.'
  - 'The game plays the playback sections: lurking and shadowed (rooms), break_in (one time), raid and brute (the raid''s waves), aftermath (one time, the raid cleared).'
seed: 1117
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: {{tonic: D, mode: minor}}
end: {{bar: {END_BAR}, beat: 1}}
form:
{form_rows()}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: guitar, group: guitar, program: steel_guitar, volume: 100, pan: 64, expression: 104, controls: {{100: 126}}, {sfz("guitar.acoustic")}}}
  - {{name: fiddle, group: fiddle, program: violin, volume: 100, pan: 64, expression: 104, {sfz("strings.violin_solo")}}}
  - {{name: flute, group: winds, program: flute, volume: 100, pan: 64, expression: 104, controls: {{1: 100}}, {sfz("vpo.flute_solo_perf")}}}
  - {{name: clarinet, group: winds, program: clarinet, volume: 100, pan: 64, expression: 104, controls: {{1: 100}}, {sfz("vpo.clarinet_solo_perf")}}}
  - {{name: violins, group: strings, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1")}}}
  - {{name: violins_st, group: strings, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1_staccato")}}}
  - {{name: celli, group: strings, program: cello, volume: 100, pan: 64, expression: 104, {sfz("strings.celli")}}}
  - {{name: celli_st, group: strings, program: cello, volume: 100, pan: 64, expression: 104, {sfz("strings.celli_staccato")}}}
  - {{name: cello_solo, group: cello_solo, program: cello, volume: 104, pan: 64, expression: 108, {sfz("strings.cello")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 106, pan: 64, expression: 108, {sfz("bass.upright")}}}
  - {{name: harp, group: harp, program: orchestral_harp, volume: 100, pan: 64, expression: 104, {sfz("folk.harp")}}}
  - {{name: horns, group: brass, program: french_horn, volume: 104, pan: 64, expression: 108, {sfz("orchestra.horns_sustain")}}}
  - {{name: trombones, group: brass, program: trombone, volume: 104, pan: 64, expression: 108, {sfz("orchestra.trombones_sustain")}}}
  - {{name: tuba, group: brass, program: tuba, volume: 104, pan: 64, expression: 108, {sfz("orchestra.tuba_sustain")}}}
  - {{name: choir, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {sfz("vpo.choir_male")}}}
  - {{name: timpani, group: timpani, volume: 110, pan: 64, expression: 112, is_drum: true, {sfz("orchestra.timpani")}}}
  - {{name: snare, group: drums, volume: 108, pan: 64, expression: 110, is_drum: true, {vcsl(SNARE_PATH)}}}
  - {{name: bass_drum, group: drums, volume: 112, pan: 64, expression: 112, is_drum: true, {vcsl(BASS_DRUM_PATH)}}}
parts:
{chr(10).join(part(f"{name}_part", name, clip) for name, clip in PARTS)}
processing:
  groups:
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 250, q: 1.0, db: -2.0}}
            - {{type: high_shelf, hz: 6000, q: 0.7, db: 1.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 4.0}}
        - {{processor: balance, position: -0.3}}
    fiddle:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.25}}
    winds:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: 0.2}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 6.0}}
    cello_solo:
      chain:
        - {{processor: highpass, cutoff_hz: 55}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: -0.1}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3500}}
        - {{processor: reverb, wet: 0.08, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 5.0}}
    harp:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.35}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: -0.15}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 3.0}}
    timpani:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 2.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.0, attack_ms: 12.0, release_ms: 90.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - processor: parametric_eq
        bands:
          - {{type: peak, hz: 350, q: 0.8, db: -1.0}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 120.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: reverb, wet: 0.04, decay_seconds: 1.4}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  full: true
  sections:
{playback_rows()}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

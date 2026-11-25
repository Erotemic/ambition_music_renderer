"""Glider Gun: the Perfect Cellular Automaton's fight, in its arena in the
Automaton dimension. Heavy metal in E Lydian. Writes its MusicIR v3 score:

    python3 dev/compose_glider_gun.py scores/active/glider_gun.music.yaml

Jon, 2026-11-25: "PCA needs an arena to challenge people in the automaton
dimension ... You can compose new music if you want". His reviews favour
the heavy boss tracks (The Iron Toccata, The Phrygian Furnace, The Tritone
Decree) and the ones that are not self-serious. Each of those has its own
mode; this one is Lydian, the major scale with a raised fourth: bright,
pleased with itself, a little uncanny. The PCA is all three.

The rule writes the riff. Rule 150 (each cell becomes the XOR of itself and
its two neighbours) on a ring of sixteen cells, from two live cells eight
apart, comes back to its start every four generations:

    x.......x.......   2 live
    xx.....xxx.....x   6
    x.x...x.x.x...x.   6
    x.xx.xx.x.xx.xx.  10

One generation is one bar of sixteenths. Where a cell lives, the guitars hit
a power chord and the kick drum plays; where it is dead, they chug the
palm-muted pedal. So the riff builds over four bars and starts again,
"without one bad step". The intro is the same rows on String Cyborgs: the
lattice switching on.

In the breakdown ("the fault") one cell is flipped and the rule is run on
from there. The pattern no longer comes back, and the riff comes apart.

The hook (original): a dotted eighth, a sixteenth that drops a fourth or a
tritone below it, then a leap back up past where it started. The tritone is
the Lydian A# under the E: a cell that dies and is born again one step on.

Form, 4/4 at 160 BPM:
  intro      1-8    the lattice on the cyborg strings; the band joins at 5.
  verse      9-24   the rule's riff on E, E, F# and C#; lead fills. (loop start)
  rise       25-32  half time on C#m, B, F#, G#m and B; the choir comes in.
  chorus     33-48  the hook on the lead, the twin under it, the choir.
  fault      49-56  a flipped cell: the riff breaks up; a lead break.
  rerun      57-64  the hook's first half again, double kick, all in.
  homeward   65-68  every cell lit, then D# back to E and the riff.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 160
OUT = Path(sys.argv[1])
rng = random.Random(1970)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7,
        "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "B#": 0}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


#: E Lydian: E F# G# A# B C# D#.
MODE = [4, 6, 8, 10, 11, 1, 3]
#: Jon hears high lead guitar as piercing: no lead note above A5.
TOP = midi("A5")

CHORD_PCS = {
    "E": {4, 8, 11}, "F#": {6, 10, 1}, "C#m": {1, 4, 8}, "B": {11, 3, 6}, "G#m": {8, 11, 3}, "D#m": {3, 6, 10},
}
#: Each chord's root in the bass's octave.
ROOTS = {"E": "E2", "F#": "F#2", "C#m": "C#3", "B": "B2", "G#m": "G#2", "D#m": "D#2"}
#: The pitch classes that carry a perfect fifth in the mode: power chords.
FIFTHS = {4, 6, 8, 11, 1, 3}


def degree(pitch: int, steps: int) -> int:
    """`steps` scale steps from `pitch` (which is in the mode)."""
    direction = 1 if steps > 0 else -1
    for _ in range(abs(steps)):
        pitch += direction
        while pitch % 12 not in MODE:
            pitch += direction
    return pitch


def twin_under(pitch: int, chord: str, held: bool) -> int:
    """The twin's note under the lead: a chord tone below a held note, else
    the scale's third below."""
    if held:
        for below in range(pitch - 3, pitch - 10, -1):
            if below % 12 in CHORD_PCS[chord]:
                return below
    return degree(pitch, -2)


def frac(beats) -> str:
    """Beats as a fraction of a whole note on whole ticks of ppq 960; always a
    fraction, since a bare integer is a tick offset."""
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


class Clip:
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
    return (n - 1) * 4.0


rhythm_l = Clip(jitter_ms=4, vel_jitter=4)
rhythm_r = Clip(jitter_ms=4, vel_jitter=4)
bass = Clip(jitter_ms=3, vel_jitter=3)
kit = Clip(jitter_ms=2, vel_jitter=4)
lead = Clip(jitter_ms=2, vel_jitter=3)
twin = Clip(jitter_ms=3, vel_jitter=3)
cyborg = Clip(jitter_ms=1, vel_jitter=3)
choir_m = Clip()
choir_f = Clip()
rhythms = (rhythm_l, rhythm_r)


def both(at, dur, pitches, vel):
    for r in rhythms:
        r.note(at, dur, pitches, vel)


def power(root: int) -> list[int]:
    return [root, root + 7, root + 12] if root % 12 in FIFTHS else [root, root + 12]


# ---- The rule ----------------------------------------------------------------------------
def rule150(row: list[int]) -> list[int]:
    n = len(row)
    return [row[(i - 1) % n] ^ row[i] ^ row[(i + 1) % n] for i in range(n)]


def generations(seed: list[int], count: int) -> list[list[int]]:
    rows = [seed]
    for _ in range(count - 1):
        rows.append(rule150(rows[-1]))
    return rows


SEED = [1 if i in (0, 8) else 0 for i in range(16)]
CYCLE = generations(SEED, 4)
assert rule150(CYCLE[-1]) == SEED, "rule 150 from two cells eight apart comes back in four"
#: The fault: one cell of the seed flipped, and the rule run on from there.
FAULT = generations([1 if i in (0, 8, 5) else 0 for i in range(16)], 8)


# ---- Drums (GM keys of the Muldjord kit) -----------------------------------------
KICK, SNARE, HAT, OPEN_HAT, CRASH, CHINA, RIDE, RIDE_BELL, FLOOR, MID, HIGH = 36, 38, 42, 46, 49, 52, 51, 53, 41, 45, 48


def drums(n: int, style: str, row: list[int] | None = None, crash=False):
    t = bar(n)
    if style == "rule":  # the kick on the live cells, the snare on 2 and 4, the ride in eighths
        for i, live in enumerate(row):
            if live:
                kit.note(t + 0.25 * i, 0.07, KICK, 108 if i % 4 == 0 else 96)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 120)
        for i in range(8):
            kit.note(t + 0.5 * i, 0.08, RIDE_BELL if i % 4 == 0 else RIDE, 80 if i % 2 == 0 else 62)
    elif style == "double":
        for i in range(16):
            kit.note(t + 0.25 * i, 0.07, KICK, 100 if i % 2 == 0 else 86)
        for beat in range(4):
            kit.note(t + beat, 0.2, CHINA if beat == 0 else RIDE, 88)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 122)
    elif style == "half":
        for o in (0, 1.5, 2.75):
            kit.note(t + o, 0.1, KICK, 112)
        kit.note(t + 2, 0.14, SNARE, 122)
        for i in range(8):
            kit.note(t + 0.5 * i, 0.07, HAT, 78 if i % 2 == 0 else 58)
    elif style == "anthem":
        for i in range(8):
            kit.note(t + 0.5 * i, 0.08, KICK, 106 if i % 2 == 0 else 92)
        for beat in range(4):
            kit.note(t + beat, 0.2, CRASH if beat == 0 else RIDE, 92 if beat == 0 else 84)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 120)
    elif style == "clock":  # the intro: a closed hat ticking, the kick on the live cells
        for i in range(8):
            kit.note(t + 0.5 * i, 0.06, HAT, 70 if i % 2 == 0 else 52)
        if row:
            for i, live in enumerate(row):
                if live:
                    kit.note(t + 0.25 * i, 0.07, KICK, 90)
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


def play(clip: Clip, at: float, notes: list[int], sub: float, vel: int = 100, twin_chord: str | None = None,
         cap: int = TOP) -> float:
    for i, pitch in enumerate(notes):
        pitch = min(pitch, cap)
        accent = 8 if i % 4 == 0 else 0
        clip.note(at + i * sub, sub * 0.9, pitch, vel + accent)
        if twin_chord:
            twin.note(at + i * sub, sub * 0.9, twin_under(pitch, twin_chord, False), vel - 6 + accent)
    return at + len(notes) * sub


def run(start: str, count: int, direction: int) -> list[int]:
    notes = [midi(start)]
    for _ in range(count - 1):
        notes.append(degree(notes[-1], direction))
    return notes


def fours_down(top: str, groups: int) -> list[int]:
    out, head = [], midi(top)
    for _ in range(groups):
        out += [head, degree(head, -1), degree(head, -2), degree(head, -3)]
        head = degree(head, -1)
    return out


#: The keys each choir sings (VPO: male G2-F#4, female G4-C6).
RANGE = {"m": (43, 66), "f": (67, 84)}


def pad(n: int, chord: str, vel=70, beats=4.0, female=False):
    clip, (lo, hi) = (choir_f, RANGE["f"]) if female else (choir_m, RANGE["m"])
    for pc in sorted(CHORD_PCS[chord]):
        pitch = lo + (pc - lo) % 12
        if pitch <= hi:
            clip.note(bar(n), beats - 0.15, pitch, vel)


harmony: dict[int, str] = {}


# ---- The riff ---------------------------------------------------------------------------
#: The roots the live cells walk through, in scale steps above the pedal:
#: each live cell of a bar takes the next one, so a fuller generation climbs
#: further (E F# G# B C# B G# F# E D# from the E pedal).
WALK = [0, 1, 2, 4, 5, 4, 2, 1, 0, -1]


def riff_bar(n: int, pedal: str, row: list[int], vel=100):
    """One generation as one bar: live cells hit a power chord on the walk,
    dead cells chug the palm-muted pedal; the bass doubles the roots."""
    p = midi(pedal)
    t = bar(n)
    k = 0
    for i, live in enumerate(row):
        at = t + 0.25 * i
        if live:
            root = degree(p, WALK[k % len(WALK)]) if WALK[k % len(WALK)] else p
            k += 1
            both(at, 0.22, power(root), vel + (8 if i % 4 == 0 else 0))
            bass.note(at, 0.22, root, 104)
        else:
            both(at, 0.16, [p], vel - 18)
            if i % 2 == 0:
                bass.note(at, 0.2, p, 90)


# ---- Intro, bars 1-8: the lattice switching on ---------------------------------------------
#: The cyborg strings play a live cell as a note of the E Lydian chord (E B D# F# A#) stacked up
#: the ring: cell i sounds the i-th note of the stack.
STACK = [midi(x) for x in ("E3", "B3", "D#4", "F#4", "A#4", "B4", "D#5", "E5")] * 2
for k in range(8):
    n = 1 + k
    row = CYCLE[k % 4]
    for i, live in enumerate(row):
        if live:
            cyborg.note(bar(n) + 0.25 * i, 0.22, STACK[(i + 3 * k) % 16], 84 + (10 if i == 0 else 0))
    harmony[n] = "E" if k % 4 < 2 else "F#"
    if k < 4:
        drums(n, "clock", row if k >= 2 else None)
    else:
        riff_bar(n, "E2" if k % 4 < 2 else "F#2", row, vel=96)
        drums(n, "rule", row, crash=k == 4)
pad(5, "E", 56, beats=8.0)
pad(7, "F#", 60, beats=8.0)
fill(8, 3.0)

# ---- Verse, bars 9-24: the rule's riff ------------------------------------------------------
VERSE = [("E2", "E"), ("E2", "E"), ("F#2", "F#"), ("C#3", "C#m")]
for block, (pedal, name) in enumerate(VERSE):
    for g in range(4):
        n = 9 + 4 * block + g
        riff_bar(n, pedal, CYCLE[g])
        drums(n, "rule", CYCLE[g], crash=g == 0 and block in (0, 2))
        harmony[n] = name
# Lead fills in the dead half of each four bars' first generation.
play(lead, bar(13) + 2.5, [midi(x) for x in ("B4", "A#4", "B4", "E5", "D#5", "E5")], 0.25, 100)
play(lead, bar(17) + 1.5, fours_down("F#5", 2) + [midi("A#4"), midi("B4")], 0.25, 100)
play(lead, bar(21) + 2.0, [midi(x) for x in ("C#5", "G#4", "A#4", "C#5", "E5", "D#5", "C#5", "G#5")], 0.25, 100)
play(lead, bar(24) + 2.0, run("G#4", 8, 1), 0.25, 102)
fill(24, 3.0)

# ---- Rise, bars 25-32: half time; the choir comes in ---------------------------------------
RISE = ["C#m", "C#m", "B", "B", "F#", "F#", "G#m", "B"]
for k, name in enumerate(RISE):
    n = 25 + k
    r = midi(ROOTS[name])
    for o, dur in ((0, 1.4), (1.5, 0.9), (2.75, 1.15)):
        both(bar(n) + o, dur, power(r), 112)
        bass.note(bar(n) + o, dur, r, 104)
    # The cyborgs keep the lattice ticking: the chord's tones in sixteenths, a cell missing each beat.
    tones = sorted(p for p in range(midi("E4"), midi("E5") + 1) if p % 12 in CHORD_PCS[name])
    for i in range(16):
        if i % 4 != 3:
            cyborg.note(bar(n) + 0.25 * i, 0.2, tones[i % len(tones)], 78 + 2 * k)
    pad(n, name, 64 + 2 * k)
    drums(n, "half", crash=k % 2 == 0)
    harmony[n] = name
play(lead, bar(32) + 2.0, run("B4", 8, 1), 0.25, 104)
fill(32, 3.0)

# ---- The hook ------------------------------------------------------------------------------
HOOK = [
    [("E5", 0.75), ("A#4", 0.25), ("B4", 1), ("F#5", 1), ("E5", 0.5), ("D#5", 0.5)],
    [("C#5", 0.75), ("F#4", 0.25), ("A#4", 1), ("C#5", 1.5), ("E5", 0.5)],
    [("G#4", 0.75), ("C#5", 0.25), ("E5", 1), ("D#5", 0.5), ("C#5", 0.5), ("B4", 1)],
    [("D#5", 1.5), ("F#5", 0.5), ("B4", 2)],
    [("E5", 0.75), ("A#4", 0.25), ("B4", 1), ("F#5", 1), ("G#5", 0.5), ("F#5", 0.5)],
    [("F#5", 1.5), ("E5", 0.5), ("C#5", 1), ("A#4", 1)],
    [("B4", 0.75), ("D#5", 0.25), ("G#5", 1.5), ("F#5", 0.5), ("D#5", 1)],
    [("D#5", 2), ("B4", 0.5), ("C#5", 0.5), ("D#5", 1)],
    [("E5", 1), ("G#5", 1), ("F#5", 0.75), ("E5", 0.25), ("B4", 1)],
    [("C#5", 1.5), ("A#4", 0.5), ("C#5", 1), ("F#5", 1)],
    [("E5", 0.75), ("D#5", 0.25), ("C#5", 1), ("G#5", 1.5), ("E5", 0.5)],
    [("D#5", 2), ("B4", 1), ("G#4", 1)],
    [("E5", 0.75), ("A#4", 0.25), ("C#5", 1), ("E5", 1), ("G#5", 1)],
    [("F#5", 2), ("E5", 1), ("C#5", 1)],
    [("D#5", 0.75), ("E5", 0.25), ("F#5", 1), ("D#5", 1), ("C#5", 1)],
    [("B4", 1), ("E5", 3)],
]
HOOK_CHORDS = ["E", "F#", "C#m", "B", "E", "F#", "G#m", "B", "E", "F#", "C#m", "G#m", "C#m", "F#", "B", "E"]
assert all(abs(sum(d for _, d in b) - 4) < 1e-9 for b in HOOK), "every bar of the hook is four beats"


def chorus(n: int, bars, style="anthem", vel=100, female=False):
    for k, i in enumerate(bars):
        name = HOOK_CHORDS[i]
        root = midi(ROOTS[name])
        t = bar(n + k)
        for j in range(8):
            accent = j in (0, 3, 6)
            both(t + 0.5 * j, 0.4 if accent else 0.18, power(root) if accent else power(root)[:2], 104 if accent else 92)
            bass.note(t + 0.5 * j, 0.45, root, 100 if accent else 90)
        pad(n + k, name, 74)
        if female:
            pad(n + k, name, 62, female=True)
        harmony[n + k] = name
        drums(n + k, style, crash=k % 4 == 0)
        beat = 0.0
        for note, dur in HOOK[i]:
            pitch = midi(note)
            accent = 8 if beat == 0 else 0
            lead.note(t + beat, dur * 0.96, pitch, vel + accent)
            twin.note(t + beat, dur * 0.96, twin_under(pitch, name, dur >= 1), vel - 6 + accent)
            beat += dur


chorus(33, range(16))
fill(48, 3.0)

# ---- The fault, bars 49-56: one cell flipped -------------------------------------------------
for k in range(8):
    n = 49 + k
    row = FAULT[k]
    pedal, name = ("E2", "E") if k < 4 else ("C#3", "C#m")
    riff_bar(n, pedal, row, vel=98)
    drums(n, "rule", row, crash=k in (0, 4))
    harmony[n] = name
    for i, live in enumerate(row):
        if live:
            cyborg.note(bar(n) + 0.25 * i, 0.2, STACK[(i + 5 * k) % 16] + 12, 80)
# The lead's break over it: falling fours, then the hook's head turned round.
play(lead, bar(49), fours_down("G#5", 4), 0.25, 100)
play(lead, bar(51), [midi(x) for x in ("E5", "A#4", "B4", "F#5")] * 2, 0.25, 100)
play(lead, bar(52), run("A#4", 8, 1) + run("A5", 8, -1), 0.25, 100)
play(lead, bar(53), fours_down("E5", 4), 0.25, 100, twin_chord="C#m")
play(lead, bar(55), [midi(x) for x in ("C#5", "G#4", "A#4", "E5")] * 2, 0.25, 100, twin_chord="C#m")
play(lead, bar(56), run("D#5", 8, 1) + [midi(x) for x in ("A5", "G#5", "F#5", "D#5", "B4", "A#4", "B4", "D#5")], 0.25, 104,
     twin_chord="B")
fill(56, 2.0)

# ---- Rerun, bars 57-64: the hook's first half, all in -----------------------------------------
chorus(57, range(8), style="double", vel=104, female=True)
fill(64, 3.0)

# ---- Homeward, bars 65-68: every cell lit, then D# minor back to E -------------------------
for k, name in enumerate(("E", "F#", "G#m", "D#m")):
    n = 65 + k
    r = midi(ROOTS[name])
    for i in range(16):
        accent = i % 4 == 0
        both(bar(n) + 0.25 * i, 0.22 if accent else 0.16, power(r) if accent else [r], 116 if accent else 96)
        if i % 2 == 0:
            bass.note(bar(n) + 0.25 * i, 0.22, r, 106)
        cyborg.note(bar(n) + 0.25 * i, 0.2, STACK[i] if k < 2 else degree(STACK[i], 1), 82 + 3 * k)
    pad(n, name, 80)
    drums(n, "double", crash=True)
    harmony[n] = name
play(lead, bar(68) + 2, run("D#5", 8, 1), 0.25, 104)
fill(68, 3.0)

END_BAR = 69
progression = [harmony.get(n, "E") for n in range(1, END_BAR)]
for clip in (lead, twin):
    assert max(max(p) for _, _, p, _ in clip.events) <= TOP, "no lead note above A5"


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


# The guitars' chains are The Iron Toccata's (dev/compose_iron_toccata.py), which Jon rated a standout.
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
            - {{effect: delay, delay_ms: 281, feedback: 0.2, mix: 0.14}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {gain}}}
        - {{processor: balance, position: {pos}}}"""

GUITAR = "instrument_backend: {kind: sfz, optional: false, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {fold_to_range: false}}"

score = f"""schema: ambition.musicir.v3
id: glider_gun
title: Glider Gun
description: >-
  The Perfect Cellular Automaton's fight. Heavy metal in E Lydian at 160
  BPM. The riff is written by the rule: rule 150 on a ring of sixteen cells
  comes back every four bars, and its live cells are the power chords and
  the kicks. The intro switches the lattice on with String Cyborgs; a verse,
  a half-time rise with the choir, the hook on twin leads, a fault where one
  flipped cell breaks the riff under a lead break, the hook again with all
  in, and every cell lit on the way home. Composed from first principles
  (Jon, 2026-11-25). Generated by dev/compose_glider_gun.py: edit that, not
  this file.
notes:
  - 'E Lydian: E F# G# A# B C# D#. The hook leans on A#, the raised fourth.'
  - 'The intro plays once; the loop is bars 9-68, and its last bar climbs from D# back into the riff on E.'
seed: 1970
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: {{tonic: E, mode: lydian}}
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.6, density: 0.5, role: 'the lattice switching on; the band joins'}}
  - {{id: verse, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.85, density: 0.85, loopable: true, role: 'the rule writes the riff'}}
  - {{id: rise, from: {{bar: 25, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.8, density: 0.7, loopable: true, role: 'half time, the choir'}}
  - {{id: chorus, from: {{bar: 33, beat: 1}}, to: {{bar: 49, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'the hook on twin leads'}}
  - {{id: fault, from: {{bar: 49, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.9, density: 0.85, loopable: true, role: 'a flipped cell; the lead break'}}
  - {{id: rerun, from: {{bar: 57, beat: 1}}, to: {{bar: 65, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the hook again, all in'}}
  - {{id: homeward, from: {{bar: 65, beat: 1}}, to: {{bar: 69, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'every cell lit; back to E'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: rhythm_l, group: rhythm_l, program: distortion_guitar, volume: 110, pan: 64, expression: 112, {GUITAR}}}
  - {{name: rhythm_r, group: rhythm_r, program: distortion_guitar, volume: 110, pan: 64, expression: 112, {GUITAR}}}
  - {{name: lead, group: lead, program: distortion_guitar, volume: 104, pan: 64, expression: 112, {GUITAR}}}
  - {{name: twin, group: twin, program: distortion_guitar, volume: 104, pan: 64, expression: 112, controls: {{111: 0, 114: 52, 116: 20}}, instrument_backend: {{kind: sfz, optional: false, sfz_glob: '**/BlackAndGreenGuitars/Programs/02-black_keyswitch.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: bass, group: bass, program: picked_bass, volume: 116, pan: 64, expression: 116, mix_gain_db: 6.0, instrument_backend: {{kind: sfz, optional: false, library_ref: bass.growly}}}}
  - {{name: cyborg, group: cyborg, program: string_ensemble_2, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, optional: false, library_ref: strings.cyborg}}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, optional: false, library_ref: vpo.choir_male}}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 96, pan: 64, expression: 100, instrument_backend: {{kind: sfz, optional: false, library_ref: vpo.choir}}}}
  - {{name: kit, group: drums, volume: 124, pan: 64, expression: 120, is_drum: true, mix_gain_db: 1.0, instrument_backend: {{kind: sfz, optional: false, library_ref: drums.muldjord}}}}
parts:
{part("rhythm_l_part", "rhythm_l", rhythm_l)}
{part("rhythm_r_part", "rhythm_r", rhythm_r)}
{part("lead_part", "lead", lead)}
{part("twin_part", "twin", twin)}
{part("bass_part", "bass", bass)}
{part("cyborg_part", "cyborg", cyborg)}
{part("choir_m_part", "choir_m", choir_m)}
{part("choir_f_part", "choir_f", choir_f)}
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
    cyborg:
      chain:
        - {{processor: highpass, cutoff_hz: 110}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: -0.2}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 3.0}}
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
        - {{processor: gain, gain_db: -3.5}}
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
    keys: [cyborg, choir]
    lead: [lead, twin]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [verse, rise, chorus, fault, rerun, homeward], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

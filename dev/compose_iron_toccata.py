"""The Iron Toccata: neoclassical heavy metal in F# harmonic minor, opened
by an organ. Writes its MusicIR v3 score:

    python3 dev/compose_iron_toccata.py scores/active/iron_toccata.music.yaml

Jon, 2026-10-19, after The Phrygian Furnace ("Blistering. I love it"): "I
want another heavy metal track." Its own thing again: the Decree gallops in
Locrian with a choir, the Furnace thrashes in Phrygian dominant with twin
leads; this one is baroque. F# harmonic minor (F# G# A B C# D E#), whose
raised seventh pulls every phrase home, an organ toccata for an intro, a
pedal-point riff, a harpsichord, a duel between the harpsichord and the
guitar, and a last chorus a whole step up.

Only F#, B, C# and D carry a perfect fifth in the scale, so only they (and
the borrowed E of the chorus) are power chords.

Form, 4/4 at 152 BPM:
  intro      1-8    the organ's toccata alone, then the band under it.
  verse      9-24   the pedal-point riff on F#, B, C#, D; lead fills. (loop start)
  rise       25-32  half time; the harpsichord arpeggiates D, E, C#.
  chorus     33-48  the tune on the lead and the organ, the twin under it.
  duel       49-64  harpsichord against guitar, then both, then all.
  ascent     65-72  the chorus a whole step up, in G# minor.
  homeward   73-76  B, C#, D, C#: back down to F# and the riff.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 152
OUT = Path(sys.argv[1])
rng = random.Random(1685)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7,
        "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "B#": 0}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


#: F# harmonic minor; the chorus also borrows E natural (its E chord).
MODE = [6, 8, 9, 11, 1, 2, 5]
#: Jon hears high lead guitar as piercing: no lead note above A5.
TOP = midi("A5")


def step(pitch: int, direction: int, mode=MODE) -> int:
    pitch += direction
    while pitch % 12 not in mode:
        pitch += direction
    return pitch


CHORD_PCS = {
    "F#m": {6, 9, 1}, "D": {2, 6, 9}, "E": {4, 8, 11}, "C#": {1, 5, 8}, "Bm": {11, 2, 6}, "B": {11, 3, 6},
    "G#m": {8, 11, 3}, "F#": {6, 10, 1}, "D#": {3, 7, 10},
}


def twin_under(pitch: int, chord: str, held: bool, shift: int = 0) -> int:
    """The twin's note under the lead: a chord tone below a held note, else
    the scale's third below (in the scale `shift` semitones up)."""
    if held:
        for below in range(pitch - 3, pitch - 10, -1):
            if below % 12 in CHORD_PCS[chord]:
                return below
    mode = [(p + shift) % 12 for p in MODE] + ([(4 + shift) % 12] if chord in ("E", "F#") else [])
    for below in range(pitch - 3, pitch - 6, -1):
        if below % 12 in mode:
            return below
    return pitch - 3


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
organ = Clip()
harpsichord = Clip(jitter_ms=1, vel_jitter=3)
rhythms = (rhythm_l, rhythm_r)


def both(at, dur, pitches, vel):
    for r in rhythms:
        r.note(at, dur, pitches, vel)


FIFTHS = {6, 11, 1, 2, 4, 8}  # F#, B, C#, D, E (borrowed), G# (the ascent's tonic)


def chord(root: int) -> list[int]:
    return [root, root + 7, root + 12] if root % 12 in FIFTHS else [root, root + 12]


# ---- Drums (GM keys of the Muldjord kit) -----------------------------------------
KICK, SNARE, HAT, CRASH, CHINA, RIDE, RIDE_BELL, FLOOR, MID, HIGH = 36, 38, 42, 49, 52, 51, 53, 41, 45, 48


def drums(n: int, style: str, crash=False):
    t = bar(n)
    if style == "double":
        for i in range(16):
            kit.note(t + 0.25 * i, 0.07, KICK, 100 if i % 2 == 0 else 86)
        for beat in range(4):
            kit.note(t + beat, 0.1, RIDE_BELL if beat % 2 == 0 else RIDE, 82)
            kit.note(t + beat + 0.5, 0.08, RIDE, 62)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 120)
    elif style == "half":
        for o in (0, 1.5, 2.5):
            kit.note(t + o, 0.1, KICK, 112)
        kit.note(t + 2, 0.14, SNARE, 122)
        for i in range(8):
            kit.note(t + 0.5 * i, 0.07, HAT, 78 if i % 2 == 0 else 58)
    elif style == "anthem":  # the chorus: a driving eighth kick, crash-ride on the beat
        for i in range(8):
            kit.note(t + 0.5 * i, 0.08, KICK, 106 if i % 2 == 0 else 92)
        for beat in range(4):
            kit.note(t + beat, 0.2, CRASH if beat == 0 else RIDE, 92 if beat == 0 else 84)
        for beat in (1, 3):
            kit.note(t + beat, 0.12, SNARE, 120)
    elif style == "skank":
        for beat in range(4):
            kit.note(t + beat, 0.1, KICK, 110)
            kit.note(t + beat + 0.5, 0.1, SNARE, 104)
            kit.note(t + beat, 0.1, RIDE, 80)
    elif style == "march":
        for beat in range(4):
            kit.note(t + beat, 0.2, FLOOR, 96 + 4 * beat)
        kit.note(t + 3.5, 0.1, SNARE, 90)
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
    """`notes` one after another, `sub` beats each; with `twin_chord` the
    twin plays a third below. Returns the beat after the last note."""
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


def sweep(names: list[str]) -> list[int]:
    up = [midi(n) for n in names]
    return up + up[-2::-1]


harmony: dict[int, str] = {}

# ---- Intro, bars 1-8: the toccata ---------------------------------------------------
# A broken-chord figure in sixteenths, tonic against dominant, over a pedal: F#
# minor, the dominant C# with its raised seventh E#, the sixth D, the dominant.
TOCCATA = [
    ["F#4", "A4", "C#5", "A4", "F#4", "A4", "C#5", "F#5", "E#5", "C#5", "G#4", "C#5", "E#4", "G#4", "C#5", "G#4"],
    ["F#4", "A4", "D5", "A4", "F#4", "A4", "D5", "F#5", "E#5", "D5", "B4", "G#4", "E#4", "G#4", "B4", "G#4"],
]
PEDALS = ["F#2", "C#2", "D2", "C#2"]
for k in range(8):
    n = 1 + k
    figure = TOCCATA[k % 2]
    play(organ, bar(n), [midi(x) for x in figure], 0.25, 92, cap=midi("F#5"))
    organ.note(bar(n), 3.9, [midi(PEDALS[k % 4]), midi(PEDALS[k % 4]) + 12], 84)
    harmony[n] = ("F#m", "C#", "D", "C#")[k % 4]
    if k >= 4:
        root = midi(PEDALS[k % 4])
        for o, dur in ((0, 1.4), (1.5, 0.4), (2.5, 1.4)):
            both(bar(n) + o, dur, chord(root + 12 if root < midi("E2") else root), 116)
            bass.note(bar(n) + o, dur, root + 12 if root < midi("E2") else root, 110)
        drums(n, "half", crash=k in (4, 6))
    else:
        drums(n, "march")
fill(8, 2.0)


# ---- Verse, bars 9-24: the pedal-point riff -----------------------------------------
def pedal_riff(n: int, root: str, vel=98):
    """Two bars of sixteenths: the open root against a line that climbs and
    falls over it, the line on the accent."""
    r = midi(root)
    line = [r + 7, r + 8, r + 7, r + 5, r + 7, r + 8, r + 10, r + 8] if r % 12 != 2 else [r + 7, r + 8, r + 7, r + 4, r + 7, r + 8, r + 11, r + 8]
    # Keep the line in the scale.
    line = [p if p % 12 in MODE else p - 1 for p in line]
    for b in (0, 1):
        t = bar(n + b)
        for i in range(8):
            both(t + 0.5 * i, 0.2, [r], vel - 14)
            both(t + 0.5 * i + 0.25, 0.2, [line[(i + 4 * b) % 8]], vel)
        for i in range(8):
            bass.note(t + 0.5 * i, 0.45, r, 96 if i % 2 == 0 else 86)


VERSE = [("F#2", 9), ("F#2", 11), ("B2", 13), ("C#3", 15), ("F#2", 17), ("F#2", 19), ("D2", 21), ("C#3", 23)]
VERSE_CHORDS = {"F#2": "F#m", "B2": "Bm", "C#3": "C#", "D2": "D"}
for root, n in VERSE:
    pedal_riff(n, root)
    harmony.update({n: VERSE_CHORDS[root], n + 1: VERSE_CHORDS[root]})
for n in range(9, 25):
    drums(n, "double", crash=n in (9, 17))
# Lead fills at the end of each four bars.
play(lead, bar(12) + 2, fours_down("A5", 2), 0.25, 100)
play(lead, bar(16) + 2, run("E#4", 8, 1), 0.25, 100)
play(lead, bar(20) + 2, [midi(x) for x in ("C#5", "F#5", "A5", "F#5", "C#5", "A4", "F#4", "A4")], 0.25, 100)
play(lead, bar(24) + 2, fours_down("G#5", 1) + run("C#5", 4, -1), 0.25, 100)
fill(24, 3.0)

# ---- Rise, bars 25-32: the harpsichord over half time -------------------------------------
RISE = [("D", "D2", ["D4", "F#4", "A4", "D5", "A4", "F#4"]), ("E", "E2", ["E4", "G#4", "B4", "E5", "B4", "G#4"]),
        ("C#", "C#3", ["C#4", "E#4", "G#4", "C#5", "G#4", "E#4"]), ("C#", "C#3", ["E#4", "G#4", "C#5", "E#5", "C#5", "G#4"])] * 2
for k, (name, root, arp) in enumerate(RISE):
    n = 25 + k
    r = midi(root)
    both(bar(n), 3.9, chord(r), 112)
    bass.note(bar(n), 3.9, r, 104)
    play(harpsichord, bar(n), [midi(x) for x in arp] * 4, 1 / 6, 92, cap=midi("F#5"))
    organ.note(bar(n), 3.9, [p + 24 for p in chord(r)[:2]], 70 + 2 * k)
    drums(n, "half", crash=k % 2 == 0)
    harmony[n] = name
fill(32, 2.0)

# ---- The chorus tune ------------------------------------------------------------------
CHORUS = [
    [("C#5", 2), ("B4", 1), ("A4", 1)],
    [("A4", 1.5), ("B4", 0.5), ("D5", 2)],
    [("E5", 2), ("D5", 1), ("C#5", 1)],
    [("G#4", 2), ("E#4", 1), ("G#4", 1)],
    [("C#5", 2), ("B4", 1), ("A4", 1)],
    [("A4", 1.5), ("B4", 0.5), ("F#5", 2)],
    [("E5", 1), ("D5", 1), ("C#5", 1), ("B4", 1)],
    [("C#5", 4)],
    [("F#5", 2), ("E5", 1), ("D5", 1)],
    [("D5", 1.5), ("E5", 0.5), ("F#5", 2)],
    [("G#5", 2), ("F#5", 1), ("E5", 1)],
    [("E#5", 2), ("D5", 1), ("C#5", 1)],
    [("D5", 2), ("C#5", 1), ("B4", 1)],
    [("B4", 1.5), ("C#5", 0.5), ("D5", 2)],
    [("E#5", 1), ("D5", 1), ("C#5", 1), ("B4", 1)],
    [("F#5", 4)],
]
CHORUS_CHORDS = ["F#m", "D", "E", "C#", "F#m", "D", "B", "C#", "F#m", "D", "E", "C#", "D", "Bm", "C#", "F#m"]
CHORUS_ROOTS = {"F#m": "F#2", "D": "D2", "E": "E2", "C#": "C#3", "B": "B2", "Bm": "B2",
                "G#m": "G#2", "F#": "F#2", "D#": "D#2"}
SHIFTED = {"F#m": "G#m", "D": "E", "E": "F#", "C#": "D#", "B": "C#", "Bm": "C#"}


def chorus(n: int, bars, shift=0, vel=100):
    for k, i in enumerate(bars):
        name = CHORUS_CHORDS[i] if not shift else SHIFTED[CHORUS_CHORDS[i]]
        root = midi(CHORUS_ROOTS[name])
        t = bar(n + k)
        for j in range(8):  # eighth chugs, accents on 1 and 3
            accent = j in (0, 4)
            both(t + 0.5 * j, 0.4 if accent else 0.18, chord(root) if accent else chord(root)[:2], 104 if accent else 92)
            bass.note(t + 0.5 * j, 0.45, root, 100 if accent else 90)
        organ.note(t, 3.9, sorted({p for p in range(midi("F#3"), midi("F#4")) if p % 12 in CHORD_PCS[name]})[:3], 78)
        harmony[n + k] = name
        drums(n + k, "anthem")
        beat = 0.0
        for note, dur in CHORUS[i]:
            pitch = midi(note) + shift
            accent = 8 if beat == 0 else 0
            lead.note(t + beat, dur * 0.96, pitch, vel + accent)
            twin.note(t + beat, dur * 0.96, twin_under(pitch, name, dur >= 1, shift), vel - 6 + accent)
            organ.note(t + beat, dur * 0.96, pitch, 70 + accent)
            beat += dur


chorus(33, range(16))
fill(48, 3.0)

# ---- Duel, bars 49-64, over F#m, D, E, C# -----------------------------------------------
DUEL = ["F#m", "D", "E", "C#"] * 4
ARPS = {"F#m": ["F#4", "A4", "C#5", "F#5", "C#5", "A4"], "D": ["D4", "F#4", "A4", "D5", "A4", "F#4"],
        "E": ["E4", "G#4", "B4", "E5", "B4", "G#4"], "C#": ["C#4", "E#4", "G#4", "C#5", "G#4", "E#4"]}
SWEEPS = {"F#m": ["F#4", "A4", "C#5", "F#5", "A5"], "D": ["D4", "F#4", "A4", "D5", "F#5"],
          "E": ["E4", "G#4", "B4", "E5", "G#5"], "C#": ["C#4", "E#4", "G#4", "C#5", "E#5"]}
for k in range(16):
    n = 49 + k
    name = DUEL[k]
    root = midi(CHORUS_ROOTS[name])
    t = bar(n)
    for j in range(8):
        accent = j in (0, 3, 6)
        both(t + 0.5 * j, 0.4 if accent else 0.18, chord(root) if accent else chord(root)[:2], 100 if accent else 88)
        bass.note(t + 0.5 * j, 0.45, root, 96)
    drums(n, "skank" if k < 8 else "double", crash=k % 4 == 0)
    harmony[n] = name
    if k < 4:  # the harpsichord states each chord; the guitar answers it
        play(harpsichord, t, [midi(x) for x in ARPS[name]] * 2, 1 / 6, 96, cap=midi("F#5"))
        play(lead, t + 2, fours_down(("A5", "F#5", "G#5", "E#5")[k], 2), 0.25, 100)
    elif k < 8:  # the guitar sweeps each chord, the harpsichord runs back down
        play(lead, t, sweep(SWEEPS[name]), 1 / 6, 100)
        play(harpsichord, t + 2, run(("F#5", "D5", "E5", "E#5")[k - 4], 8, -1), 0.25, 96, cap=midi("F#5"))
    elif k < 12:  # both at once, an octave apart: the scale up and down
        play(lead, t, run(("F#4", "D4", "E4", "C#4")[k - 8], 8, 1) + run(("F#5", "D5", "E5", "C#5")[k - 8], 8, -1), 0.25, 100)
        play(harpsichord, t, run(("F#3", "D3", "E3", "C#3")[k - 8], 8, 1) + run(("F#4", "D4", "E4", "C#4")[k - 8], 8, -1), 0.25, 92)
    else:  # the twin joins in thirds, and the organ holds the chord
        play(lead, t, fours_down(("A5", "F#5", "G#5", "E#5")[k - 12], 4), 0.25, 100, twin_chord=name)
        organ.note(t, 3.9, sorted({p for p in range(midi("F#3"), midi("F#4")) if p % 12 in CHORD_PCS[name]})[:3], 84)
fill(64, 3.0)

# ---- Ascent, bars 65-72: the chorus's first half a whole step up -------------------------------
chorus(65, range(8), shift=2, vel=104)
fill(72, 3.0)

# ---- Homeward, bars 73-76: B, C#, D, C# back to F# ----------------------------------------------
for k, (name, root) in enumerate((("B", "B2"), ("C#", "C#3"), ("D", "D2"), ("C#", "C#3"))):
    n = 73 + k
    r = midi(root)
    for o, dur in ((0, 1.4), (1.5, 0.9), (2.5, 1.4)):
        both(bar(n) + o, dur, chord(r), 118)
        bass.note(bar(n) + o, dur, r, 110)
    organ.note(bar(n), 3.9, [p + 24 for p in chord(r)[:2]], 86)
    drums(n, "half", crash=True)
    harmony[n] = name
play(lead, bar(76) + 2, run("C#5", 8, 1), 0.25, 102)
fill(76, 2.0)

END_BAR = 77
progression = [harmony.get(n, "F#m") for n in range(1, END_BAR)]


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
            - {{effect: delay, delay_ms: 296, feedback: 0.2, mix: 0.14}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {gain}}}
        - {{processor: balance, position: {pos}}}"""

GUITAR = "instrument_backend: {kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {fold_to_range: false}}"

score = f"""schema: ambition.musicir.v3
id: iron_toccata
title: The Iron Toccata
description: >-
  Neoclassical heavy metal in F# harmonic minor at 152 BPM: an organ
  toccata, a pedal-point riff with lead fills, a half-time rise under a
  harpsichord, a chorus on lead guitar and organ with a twin under it, a
  duel between the harpsichord and the guitar, and the chorus a whole step
  up before the way home. Composed from first principles (Jon, 2026-10-19:
  "I want another heavy metal track"). Generated by dev/compose_iron_toccata.py:
  edit that, not this file.
notes:
  - 'F# harmonic minor: F# G# A B C# D E#. The chorus borrows E natural for its E chord; the ascent is in G# minor.'
  - 'The intro plays once; the loop is bars 9-76, and its last bars walk B, C#, D, C# back into the riff.'
  - 'The organ and the harpsichord are General MIDI programs.'
seed: 1685
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: {{tonic: F#, mode: harmonic_minor}}
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.6, density: 0.5, role: 'the organ toccata; the band joins under it'}}
  - {{id: verse, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.85, density: 0.85, loopable: true, role: 'the pedal-point riff, lead fills'}}
  - {{id: rise, from: {{bar: 25, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.8, density: 0.7, loopable: true, role: 'half time under the harpsichord'}}
  - {{id: chorus, from: {{bar: 33, beat: 1}}, to: {{bar: 49, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'the tune on the lead and the organ'}}
  - {{id: duel, from: {{bar: 49, beat: 1}}, to: {{bar: 65, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'harpsichord against guitar'}}
  - {{id: ascent, from: {{bar: 65, beat: 1}}, to: {{bar: 73, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the chorus a whole step up'}}
  - {{id: homeward, from: {{bar: 73, beat: 1}}, to: {{bar: 77, beat: 1}}, energy: 0.9, density: 0.8, loopable: true, role: 'back down to F# and the riff'}}
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
  - {{name: organ, group: organ, program: church_organ, volume: 96, pan: 64, expression: 100}}
  - {{name: harpsichord, group: harpsichord, program: harpsichord, volume: 100, pan: 64, expression: 104}}
  - {{name: kit, group: drums, volume: 124, pan: 64, expression: 120, is_drum: true, mix_gain_db: 1.0, instrument_backend: {{kind: sfz, library_ref: drums.muldjord}}}}
parts:
{part("rhythm_l_part", "rhythm_l", rhythm_l)}
{part("rhythm_r_part", "rhythm_r", rhythm_r)}
{part("lead_part", "lead", lead)}
{part("twin_part", "twin", twin)}
{part("bass_part", "bass", bass)}
{part("organ_part", "organ", organ)}
{part("harpsichord_part", "harpsichord", harpsichord)}
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
    organ:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.25, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 0.0}}
    harpsichord:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: 0.25}}
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
    keys: [organ, harpsichord]
    lead: [lead, twin]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [verse, rise, chorus, duel, ascent, homeward], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

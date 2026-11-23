"""The Leaden Saddle: the Frontier dimension's music, a spaceport town in a
desert pass (Ambition's `docs/planning/game/leadensaddle.md`). Writes two
MusicIR v3 scores:

    python3 dev/compose_leaden_saddle.py scores/active

- `leaden_saddle`: the dimension, four sections the game binds to its rooms.
- `marshal_gallus_showdown`: the boss, Marshal Gallus, a rooster rebuilt as
  a machine, who keeps the town's law with a whistle and a revolver.

The request (Jon, 2026-11-20): western music for the biome and a boss theme;
the feel of a space western, where the frontier has docked ships and a
refinery beside the saloon. The named shows and games were mood only: no
melody, progression or arrangement is taken from any of them.

THE TWO MOTIFS (both original):
  the saddle: A C D E, G E D C D: a rise of a fourth and a fall back, the
      shape of a pass seen from the road. Every section of the town cue
      says it.
  the strut: B G F# G, A D C A F#: from the fifth up a minor sixth to the
      third, a semitone dip and back, then a fall through D7: a rooster
      lifting his chest and walking the yard. The boss cue is built on it;
      its last section turns the minor sixth major and falls into the
      saddle. (Jon, 2026-11-20: the first boss theme, "the crow", leaned on
      familiar western calls; the strut replaced it, written from its own
      intervals.)

LEADEN SADDLE (96 BPM, A minor), sections:
  dry_dock        1-32   the town: a boom-chick acoustic guitar, upright
                         bass, a clip-clop rim, the saddle on the fiddle and
                         then on a trumpet; a Rhodes, for the spaceport.  (loop)
  wet_whistle    33-56   the saloon: an upright piano in stride, the saddle
                         turned major, brushes, a walking bass.           (loop)
  refinery_shift 57-80   the refinery: a heavy half-time kit, a pulse of
                         effected strings, low brass on the saddle, the
                         twang guitar.                                    (loop)
  mesa_top       81-96   the mesa top after the fight: the guitar alone,
                         a distant trumpet, strings.                      (loop)

MARSHAL GALLUS SHOWDOWN (132 BPM, E minor), sections:
  standoff        1-8    the corral before the draw: tremolo strings, the
                         strut's opening on a lone trumpet, hanging on the
                         minor sixth; low piano tolls.                (one time)
  duel            9-40   the fight: a gallop on the snare, a twang
                         ostinato; the strut in the trumpets, its bridge
                         (the relative major's colours, a Dorian C# rising
                         to D#) on the solo trumpet; effected strings for
                         his machinery, a male choir.                     (loop)
  high_noon      41-56   enraged: up a semitone to F minor, the strut in
                         the trumpets with the solo above, timpani.       (loop)
  sundown        57-66   his defeat: the strut slowed on the guitar, its
                         minor sixth turned major, falling into the
                         saddle, ending on E major.                   (one time)
"""

from __future__ import annotations

import math
import random
import sys
from fractions import Fraction as F
from pathlib import Path

OUT_DIR = Path(sys.argv[1])

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


CHORD = {
    "Am": ["A", "C", "E"], "C": ["C", "E", "G"], "Dm": ["D", "F", "A"], "D": ["D", "F#", "A"], "E": ["E", "G#", "B"],
    "E7": ["E", "G#", "B", "D"], "F": ["F", "A", "C"], "G": ["G", "B", "D"], "G7": ["G", "B", "D", "F"],
    "A7": ["A", "C#", "E", "G"], "D7": ["D", "F#", "A", "C"], "Bb": ["Bb", "D", "F"], "Em": ["E", "G", "B"],
    "B7": ["B", "D#", "F#", "A"], "Fm": ["F", "Ab", "C"], "Db": ["Db", "F", "Ab"], "Eb": ["Eb", "G", "Bb"],
    "C7": ["C", "E", "G", "Bb"], "Bbm": ["Bb", "Db", "F"], "Fmaj7": ["F", "A", "C", "E"], "Am7": ["A", "C", "E", "G"],
    "Cmaj7": ["C", "E", "G", "B"], "Em7": ["E", "G", "B", "D"],
    "Eb7": ["Eb", "G", "Bb", "Db"], "Dbmaj7": ["Db", "F", "Ab", "C"],
}


def tones(chord: str, octave: int) -> list[int]:
    out = []
    for name in CHORD[chord]:
        p = midi(f"{name}{octave}")
        while out and p <= out[-1]:
            p += 12
        out.append(p)
    return out


def root(chord: str, octave: int) -> int:
    return midi(f"{CHORD[chord][0]}{octave}")


# The longest group reverb here decays within this, so a gap of it holds a ring.
RING_SECONDS = 2.5


class Cue:
    """One score: its tempo, its sections and its clips."""

    def __init__(self, cue_id: str, bpm: int, seed: int, segments):
        self.id, self.bpm, self.rng = cue_id, bpm, random.Random(seed)
        self.seed = seed
        # (id, first logical bar, last logical bar, first score bar). The
        # first section starts the score: a silent opening is dead air in the
        # radio mix and the inspector's preview. Between sections, and after
        # the last, a gap long enough for the ring (the tail of the one
        # before, the lead-in of the one after).
        gap = max(1, math.ceil(RING_SECONDS * bpm / 240))
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
        self.jitter = jitter_ms / 1000.0 * cue.bpm / 60.0
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


def cell(clip: Clip, start: float, base: int, steps, rhythm, vel: int, *, stretch: float = 1.0, legato: float = 0.92,
         accent_first: int = 6, shape=None) -> float:
    at = start
    for i, (step, span) in enumerate(zip(steps, rhythm)):
        span *= stretch
        clip.note(at, span * legato, base + step, vel + (accent_first if i == 0 else 0) + (shape(i) if shape else 0))
        at += span
    return at


# ---- The motifs ----------------------------------------------------------
# The saddle, from A: A C D E, G E D C D.
SADDLE = [0, 3, 5, 7, 10, 7, 5, 3, 5]
SADDLE_RHYTHM = [1.0, 0.5, 0.5, 2.0, 1.0, 0.5, 0.5, 1.0, 1.0]
# Turned major for the saloon, from C: C E F G, A G F E F.
SADDLE_MAJOR = [0, 4, 5, 7, 9, 7, 5, 4, 5]
# The strut (the boss theme), in E minor: two phrases of four bars and a
# bridge, as (note, beats) per bar; `None` is a rest.
STRUT_A = [
    [("B3", 1.5), ("G4", 1.5), ("F#4", 0.5), ("G4", 0.5)],
    [("A4", 0.5), ("D5", 1.0), ("C5", 0.5), ("A4", 0.5), ("F#4", 1.5)],
    [("G4", 1.0), ("E4", 0.5), ("D#4", 0.5), ("E4", 1.0), ("B4", 1.0)],
    [("C5", 2.0), ("B4", 2.0)],
    [("B3", 1.5), ("G4", 1.5), ("F#4", 0.5), ("G4", 0.5)],
    [("A4", 0.5), ("C5", 1.0), ("D5", 0.5), ("E5", 0.5), ("D5", 1.0), ("C5", 0.5)],
    [("B4", 1.0), ("G4", 0.5), ("A4", 0.5), ("F#4", 1.0), ("D#4", 1.0)],
    [("E4", 3.0), (None, 1.0)],
]
STRUT_A_HARMONY = ["Em", "D7", "Em", "Cmaj7", "Em", "Am", "B7", "Em"]
STRUT_B = [
    [("E5", 1.0), ("D5", 0.5), ("B4", 0.5), ("D5", 1.0), ("E5", 1.0)],
    [("G5", 1.5), ("F#5", 0.5), ("E5", 1.0), ("D5", 1.0)],
    [("C5", 0.5), ("D5", 0.5), ("E5", 1.0), ("B4", 1.0), ("G4", 1.0)],
    [("A4", 1.5), ("B4", 0.5), ("C#5", 1.0), ("D#5", 1.0)],
    [("B4", 1.5), ("G5", 1.5), ("F#5", 0.5), ("G5", 0.5)],
    [("E5", 1.0), ("C5", 0.5), ("B4", 0.5), ("A4", 1.0), ("C5", 1.0)],
    [("B4", 1.0), ("A4", 0.5), ("G4", 0.5), ("F#4", 1.0), ("A4", 1.0)],
    [("B4", 4.0)],
]
STRUT_B_HARMONY = ["C", "D", "Am", "B7", "Em", "Am", "B7", "B7"]
for _bar in STRUT_A + STRUT_B:
    assert sum(beats for _, beats in _bar) == 4, _bar

# GM drum notes of the kits (Big Rusty Drums and Naked Drums map like GM).
KICK, SNARE, RIM, SIDESTICK, HAT, HAT_OPEN, RIDE, RIDE_BELL, CRASH, TOM_LO, TOM_HI = 36, 38, 37, 37, 42, 46, 51, 53, 49, 45, 50
BRUSH = 38


def sfz(ref: str, extra: str = "") -> str:
    return f"{extra}instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def glob(pattern: str, controls: str = "") -> str:
    return f"{controls}instrument_backend: {{kind: sfz, optional: false, sfz_glob: '{pattern}', settings: {{fold_to_range: false}}}}"


SHINY = glob("**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz", "controls: {100: 0, 107: 0}, ")
TRUMPET_SOLO = glob("**/Virtual-Playing-Orchestra3/Brass/trumpet-SOLO-PERF.sfz", "controls: {1: 100}, ")


def form_and_playback(cue: Cue, shapes: dict, loops: set) -> tuple[str, str]:
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
        fields = [f"id: {sid}", f"form: [{sid}]"]
        if sid in loops:
            fields.append("loop: true")
            if i > 0:
                fields.append(f"lead_in: before_{sid}")
        fields.append(f"tail: before_{cue.segments[i + 1][0]}" if i + 1 < len(cue.segments) else "tail: after_all")
        play.append("    - {" + ", ".join(fields) + "}")
    return "\n".join(rows), "\n".join(play)


def parts_yaml(cue: Cue) -> str:
    out = []
    for name, clip in cue.clips.items():
        out.append("\n".join([f"  - id: {name}_part", f"    instrument: {name}", "    voices:", f"      - id: {name}_main",
                              "        clips:", clip.yaml(f"{name}_all", "          ")]))
    return "\n".join(out)


def harmony_list(cue: Cue, default: str) -> str:
    score_harmony = {cue.score_bar(b): chord for b, chord in cue.harmony.items()}
    return ", ".join(score_harmony.get(b, default) for b in range(1, cue.end_bar))


# ===========================================================================
# LEADEN SADDLE
# ===========================================================================
town = Cue("leaden_saddle", 96, 1120, [
    ("dry_dock", 1, 32),
    ("wet_whistle", 33, 56),
    ("refinery_shift", 57, 80),
    ("mesa_top", 81, 96),
])
t = town.t
guitar = town.clip("guitar", 6, 6)
fiddle = town.clip("fiddle", 8, 5)
trumpet = town.clip("trumpet", 6, 4)
rhodes = town.clip("rhodes", 5, 4)
bass = town.clip("bass", 5, 5)
banjo = town.clip("banjo", 6, 5)
piano = town.clip("piano", 4, 6)
strings = town.clip("strings", 4, 3)
pulse = town.clip("pulse", 3, 5)
twang = town.clip("twang", 5, 5)
low_brass = town.clip("low_brass", 5, 4)
kit = town.clip("kit", 3, 6)
heavy_kit = town.clip("heavy_kit", 3, 6)

# ---- DRY DOCK (1-32): the town ------------------------------------------
DOCK = ["Am", "Am", "F", "G", "Am", "Am", "Dm", "E", "C", "G", "Am", "F", "Dm", "Am", "E", "E"]
for half in (0, 16):
    for i, chord in enumerate(DOCK):
        bar = 1 + half + i
        town.harmony[bar] = chord
        r = root(chord, 2)
        if r < midi("E2"):
            r += 12
        # Boom-chick: the bass string on 1 and 3, the chord on 2 and 4.
        upper = [p for p in tones(chord, 3) if p > r][:3]
        guitar.note(t(bar), 0.9, r, 84)
        guitar.note(t(bar, 1), 0.45, upper, 70)
        guitar.note(t(bar, 2), 0.9, r + 7 if r + 7 <= midi("B2") + 12 else r, 78)
        guitar.note(t(bar, 3), 0.45, upper, 68)
        guitar.note(t(bar, 3.5), 0.3, upper, 56)
        # The upright: root and fifth.
        b = root(chord, 1) if root(chord, 1) >= midi("E1") else root(chord, 2)
        bass.note(t(bar), 0.9, b, 88)
        bass.note(t(bar, 2), 0.9, b + 7, 78)
        # The clip-clop on the rim, a mule in no hurry.
        for beat, v in ((0, 70), (0.75, 52), (2, 66), (2.75, 50)):
            kit.note(t(bar, beat), 0.2, RIM, v)
        if half:
            kit.note(t(bar, 1), 0.2, HAT, 44)
            kit.note(t(bar, 3), 0.2, HAT, 44)
        # The Rhodes holds the chord, high and soft: the spaceport.
        if i % 2 == 0:
            rhodes.note(t(bar), 7.6, tones(chord, 4), 52 + (6 if half else 0))
# The saddle: the fiddle first, the trumpet answers it; the banjo rolls in the
# second half.
cell(fiddle, t(3), midi("A4"), SADDLE, SADDLE_RHYTHM, 86, stretch=1.0, legato=0.95)
cell(fiddle, t(7), midi("D5"), [0, -2, -4, -2, 2, -2], [1, 0.5, 0.5, 2, 2, 2], 82, legato=0.95)
cell(trumpet, t(11), midi("A4"), SADDLE, SADDLE_RHYTHM, 84, legato=0.9)
trumpet.note(t(13), 3.6, midi("A4"), 78)
trumpet.note(t(14), 1.8, midi("G4"), 74)
trumpet.note(t(14, 2), 1.8, midi("E4"), 70)
fiddle.note(t(15), 7.4, midi("G#4"), 74)
for bar in range(17, 33):
    chord = town.harmony[bar]
    roll = tones(chord, 4) + [tones(chord, 4)[0] + 12]
    for k in range(8):
        banjo.note(t(bar, 0.5 * k), 0.4, roll[[0, 1, 2, 3, 1, 2, 0, 3][k]], 64 if k % 2 else 72)
cell(fiddle, t(19), midi("A4"), SADDLE, SADDLE_RHYTHM, 88, legato=0.95)
cell(trumpet, t(23), midi("E5"), [0, -2, -4, -2, 0, 3, 5, 3, 0], SADDLE_RHYTHM, 82, legato=0.9)
cell(fiddle, t(27), midi("A4"), SADDLE, SADDLE_RHYTHM, 86, legato=0.95)
trumpet.note(t(31), 7.2, midi("B4"), 72)
fiddle.note(t(31), 7.2, midi("G#4"), 70)

# ---- WET WHISTLE (33-56): the saloon ------------------------------------
SALOON = ["C", "C", "A7", "A7", "Dm", "Dm", "G7", "G7", "C", "C7", "F", "F",
          "D7", "D7", "G7", "G7", "C", "E7", "Am", "A7", "Dm", "G7", "C", "G7"]
for i, chord in enumerate(SALOON):
    bar = 33 + i
    town.harmony[bar] = chord
    # Stride: the bass note low on 1 and 3, the chord in the middle on 2 and 4.
    low = root(chord, 2)
    if low > midi("G2"):
        low -= 12
    mid_chord = [p for p in tones(chord, 3) if p >= midi("E3")][:3] or tones(chord, 4)[:3]
    piano.note(t(bar), 0.8, [low, low + 12] if i % 2 == 0 else low + 7, 86)
    piano.note(t(bar, 1), 0.5, mid_chord, 72)
    piano.note(t(bar, 2), 0.8, low + 7 if i % 2 == 0 else [low, low + 12], 82)
    piano.note(t(bar, 3), 0.5, mid_chord, 70)
    # The walking bass.
    walk = [root(chord, 2), tones(chord, 2)[1], tones(chord, 2)[2], tones(chord, 2)[2] + 2]
    for k, p in enumerate(walk):
        bass.note(t(bar, k), 0.9, p if p >= midi("E1") else p + 12, 84 if k == 0 else 74)
    # Brushes: a swish on 2 and 4, a light ride.
    kit.note(t(bar, 1), 0.3, BRUSH, 46)
    kit.note(t(bar, 3), 0.3, BRUSH, 48)
    for beat in (0, 1, 1.66, 2, 3, 3.66):
        kit.note(t(bar, beat), 0.2, RIDE, 40 if beat % 1 else 50)
# The right hand: the saddle turned major, with a ragtime skip.
for bar, base in ((33, midi("C5")), (41, midi("C5")), (49, midi("E5"))):
    at = t(bar)
    for k, (step, span) in enumerate(zip(SADDLE_MAJOR, SADDLE_RHYTHM)):
        piano.note(at, span * 0.8, [base + step, base + step - 12] if k in (0, 3) else base + step, 90)
        if span >= 2:
            piano.note(at + 1.5, 0.4, base + step + 2, 70)
        at += span
for bar, run in ((37, [midi("A4"), midi("C#5"), midi("E5"), midi("G5")]), (45, [midi("D5"), midi("F#5"), midi("A5"), midi("C6")]),
                 (53, [midi("A4"), midi("C5"), midi("E5"), midi("A5")])):
    for k in range(8):
        piano.note(t(bar, 0.5 * k), 0.4, run[k % 4], 76)
    piano.note(t(bar + 1), 3.5, [run[0], run[2]], 80)
for bar in (39, 47):
    cell(piano, t(bar), midi("D5"), [0, 2, 4, 5, 7, 5, 4, 2], [0.5] * 8, 82)
    cell(piano, t(bar + 1), midi("G4"), [0, 4, 7, 11, 9, 7, 4, 2], [0.5] * 8, 80)
piano.note(t(55), 3.5, [midi("C5"), midi("E5"), midi("G5")], 84)
piano.note(t(56), 1.5, [midi("B4"), midi("D5"), midi("G5")], 78)
piano.note(t(56, 2), 1.5, [midi("F4"), midi("B4"), midi("D5")], 74)

# ---- REFINERY SHIFT (57-80): the refinery --------------------------------
WORKS = ["Am", "Am", "Bb", "Am", "Am", "Am", "G", "Bb"]
for block in range(3):
    for i, chord in enumerate(WORKS):
        bar = 57 + 8 * block + i
        town.harmony[bar] = chord
        # The heavy kit in half time: the kick on 1 and the and of 2, the
        # snare on 3, the hat as a machine.
        heavy_kit.note(t(bar), 0.4, KICK, 110)
        heavy_kit.note(t(bar, 1.5), 0.4, KICK, 92)
        heavy_kit.note(t(bar, 2), 0.4, SNARE, 108)
        if i == 7:
            for k in range(4):
                heavy_kit.note(t(bar, 3 + 0.25 * k), 0.2, TOM_HI if k < 2 else TOM_LO, 90 + 4 * k)
        for k in range(8):
            heavy_kit.note(t(bar, 0.5 * k), 0.2, RIDE_BELL if k % 4 == 2 else HAT, 66 if k % 2 == 0 else 48)
        # The pulse: effected strings in eighths on the root, the fifth on the off-beats.
        lo = root(chord, 3)
        for k in range(8):
            pulse.note(t(bar, 0.5 * k), 0.35, lo + (7 if k in (3, 6) else 0), 84 if k % 2 == 0 else 70)
        bass.note(t(bar), 1.8, root(chord, 1) if root(chord, 1) >= midi("E1") else root(chord, 2), 92)
        bass.note(t(bar, 2.5), 1.4, root(chord, 1) if root(chord, 1) >= midi("E1") else root(chord, 2), 84)
        if block > 0 and i % 2 == 0:
            strings.note(t(bar), 7.6, tones(chord, 4)[1:], 54 + 6 * block)
# The saddle in the low brass, slowed: the shift's work song.
for bar in (59, 67, 75):
    cell(low_brass, t(bar), midi("A2"), SADDLE, SADDLE_RHYTHM, 96, stretch=1.0, legato=0.94)
# The twang answers each time, up an octave and dry.
for bar in (63, 71):
    cell(twang, t(bar), midi("A3"), [0, 3, 5, 7, 10, 12, 10, 7], [0.5] * 8, 88, legato=0.7)
    cell(twang, t(bar + 1), midi("A3"), [12, 10, 7, 5, 3, 1, 0], [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0], 86, legato=0.7)
twang.note(t(79), 3.6, [midi("A3"), midi("E4")], 88)
twang.note(t(80), 3.6, [midi("Bb3"), midi("F4")], 86)

# ---- MESA TOP (81-96): after the fight ----------------------------------
MESA = ["Am7", "Fmaj7", "Cmaj7", "G", "Am7", "Fmaj7", "Dm", "E"]
for half in (0, 8):
    for i, chord in enumerate(MESA):
        bar = 81 + half + i
        town.harmony[bar] = chord
        # The guitar arpeggiates, open and slow.
        r = root(chord, 2)
        if r < midi("E2"):
            r += 12
        arp = [r] + [p for p in tones(chord, 3) if p > r][:3] + [tones(chord, 4)[0]]
        for k, idx in enumerate([0, 1, 2, 3, 4, 3, 2, 1]):
            guitar.note(t(bar, 0.5 * k), 1.4 if k == 0 else 0.9, arp[idx % len(arp)], 74 if k == 0 else 62)
        strings.note(t(bar), 3.9, tones(chord, 4)[:3], 46 + (6 if half else 0))
        bass.note(t(bar), 3.6, root(chord, 1) if root(chord, 1) >= midi("E1") else root(chord, 2), 72)
cell(trumpet, t(83), midi("A4"), SADDLE, [x * 1.5 for x in SADDLE_RHYTHM][:6] + [1.0, 1.0, 1.0], 70, legato=0.96)
cell(trumpet, t(91), midi("A4"), SADDLE[:4], [2, 1, 1, 8], 66, legato=0.97)
rhodes.note(t(89), 15.5, [midi("E5"), midi("A5")], 40)

town_shapes = {
    "dry_dock": "energy: 0.35, density: 0.45, loopable: true, role: 'the town: boom-chick guitar, the saddle on the fiddle and the trumpet'",
    "wet_whistle": "energy: 0.5, density: 0.55, loopable: true, role: 'the saloon: stride piano, the saddle turned major'",
    "refinery_shift": "energy: 0.65, density: 0.65, loopable: true, role: 'the refinery: half-time kit, string pulse, the saddle in the low brass'",
    "mesa_top": "energy: 0.2, density: 0.3, loopable: true, role: 'the mesa top: the guitar alone, a distant trumpet'",
}
town_form, town_play = form_and_playback(town, town_shapes, {"dry_dock", "wet_whistle", "refinery_shift", "mesa_top"})

COMMON_MASTER = """  master:
    chain:
      - {processor: highpass, cutoff_hz: 30}
      - processor: parametric_eq
        bands:
          - {type: peak, hz: 350, q: 0.8, db: -1.0}
      - {processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 120.0, makeup_db: 1.5, knee_db: 6.0}
      - {processor: reverb, wet: 0.05, decay_seconds: 1.6}
      - {processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}
  adaptive_sections:
    mode: composition_master"""

town_score = f"""schema: ambition.musicir.v3
id: leaden_saddle
title: The Leaden Saddle
description: >-
  The Frontier dimension: Dry Dock, a spaceport town in a desert pass. The
  town on a boom-chick guitar and a fiddle, the saloon's stride piano, the
  refinery's machine half-time, and the mesa top after the Marshal's fall,
  all on one motif, the saddle. Generated by dev/compose_leaden_saddle.py:
  edit that, not this file.
notes:
  - 'Jon, 2026-11-20: a western biome with its own music and a boss theme; a space western. The references were mood only.'
  - 'The saddle: A C D E, G E D C D. The saloon turns it major; the refinery slows it in the low brass.'
  - 'The game binds the sections to rooms (Ambition music_cues.ron): dry_dock (the pad, the street, the livery), wet_whistle (the saloon), refinery_shift (the refinery, the corral), mesa_top (the lookout).'
seed: {town.seed}
timebase: {{ppq: 960}}
meter: 4/4
tempo: {town.bpm}
key: {{tonic: A, mode: minor}}
end: {{bar: {town.end_bar}, beat: 1}}
form:
{town_form}
harmony:
  every_bars: 1
  cycle: false
  progression: [{harmony_list(town, "Am")}]
instruments:
  - {{name: guitar, group: guitar, program: steel_guitar, volume: 100, pan: 64, expression: 104, {sfz("guitar.acoustic", "controls: {100: 126}, ")}}}
  - {{name: fiddle, group: fiddle, program: violin, volume: 100, pan: 64, expression: 104, {sfz("strings.violin_solo")}}}
  - {{name: trumpet, group: trumpet, program: trumpet, volume: 100, pan: 64, expression: 106, {TRUMPET_SOLO}}}
  - {{name: rhodes, group: rhodes, program: electric_piano_1, volume: 96, pan: 64, expression: 100, {sfz("epiano.rhodes")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 106, pan: 64, expression: 108, {sfz("bass.upright")}}}
  - {{name: banjo, group: banjo, program: banjo, volume: 100, pan: 64, expression: 104, {sfz("folk.banjo")}}}
  - {{name: piano, group: piano, program: honky_tonk_piano, volume: 104, pan: 64, expression: 108, {sfz("freepats.upright_piano_kw")}}}
  - {{name: strings, group: strings, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1")}}}
  - {{name: pulse, group: pulse, program: string_ensemble_2, volume: 100, pan: 64, expression: 104, {sfz("strings.cyborg")}}}
  - {{name: twang, group: twang, program: clean_guitar, volume: 104, pan: 64, expression: 110, {SHINY}}}
  - {{name: low_brass, group: brass, program: trombone, volume: 104, pan: 64, expression: 108, {sfz("orchestra.trombones_sustain")}}}
  - {{name: kit, group: kit, volume: 112, pan: 64, expression: 112, is_drum: true, {sfz("drums.naked")}}}
  - {{name: heavy_kit, group: heavy_kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz("drums.big_rusty")}}}
parts:
{parts_yaml(town)}
processing:
  groups:
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 4.0}}
        - {{processor: balance, position: -0.3}}
    fiddle:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 11.0}}
        - {{processor: balance, position: 0.25}}
    trumpet:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 7.0}}
        - {{processor: balance, position: 0.15}}
    rhodes:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 1.0}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3500}}
        - {{processor: gain, gain_db: 5.0}}
    banjo:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 7.0}}
        - {{processor: balance, position: 0.35}}
    piano:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 3.0}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 4.0}}
    pulse:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 2.0}}
        - {{processor: balance, position: -0.2}}
    twang:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: 0.3}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 3.0}}
    kit:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 12.0}}
    heavy_kit:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 90.0}}
{COMMON_MASTER}
playback:
  full: true
  sections:
{town_play}
"""

# ===========================================================================
# MARSHAL GALLUS SHOWDOWN
# ===========================================================================
duel = Cue("marshal_gallus_showdown", 132, 1121, [
    ("standoff", 1, 8),
    ("duel", 9, 40),
    ("high_noon", 41, 56),
    ("sundown", 57, 66),
])
t = duel.t
d_trumpet = duel.clip("trumpet", 5, 4)
d_trumpets = duel.clip("trumpets", 5, 4)
d_twang = duel.clip("twang", 4, 5)
d_bass = duel.clip("bass", 4, 4)
d_tremolo = duel.clip("tremolo", 3, 3)
d_strings = duel.clip("strings", 4, 3)
d_cyborg = duel.clip("cyborg", 3, 5)
d_choir = duel.clip("choir", 4, 3)
d_piano = duel.clip("piano", 3, 3)
d_timpani = duel.clip("timpani", 3, 4)
d_kit = duel.clip("kit", 3, 6)
d_guitar = duel.clip("guitar", 7, 5)


def tim(pitch: int) -> int:
    """`pitch` folded into the sampled range of the catalog's timpani (F2-G3)."""
    while pitch < midi("F2"):
        pitch += 12
    while pitch > midi("G3"):
        pitch -= 12
    return pitch


def phrase(clip: Clip, bar: int, bars, vel: int, *, transpose: int = 0, legato: float = 0.92, accent: int = 6) -> None:
    """Play `bars` (lists of (note, beats)) from `bar`, `transpose` semitones up;
    the first note of each bar takes `accent`."""
    for k, notes in enumerate(bars):
        at = t(bar + k)
        for i, (name, beats) in enumerate(notes):
            if name is not None:
                clip.note(at, beats * legato, midi(name) + transpose, vel + (accent if i == 0 else 0))
            at += beats


# ---- STANDOFF (1-8) -----------------------------------------------------
for bar in range(1, 9):
    duel.harmony[bar] = "Em"
    d_tremolo.note(t(bar), 3.95, [midi("E4"), midi("B4")] if bar < 7 else [midi("D#4"), midi("B4")], 40 + 4 * bar)
    if bar % 2 == 1:
        d_piano.note(t(bar), 3.8, [midi("E1"), midi("E2")], 76)
# The strut's opening, slowed and alone: asked once, then again, hanging on
# the minor sixth (C) over the leading tone.
phrase(d_trumpet, 2, [[("B3", 2.0), ("G4", 2.0)], [("G4", 1.0), ("F#4", 1.0), ("G4", 2.0)]], 86, legato=0.96)
phrase(d_trumpet, 5, [[("B3", 2.0), ("G4", 2.0)], [("A4", 1.0), ("C5", 3.0)], [("B4", 4.0)]], 88, legato=0.97)
d_timpani.note(t(8), 0.5, tim(midi("B2")), 80)
for k in range(8):
    d_timpani.note(t(8, 2 + 0.25 * k), 0.2, tim(midi("E3")), 60 + 6 * k)

# ---- DUEL (9-40) ----------------------------------------------------------
DUEL = STRUT_A_HARMONY + STRUT_B_HARMONY


def gallop_bar(bar: int, chord: str, hot: bool = False):
    # The gallop: a hoof-beat on the snare (an eighth and two sixteenths).
    for beat in range(4):
        d_kit.note(t(bar, beat), 0.2, SNARE, 92 if beat in (1, 3) else 70)
        d_kit.note(t(bar, beat + 0.5), 0.1, SNARE, 58)
        d_kit.note(t(bar, beat + 0.75), 0.1, SNARE, 64)
    d_kit.note(t(bar), 0.4, KICK, 104)
    d_kit.note(t(bar, 2), 0.4, KICK, 96)
    for k in range(8 if not hot else 16):
        step = 0.5 if not hot else 0.25
        d_kit.note(t(bar, step * k), 0.1, HAT, 56 if k % 2 else 66)
    # The twang ostinato: the chord's root, its third, the root an octave
    # up, the fifth, in a figure that runs like the hoof-beat.
    r = root(chord, 3)
    if r > midi("B3"):
        r -= 12
    third = tones(chord, 3)[1] - tones(chord, 3)[0]
    for k, step_ in enumerate([0, 0, 12, 7, 0, third, 7, 12]):
        d_twang.note(t(bar, 0.5 * k), 0.32, r + step_, 92 if k % 4 == 0 else 76)
    b = root(chord, 1) if root(chord, 1) >= midi("E1") else root(chord, 2)
    d_bass.note(t(bar), 0.9, b, 96)
    d_bass.note(t(bar, 1.5), 0.4, b + 7, 80)
    d_bass.note(t(bar, 2), 0.9, b + 12 if b + 12 <= midi("E3") else b, 88)
    d_bass.note(t(bar, 3.5), 0.4, b + 7, 80)
    # The machinery: effected strings stab off the beat.
    d_cyborg.note(t(bar, 1.5), 0.3, tones(chord, 4), 76)
    d_cyborg.note(t(bar, 3.5), 0.3, tones(chord, 4), 72)


for half in (0, 16):
    for i, chord in enumerate(DUEL):
        bar = 9 + half + i
        duel.harmony[bar] = chord
        gallop_bar(bar, chord)
        if half:
            d_strings.note(t(bar), 3.9, tones(chord, 4)[:3], 60)
# The strut in the trumpets; its bridge on the solo trumpet. The second time
# the solo takes the strut over the section, and the choir holds under the
# bridge.
phrase(d_trumpets, 9, STRUT_A, 94, legato=0.9)
phrase(d_trumpet, 17, STRUT_B, 92, legato=0.93)
phrase(d_trumpet, 25, STRUT_A, 94, legato=0.92)
phrase(d_trumpets, 25, STRUT_A, 84, legato=0.9, accent=0)
phrase(d_trumpet, 33, STRUT_B, 94, legato=0.93)
for k, chord in enumerate(STRUT_B_HARMONY):
    if k % 2 == 0:
        d_choir.note(t(33 + k), 7.6, [p for p in tones(chord, 3)][:3], 84)
d_timpani.note(t(40, 3), 0.8, tim(midi("B2")), 104)

# ---- HIGH NOON (41-56): enraged, up a semitone -----------------------------
NOON = ["Fm", "Eb7", "Fm", "Dbmaj7", "Fm", "Bbm", "C7", "Fm",
        "Fm", "Eb7", "Fm", "Dbmaj7", "Fm", "Bbm", "C7", "C7"]
for i, chord in enumerate(NOON):
    bar = 41 + i
    duel.harmony[bar] = chord
    gallop_bar(bar, chord, hot=True)
    d_strings.note(t(bar), 3.9, tones(chord, 4), 76)
    d_timpani.note(t(bar), 0.6, tim(root(chord, 2)), 100)
    d_timpani.note(t(bar, 2), 0.6, tim(root(chord, 2) + 7), 90)
    if i % 2 == 0:
        d_choir.note(t(bar), 7.6, [p for p in tones(chord, 3)][1:] + [tones(chord, 3)[0] + 12], 96)
# The strut a semitone up, then its opening again and the bridge's high close,
# which ends on the dominant for the loop.
NOON_LINE = STRUT_A + STRUT_A[:4] + STRUT_B[4:]
phrase(d_trumpets, 41, NOON_LINE, 102, transpose=1, legato=0.9)
phrase(d_trumpet, 41, NOON_LINE[:8], 98, transpose=13, legato=0.9)
phrase(d_trumpet, 49, NOON_LINE[8:], 100, transpose=1, legato=0.92)
d_kit.note(t(56, 3), 0.6, CRASH, 110)

# ---- SUNDOWN (57-66): his defeat --------------------------------------------
SUN = ["Em", "Em", "C", "C", "Am", "Am", "B7", "B7", "E", "E"]
for i, chord in enumerate(SUN):
    bar = 57 + i
    duel.harmony[bar] = chord
    d_strings.note(t(bar), 3.95, tones(chord, 4)[:3], 50 if bar < 65 else 44)
    d_bass.note(t(bar), 3.8, root(chord, 1) if root(chord, 1) >= midi("E1") else root(chord, 2), 66)
# The strut slowed on the guitar; then the town's saddle; then the strut once
# more with its minor sixth turned major, at rest on E major.
phrase(d_guitar, 57, [[("B3", 2.0), ("G4", 2.0)], [("F#4", 1.0), ("G4", 3.0)],
                      [("A4", 1.0), ("D5", 2.0), ("C5", 1.0)], [("A4", 2.0), ("G4", 2.0)]], 80, legato=0.98, accent=0)
cell(d_guitar, t(61), midi("A3"), SADDLE, [1, 0.5, 0.5, 2, 1, 0.5, 0.5, 1, 1], 74, legato=0.98)
phrase(d_guitar, 63, [[("F#4", 2.0), ("D#4", 2.0)], [("B3", 4.0)]], 72, legato=0.98, accent=0)
d_guitar.note(t(65), 1.9, midi("B3"), 72)
d_guitar.note(t(65, 2), 5.5, [midi("E3"), midi("B3"), midi("E4"), midi("G#4")], 70)
d_trumpet.note(t(65, 2), 5.0, midi("G#4"), 36)

duel_shapes = {
    "standoff": "energy: 0.4, density: 0.25, role: 'the corral before the draw: tremolo strings, the strut on a lone trumpet'",
    "duel": "energy: 0.85, density: 0.75, loopable: true, role: 'the fight: the gallop, the twang ostinato, the strut in the trumpets'",
    "high_noon": "energy: 0.95, density: 0.85, loopable: true, role: 'enraged: F minor, the strut in the trumpets, choir, timpani'",
    "sundown": "energy: 0.2, density: 0.25, role: 'his defeat: the strut slowed on the guitar, its sixth turned major, into the saddle'",
}
duel_form, duel_play = form_and_playback(duel, duel_shapes, {"duel", "high_noon"})

duel_score = f"""schema: ambition.musicir.v3
id: marshal_gallus_showdown
title: Cock of the Walk
description: >-
  Marshal Gallus's fight in the Ore Corral: a standoff on a lone trumpet, the
  duel on a galloping snare and a twang ostinato under the strut, high noon a
  semitone up with a choir, and his fall, the strut slowed into the town's
  saddle motif.
  Generated by dev/compose_leaden_saddle.py: edit that, not this file.
notes:
  - 'Jon, 2026-11-20: a boss theme for the robot rooster marshal of the western biome. The references were mood only.'
  - 'The strut: B G F# G, A D C A F#: up a minor sixth from the fifth, a semitone dip, a fall through D7. Original (Jon, 2026-11-20, replacing the crow, which leaned on familiar western calls). The sundown section turns its sixth major and ends on E major.'
  - 'The game plays standoff as the intro, duel for phases 1 and 2, high_noon for the enrage, sundown at the defeat.'
seed: {duel.seed}
timebase: {{ppq: 960}}
meter: 4/4
tempo: {duel.bpm}
key: {{tonic: E, mode: minor}}
end: {{bar: {duel.end_bar}, beat: 1}}
form:
{duel_form}
harmony:
  every_bars: 1
  cycle: false
  progression: [{harmony_list(duel, "Em")}]
instruments:
  - {{name: trumpet, group: trumpet, program: trumpet, volume: 104, pan: 64, expression: 110, {TRUMPET_SOLO}}}
  - {{name: trumpets, group: brass, program: trumpet, volume: 100, pan: 64, expression: 108, {sfz("orchestra.trumpets_sustain")}}}
  - {{name: twang, group: twang, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 108, pan: 64, expression: 110, {sfz("bass.upright")}}}
  - {{name: tremolo, group: strings, program: tremolo_strings, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1")}}}
  - {{name: strings, group: strings, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_2")}}}
  - {{name: cyborg, group: cyborg, program: string_ensemble_2, volume: 100, pan: 64, expression: 104, {sfz("strings.cyborg")}}}
  - {{name: choir, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {sfz("vpo.choir_male")}}}
  - {{name: piano, group: piano, program: acoustic_grand_piano, volume: 100, pan: 64, expression: 104, {sfz("freepats.salamander_grand")}}}
  - {{name: timpani, group: timpani, volume: 110, pan: 64, expression: 112, is_drum: true, {sfz("orchestra.timpani")}}}
  - {{name: kit, group: kit, volume: 116, pan: 64, expression: 116, is_drum: true, {sfz("drums.naked")}}}
  - {{name: guitar, group: guitar, program: steel_guitar, volume: 100, pan: 64, expression: 104, {sfz("guitar.acoustic", "controls: {100: 126}, ")}}}
parts:
{parts_yaml(duel)}
processing:
  groups:
    trumpet:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.34, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 4.0}}
        - {{processor: balance, position: 0.1}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 13.0}}
        - {{processor: balance, position: -0.15}}
    twang:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: 0.3}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 3500}}
        - {{processor: gain, gain_db: 5.0}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 4.0}}
    cyborg:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 1.0}}
        - {{processor: balance, position: -0.3}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -1.0}}
    piano:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.0}}
    timpani:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 2.0}}
    kit:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.0, attack_ms: 10.0, release_ms: 90.0}}
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 10.0}}
{COMMON_MASTER}
playback:
  full: true
  sections:
{duel_play}
"""

for cue, text in ((town, town_score), (duel, duel_score)):
    path = OUT_DIR / f"{cue.id}.music.yaml"
    path.write_text(text)
    print(f"wrote {path}: {cue.end_bar - 1} bars, {(cue.end_bar - 1) * 4 * 60 / cue.bpm:.0f} s")

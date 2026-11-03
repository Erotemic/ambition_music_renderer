"""Yellow Earth, Long Sky: the History dimension's East Asia and steppe floor.
Writes its MusicIR v3 score:

    python3 dev/compose_history_east_asia_yellow_earth.py scores/active/history_east_asia_yellow_earth.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different locations
in the history dimension." The History dimension is a grid of rooms: each
column is an age, each floor is a region. This cue plays on every room of the
East Asia and steppe floor, west (oldest) to east: the Mammoth Steppe (Ice Age
hunters in the cold north), the Yellow River (the first millet farmers and
their painted pottery), the Shang Court (bronze, oracle bones, the first
Chinese writing), the Silk Road (caravans between East and West) and the
Mongol Steppe (horses and the great ger). One loop must suit all five ages and
sit under dialogue, so it is exploration music at mid energy.

G# minor pentatonic (the yu mode: G# B C# D# F#) at 84 BPM, 4/4. The melody
stays in the pentatonic set; the harmony under it uses the full G# minor
collection, so the tune is pentatonic but the music moves. Three places leave
that collection on purpose, for contrast:

  - THE BRONZE (the Shang court) moves the centre to C#, the shang mode of the
    same five notes, with open fifths and a borrowed A major for weight. It is
    still: no drum, bells on the half bar, the choir on a long chord.
  - THE CARAVAN (the Silk Road) borrows D natural (the flat second over C#)
    and A natural, a colour from further west, and walks.
  - THE GALLOP (the Mongol steppe) brings the theme back over celli staccato
    and a frame drum in a horse-gait rhythm (long, short, short), with a
    plucked bass tagelharpa on the strong beats.

The Dan Tranh zither (a zither like the guzheng) is sampled in its own B
pentatonic tuning, which is the G# yu set, so its open strings are the tune's
notes and its glissandi fit every pentatonic bar. The VCSL ocarina stands in
for the xun, the clay vessel flute of the Yellow River villages. All melodies
are original.

Form, 4/4 at 84 BPM, 64 bars (about 3:03), the whole cue loops (dusk ends on
F#sus2, as the sky does, and hands to G# minor at bar 1):

  section  bars   room it suits       texture
  sky      1-8    the Mammoth Steppe  choir hum, zither tremolo, bowed psaltery, the ocarina's call
  loess    9-24   the Yellow River    the theme on the ocarina over zither arpeggios and celli
  bronze   25-32  the Shang Court     C# shang mode: tubular bells, hand chimes, gong, choir; still
  caravan  33-40  the Silk Road       the zither leads, frame drum lilt, a walking bass, D natural
  gallop   41-56  the Mongol Steppe   the theme again over a galloping bass and frame drum
  dusk     57-64  any                 the theme head slowed on the zither, a glissando, the hum
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 84
OUT = Path(sys.argv[1])
rng = random.Random(1600)  # Shang bronze: about 1600 BCE

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "B#": 0}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    value = 12 * (octave + 1) + NOTE[pitch]
    return value + 12 if pitch == "B#" else value


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


def T(n: int) -> float:
    """The first beat of bar n, in beats."""
    return (n - 1) * 4.0


ocarina = Clip(0.006, 3)
psaltery = Clip(0.006, 2)
zither = Clip(0.004, 4)
zither_lead = Clip(0.004, 3)
zither_trem = Clip(0.004, 2)
zither_gliss = Clip()
tagel = Clip(0.003, 4)
gait = Clip(0.003, 4)
celli = Clip(0.006, 2)
choir = Clip(0.008, 2)
bells = Clip(0.003, 3)
chimes = Clip(0.004, 3)
handbells = Clip(0.004, 4)
gong = Clip()
drum = Clip(0.004, 5)
harmony: dict[int, str] = {}

# ---- Harmony ---------------------------------------------------------------------------
#: (bass pitch class, chord tones low to high round G#3-G#4). The zither, celli and choir take their notes from here.
CHORDS = {
    "G#m": ("G#", ["G#3", "B3", "D#4", "G#4"]),
    "G#m/F#": ("F#", ["F#3", "B3", "D#4", "G#4"]),
    "G#m/B": ("B", ["B3", "D#4", "G#4", "B4"]),
    "Emaj7": ("E", ["E3", "G#3", "B3", "D#4"]),
    "Emaj7/G#": ("G#", ["E3", "G#3", "B3", "D#4"]),
    "Eadd9": ("E", ["E3", "B3", "F#4", "G#4"]),
    "C#m7": ("C#", ["G#3", "B3", "C#4", "E4"]),
    "C#m9": ("C#", ["E3", "G#3", "B3", "D#4"]),
    "F#": ("F#", ["F#3", "A#3", "C#4", "F#4"]),
    "F#6": ("F#", ["F#3", "A#3", "C#4", "D#4"]),
    "F#sus4": ("F#", ["F#3", "B3", "C#4", "F#4"]),
    "F#sus2": ("F#", ["F#3", "G#3", "C#4", "F#4"]),
    "D#m7": ("D#", ["A#3", "C#4", "D#4", "F#4"]),
    "C#5": ("C#", ["G#3", "C#4", "D#4", "G#4"]),
    "Asus2": ("A", ["A3", "B3", "E4", "A4"]),
    "G#sus4": ("G#", ["G#3", "C#4", "D#4", "G#4"]),
    "G#": ("G#", ["G#3", "B#3", "D#4", "G#4"]),
    "Dmaj7": ("D", ["A3", "C#4", "D4", "F#4"]),
    "Bm7": ("B", ["A3", "B3", "D4", "F#4"]),
    "A": ("A", ["A3", "C#4", "E4", "A4"]),
}
SKY_CH = ["G#m", "G#m", "Emaj7/G#", "Emaj7/G#", "G#m", "G#m", "F#sus2", "F#sus2"]
LOESS_A = ["G#m", "G#m/F#", "Emaj7", "C#m7", "G#m/B", "F#", "C#m9", "D#m7"]
LOESS_B = ["Emaj7", "F#6", "D#m7", "G#m", "C#m9", "Eadd9", "F#sus4", "F#"]
BRONZE_CH = ["C#5", "C#5", "Asus2", "Asus2", "F#sus2", "F#sus2", "G#sus4", "G#"]
CARAVAN_CH = ["C#m7", "Dmaj7", "C#m7", "Dmaj7", "Bm7", "A", "F#sus4", "F#"]
DUSK_CH = ["Emaj7", "Emaj7", "G#m", "G#m", "C#m9", "Eadd9", "F#sus2", "F#sus2"]


def in_range(pc: str, lo: int) -> int:
    """The lowest note of pitch class pc at or above midi lo."""
    n = NOTE[pc]
    return lo + (n - lo) % 12


def tones(chord: str) -> list[int]:
    return [midi(x) for x in CHORDS[chord][1]]


def bass_pc(chord: str) -> str:
    return CHORDS[chord][0]


def fifth_of(pc: str) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return names[(NOTE[pc] + 7) % 12]


# ---- Tunes -----------------------------------------------------------------------------
#: The loess theme, phrase A, one bar per chord of LOESS_A: (beat, duration, note). A rising call, a long fall.
THEME_A = [
    [(0.0, 1.5, "D#5"), (1.5, 0.5, "F#5"), (2.0, 2.0, "G#5")],
    [(0.0, 1.5, "B5"), (1.5, 0.5, "G#5"), (2.0, 2.0, "F#5")],
    [(0.0, 3.0, "D#5"), (3.0, 0.5, "F#5"), (3.5, 0.5, "D#5")],
    [(0.0, 2.0, "C#5"), (2.0, 1.0, "B4"), (3.0, 1.0, "C#5")],
    [(0.0, 1.5, "D#5"), (1.5, 0.5, "F#5"), (2.0, 1.5, "G#5"), (3.5, 0.5, "B5")],
    [(0.0, 3.0, "C#6"), (3.0, 1.0, "B5")],
    [(0.0, 1.5, "G#5"), (1.5, 0.5, "F#5"), (2.0, 2.0, "D#5")],
    [(0.0, 1.0, "F#5"), (1.0, 2.5, "D#5")],
]
#: Phrase B, one bar per chord of LOESS_B: it climbs to C#6, touches A#5 and settles on the sus4 to 3 of F#.
THEME_B = [
    [(0.0, 2.0, "G#5"), (2.0, 1.0, "B5"), (3.0, 1.0, "C#6")],
    [(0.0, 2.0, "C#6"), (2.0, 1.0, "B5"), (3.0, 1.0, "G#5")],
    [(0.0, 2.0, "A#5"), (2.0, 1.0, "G#5"), (3.0, 1.0, "F#5")],
    [(0.0, 2.5, "G#5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "D#5")],
    [(0.0, 2.0, "D#5"), (2.0, 1.0, "C#5"), (3.0, 1.0, "B4")],
    [(0.0, 1.0, "B4"), (1.0, 1.0, "C#5"), (2.0, 2.0, "F#5")],
    [(0.0, 3.0, "B5"), (3.0, 1.0, "G#5")],
    [(0.0, 3.5, "A#5")],
]
#: The gallop's phrase A ends with a pickup into phrase B instead of a held D#: up to A#, a step over phrase B's G#.
THEME_A_PICKUP = [(0.0, 1.0, "F#5"), (1.0, 1.5, "D#5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "A#5")]
#: The psaltery's held line under phrase B in the gallop: chord tones under the tune, inside its sampled G4-G6.
PSALTERY_B = ["B4", "A#4", "C#5", "B4", "G#4", "G#4", "C#5", "C#5"]
#: The ocarina's call in the sky: the theme's head, before the theme.
SKY_CALL = {
    5: [(2.0, 1.5, "D#5"), (3.5, 0.5, "F#5")],
    6: [(0.0, 3.0, "G#5")],
    7: [(1.0, 1.0, "F#5"), (2.0, 2.0, "G#5")],
    8: [(0.0, 2.5, "C#5")],
}
#: The bronze bells: the theme's head transposed to the C# shang centre, two notes a bar.
BRONZE_BELLS = [
    [(0.0, 2.0, "G#4"), (2.0, 2.0, "C#5")],
    [(0.0, 2.0, "B4"), (2.0, 2.0, "G#4")],
    [(0.0, 2.0, "B4"), (2.0, 2.0, "E4")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "B4")],
    [(0.0, 2.0, "G#4"), (2.0, 2.0, "C#5")],
    [(0.0, 2.0, "F#4"), (2.0, 2.0, "G#4")],
    [(0.0, 2.0, "D#5"), (2.0, 2.0, "C#5")],
    [(0.0, 2.0, "D#5"), (2.0, 2.0, "B#4")],
]
#: The caravan tune on the zither: eighths and quarters, with the borrowed D natural.
CARAVAN_TUNE = [
    [(0.0, 0.5, "G#4"), (0.5, 0.5, "B4"), (1.0, 1.0, "C#5"), (2.0, 0.5, "E5"), (2.5, 0.5, "C#5"), (3.0, 1.0, "B4")],
    [(0.0, 1.5, "A4"), (1.5, 0.5, "C#5"), (2.0, 1.0, "D5"), (3.0, 0.5, "E5"), (3.5, 0.5, "F#5")],
    [(0.0, 1.5, "E5"), (1.5, 0.5, "D5"), (2.0, 2.0, "C#5")],
    [(0.0, 0.5, "F#5"), (0.5, 0.5, "E5"), (1.0, 1.0, "D5"), (2.0, 1.0, "A4"), (3.0, 1.0, "C#5")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "E5"), (2.0, 1.0, "F#5"), (3.0, 1.0, "A5")],
    [(0.0, 2.0, "E5"), (2.0, 0.5, "C#5"), (2.5, 0.5, "E5"), (3.0, 1.0, "A5")],
    [(0.0, 1.5, "G#5"), (1.5, 0.5, "F#5"), (2.0, 2.0, "C#5")],
    [(0.0, 1.0, "A#4"), (1.0, 1.0, "C#5"), (2.0, 2.0, "F#5")],
]
#: The ocarina's held counter-line in the second half of the caravan.
CARAVAN_OCARINA = ["F#5", "E5", "C#6", "A#5"]
#: Dusk: the theme's head at half speed on the zither, tremolo on the long notes.
DUSK_LINE = [
    [(0.0, 2.0, "D#5"), (2.0, 2.0, "F#5")],
    [(0.0, 4.0, "G#5")],
    [(0.0, 2.0, "F#5"), (2.0, 2.0, "D#5")],
    [(0.0, 4.0, "B4")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "D#5")],
    [(0.0, 4.0, "B4")],
]


def sing(clip: Clip, n0: int, phrase, vel=90, octave=0, legato=0.96):
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            held = dur >= 1.5
            clip.note(T(n0 + k) + at, dur * (legato if held else 0.9), midi(name) + 12 * octave,
                      vel + (5 if held else 0))


def pluck_line(n0: int, phrase, vel: int):
    """The zither lead: a plucked note, and a tremolo under any note of two beats or more so it sustains."""
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            zither_lead.note(T(n0 + k) + at, min(dur, 2.0) * 0.95, midi(name), vel + (6 if at == 0 else 0))
            if dur >= 2.0:
                zither_trem.note(T(n0 + k) + at + 0.25, dur - 0.35, midi(name), vel - 18)


# ---- Beds ------------------------------------------------------------------------------
def zither_flow(n: int, chord: str, vel: int):
    """Eighth notes up through the chord and back: low root, fifth, then the voicing, like a guzheng's open strings."""
    root = in_range(bass_pc(chord), 47)  # the Dan Tranh's lowest string is B2
    t = tones(chord)
    pool = sorted({p for p in t + [x + 12 for x in t] if root + 7 < p <= 84})[:4]
    order = [root, root + 7] + pool + pool[-2::-1][:2]
    for i, p in enumerate(order):
        # Each string rings over the next ones, but not over the next chord.
        zither.note(T(n) + 0.5 * i, min(1.6, 3.9 - 0.5 * i), p, vel + (8 if i == 0 else 0) - (5 if i % 2 else 0))


def zither_gallop(n: int, chord: str, vel: int):
    """The gallop bed: chord tones on each eighth, the root and fifth pairs on the beat."""
    t = tones(chord)
    for beat in range(4):
        zither.note(T(n) + beat, 0.9, [t[0], t[2]], vel + (6 if beat in (0, 2) else 0))
        zither.note(T(n) + beat + 0.5, 0.45, t[3] if beat % 2 == 0 else t[1], vel - 10)


def celli_bar(n: int, chord: str, vel: int, bars: int = 1):
    root = in_range(bass_pc(chord), 40)
    celli.note(T(n), 4.0 * bars - 0.15, [root, root + 7], vel)


def choir_bar(n: int, chord: str, vel: int, bars: int = 1, end_early: float = 0.0):
    """A hum on the root and fifth, inside the male choir's sampled G2-F#4."""
    root = in_range(bass_pc(chord), 44)
    fifth = in_range(fifth_of(bass_pc(chord)), root + 1)
    choir.note(T(n) + 0.05, 4.0 * bars - 0.25 - end_early, [root, fifth], vel)


# The Horse Pulse samples are a folk instrument's own tuning, and its other strings ring in every sample (peaks
# near 208, 222 and 262 Hz whatever the key). Measured from the harmonics of every round robin (2026-11-03), keys
# 39, 41, 43, 48, 49, 63 and 65 are 50 to 110 cents from their names or differ between round robins. So the
# tagelharpa only thumps the low note on the strong beats, on the other keys, and TAGEL_TUNING corrects the steady
# offsets of the keys it uses. The pitched gait is the celli staccato, which is in tune.
#: For each bass pitch class, its key on the tagelharpa. A C# chord takes its fifth, G#2: the C#3 key is out of tune.
TAGEL_LOW = {"G#": 44, "F#": 42, "E": 40, "D#": 51, "C#": 44, "B": 47, "A": 45, "D": 38}
#: Cents to add at each key: the negative of the measured median offset.
TAGEL_TUNING = {38: 12, 40: 4, 42: 34, 44: -5, 45: 35, 47: 10, 51: -2}


def tagel_root(chord: str) -> int:
    return TAGEL_LOW[bass_pc(chord)]


def tagel_thump(n: int, chord: str, vel: int):
    """The tagelharpa's pluck on one and three."""
    low = tagel_root(chord)
    tagel.note(T(n), 0.9, low, vel)
    tagel.note(T(n) + 2, 0.9, low, vel - 8)


def gait_walk(n: int, chord: str, vel: int):
    """The caravan's walk on the celli staccato: root, fifth, octave, fifth."""
    root = in_range(bass_pc(chord), 40)
    for beat, p in enumerate((root, root + 7, root + 12, root + 7)):
        gait.note(T(n) + beat, 0.45, p, vel + (8 if beat == 0 else 0) - (6 if beat % 2 else 0))


def gait_gallop(n: int, chord: str, vel: int, last: bool = False):
    """Long, short, short on each beat: the horse's gait. The fourth beat climbs to the octave."""
    root = in_range(bass_pc(chord), 40)
    for beat in range(4):
        if last and beat == 3:
            gait.note(T(n) + beat, 0.45, root + 12, vel)
            break
        top = root + 12 if beat == 3 else root + 7
        gait.note(T(n) + beat, 0.4, root, vel + (10 if beat in (0, 2) else 2))
        gait.note(T(n) + beat + 0.5, 0.2, root, vel - 12)
        gait.note(T(n) + beat + 0.75, 0.2, top, vel - 8)


# The VCSL frame drum: 60 large, hand; 61 large, stick hit; 62 large, muted; 63 small, hand; 64 small, hit; 65 small, muted.
BIG_HAND, BIG, BIG_MUTE, SMALL_HAND, SMALL, SMALL_MUTE = 60, 61, 62, 63, 64, 65


def drum_heartbeat(n: int, vel: int):
    drum.note(T(n), 0.5, BIG_MUTE, vel)
    drum.note(T(n) + 2.5, 0.5, BIG_MUTE, vel - 16)


def drum_caravan(n: int, vel: int):
    """A walking lilt: the big drum on one and three, the small drum skipping between."""
    for at, key, dv in ((0, BIG, 8), (1.5, SMALL_HAND, -10), (2.0, BIG_MUTE, -4), (3.0, SMALL, -6), (3.5, SMALL_MUTE, -14)):
        drum.note(T(n) + at, 0.4, key, vel + dv)


def drum_gallop(n: int, vel: int, fill: bool = False):
    for beat in range(4):
        drum.note(T(n) + beat, 0.4, BIG if beat in (0, 2) else BIG_MUTE, vel + (8 if beat == 0 else 0))
        if fill and beat >= 2:
            for i in (1, 2, 3):
                drum.note(T(n) + beat + 0.25 * i, 0.2, SMALL, vel - 12 + 3 * i)
        else:
            drum.note(T(n) + beat + 0.5, 0.2, SMALL, vel - 14)
            drum.note(T(n) + beat + 0.75, 0.2, SMALL_MUTE, vel - 18)


GONG, GONG_2 = 60, 61


# ---- Sky, 1-8: the Mammoth Steppe ---------------------------------------------------------
for k, chord in enumerate(SKY_CH):
    harmony[1 + k] = chord
choir_bar(1, "G#m", 58, bars=2)
choir_bar(3, "Emaj7/G#", 58, bars=2)
choir_bar(5, "G#m", 62, bars=2)
choir_bar(7, "F#sus2", 62, bars=2)
for n, notes, vel in ((1, ["G#3", "D#4"], 70), (3, ["E3", "B3"], 66), (5, ["G#3", "D#4"], 72), (7, ["F#3", "C#4"], 70)):
    zither_trem.note(T(n) + 0.1, 7.6, [midi(x) for x in notes], vel)
psaltery.note(T(2), 6.0, midi("D#6"), 58)
psaltery.note(T(6) + 1.0, 6.5, midi("B5"), 60)
chimes.note(T(4) + 2.0, 3.0, midi("G#5"), 56)
chimes.note(T(8) + 1.0, 2.5, midi("C#6"), 52)
for n in (5, 6, 7, 8):
    drum_heartbeat(n, 84 + 3 * (n - 5))
for n, notes in SKY_CALL.items():
    for at, dur, name in notes:
        ocarina.note(T(n) + at, dur * 0.95, midi(name), 80)
zither_gliss.note(T(8) + 2.0, 4.0, 64, 70)  # an upward glissando into the theme

# ---- Loess, 9-24: the Yellow River --------------------------------------------------------
for k, chord in enumerate(LOESS_A + LOESS_B):
    n = 9 + k
    harmony[n] = chord
    second = k >= 8
    zither_flow(n, chord, 70 if not second else 74)
    celli_bar(n, chord, 62 if not second else 68)
    if second:
        choir_bar(n, chord, 56)
sing(ocarina, 9, THEME_A, vel=86)
sing(ocarina, 17, THEME_B, vel=90)
for k, name in enumerate(PSALTERY_B):
    if k % 2 == 0:  # a softer echo of the gallop's held line: every other bar
        psaltery.note(T(17 + k), 3.8, midi(name), 56)
drum_heartbeat(23, 84)
drum_heartbeat(24, 90)

# ---- Bronze, 25-32: the Shang court -------------------------------------------------------
for k, chord in enumerate(BRONZE_CH):
    n = 25 + k
    harmony[n] = chord
    for at, dur, name in BRONZE_BELLS[k]:
        bells.note(T(n) + at, dur, midi(name), 76 if at == 0 else 66)
    if k % 2 == 0 and k < 6:
        root = in_range(bass_pc(chord), 47)
        zither.note(T(n), 7.5, [root, root + 7], 74)
    if k in (1, 3, 5):
        chimes.note(T(n) + 3.0, 1.0, midi(BRONZE_BELLS[k][0][2]) + 12, 50)
choir_bar(25, "C#5", 64, bars=2)
choir_bar(27, "Asus2", 64, bars=2)
choir_bar(29, "F#sus2", 66, bars=2)
choir_bar(31, "G#sus4", 66)
choir_bar(32, "G#", 64)
celli_bar(25, "C#5", 64, bars=2)
celli_bar(27, "Asus2", 64, bars=2)
celli_bar(29, "F#sus2", 64, bars=2)
celli_bar(31, "G#sus4", 62)
celli_bar(32, "G#", 66)
zither.note(T(31), 3.8, [midi("G#3"), midi("D#4")], 66)
zither.note(T(32), 3.8, [midi("G#3"), midi("B#3"), midi("D#4")], 68)
gong.note(T(25), 7.0, GONG, 88)
gong.note(T(29), 7.0, GONG_2, 64)
psaltery.note(T(29), 7.6, midi("C#6"), 52)

# ---- Caravan, 33-40: the Silk Road --------------------------------------------------------
for k, chord in enumerate(CARAVAN_CH):
    n = 33 + k
    harmony[n] = chord
    gait_walk(n, chord, 80)
    tagel_thump(n, chord, 80)
    drum_caravan(n, 70)
    celli_bar(n, chord, 60)
    # The Nepalese bells are not tuned to a scale: key 61 sounds near E5, key 62 near D5 and F#4.
    handbells.note(T(n), 1.0, 62 if chord in ("Dmaj7", "Bm7") else 61, 58 if k % 2 == 0 else 48)
    if k >= 4:
        ocarina.note(T(n) + 0.1, 3.7, midi(CARAVAN_OCARINA[k - 4]), 62)
pluck_line(33, CARAVAN_TUNE, 84)
zither_gliss.note(T(40) + 2.0, 6.0, 64, 92)  # the glissando that launches the gallop

# ---- Gallop, 41-56: the Mongol steppe -----------------------------------------------------
for k, chord in enumerate(LOESS_A + LOESS_B):
    n = 41 + k
    harmony[n] = chord
    gait_gallop(n, chord, 90, last=k == 15)
    tagel_thump(n, chord, 90)
    drum_gallop(n, 80, fill=k in (7, 15))
    zither_gallop(n, chord, 68)
    celli_bar(n, chord, 72)
    choir_bar(n, chord, 66 if k < 8 else 72)
sing(ocarina, 41, THEME_A[:7] + [THEME_A_PICKUP], vel=94)
sing(ocarina, 49, THEME_B, vel=98)
for k, name in enumerate(PSALTERY_B):
    psaltery.note(T(49 + k) + 0.05, 3.8, midi(name), 64)
bells.note(T(41), 4.0, midi("G#4"), 74)
bells.note(T(49), 4.0, midi("B4"), 72)

# ---- Dusk, 57-64: back to the sky ---------------------------------------------------------
for k, chord in enumerate(DUSK_CH):
    n = 57 + k
    harmony[n] = chord
    if k < 6:
        celli_bar(n, chord, 60 - 2 * k)
choir_bar(57, "Emaj7", 60, bars=2)
choir_bar(59, "G#m", 58, bars=2)
choir_bar(61, "C#m9", 58)
choir_bar(62, "Eadd9", 56)
choir_bar(63, "F#sus2", 56, bars=2, end_early=0.5)  # ends before the seam, so bar 1's hum is the only attack
zither_gliss.note(T(57), 6.0, 63, 66)  # a slow swell down from the gallop
pluck_line(57, DUSK_LINE, 84)
zither_trem.note(T(63) + 0.1, 7.0, [midi("F#3"), midi("C#4")], 62)
chimes.note(T(60) + 2.0, 3.0, midi("D#6"), 50)
psaltery.note(T(62), 6.5, midi("G#5"), 52)

END_BAR = 65
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def curve(points: dict[int, float]) -> str:
    body = ", ".join(f"{k}: {v}" for k, v in sorted(points.items()))
    return f"tuning_correction: {{mode: curve, interpolation: linear, max_abs_cents: 50, points: {{{body}}}}}, "


# The Dan Tranh samples carry the instrument's own tuning (generated with --notuning). Measured from the
# samples (2026-11-03): the Normal C#4 string (keys 61-62) is 40-48 cents sharp at every velocity, the C#3, D#3
# and G#3 strings 18 sharp at the f layer (the first render measured G#3 30 sharp), and three Tremolo strings
# are 20-38 cents off. Each map pins the keys round a bad string so the others stay at 0.
ZITHER_TUNING = {47: 0, 48: 0, 49: -15, 52: -15, 53: 0, 55: 0, 56: -18, 57: -18, 58: 0, 60: 0, 61: -42, 62: -42,
                 63: 0, 84: 0}
TREMOLO_TUNING = {47: 0, 52: 0, 53: 20, 55: 20, 56: -6, 57: -6, 58: 0, 60: 0, 61: 30, 62: 30, 63: -15, 64: -15,
                  65: 0, 79: 0, 80: -38, 81: -38, 82: 0}
# Tubular Bells 1: the F#4 and G#4 bells (keys 65-69) measure 22 cents flat in the samples and 28 in the render.
BELL_TUNING = {64: 0, 65: 20, 69: 20, 70: 0}


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


score = f"""schema: ambition.musicir.v3
id: history_east_asia_yellow_earth
title: Yellow Earth, Long Sky
description: >-
  The History dimension's East Asia and steppe floor, from the Ice Age
  mammoth steppe to the Mongol steppe: G# minor pentatonic at 84 BPM. An
  ocarina (standing in for the xun, the clay flute of the Yellow River
  villages) has a long-breathed theme over a Dan Tranh zither in its own
  pentatonic tuning, celli and a humming male choir. The Shang court is
  still and ceremonial in the C# shang mode with tubular bells, hand chimes
  and a gong; the Silk Road borrows D natural and walks; the Mongol steppe
  gallops on celli staccato, a frame drum and a plucked bass tagelharpa. The whole cue
  loops. Generated by dev/compose_history_east_asia_yellow_earth.py: edit
  that, not this file.
notes:
  - 'Form: sky 1-8, loess 9-24, bronze 25-32, caravan 33-40, gallop 41-56, dusk 57-64; dusk ends on F#sus2 and hands to G# minor at bar 1.'
  - 'Layered for a room: bed (zither, celli, choir, tagelharpa, celli staccato), drums (frame drum, gong), tune (ocarina, zither lead, psaltery, bells).'
seed: 1600
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: G# minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: sky, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.3, density: 0.3, loopable: true, role: 'the Mammoth Steppe: hum, tremolo, the ocarina calls'}}
  - {{id: loess, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.5, density: 0.55, loopable: true, role: 'the Yellow River: the theme over zither and celli'}}
  - {{id: bronze, from: {{bar: 25, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.4, density: 0.35, loopable: true, role: 'the Shang court: bells, gong, choir, still'}}
  - {{id: caravan, from: {{bar: 33, beat: 1}}, to: {{bar: 41, beat: 1}}, energy: 0.6, density: 0.6, loopable: true, role: 'the Silk Road: the zither leads, the drum walks'}}
  - {{id: gallop, from: {{bar: 41, beat: 1}}, to: {{bar: 57, beat: 1}}, energy: 0.8, density: 0.85, loopable: true, role: 'the Mongol steppe: the theme over a gallop'}}
  - {{id: dusk, from: {{bar: 57, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'the theme slowed, back to the sky'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: ocarina, group: ocarina, program: ocarina, volume: 104, pan: 64, expression: 108, {vcsl("Aerophones/Edge-blown Aerophones/Ocarina, Typical - SusVib")}}}
  - {{name: psaltery, group: psaltery, program: violin, volume: 100, pan: 64, expression: 104, {vcsl("Chordophones/Zithers/Psaltery, Bowed and Plucked - LongBow")}}}
  - {{name: zither, group: zither, program: koto, volume: 104, pan: 64, expression: 108, {curve(ZITHER_TUNING)}{vcsl("Chordophones/Zithers/Dan Tranh - Normal")}}}
  - {{name: zither_trem, group: zither, program: koto, volume: 100, pan: 64, expression: 104, {curve(TREMOLO_TUNING)}{vcsl("Chordophones/Zithers/Dan Tranh - Tremolo")}}}
  - {{name: zither_gliss, group: zither, program: koto, volume: 100, pan: 64, expression: 104, {vcsl("Chordophones/Zithers/Dan Tranh - Gliss")}}}
  - {{name: zither_lead, group: zither_lead, program: koto, volume: 106, pan: 64, expression: 110, {curve(ZITHER_TUNING)}{vcsl("Chordophones/Zithers/Dan Tranh - Normal")}}}
  - {{name: tagel, group: tagel, program: acoustic_bass, volume: 110, pan: 64, expression: 112, {curve(TAGEL_TUNING)}instrument_backend: {{kind: sfz, sfz_glob: '**/HorsePulse/Programs/03-pluck.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: celli, group: strings, program: cello, volume: 100, pan: 64, expression: 104, {sfz("strings.celli")}}}
  - {{name: gait, group: gait, program: cello, volume: 104, pan: 64, expression: 108, {sfz("strings.celli_staccato")}}}
  - {{name: choir, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {sfz("vpo.choir_male")}}}
  - {{name: bells, group: bells, program: tubular_bells, volume: 100, pan: 64, expression: 104, {curve(BELL_TUNING)}{vcsl("Idiophones/Struck Idiophones/Tubular Bells 1")}}}
  - {{name: chimes, group: bells, program: tubular_bells, volume: 100, pan: 64, expression: 104, {vcsl("Idiophones/Struck Idiophones/Hand Chimes")}}}
  - {{name: handbells, group: bells, program: tinkle_bell, volume: 96, pan: 64, expression: 100, {vcsl("Idiophones/Struck Idiophones/Hand Bells, Nepalese")}}}
  - {{name: gong, group: gong, is_drum: true, volume: 100, pan: 64, expression: 104, {vcsl("Idiophones/Struck Idiophones/Gong 1")}}}
  - {{name: drum, group: drums, is_drum: true, volume: 110, pan: 64, expression: 112, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
parts:
{part("ocarina_part", "ocarina", ocarina)}
{part("psaltery_part", "psaltery", psaltery)}
{part("zither_part", "zither", zither)}
{part("zither_trem_part", "zither_trem", zither_trem)}
{part("zither_gliss_part", "zither_gliss", zither_gliss)}
{part("zither_lead_part", "zither_lead", zither_lead)}
{part("tagel_part", "tagel", tagel)}
{part("celli_part", "celli", celli)}
{part("gait_part", "gait", gait)}
{part("choir_part", "choir", choir)}
{part("bells_part", "bells", bells)}
{part("chimes_part", "chimes", chimes)}
{part("handbells_part", "handbells", handbells)}
{part("gong_part", "gong", gong)}
{part("drum_part", "drum", drum)}
processing:
  groups:
    ocarina:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 15.0, release_ms: 120.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 4.0}}
        - {{processor: balance, position: 0.1}}
    psaltery:
      chain:
        - {{processor: highpass, cutoff_hz: 250}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.38, decay_seconds: 3.4}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: 0.3}}
    zither:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 8.0, release_ms: 110.0}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: -0.2}}
    zither_lead:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 2.2, attack_ms: 6.0, release_ms: 100.0}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 10.0}}
        - {{processor: balance, position: 0.05}}
    tagel:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.4, attack_ms: 10.0, release_ms: 90.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: -3.0}}
    gait:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.2, attack_ms: 8.0, release_ms: 90.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: -0.15}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: -0.1}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - {{processor: reverb, wet: 0.34, decay_seconds: 3.2}}
        - {{processor: gain, gain_db: 0.0}}
    bells:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.34, decay_seconds: 3.4}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: 0.2}}
    gong:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.4}}
        - {{processor: gain, gain_db: 5.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: compressor, threshold_db: -18.0, ratio: 2.0, attack_ms: 15.0, release_ms: 90.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 0.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [zither, strings, choir, tagel, gait]
    drums: [drums, gong]
    tune: [ocarina, zither_lead, psaltery, bells]
  sections:
    - {{id: song, form: [sky, loess, bronze, caravan, gallop, dusk], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

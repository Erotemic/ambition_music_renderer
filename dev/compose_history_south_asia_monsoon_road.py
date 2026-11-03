"""The Monsoon Road: the South Asia floor of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_south_asia_monsoon_road.py scores/active/history_south_asia_monsoon_road.music.yaml

Jon, 2026-11-03: "I also think we will want new music for different locations
in the history dimension." Each region floor of the History dimension gets its
own cue. This floor walks east through three ages of South Asia: the Southern
Route (people who walk the coast of the Indian Ocean out of Africa), Mehrgarh
(barley, cattle, the first dentistry) and the Indus cities (planned streets,
drains, weights and measures, the unicorn seal). One cue plays in all three
rooms, so it is exploration music at mid energy that loops for a long time.

Nobody knows the music of the Indus cities. This cue evokes the region and does
not try to reconstruct it, and it does not imitate a raga performance. All
melodies are original.

D, 7/4 at 108 BPM. The cycle is 7 beats, in groups of 3 + 2 + 2.
  - THE DRONE: low strings hold D and A for the whole cue. It never stops.
  - THE TANPURA: a plucked psaltery repeats A D D D every 1.75 beats, a
    shimmer that does not align with the drums.
  - THE SCALE: D Lydian (raised 4th, G#), bright and patient. The grid uses
    the flat 2nd (Eb) as one more colour, always as a fall to D.
  - THE MARKS: finger cymbals and Nepalese hand bells mark the cycle.

Form, 7/4 at 108 BPM (bar = 3.89 s), 48 bars, about 3 min 7 s, all of it loops:
  alap     1-8    drone, tanpura, free flute phrases across the bar lines;
                  the frame drum hints at the cycle in bars 7-8.
  road     9-20   the cycle starts: darbuka and frame drum in 3 + 2 + 2; the
                  flute theme, A A' B, ends on D.
  grid     21-32  the Indus streets: a 7-note row rotates one step each bar on
                  the plucked psaltery (one note for each beat); congas in
                  exact eighths; the bowed psaltery holds one note for each
                  group; a three-times cadence lands on the first beat of 33.
  monsoon  33-42  rain: the violin sings high over random soft plucks and
                  darbuka rain; frame-drum thunder on the first beat.
  return   43-48  the rain stops; the drums thin out; the flute recalls the
                  alap and comes to rest on D; drone and tanpura lead to bar 1.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 108
BEATS = 7
OUT = Path(sys.argv[1])
rng = random.Random(2600)  # about 2600 BCE: the Indus cities at their height

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


def T(n: int) -> float:
    """The first beat of bar n, in beats."""
    return (n - 1) * float(BEATS)


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.drift = drift
        self.vel_jitter = vel_jitter
        #: (cc, [(bar, value), ...]) step curves, for a patch whose dynamics follow a controller
        self.controllers: list[tuple[int, list[tuple[int, int]]]] = []
        #: (cc, [(beat, value), ...]) linear curves
        self.ramps: list[tuple[int, list[tuple[float, int]]]] = []

    def note(self, at, dur, pitches, vel):
        at = F(at).limit_denominator(960)
        if self.drift and at > 0:
            at += F(rng.uniform(-self.drift, self.drift)).limit_denominator(960)
        at = max(F(0), at)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        self.events.append((at, F(dur).limit_denominator(960), [p if isinstance(p, int) else midi(p) for p in pitches], vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}"]
        if self.controllers or self.ramps:
            lines.append(f"{indent}  automation:")
            for cc, points in self.controllers:
                pts = ", ".join(f"[{{beats: {T(bar):g}}}, {value}]" for bar, value in points)
                lines.append(f"{indent}    - {{id: {clip_id}_cc{cc}, cc: {cc}, interpolation: step, resolution: 1/4, points: [{pts}]}}")
            for cc, points in self.ramps:
                pts = ", ".join(f"[{{beats: {beat:g}}}, {value}]" for beat, value in points)
                lines.append(f"{indent}    - {{id: {clip_id}_ramp{cc}, cc: {cc}, interpolation: linear, resolution: 1/16, points: [{pts}]}}")
        lines.append(f"{indent}  events:")
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


drone_bass = Clip()
drone_cello = Clip()
tanpura = Clip(0.004, 3)
rain = Clip(0.01, 4)
flute = Clip(0.004, 3)
violin = Clip(0.004, 3)
psaltery = Clip(0.002, 2)
darbuka = Clip(0.004, 4)
frame = Clip(0.004, 3)
conga = Clip(0.001, 2)  # the grid: precise
bongos = Clip(0.004, 4)
cymbal = Clip(0.002, 2)
bells = Clip(0.002, 2)

# The VPO performance patches follow CC1 for dynamics. CC1 at 122 or more can make
# sfizz hold a violin note for ever, so the curves stay at 118 or less.
flute.controllers.append((1, [(1, 92), (9, 104), (21, 96), (43, 96)]))
violin.controllers.append((1, [(1, 100), (33, 104), (37, 112), (41, 100)]))

# ---- Percussion keys (VCSL) --------------------------------------------------------------
DOUM, TEK, KA1, KA2, KA3 = 60, 61, 62, 63, 64             # Darbuka: 1 is the low doum, 2 the bright tek
FR_L_HIT, FR_L_MUTE, FR_S_HIT, FR_S_MUTE = 61, 62, 64, 65   # Frame Drum, large and small
CONGA_N, QUINTO_FM, QUINTO_N, TUMBA_N = 61, 62, 63, 65      # Conga
BONGO_H, BONGO_H_ROLL, BONGO_L = 60, 62, 63                 # Bongos
FINGER = 60                                                 # Finger Cymbals
BELL_1, BELL_2, BELL_3 = 60, 61, 62                         # Hand Bells, Nepalese

E = 0.5  # one eighth note, in beats


def at8(n: int, eighth: float) -> float:
    return T(n) + E * eighth


# ---- The drone and the tanpura --------------------------------------------------------------
SECTIONS = [(1, 9, 74), (9, 21, 68), (21, 33, 72), (33, 43, 78), (43, 49, 72)]
# The drone cannot sound across the loop seam, so it breathes there: the expression
# falls to zero over the last four beats, and the bow attack at bar 1 brings it back.
for clip in (drone_bass, drone_cello):
    clip.ramps.append((11, [(0.0, 104), (T(48) + 3.0, 104), (T(49) - 0.1, 0)]))
for first, end, vel in SECTIONS:
    # A new bow at each section; the old note releases under the new one.
    span = T(end) - T(first)
    drone_bass.note(T(first), span, "D2", vel)
    drone_cello.note(T(first), span, ["A2", "D3"], vel - 4)

TANPURA = [("A4", 58), ("D5", 52), ("D5", 50), ("D6", 38)]
step = 1.75
t, k = 0.0, 0
while t < T(48) + 3.5:  # the last bar lets the strings ring out before the loop
    name, vel = TANPURA[k % 4]
    bar = int(t // BEATS) + 1
    if not 21 <= bar <= 32:  # in the grid the same strings play the row in strict time
        soft = -8 if 33 <= bar <= 42 else 0  # under the rain the tanpura steps back
        tanpura.note(t, 1.6, name, vel + soft)
    t += step
    k += 1

# ---- Alap, 1-8: free phrases across the bar lines --------------------------------------------
ALAP = {
    1: [(0.5, 2.5, "A5"), (3.0, 0.35, "B5"), (3.35, 1.4, "A5"), (4.9, 0.6, "G#5"), (5.5, 0.5, "F#5"),
        (6.0, 0.9, "E5"), (6.9, 3.4, "D5")],
    3: [(0.75, 1.6, "F#5"), (2.35, 0.5, "G#5"), (2.85, 2.6, "A5"), (5.5, 0.4, "C#6"), (5.9, 0.4, "B5"),
        (6.3, 1.2, "A5"), (7.6, 0.5, "G#5"), (8.1, 0.6, "F#5"), (8.7, 2.9, "E5")],
    5: [(0.5, 1.0, "A5"), (1.5, 0.5, "B5"), (2.0, 2.4, "C#6"), (4.5, 0.5, "D6"), (5.0, 2.2, "E6"),
        (7.3, 0.5, "D6"), (7.8, 0.5, "C#6"), (8.3, 0.7, "B5"), (9.0, 3.2, "A5")],
    7: [(0.5, 0.6, "G#5"), (1.1, 0.6, "A5"), (1.7, 1.8, "F#5"), (3.6, 0.5, "E5"), (4.1, 3.2, "D5"),
        (8.5, 0.5, "E5"), (9.0, 0.5, "F#5"), (9.5, 1.5, "A5"), (11.2, 0.6, "F#5"), (11.8, 1.9, "E5")],
}


def play(clip: Clip, start: float, notes, vel: int):
    for at, dur, name in notes:
        long = dur >= 1.5
        clip.note(start + at, dur * (0.97 if long else 0.9), name, vel + (6 if long else 0))


for bar, notes in ALAP.items():
    play(flute, T(bar), notes, 74)
cymbal.note(T(1), 3.0, FINGER, 90)
cymbal.note(T(5), 3.0, FINGER, 82)
for n in (7, 8):  # the frame drum hints at the cycle
    frame.note(at8(n, 0), 0.4, FR_S_MUTE, 88)
    frame.note(at8(n, 6), 0.3, FR_S_MUTE, 84)
    frame.note(at8(n, 10), 0.3, FR_S_MUTE, 84)
darbuka.note(at8(8, 12), 0.2, TEK, 56)
darbuka.note(at8(8, 13), 0.2, TEK, 64)


# ---- The road cycle: 3 + 2 + 2 ---------------------------------------------------------------
ROAD = [(0, DOUM, 100), (2, TEK, 70), (3, KA1, 56), (4, TEK, 76), (6, DOUM, 92), (7, KA2, 50), (8, TEK, 72),
        (10, DOUM, 80), (11, KA1, 50), (12, TEK, 72), (13, KA3, 58)]
ROAD_FILL = [(10, DOUM, 82), (10.5, KA1, 52), (11, TEK, 70), (11.5, KA2, 56), (12, TEK, 76), (12.5, KA1, 60),
             (13, TEK, 82), (13.5, TEK, 90)]


def road_bar(n: int, scale: float = 1.0, fill: bool = False, sparse: bool = False):
    for e, key, vel in ROAD:
        if fill and e >= 10:
            continue
        if sparse and e not in (0, 6):
            continue
        darbuka.note(at8(n, e), 0.3, key, round(vel * scale))
    if fill:
        for e, key, vel in ROAD_FILL:
            darbuka.note(at8(n, e), 0.2, key, round(vel * scale))
    # The frame drum has a soft layer 20 dB down below velocity 84; stay above it.
    frame.note(at8(n, 0), 0.6, FR_L_HIT, max(88, round(104 * min(1.0, scale + 0.1))))
    if not sparse:
        frame.note(at8(n, 6), 0.3, FR_S_MUTE, 90)
        frame.note(at8(n, 10), 0.3, FR_S_MUTE, 88)


# ---- Road, 9-20: the flute theme ---------------------------------------------------------------
def bars_of(lines):
    """[(dur, name or None), ...] per bar -> [(at, dur, name)] with rests skipped."""
    out = []
    for line in lines:
        t0, notes = 0.0, []
        for dur, name in line:
            if name:
                notes.append((t0, dur, name))
            t0 += dur
        assert abs(t0 - BEATS) < 1e-9, (line, t0)
        out.append(notes)
    return out


THEME_A = bars_of([
    [(1.0, "D5"), (0.5, "F#5"), (1.5, "A5"), (1.0, "B5"), (1.0, "A5"), (0.5, "G#5"), (0.5, "A5"), (1.0, "F#5")],
    [(3.0, "E5"), (1.0, "F#5"), (1.0, "G#5"), (2.0, "A5")],
    [(1.5, "C#6"), (0.5, "B5"), (1.0, "A5"), (1.0, "G#5"), (1.0, "F#5"), (1.0, "E5"), (1.0, "F#5")],
    [(5.0, "D5"), (2.0, None)],
])
THEME_A2 = THEME_A[:2] + bars_of([
    [(1.5, "C#6"), (0.5, "D6"), (1.0, "E6"), (1.0, "D6"), (1.0, "C#6"), (1.0, "B5"), (1.0, "C#6")],
    [(5.0, "A5"), (2.0, None)],
])
THEME_B = bars_of([
    [(2.0, "E6"), (0.5, "D6"), (0.5, "C#6"), (1.0, "B5"), (1.0, "C#6"), (2.0, "A5")],
    [(1.0, "G#5"), (0.5, "A5"), (0.5, "B5"), (1.0, "G#5"), (2.0, "F#5"), (2.0, "E5")],
    [(1.0, "F#5"), (1.0, "A5"), (1.0, "D6"), (1.0, "C#6"), (1.0, "A5"), (0.5, "B5"), (0.5, "A5"), (1.0, "G#5")],
    [(3.0, "A5"), (1.0, "F#5"), (1.0, "E5"), (2.0, "D5")],
])
for k, notes in enumerate(THEME_A + THEME_A2 + THEME_B):
    play(flute, T(9 + k), notes, 84)
for k in range(12):
    n = 9 + k
    road_bar(n, scale=0.9 if k < 4 else 1.0, fill=k % 4 == 3)
    if k % 2 == 0:
        cymbal.note(T(n), 3.0, FINGER, 94)
    bells.note(at8(n, 6), 1.0, BELL_3, 52)

# ---- Grid, 21-32: the Indus streets ------------------------------------------------------------
#: one note for each beat of the cycle; each bar starts the row one step later
ROW = ["D5", "F#5", "A5", "C#6", "B5", "G#5", "E5"]
ACCENT = {0: 84, 3: 76, 5: 76}  # the first beat of each group
for k in range(12):
    n = 21 + k
    if n >= 31:
        break  # the cadence takes bars 31-32
    for b in range(BEATS):
        name = ROW[(b + k) % BEATS]
        psaltery_vel = ACCENT.get(b, 64)
        tanpura.note(T(n) + b, 0.45, name, psaltery_vel)  # same plucked psaltery, now in strict time
        tanpura.note(T(n) + b + E, 0.4, "A4", 44)
for k in range(12):
    n = 21 + k
    if n >= 31:
        break
    # congas in exact eighths: the low tumba opens each group
    for e in range(14):
        if e in (0, 6, 10):
            conga.note(at8(n, e), 0.3, TUMBA_N, 96 if e == 0 else 86)
        elif e in (2, 4, 8, 12):
            conga.note(at8(n, e), 0.3, CONGA_N, 72)
        elif e == 13:
            conga.note(at8(n, e), 0.3, QUINTO_N, 74)
        else:
            conga.note(at8(n, e), 0.25, QUINTO_FM, 52)
    darbuka.note(at8(n, 0), 0.3, DOUM, 94)
    frame.note(at8(n, 0), 0.6, FR_L_HIT, 100)
    bells.note(at8(n, 0), 1.0, BELL_1, 60)
    bells.note(at8(n, 6), 1.0, BELL_2, 50)
    bells.note(at8(n, 10), 1.0, BELL_2, 46)

#: the bowed psaltery: one long note for each group (3, 2, 2 beats)
GRID_LINE = bars_of([
    [(3.0, "A5"), (2.0, "B5"), (2.0, "A5")],
    [(3.0, "F#5"), (2.0, "G#5"), (2.0, "A5")],
    [(3.0, "B5"), (2.0, "C#6"), (2.0, "D6")],
    [(3.0, "C#6"), (4.0, "A5")],
    [(1.0, "Eb6"), (2.0, "D6"), (2.0, "C#6"), (2.0, "B5")],
    [(3.0, "A5"), (2.0, "G#5"), (2.0, "F#5")],
    [(3.0, "G#5"), (2.0, "A5"), (2.0, "B5")],
    [(7.0, "A5")],
    [(1.0, "Eb5"), (2.0, "D5"), (2.0, "F#5"), (2.0, "A5")],
    [(3.0, "C#6"), (2.0, "B5"), (2.0, "A5")],
])
for k, notes in enumerate(GRID_LINE):
    play(psaltery, T(21 + k), notes, 80)

# The cadence: one phrase three times; its last stroke lands on the first beat of bar 33.
SAM = T(33)
PHRASE = [(0.0, "D6", TUMBA_N), (0.5, "C#6", CONGA_N), (1.0, "A5", CONGA_N), (1.5, "B5", QUINTO_N), (2.0, "A5", TUMBA_N)]
GAP = 3.0  # from the start of one phrase to the start of the next
start = SAM - 2.0 - 2 * GAP
# Bars 31-32 before the cadence: the row once more, softer, and the drums on the groups.
for n in (31, 32):
    for b in range(BEATS):
        if T(n) + b >= start:
            break
        tanpura.note(T(n) + b, 0.45, ROW[(b + n - 21) % BEATS], ACCENT.get(b, 62) - 6)
        tanpura.note(T(n) + b + E, 0.4, "A4", 42)
    for e in (0, 6, 10):
        if at8(n, e) < start:
            conga.note(at8(n, e), 0.3, TUMBA_N, 92 if e == 0 else 84)
            if e:
                conga.note(at8(n, e + 2), 0.3, CONGA_N, 70)
    frame.note(at8(n, 0), 0.6, FR_L_HIT, 100)
    bells.note(at8(n, 0), 1.0, BELL_1, 58)
psaltery.note(T(31), 4.0, "A5", 82)
psaltery.note(T(31) + 4.0, 3.0, "B5", 80)
psaltery.note(T(32), 1.0, "C#6", 82)
for r in range(3):
    t0 = start + r * GAP
    for at, name, drum in PHRASE:
        last = r == 2 and at == 2.0
        if t0 + at >= SAM:
            continue  # the landing stroke belongs to bar 33 (written there)
        tanpura.note(t0 + at, 0.45, name, 78 + 4 * r)
        conga.note(t0 + at, 0.3, drum, 80 + 6 * r)
        darbuka.note(t0 + at, 0.25, TEK, 64 + 6 * r)

# ---- Monsoon, 33-42: rain -------------------------------------------------------------------
cymbal.note(SAM, 3.0, FINGER, 108)
conga.note(SAM, 0.3, TUMBA_N, 100)
tanpura.note(SAM, 1.6, "A5", 80)
MONSOON = bars_of([
    [(3.0, "A5"), (1.0, "B5"), (1.0, "C#6"), (2.0, "D6")],
    [(3.0, "E6"), (1.0, "D6"), (1.0, "C#6"), (2.0, "B5")],
    [(1.5, "C#6"), (0.5, "B5"), (1.0, "A5"), (2.0, "G#5"), (2.0, "A5")],
    [(5.0, "F#5"), (1.0, "E5"), (1.0, "F#5")],
    [(1.0, "A5"), (1.0, "B5"), (1.0, "D6"), (2.0, "E6"), (2.0, "F#6")],
    [(3.0, "E6"), (1.0, "D6"), (1.0, "E6"), (2.0, "C#6")],
    [(1.0, "B5"), (1.0, "C#6"), (1.0, "A5"), (1.0, "G#5"), (1.0, "B5"), (1.0, "A5"), (1.0, "F#5")],
    [(3.0, "E5"), (2.0, "F#5"), (2.0, "A5")],
    [(5.0, "D6"), (1.0, "C#6"), (1.0, "B5")],
    [(5.0, "A5"), (2.0, None)],
])
for k, notes in enumerate(MONSOON):
    play(violin, T(33 + k), notes, 86 if k < 4 else 94)
RAIN = ["A5", "B5", "C#6", "D6", "E6", "F#6"]
#: (start, end, midi) of each violin note, so the rain avoids a semitone against it
VIOLIN_SPANS = [(T(33 + k) + at, T(33 + k) + at + dur, midi(name)) for k, notes in enumerate(MONSOON)
                for at, dur, name in notes]


def rain_choice(t: float) -> str:
    held = [m for a, b, m in VIOLIN_SPANS if a - 0.25 <= t < b]
    choices = [n for n in RAIN if all(abs(midi(n) - m) % 12 not in (1, 11) for m in held)]
    return rng.choice(choices)


for k in range(10):
    n = 33 + k
    density = 0.22 + 0.04 * min(k, 5) - (0.08 if k >= 8 else 0)
    for s in range(28):  # sixteenths
        if rng.random() < density:
            rain.note(T(n) + 0.25 * s, 0.4, rain_choice(T(n) + 0.25 * s), rng.randint(30, 54))
        if s % 2 and rng.random() < density * 1.2:  # between the eighths of the cycle
            darbuka.note(T(n) + 0.25 * s, 0.1, rng.choice((KA2, KA3)), rng.randint(30, 46))
    road_bar(n, scale=1.0, fill=k in (3, 7))
    if k % 4 == 0 and k:
        frame.note(at8(n, 1), 0.6, FR_L_HIT, 112)  # thunder: a second low stroke just after the first beat
    if k in (3, 7):
        bongos.note(at8(n, 10), 1.8, BONGO_H_ROLL, 70)
    for e in (3, 7, 11):
        bongos.note(at8(n, e), 0.2, BONGO_H, 58)
    if k % 2 == 1:
        cymbal.note(T(n), 3.0, FINGER, 88)
    bells.note(at8(n, 6), 1.0, BELL_3, 50)

# ---- Return, 43-48: the rain stops; the flute comes to rest -----------------------------------
RETURN = bars_of([
    [(0.5, None), (2.5, "A5"), (0.5, "B5"), (1.5, "A5"), (1.0, "F#5"), (1.0, "E5")],
    [(5.0, "D5"), (2.0, None)],
    [(1.0, "F#5"), (1.0, "G#5"), (1.0, "A5"), (1.5, "C#6"), (0.5, "B5"), (2.0, "A5")],
    [(3.0, "E5"), (1.0, "F#5"), (1.0, "E5"), (2.0, "D5")],
    [(4.0, "D5"), (3.0, None)],
])
for k, notes in enumerate(RETURN):
    play(flute, T(43 + k), notes, 78)
road_bar(43, scale=0.8)
road_bar(44, scale=0.72)
road_bar(45, scale=0.66, sparse=True)
road_bar(46, scale=0.6, sparse=True)
frame.note(T(47), 0.6, FR_S_MUTE, 86)
cymbal.note(T(43), 3.0, FINGER, 90)
cymbal.note(T(45), 3.0, FINGER, 80)
bells.note(at8(44, 6), 1.0, BELL_3, 46)
bells.note(at8(46, 6), 1.0, BELL_3, 42)

END_BAR = 49


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def vpo(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/Virtual-Playing-Orchestra3/{path}.sfz', settings: {{fold_to_range: false}}}}"


PSALTERY = "Chordophones/Zithers/Psaltery, Bowed and Plucked"
HAND = "Membranophones/Struck Membranophones"
score = f"""schema: ambition.musicir.v3
id: history_south_asia_monsoon_road
title: The Monsoon Road
description: >-
  The South Asia floor of the History dimension: the Southern Route, Mehrgarh
  and the Indus cities. D Lydian in 7/4 (3 + 2 + 2) at 108 BPM. Low strings
  hold D and A for the whole cue under a plucked-psaltery tanpura figure. A
  free flute alap settles into the cycle of darbuka and frame drum; the flute
  theme walks the road; the Indus streets are a 7-note row that rotates one
  step each bar, with congas in exact eighths, a bowed psaltery and a
  three-times cadence; the monsoon brings a high violin over soft rain; the
  rain stops and the flute comes to rest on D. Evokes the region; it does not
  reconstruct the unknown music of the Indus cities, and all melodies are
  original. Jon, 2026-11-03: "I also think we will want new music for
  different locations in the history dimension." Generated by
  dev/compose_history_south_asia_monsoon_road.py: edit that, not this file.
notes:
  - 'The whole file loops: bar 48 is drone and tanpura only, and leads back to the alap at bar 1.'
  - 'The cycle is 7 beats in groups of 3 + 2 + 2; finger cymbals and Nepalese hand bells mark it.'
seed: 2600
timebase: {{ppq: 960}}
meter: 7/4
tempo: {BPM}
key: {{tonic: D, mode: lydian}}
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: alap, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.3, density: 0.3, loopable: true, role: 'drone, tanpura, free flute'}}
  - {{id: road, from: {{bar: 9, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'the cycle and the flute theme'}}
  - {{id: grid, from: {{bar: 21, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.6, density: 0.6, loopable: true, role: 'the Indus streets: a rotating row'}}
  - {{id: monsoon, from: {{bar: 33, beat: 1}}, to: {{bar: 43, beat: 1}}, energy: 0.75, density: 0.75, loopable: true, role: 'rain and a high violin'}}
  - {{id: return, from: {{bar: 43, beat: 1}}, to: {{bar: 49, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'the rain stops; the flute rests on D'}}
harmony:
  events:
    - {{bar: 1, chord: D5}}
instruments:
  - {{name: drone_bass, group: drone, program: contrabass, volume: 104, pan: 60, expression: 104, {vpo("Strings/bass-SEC-sustain")}}}
  - {{name: drone_cello, group: drone, program: cello, volume: 100, pan: 70, expression: 100, {vpo("Strings/cello-SEC-sustain")}}}
  - {{name: tanpura, group: tanpura, program: dulcimer, volume: 100, pan: 56, expression: 100, {vcsl(PSALTERY + " - Pluck")}}}
  - {{name: rain, group: rain, program: dulcimer, volume: 100, pan: 80, expression: 100, {vcsl(PSALTERY + " - Pluck")}}}
  - {{name: flute, group: flute, program: flute, volume: 104, pan: 64, expression: 108, controls: {{1: 92}}, {sfz("vpo.flute_solo_perf")}}}
  - {{name: violin, group: violin, program: violin, volume: 106, pan: 64, expression: 108, controls: {{1: 100}}, {sfz("vpo.violin_solo_perf")}}}
  - {{name: psaltery, group: psaltery, program: violin, volume: 104, pan: 66, expression: 104, {vcsl(PSALTERY + " - LongBow")}}}
  - {{name: darbuka, group: hand_drums, program: woodblock, volume: 104, pan: 58, expression: 104, {vcsl(HAND + "/Darbuka")}}}
  - {{name: conga, group: hand_drums, program: woodblock, volume: 100, pan: 72, expression: 100, {vcsl(HAND + "/Conga")}}}
  - {{name: bongos, group: hand_drums, program: woodblock, volume: 96, pan: 80, expression: 96, {vcsl(HAND + "/Bongos")}}}
  - {{name: frame, group: frame, program: taiko_drum, volume: 104, pan: 64, expression: 104, {vcsl(HAND + "/Frame Drum")}}}
  - {{name: cymbal, group: bells, program: tinkle_bell, volume: 96, pan: 44, expression: 96, {vcsl("Idiophones/Struck Idiophones/Finger Cymbals")}}}
  - {{name: bells, group: bells, program: tinkle_bell, volume: 96, pan: 84, expression: 96, {vcsl("Idiophones/Struck Idiophones/Hand Bells, Nepalese")}}}
parts:
{part("drone_bass_part", "drone_bass", drone_bass)}
{part("drone_cello_part", "drone_cello", drone_cello)}
{part("tanpura_part", "tanpura", tanpura)}
{part("rain_part", "rain", rain)}
{part("flute_part", "flute", flute)}
{part("violin_part", "violin", violin)}
{part("psaltery_part", "psaltery", psaltery)}
{part("darbuka_part", "darbuka", darbuka)}
{part("conga_part", "conga", conga)}
{part("bongos_part", "bongos", bongos)}
{part("frame_part", "frame", frame)}
{part("cymbal_part", "cymbal", cymbal)}
{part("bells_part", "bells", bells)}
processing:
  groups:
    drone:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: lowpass, cutoff_hz: 4000}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: -6.0}}
    tanpura:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.28, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: -0.2}}
    rain:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: reverb, wet: 0.4, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: 0.35}}
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 12.0, release_ms: 110.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 2.0}}
    violin:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 12.0, release_ms: 110.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 1.0}}
    psaltery:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.1}}
    hand_drums:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 3.0, release_ms: 80.0, makeup_db: 3.0}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 1.0}}
    frame:
      chain:
        - {{processor: highpass, cutoff_hz: 38}}
        # The large frame drum is the highest peak of the mix; hold its strokes down.
        - {{processor: compressor, threshold_db: -26.0, ratio: 4.0, attack_ms: 2.0, release_ms: 120.0, makeup_db: 3.0}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 1.0}}
    bells:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 15.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.4, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 1.1, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [drone, tanpura, rain]
    drums: [hand_drums, frame, bells]
    tune: [flute, violin, psaltery]
  sections:
    - {{id: road, form: [alap, road, grid, monsoon, return], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * BEATS * 60 / BPM:.0f} s")

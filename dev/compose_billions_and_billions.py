"""Billions and Billions: Carl Stargan's song, a cosmic orchestral single.
Writes its MusicIR v3 score:

    python3 dev/compose_billions_and_billions.py scores/active/billions_and_billions.music.yaml

Jon, 2026-10-29: "compose a song specifically for Carl Stargan ... a
completely original tune using high quality instruments. Make it a standout
single for the game." Carl is the astronomer of Eureka's observatory: look
up, the pale dot above the cable is the station, billions and billions of
stars, you are made of starstuff.

D major at 96 BPM. The sound is a sequencer pulse and a synth pad under a
real orchestra: a solo violin has the tune, a grand piano keeps it moving,
and the strings, horns, choir and timpani arrive for the chorus.

  - THE PULSE: a sixteenth-note pluck sequencer, root root fifth octave, that
    never stops except in the breakdown. The space-telescope hum.
  - THE LOOK-UP THEME (verse): a slow tune that climbs three steps and holds,
    over Dmaj7 and the Lydian E/D (the raised fourth is the wonder).
  - THE HOOK (chorus): "bil-lions-AND": two eighth pickups vault into a held
    note, and the held notes climb D, F#, G, A while the bass walks down
    D C# B A G G A. Gm (the borrowed minor) is the shiver at the sixth bar.
  - THE PALE BLUE DOT (breakdown): the pulse stops; a celesta rings one high
    note over Bbmaj7 C Gm A, the tempo eases to 80 and climbs back to 96
    through a snare and timpani build.

Form, 4/4 at 96 BPM, 64 bars, the whole song loops (the outro is the intro's
texture on the dominant, back to D at bar 1):
  intro     1-4    pulse, pad, harp ripple
  verse_1   5-12   piano eighths, celli and basses, the look-up theme low
  verse_2   13-20  half-time drums, violas and violins, the theme with harp
  chorus_1  21-28  the hook: violin and violins, horns, full drums
  dot       29-36  the pale blue dot: celesta, pad, piano; then the build
  verse_3   37-44  the theme with a flute answering
  chorus_2  45-52  the hook with choir and timpani
  chorus_3  53-60  the hook with a horn counter-line and a violin descant
  outro     61-64  the pulse and pad thin out over G, Gm, D, A
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 96
OUT = Path(sys.argv[1])
rng = random.Random(1934)  # Carl Sagan's birth year

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


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
        self.drift = drift
        self.vel_jitter = vel_jitter
        #: (cc, [(bar, value), ...]) step curves, for a patch whose dynamics follow a controller
        self.controllers: list[tuple[int, list[tuple[int, int]]]] = []

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
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}"]
        if self.controllers:
            lines.append(f"{indent}  automation:")
            for cc, points in self.controllers:
                pts = ", ".join(f"[{{beats: {T(bar):g}}}, {value}]" for bar, value in points)
                lines.append(f"{indent}    - {{id: {clip_id}_cc{cc}, cc: {cc}, interpolation: step, resolution: 1/4, points: [{pts}]}}")
        lines.append(f"{indent}  events:")
        for at, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(at)}, {frac(dur)}, {pitch}, {vel}]")
        return "\n".join(lines)


def T(n: int) -> float:
    """The first beat of bar n, in beats."""
    return (n - 1) * 4.0


violin = Clip(0.004, 3)
violins = Clip(0.006, 3)
violas = Clip(0.006, 3)
celli = Clip(0.006, 3)
basses = Clip(0.006, 3)
flute = Clip(0.004, 3)
horns = Clip(0.006, 3)
choir_f = Clip(0.008, 2)
choir_m = Clip(0.008, 2)
piano = Clip(0.003, 4)
harp = Clip(0.003, 3)
celesta = Clip(0.002, 2)
pad = Clip()
pulse = Clip(0.0, 3)
bass = Clip(0.002, 3)
timpani = Clip(0.002, 3)
kit = Clip(0.003, 4)
harmony: dict[int, str] = {}

# ---- Harmony ---------------------------------------------------------------------------
#: chord tones low to high, a close voicing round the middle of the keyboard
TONES = {
    "Dmaj7": ["D4", "F#4", "A4", "C#5"], "E/D": ["E4", "G#4", "B4", "D5"], "Bm7": ["B3", "D4", "F#4", "A4"],
    "Gmaj7": ["G3", "B3", "D4", "F#4"], "Asus4": ["A3", "D4", "E4", "A4"], "A": ["A3", "C#4", "E4", "A4"],
    "D": ["D4", "F#4", "A4", "D5"], "A/C#": ["A3", "C#4", "E4", "A4"], "Bm": ["B3", "D4", "F#4", "B4"],
    "Bm/A": ["B3", "D4", "F#4", "B4"], "G": ["G3", "B3", "D4", "G4"], "Gm": ["G3", "Bb3", "D4", "G4"],
    "D/A": ["D4", "F#4", "A4", "D5"], "Bbmaj7": ["Bb3", "D4", "F4", "A4"], "C": ["C4", "E4", "G4", "C5"],
    "Gm/D": ["G3", "Bb3", "D4", "G4"],
}
#: the bass note of each chord (Growlybass is written at concert pitch, like tritone_decree)
BASS = {
    "Dmaj7": "D2", "E/D": "D2", "Bm7": "B1", "Gmaj7": "G1", "Asus4": "A1", "A": "A1", "D": "D2", "A/C#": "C#2",
    "Bm": "B1", "Bm/A": "A1", "G": "G1", "Gm": "G1", "D/A": "A1", "Bbmaj7": "Bb1", "C": "C2", "Gm/D": "D2",
}
#: the fifth over the bass note, for the sequencer and the piano
FIFTH = {
    "Dmaj7": "A2", "E/D": "A2", "Bm7": "F#2", "Gmaj7": "D2", "Asus4": "E2", "A": "E2", "D": "A2", "A/C#": "G#2",
    "Bm": "F#2", "Bm/A": "E2", "G": "D2", "Gm": "D2", "D/A": "E2", "Bbmaj7": "F2", "C": "G2", "Gm/D": "A2",
}
INTRO_CH = ["Dmaj7", "Dmaj7", "E/D", "E/D"]
VERSE_CH = ["Dmaj7", "Dmaj7", "E/D", "E/D", "Bm7", "Gmaj7", "Asus4", "A"]
CHORUS_CH = ["D", "A/C#", "Bm", "Bm/A", "G", "Gm", "D/A", "A"]
DOT_CH = ["Bbmaj7", "C", "Gm", "A", "Bbmaj7", "C", "Gm", "Asus4"]
OUTRO_CH = ["Gmaj7", "Gm/D", "Dmaj7", "Asus4"]


def tones(chord: str) -> list[int]:
    return [midi(x) for x in TONES[chord]]


# ---- Tunes -----------------------------------------------------------------------------
#: The look-up theme, one bar per chord of VERSE_CH: (beat, duration, note).
LOOK_UP = [
    [(0.5, 0.5, "A4"), (1.0, 0.5, "B4"), (1.5, 0.5, "C#5"), (2.0, 2.0, "D5")],
    [(0.0, 2.0, "A4"), (2.0, 1.0, "F#4"), (3.0, 1.0, "A4")],
    [(0.5, 0.5, "G#4"), (1.0, 0.5, "B4"), (1.5, 0.5, "E5"), (2.0, 2.0, "B4")],
    [(0.0, 2.0, "G#4"), (2.0, 1.0, "E4"), (3.0, 1.0, "F#4")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "C#5"), (2.0, 2.0, "B4")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "E5"), (2.0, 2.0, "F#5")],
    [(0.0, 3.0, "E5"), (3.0, 1.0, "D5")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "A4")],
]
#: The last bar of the theme when a chorus follows: it leads up.
LOOK_UP_LIFT = [(0.0, 2.0, "C#5"), (2.0, 1.0, "E5"), (3.0, 1.0, "F#5")]
#: The hook, one bar per chord of CHORUS_CH. "bil-lions-AND": two eighth pickups into a held note.
HOOK = [
    [(0.0, 0.5, "A4"), (0.5, 0.5, "B4"), (1.0, 1.5, "D5"), (2.5, 0.5, "E5"), (3.0, 1.0, "F#5")],
    [(0.0, 1.5, "E5"), (1.5, 0.5, "C#5"), (2.0, 2.0, "A4")],
    [(0.0, 0.5, "B4"), (0.5, 0.5, "D5"), (1.0, 1.5, "F#5"), (2.5, 0.5, "G5"), (3.0, 1.0, "A5")],
    [(0.0, 1.5, "F#5"), (1.5, 0.5, "E5"), (2.0, 2.0, "D5")],
    [(0.0, 0.5, "D5"), (0.5, 0.5, "E5"), (1.0, 1.5, "G5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "E5")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "Bb4"), (2.0, 2.0, "D5")],
    [(0.0, 0.5, "D5"), (0.5, 0.5, "F#5"), (1.0, 2.0, "A5"), (3.0, 1.0, "G5")],
    [(0.0, 1.5, "F#5"), (1.5, 0.5, "E5"), (2.0, 2.0, "E5")],
]
#: The hook's last bar when the song goes on to the dot or the outro: it lands on D.
HOOK_LAND = [(0.0, 1.0, "F#5"), (1.0, 1.0, "E5"), (2.0, 2.0, "D5")]
#: The violin in the dot: long notes, the top voice of each chord, quiet.
DOT_LINE = [
    [(0.0, 4.0, "D5")], [(0.0, 4.0, "E5")], [(0.0, 2.0, "D5"), (2.0, 2.0, "Bb4")], [(0.0, 4.0, "C#5")],
]
#: The flute answers the theme in the gaps of its even bars (verse 3).
FLUTE_ANSWERS = {
    1: [(2.0, 0.5, "D5"), (2.5, 0.5, "E5"), (3.0, 1.0, "F#5")],
    3: [(2.0, 0.5, "E5"), (2.5, 0.5, "F#5"), (3.0, 1.0, "G#5")],
    5: [(2.5, 0.5, "A5"), (3.0, 1.0, "B5")],
    7: [(0.0, 0.5, "A5"), (0.5, 0.5, "G5"), (1.0, 0.5, "F#5"), (1.5, 0.5, "E5"), (2.0, 2.0, "A5")],
}
D_MAJOR = ["D", "E", "F#", "G", "A", "B", "C#"]


def third_below(name: str, chord: str) -> int:
    """The diatonic third under a note of the tune, in D major; B flat under the borrowed G minor."""
    pitch, octave = name[:-1], int(name[-1])
    i = D_MAJOR.index(pitch)
    below = D_MAJOR[(i - 2) % 7]
    if chord == "Gm" and below == "B":
        below = "Bb"
    drop = octave - 1 if NOTE[below] > NOTE[pitch] else octave
    return midi(f"{below}{drop}")


#: The horns' counter-line in chorus 3: one long note a bar, under the hook.
HORN_COUNTER = ["A3", "G3", "F#3", "E3", "D3", "D3", "F#3", "E3"]


def sing(clip: Clip, n0: int, phrase, vel=96, octave=0, last=None):
    bars = list(phrase)
    if last is not None:
        bars[-1] = last
    for k, notes in enumerate(bars):
        for at, dur, name in notes:
            held = dur >= 1.0
            clip.note(T(n0 + k) + at, dur * (0.97 if held else 0.9), midi(name) + 12 * octave, vel + (6 if held else 0))


# ---- Beds ------------------------------------------------------------------------------
def sequencer(n: int, chord: str, vel: int):
    """The pulse: sixteenths, root root fifth octave, an accent on each beat."""
    root, fifth = midi(BASS[chord]) + 12, midi(FIFTH[chord]) + 12
    for i in range(16):
        p = (root, root, fifth, root + 12)[i % 4]
        pulse.note(T(n) + 0.25 * i, 0.18, p, vel + (10 if i % 4 == 0 else 0) + (4 if i % 8 == 6 else 0))


def pad_bar(n: int, chord: str, vel: int, bars: int = 1):
    pad.note(T(n), 4.0 * bars - 0.1, tones(chord), vel)


def piano_verse(n: int, chord: str, vel: int):
    """Eighth-note broken chord: low root, then up through the voicing and back."""
    low = midi(BASS[chord]) + 12
    t = tones(chord)
    order = [low, t[0], t[1], t[2], t[3], t[2], t[1], t[0]]
    for i, p in enumerate(order):
        piano.note(T(n) + 0.5 * i, 0.55, p, vel + (8 if i == 0 else 0) - (4 if i % 2 else 0))


def piano_chorus(n: int, chord: str, vel: int):
    """Octaves on the beat, chord tones between: the piano drives the chorus."""
    low = midi(BASS[chord]) + 12
    t = tones(chord)
    for beat in range(4):
        piano.note(T(n) + beat, 0.5, [low, low + 12], vel + (6 if beat in (0, 2) else 0))
        piano.note(T(n) + beat + 0.5, 0.45, [t[1], t[3]] if beat % 2 == 0 else [t[0], t[2]], vel - 10)


def bass_long(n: int, chord: str, vel: int):
    bass.note(T(n), 3.8, midi(BASS[chord]), vel)


def bass_drive(n: int, chord: str, vel: int):
    """Eighth notes on the root, the octave on the and of four."""
    root = midi(BASS[chord])
    for i in range(8):
        p = root + 12 if i == 7 else root
        bass.note(T(n) + 0.5 * i, 0.42, p, vel + (8 if i in (0, 4) else 0))


def strings_bar(n: int, chord: str, vel: int, with_violins: bool):
    t = tones(chord)
    celli.note(T(n), 3.9, t[0] - 12, vel)
    basses.note(T(n), 3.9, midi(BASS[chord]) + 12, vel - 6)
    violas.note(T(n), 3.9, [t[1], t[2]], vel - 4)
    if with_violins:
        violins.note(T(n), 3.9, t[3], vel - 6)


def horns_bar(n: int, chord: str, vel: int):
    t = tones(chord)
    horns.note(T(n), 3.85, [t[0] - 12, t[2] - 12], vel)


def choir_bar(n: int, chord: str, vel: int):
    t = tones(chord)
    choir_m.note(T(n) + 0.05, 3.8, [t[0] - 12, t[2] - 12], vel - 4)
    choir_f.note(T(n) + 0.05, 3.8, [t[3], t[1] + 12], vel)  # the female choir is sampled from G4 up


def harp_ripple(n: int, chord: str, vel: int, bars: int = 1):
    """Sixteenths up through two octaves of the chord, then down: the harp's wave."""
    t = tones(chord)
    seq = [p - 12 for p in t] + t + [p + 12 for p in t[:2]]
    seq = seq + seq[-2::-1]
    for i, p in enumerate(seq[: 16 * bars]):
        harp.note(T(n) + 0.25 * i, 0.3, p, vel - abs(8 - i % 16) // 2)


def harp_gliss(n: int, chord: str, vel: int):
    """The last beat of bar n: a run up two octaves into the next bar's downbeat."""
    t = tones(chord)
    seq = [p - 12 for p in t] + t + [p + 12 for p in t]
    for i, p in enumerate(seq[:12]):
        harp.note(T(n) + 3.0 + i / 12, 0.2, p, vel + i)


KICK, SNARE, SIDE, HAT, OPEN_HAT, CRASH, RIDE, HI_TOM, MID_TOM, FLOOR_TOM = 36, 38, 37, 42, 46, 49, 51, 50, 47, 41


def drums(n: int, style: str, crash=False, fill=False):
    t = T(n)
    if crash:
        kit.note(t, 1.0, CRASH, 100)
    if style == "half":
        kit.note(t, 0.1, KICK, 104)
        kit.note(t + 2.5, 0.1, KICK, 84)
        kit.note(t + 2.0, 0.1, SNARE, 100)
        for i in range(8):
            kit.note(t + 0.5 * i, 0.05, HAT, 56 if i % 2 == 0 else 40)
    elif style == "full":
        for at, v in ((0, 110), (1.5, 88), (2.0, 96), (3.5, 80)):
            kit.note(t + at, 0.1, KICK, v)
        kit.note(t + 1.0, 0.1, SNARE, 106)
        kit.note(t + 3.0, 0.1, SNARE, 110)
        for i in range(8):
            kit.note(t + 0.5 * i, 0.05, RIDE if n % 2 else HAT, 68 if i % 2 == 0 else 50)
        kit.note(t + 3.5, 0.3, OPEN_HAT, 62)
    if fill:
        for i, d in enumerate((SNARE, SNARE, HI_TOM, HI_TOM, MID_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM)):
            kit.note(t + 2 + 0.25 * i, 0.08, d, 76 + 5 * i)


# ---- Intro, 1-4: pulse, pad, harp ripple ---------------------------------------------------
for k, chord in enumerate(INTRO_CH):
    n = 1 + k
    harmony[n] = chord
    sequencer(n, chord, 58 + 4 * k)
for k in (0, 2):
    pad_bar(1 + k, INTRO_CH[k], 60, bars=2)
    harp_ripple(1 + k, INTRO_CH[k], 70, bars=2)
celli.note(T(3), 7.8, midi("D3"), 60)


# ---- Verses --------------------------------------------------------------------------------
def verse(n0: int, number: int):
    for k, chord in enumerate(VERSE_CH):
        n = n0 + k
        harmony[n] = chord
        if number == 1:
            sequencer(n, chord, 62)
            pad_bar(n, chord, 58)
            piano_verse(n, chord, 78)
            bass_long(n, chord, 92)
            celli.note(T(n), 3.9, tones(chord)[0] - 12, 66)
            basses.note(T(n), 3.9, midi(BASS[chord]) + 12, 56)
        else:
            sequencer(n, chord, 70)
            pad_bar(n, chord, 64)
            piano_verse(n, chord, 86)
            bass_long(n, chord, 98)
            strings_bar(n, chord, 72, with_violins=number == 3)
            drums(n, "half", crash=k == 0, fill=k == 7)
            if number == 2 and k % 2 == 1:
                harp_ripple(n, chord, 64)
    if number == 1:
        sing(violin, n0, LOOK_UP, vel=88)
    elif number == 2:
        sing(violin, n0, LOOK_UP, vel=96, last=LOOK_UP_LIFT)
    else:
        sing(violin, n0, LOOK_UP, vel=96, last=LOOK_UP_LIFT)
        for k, notes in FLUTE_ANSWERS.items():
            for at, dur, name in notes:
                flute.note(T(n0 + k) + at, dur * 0.9, midi(name), 84 + (6 if dur >= 1 else 0))
    if number != 1:
        harp_gliss(n0 + 7, VERSE_CH[7], 72)


# ---- Choruses ------------------------------------------------------------------------------
def chorus(n0: int, number: int):
    for k, chord in enumerate(CHORUS_CH):
        n = n0 + k
        harmony[n] = chord
        sequencer(n, chord, 76)
        pad_bar(n, chord, 70)
        piano_chorus(n, chord, 92)
        bass_drive(n, chord, 100)
        strings_bar(n, chord, 84, with_violins=True)
        horns_bar(n, chord, 86 if number == 1 else 94)
        drums(n, "full", crash=k in (0, 4), fill=k == 7)
        if number >= 2:
            choir_bar(n, chord, 80 if number == 2 else 88)
            if k in (0, 4):
                timpani.note(T(n), 1.0, midi(BASS[chord]) + 12, 108)
                timpani.note(T(n) + 0.5, 0.5, midi(BASS[chord]) + 12, 80)
        if number == 3:
            horns.note(T(n) + 0.02, 3.8, midi(HORN_COUNTER[k]), 92)
    last = HOOK_LAND if number != 2 else None
    sing(violin, n0, HOOK, vel=104 if number < 3 else 112, last=last)
    sing(violins, n0, HOOK, vel=84, last=last)
    if number == 3:
        # the harmony: the violins a diatonic third under the held notes of the second half
        for k in (4, 5, 6, 7):
            notes = (HOOK if last is None else HOOK[:-1] + [last])[k]
            at, dur, name = max(notes, key=lambda x: x[1])
            violins.note(T(n0 + k) + at, dur * 0.95, third_below(name, CHORUS_CH[k]), 80)
    harp_gliss(n0 + 7, CHORUS_CH[7], 76)


verse(5, 1)
verse(13, 2)
chorus(21, 1)

# ---- The pale blue dot, 29-36 --------------------------------------------------------------
for k, chord in enumerate(DOT_CH):
    n = 29 + k
    harmony[n] = chord
    pad_bar(n, chord, 66)
    piano_verse(n, chord, 70 + 3 * k)
    celesta.note(T(n), 1.5, midi("D6") if k % 2 == 0 else midi("A5"), 72)
    bass_long(n, chord, 84)
    if k >= 4:
        sequencer(n, chord, 54 + 6 * (k - 4))
        strings_bar(n, chord, 66 + 4 * (k - 4), with_violins=True)
        for i in range(16):  # the snare builds across the last four bars
            kit.note(T(n) + 0.25 * i, 0.05, SNARE, 36 + 12 * (k - 4) + i // 2)
        if k == 7:
            for i in range(16):  # a timpani roll into the verse
                timpani.note(T(n) + 0.25 * i, 0.22, midi("A2"), 50 + 4 * i)
            harp_gliss(n, chord, 76)
    else:
        celli.note(T(n), 3.9, tones(chord)[0] - 12, 60)
sing(violin, 29, DOT_LINE, vel=70)
celli.note(T(36) + 2, 1.9, midi("A2"), 72)

verse(37, 3)
chorus(45, 2)
chorus(53, 3)

# ---- Outro, 61-64: the pulse and pad thin out, back to D at bar 1 --------------------------
for k, chord in enumerate(OUTRO_CH):
    n = 61 + k
    harmony[n] = chord
    sequencer(n, chord, 68 - 4 * k)
    if k < 3:
        pad_bar(n, chord, 64 - 2 * k)
    else:
        pad.note(T(n), 2.6, tones(chord), 58)  # ends before the seam, so bar 1's pad attack is the only pad
    if k < 3:
        bass_long(n, chord, 90)
        celli.note(T(n), 3.9, tones(chord)[0] - 12, 64)
    else:
        bass.note(T(n), 2.4, midi(BASS[chord]), 84)
        celli.note(T(n), 2.4, tones(chord)[0] - 12, 60)
    if k < 2:
        drums(n, "half", crash=k == 0)
harp_ripple(63, "Dmaj7", 66, bars=1)
harp_ripple(64, "Asus4", 64, bars=1)
celesta.note(T(61), 1.5, midi("D6"), 64)
celesta.note(T(63), 1.5, midi("A5"), 60)
violin.note(T(61), 7.6, midi("D5"), 78)
violin.note(T(63), 3.0, midi("F#5"), 80)
violin.note(T(64), 2.4, midi("E5"), 72)

END_BAR = 65
progression = [harmony[n] for n in range(1, END_BAR)]
# The VPO performance violin's dynamics follow CC1 (gain_cc1=34, about 0.27 dB a step), not velocity:
# the verses sit 6 dB under the choruses, the dot 8 dB under. CC1 at 122 or more makes sfizz hold
# one note of this patch for ever (measured 2026-10-29: bar 54's A4 rang to the end), so 118 is the top.
violin.controllers.append((1, [(1, 96), (5, 96), (13, 104), (21, 118), (29, 90), (33, 100), (37, 106), (45, 118), (53, 118), (61, 100)]))


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def surge(patch: str) -> str:
    return f"instrument_backend: {{kind: surge, patch: '{patch}'}}"


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


VPO = "instrument_backend: {{kind: sfz, sfz_glob: '**/Virtual-Playing-Orchestra3/{path}.sfz', settings: {{fold_to_range: false}}}}"
ECHO = round(60000 / BPM * 0.75)  # a dotted eighth
score = f"""schema: ambition.musicir.v3
id: billions_and_billions
title: Billions and Billions
description: >-
  Carl Stargan's song: a cosmic orchestral single in D major at 96 BPM. A
  sixteenth-note pluck sequencer and a synth pad hum under a real orchestra.
  A solo violin has the look-up theme over Dmaj7 and the Lydian E/D, then the
  hook: two eighth pickups vault into held notes that climb D, F#, G, A while
  the bass walks down D C# B A G G A, with a borrowed G minor for the shiver.
  The pale blue dot is the breakdown: the pulse stops, a celesta rings one
  high note over Bbmaj7 C Gm A, the tempo eases to 80 and climbs back
  through a snare and timpani build. Choir and timpani join the second
  chorus; the third adds a horn counter-line and a violin descant. The whole
  song loops. Generated by dev/compose_billions_and_billions.py: edit that,
  not this file.
notes:
  - 'Form: intro 1-4, verse_1 5-12, verse_2 13-20, chorus_1 21-28, dot 29-36, verse_3 37-44, chorus_2 45-52, chorus_3 53-60, outro 61-64; the outro ends on Asus4 and hands to D at bar 1.'
  - 'Tempo: 96, easing to 80 across bar 28 for the dot, back to 96 across bars 33-36.'
  - 'Layered for a room: bed (pulse, pad, piano, harp, bass), drums (kit, timpani), tune (violin, flute, celesta), power (strings, horns, choir).'
seed: 1934
timebase: {{ppq: 960}}
meter: 4/4
tempo:
  bpm: {BPM}
  events:
    - {{from: {{bar: 28, beat: 1}}, to: {{bar: 29, beat: 1}}, bpm: [{BPM}, 80], curve: linear}}
    - {{from: {{bar: 33, beat: 1}}, to: {{bar: 37, beat: 1}}, bpm: [80, {BPM}], curve: linear}}
key: D major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.3, density: 0.3, loopable: true, role: 'pulse, pad, harp ripple'}}
  - {{id: verse_1, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.45, density: 0.5, loopable: true, role: 'the look-up theme, low'}}
  - {{id: verse_2, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.6, density: 0.65, loopable: true, role: 'half-time drums, strings, the theme with harp'}}
  - {{id: chorus_1, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.9, density: 0.85, loopable: true, role: 'the hook: violin and violins, horns, full drums'}}
  - {{id: dot, from: {{bar: 29, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'the pale blue dot, then the build'}}
  - {{id: verse_3, from: {{bar: 37, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.65, density: 0.7, loopable: true, role: 'the theme with a flute answering'}}
  - {{id: chorus_2, from: {{bar: 45, beat: 1}}, to: {{bar: 53, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the hook with choir and timpani'}}
  - {{id: chorus_3, from: {{bar: 53, beat: 1}}, to: {{bar: 61, beat: 1}}, energy: 1.0, density: 1.0, loopable: true, role: 'the hook with a horn counter-line and a descant'}}
  - {{id: outro, from: {{bar: 61, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.4, density: 0.35, loopable: true, role: 'the pulse and pad thin out, on to D at bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: violin, group: violin, program: violin, volume: 110, pan: 64, expression: 112, controls: {{1: 96}}, {sfz("vpo.violin_solo_perf")}}}
  - {{name: violins, group: strings, program: string_ensemble_1, volume: 100, pan: 64, expression: 104, {sfz("strings.violins_1")}}}
  - {{name: violas, group: strings, program: viola, volume: 100, pan: 64, expression: 104, {sfz("strings.violas")}}}
  - {{name: celli, group: strings, program: cello, volume: 102, pan: 64, expression: 106, {sfz("strings.celli")}}}
  - {{name: basses, group: strings, program: contrabass, volume: 100, pan: 64, expression: 104, {sfz("strings.basses")}}}
  - {{name: flute, group: flute, program: flute, volume: 104, pan: 64, expression: 108, controls: {{1: 114}}, {sfz("vpo.flute_solo_perf")}}}
  - {{name: horns, group: horns, program: french_horn, volume: 102, pan: 64, expression: 106, {sfz("orchestra.horns_sustain")}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 98, pan: 64, expression: 102, {sfz("vpo.choir")}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {sfz("vpo.choir_male")}}}
  - {{name: piano, group: piano, program: acoustic_grand_piano, volume: 104, pan: 64, expression: 108, {sfz("freepats.salamander_grand")}}}
  - {{name: harp, group: harp, program: orchestral_harp, volume: 100, pan: 64, expression: 104, {sfz("folk.harp")}}}
  - {{name: celesta, group: celesta, program: celesta, volume: 127, pan: 64, expression: 127, {VPO.format(path="Keys/celesta")}}}
  - {{name: pad, group: pad, program: pad_warm, volume: 96, pan: 64, expression: 100, {surge("Pads/Computers In Space")}}}
  - {{name: pulse, group: pulse, program: lead_square, volume: 96, pan: 64, expression: 100, {surge("Plucks/Diamonds")}}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 116, pan: 64, expression: 116, tuning_correction: {{mode: global, cents: -9.0}}, instrument_backend: {{kind: sfz, sfz_glob: '**/Swagbass/Swagbass/swagbass_clean.sfz', settings: {{fold_to_range: false}}}}}}
  - {{name: timpani, group: timpani, volume: 110, pan: 64, expression: 112, is_drum: true, {sfz("orchestra.timpani")}}}
  - {{name: kit, group: drums, volume: 120, pan: 64, expression: 118, is_drum: true, {sfz("drums.muldjord")}}}
parts:
{part("violin_part", "violin", violin)}
{part("violins_part", "violins", violins)}
{part("violas_part", "violas", violas)}
{part("celli_part", "celli", celli)}
{part("basses_part", "basses", basses)}
{part("flute_part", "flute", flute)}
{part("horns_part", "horns", horns)}
{part("choir_f_part", "choir_f", choir_f)}
{part("choir_m_part", "choir_m", choir_m)}
{part("piano_part", "piano", piano)}
{part("harp_part", "harp", harp)}
{part("celesta_part", "celesta", celesta)}
{part("pad_part", "pad", pad)}
{part("pulse_part", "pulse", pulse)}
{part("bass_part", "bass", bass)}
{part("timpani_part", "timpani", timpani)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    violin:
      chain:
        - {{processor: highpass, cutoff_hz: 160}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 3000, q: 1.0, db: -2.0}}
            - {{type: peak, hz: 6187, q: 6.0, db: -8.0}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.2, attack_ms: 12.0, release_ms: 120.0, knee_db: 6.0}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 8.0}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 0.0}}
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 6.0}}
        - {{processor: balance, position: 0.25}}
    horns:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: -0.2}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 100}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: 0.0}}
    piano:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 12.0, release_ms: 110.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: -0.15}}
    harp:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: 14.0}}
        - {{processor: balance, position: 0.3}}
    celesta:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.35, mix: 0.3}}
        - {{processor: reverb, wet: 0.35, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 16.0}}
        - {{processor: balance, position: 0.2}}
    pad:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -16.0}}
    pulse:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 6166, q: 8.0, db: -18.0}}
            - {{type: peak, hz: 8935, q: 10.0, db: -30.0}}
        - {{processor: lowpass, cutoff_hz: 4500}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.2, mix: 0.16}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.4, attack_ms: 4.0, release_ms: 60.0}}
        - {{processor: gain, gain_db: -9.5}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 85, q: 0.8, db: 1.5}}
            - {{type: peak, hz: 250, q: 0.9, db: -1.0}}
        - {{processor: lowpass, cutoff_hz: 2200}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 2.6, attack_ms: 20.0, release_ms: 120.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: 4.0}}
    timpani:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 5.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 32}}
        - {{processor: high_shelf, hz: 6000, gain_db: 1.0}}
        - {{processor: lowpass, cutoff_hz: 12500}}
        - {{processor: compressor, threshold_db: -16.0, ratio: 2.0, attack_ms: 18.0, release_ms: 90.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.08, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 0.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.4, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [pulse, pad, piano, harp, bass]
    drums: [drums, timpani]
    tune: [violin, flute, celesta]
    power: [strings, horns, choir]
  sections:
    - {{id: song, form: [intro, verse_1, verse_2, chorus_1, dot, verse_3, chorus_2, chorus_3, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

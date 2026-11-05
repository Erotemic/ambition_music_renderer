"""Hands on the Wall: the painted cave room of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_painted_cave_hands_on_the_wall.py scores/active/history_painted_cave_hands_on_the_wall.music.yaml

The painted cave is people at work by torchlight, blowing ochre around
their own hands, drawing horses on the stone thirty thousand years ago.
The cue is lo-fi: a soft swung beat, warm electric piano, an upright bass,
and a recorder that stands in for the bone flutes found in the caves of the
same people. A slit drum and a shaker give the stone a sound. Every melody
is original.

78 BPM, 4/4, the sixteenths swung. F major. Form, 32 bars, about 1:38.
The whole file loops; bar 32's C9 leads to bar 1:
  intro    1-4    the electric piano and the shaker
  draw     5-12   the beat comes in
  flute    13-24  the flute's tune, and the slit drum answers
  torch    25-28  the beat drops: the flute alone with the keys
  outro    29-32  the beat, and C9 to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 78
OUT = Path(sys.argv[1])
rng = random.Random(30000)
SWING = F(1, 3)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: General MIDI drum notes, as the Muldjord kit maps them.
KICK, SNARE, SIDE, HAT, PEDAL_HAT, OPEN_HAT, CRASH, RIDE = 36, 38, 37, 42, 44, 46, 49, 51


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


def sw(beat) -> F:
    """A position in sixteenths moved to its swung place: the second and
    fourth sixteenth of each beat land late."""
    b = F(beat).limit_denominator(16)
    whole = b.numerator // b.denominator
    part = b - whole
    return whole + {F(1, 4): SWING, F(3, 4): F(1, 2) + SWING}.get(part, part)


def T(n: int) -> F:
    """The first beat of bar n, in beats."""
    return F((n - 1) * 4)


SECTION = {n: ("intro" if n <= 4 else "draw" if n <= 12 else "flute" if n <= 24 else "torch" if n <= 28 else "outro")
           for n in range(1, 33)}
LOOP = ["Fmaj7", "Am7", "Bbmaj7", "C9"]
PROG = LOOP * 8
VOICE = {"Fmaj7": ["A3", "C4", "E4", "G4"], "Am7": ["G3", "C4", "E4", "A4"], "Bbmaj7": ["A3", "D4", "F4", "G4"],
         "C9": ["Bb3", "D4", "E4", "G4"]}
ROOT = {"Fmaj7": "F", "Am7": "A", "Bbmaj7": "Bb", "C9": "C"}

keys = Clip(0.006, 5)
bass = Clip(0.005, 4)
flute = Clip(0.006, 4)
kit = Clip(0.005, 6)
shaker = Clip(0.003, 8)
slit = Clip(0.004, 5)

for n in range(1, 33):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    # The keys: the chord just after the beat, and again on the "and" of 3, a little late.
    keys.note(t + F(1, 16), F(3, 2), VOICE[chord], 66)
    keys.note(t + sw(F(5, 2)) + F(1, 32), F(1), VOICE[chord][1:], 58)
    if section != "intro":
        root = midi(f"{ROOT[chord]}2")
        if root > midi("E2"):
            root -= 12
        bass.note(t, F(3, 2), root, 90)
        bass.note(t + sw(F(7, 4)), F(1, 4), root + 12, 70)
        bass.note(t + 2 + F(1, 2), F(1), root + 7, 80)
    for s in range(16):
        shaker.note(t + sw(F(s, 4)), F(1, 8), 60, 50 + (14 if s % 2 == 0 else 0))

#: The flute's tune: (beat, length, note), eight bars.
TUNE = [
    [(0, 1, "C5"), (1, 0.5, "A4"), (1.5, 0.5, "C5"), (2, 2, "E5")],
    [(0, 0.5, "D5"), (0.5, 0.5, "C5"), (1, 1, "A4"), (2, 1.5, "G4"), (3.5, 0.5, "A4")],
    [(0, 1, "D5"), (1, 0.5, "F5"), (1.5, 0.5, "E5"), (2, 1.5, "D5"), (3.5, 0.5, "C5")],
    [(0, 3, "G4"), (3, 0.5, "A4"), (3.5, 0.5, "Bb4")],
    [(0, 1, "C5"), (1, 0.5, "A4"), (1.5, 0.5, "C5"), (2, 1, "F5"), (3, 1, "E5")],
    [(0, 0.5, "D5"), (0.5, 0.5, "E5"), (1, 1, "C5"), (2, 2, "A4")],
    [(0, 1, "Bb4"), (1, 0.5, "D5"), (1.5, 0.5, "F5"), (2, 1, "A5"), (3, 1, "G5")],
    [(0, 3, "E5"), (3, 1, "D5")],
]
for first, rows in ((13, TUNE), (21, TUNE[:4]), (25, TUNE[4:])):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            flute.note(T(first + k) + sw(F(pos)), F(length) * F(9, 10), name, 76 + (6 if pos == 0 else 0))
# The slit drum answers the flute: two notes at each bar's end.
for n in range(13, 25):
    root = midi(f"{ROOT[PROG[n - 1]]}3")
    slit.note(T(n) + 3, F(1, 2), 60 + (n % 2), 76)
    slit.note(T(n) + sw(F(7, 2)), F(1, 2), 61 - (n % 2), 70)

# ---- The beat: soft, swung, the snare late ----------------------------------------------------------
for n in range(1, 33):
    t, section = T(n), SECTION[n]
    if section in ("intro", "torch"):
        continue
    kit.note(t, F(1, 2), KICK, 92)
    kit.note(t + sw(F(9, 4)), F(1, 4), KICK, 74)
    kit.note(t + sw(F(5, 2)), F(1, 2), KICK, 84)
    kit.note(t + 1 + F(1, 24), F(1, 2), SIDE, 88)
    kit.note(t + 3 + F(1, 24), F(1, 2), SIDE, 92)
    for e in range(8):
        kit.note(t + sw(F(e, 2)), F(1, 8), HAT, 52 + (10 if e % 2 == 0 else 0))

END_BAR = 33
for clip in (keys, bass, flute, kit, shaker, slit):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def chain(group: str, highpass: int, wet: float, decay: float) -> str:
    rev = f"\n        - {{processor: reverb, wet: {wet}, decay_seconds: {decay}}}" if wet else ""
    return (f"    {group}:\n      chain:\n        - {{processor: highpass, cutoff_hz: {highpass}}}{rev}"
            f"\n        - {{processor: gain, gain_db: {GAIN[group]}}}")


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"keys": -1.0, "bass": 1.0, "flute": 6.0, "drums": 1.0, "perc": 18.0}
score = f"""schema: ambition.musicir.v3
id: history_painted_cave_hands_on_the_wall
title: Hands on the Wall
description: >-
  The painted cave of the History dimension: people at work by torchlight,
  blowing ochre around their own hands and drawing horses on the stone.
  Lo-fi: a soft swung beat, warm electric piano, an upright bass, and a
  recorder for the bone flutes of the same people; a slit drum and a
  shaker for the stone. F major, 78 BPM. Generated by
  dev/compose_history_painted_cave_hands_on_the_wall.py: edit that, not this file.
notes:
  - 'Form: intro 1-4, draw 5-12, flute 13-24, torch 25-28, outro 29-32; the C9 of bar 32 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (keys, bass, drums, perc), tune (flute).'
seed: 30000
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: F major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.25, density: 0.3, loopable: true, role: 'the keys and the shaker'}}
  - {{id: draw, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.45, density: 0.5, loopable: true, role: 'the beat comes in'}}
  - {{id: flute, from: {{bar: 13, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.55, density: 0.6, loopable: true, role: 'the flute tune, the slit drum'}}
  - {{id: torch, from: {{bar: 25, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.3, density: 0.35, loopable: true, role: 'the flute alone with the keys'}}
  - {{id: outro, from: {{bar: 29, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.45, density: 0.5, loopable: true, role: 'the beat, C9 to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: keys, group: keys, program: electric_piano_1, volume: 104, pan: 56, expression: 104, {sfz("epiano.rhodes")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 112, pan: 64, expression: 112, {sfz("bass.upright")}}}
  - {{name: flute, group: flute, program: recorder, volume: 104, pan: 70, expression: 106, {vcsl("Aerophones/Edge-blown Aerophones/Baroque Alto Recorder - SusVib")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 112, pan: 64, expression: 110, {sfz("drums.muldjord")}}}
  - {{name: shaker, group: perc, is_drum: true, volume: 90, pan: 84, expression: 94, {vcsl("Idiophones/Struck Idiophones/Shaker, Small")}}}
  - {{name: slit, group: perc, is_drum: true, volume: 100, pan: 40, expression: 104, {vcsl("Idiophones/Struck Idiophones/Slit Drum")}}}
parts:
{part("keys_part", "keys", keys)}
{part("bass_part", "bass", bass)}
{part("flute_part", "flute", flute)}
{part("kit_part", "kit", kit)}
{part("shaker_part", "shaker", shaker)}
{part("slit_part", "slit", slit)}
processing:
  groups:
{chain("keys", 100, 0.2, 1.8)}
{chain("bass", 35, 0, 0)}
{chain("flute", 200, 0.28, 2.4)}
{chain("drums", 30, 0.08, 0.9)}
{chain("perc", 200, 0.3, 2.6)}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: lowpass, cutoff_hz: 7000}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.5, attack_ms: 12.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.15}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [keys, bass, drums, perc]
    tune: [flute]
  sections:
    - {{id: song, form: [intro, draw, flute, torch, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

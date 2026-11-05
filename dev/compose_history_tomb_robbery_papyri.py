"""The Tomb Robbery Papyri: the pyramid tomb room of the History
dimension. Writes its MusicIR v3 score:

    python3 dev/compose_history_tomb_robbery_papyri.py scores/active/history_tomb_robbery_papyri.music.yaml

The tomb is where a king meant to stay for ever, and where the robbers
got in anyway: the court records of Thebes (about 1110 BCE) name the men
who did it. So the cue is a heist in the dark: trip-hop. A slow, heavy,
swung beat, an upright bass walking on its toes, a harp that counts the
steps, soft vibraphone, and a low clarinet for the thief who knows the way.
Every melody is original.

84 BPM, 4/4, the sixteenths swung. D minor. Form, 32 bars, about 1:31.
The whole file loops; bar 32's A7 leads to bar 1:
  intro    1-4    the harp and the bass, no drums
  creep    5-12   the beat comes in, the vibraphone
  heist    13-24  the clarinet's tune
  vault    25-28  the beat drops out: the harp, the finger cymbals
  outro    29-32  the beat, and A7 to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 84
OUT = Path(sys.argv[1])
rng = random.Random(1110)
SWING = F(1, 3)  # the second sixteenth of each eighth lands a third of a beat in

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


SECTION = {n: ("intro" if n <= 4 else "creep" if n <= 12 else "heist" if n <= 24 else "vault" if n <= 28 else "outro")
           for n in range(1, 33)}
LOOP = ["Dm", "Dm", "Bb", "A7"]
PROG = LOOP * 8
CHORD = {"Dm": ["D", "F", "A"], "Bb": ["Bb", "D", "F"], "A7": ["A", "C#", "G"], "Gm": ["G", "Bb", "D"]}

harp = Clip(0.003, 4)
vibes = Clip(0.004, 4)
bass = Clip(0.004, 4)
clarinet = Clip(0.006, 4)
kit = Clip(0.004, 6)
cymbals = Clip(0.002, 4)

for n in range(1, 33):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    root = CHORD[chord][0]
    # The harp counts the steps: an arpeggio up in eighths.
    tones = [midi(f"{p}3") for p in CHORD[chord]] + [midi(f"{root}4")]
    for e in range(8):
        harp.note(t + F(e, 2), F(1, 2), tones[[0, 1, 2, 3, 2, 1, 2, 3][e]], 66 if e % 2 else 74)
    # The bass on its toes: root, a rest, the fifth, a step up to the next.
    nxt = CHORD[PROG[n % 32]][0]
    for pos, p, v in ((0, f"{root}2", 92), (F(3, 2), f"{root}2", 76), (2, f"{CHORD[chord][2]}2", 84),
                      (3, f"{root}2", 80), (F(7, 2), None, 76)):
        if p is None:
            target = midi(f"{nxt}2")
            p = target - 1 if target - 1 != midi(f"{root}2") else target + 2
        bass.note(t + pos, F(1, 2) * F(9, 10), p, v)
    if section in ("creep", "heist", "outro"):
        # The vibraphone: a chord on the "and" of 2, soft.
        vibes.note(t + F(3, 2), F(2), [midi(f"{p}4") for p in CHORD[chord]], 62)

#: The thief's tune, low on the clarinet: (beat, length, note), eight bars.
TUNE = [
    [(0, 1.5, "D4"), (1.5, 0.5, "E4"), (2, 1, "F4"), (3, 0.75, "A4"), (3.75, 0.25, "G4")],
    [(0, 2.5, "F4"), (2.5, 0.5, "E4"), (3, 1, "D4")],
    [(0, 1, "Bb3"), (1, 0.5, "D4"), (1.5, 0.5, "F4"), (2, 1.5, "Bb4"), (3.5, 0.5, "A4")],
    [(0, 1, "G4"), (1, 1, "E4"), (2, 1, "C#4"), (3, 1, "A3")],
    [(0, 0.5, "D4"), (0.5, 0.5, "F4"), (1, 1, "A4"), (2, 0.75, "C5"), (2.75, 0.25, "Bb4"), (3, 1, "A4")],
    [(0, 3, "F4"), (3, 0.5, "G4"), (3.5, 0.5, "F4")],
    [(0, 1.5, "D4"), (1.5, 0.5, "F4"), (2, 1, "Bb4"), (3, 1, "D5")],
    [(0, 1, "C#5"), (1, 1, "A4"), (2, 1.5, "E4"), (3.5, 0.5, "C#4")],
]
for first in (13, 21):
    rows = TUNE if first == 13 else TUNE[:4]
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            clarinet.note(T(first + k) + sw(F(pos)), F(length) * F(9, 10), name, 78 + (6 if pos == 0 else 0))

# ---- The beat: heavy, swung, a little late ----------------------------------------------------------------
for n in range(1, 33):
    t, section = T(n), SECTION[n]
    if section in ("intro", "vault"):
        if section == "vault":
            for b in range(4):
                cymbals.note(t + b + F(1, 2), F(1, 4), 60, 70 - 8 * (b % 2))
        if n == 4 or n == 28:
            kit.note(t + 3 + F(1, 2), F(1, 4), SNARE, 60)
            kit.note(t + 3 + F(3, 4), F(1, 4), SNARE, 74)
        continue
    kit.note(t, F(1, 2), KICK, 104)
    kit.note(t + sw(F(7, 4)), F(1, 4), KICK, 82)
    kit.note(t + sw(F(5, 2)), F(1, 2), KICK, 92)
    kit.note(t + 1 + F(1, 32), F(1, 2), SNARE, 100)
    kit.note(t + 3 + F(1, 32), F(1, 2), SNARE, 104)
    for s in range(16):
        if s % 2 and rng.random() < 0.5:
            continue
        kit.note(t + sw(F(s, 4)), F(1, 8), OPEN_HAT if s == 14 and n % 4 == 0 else HAT, 60 + (12 if s % 4 == 0 else 0))
    if n in (5, 13, 29):
        kit.note(t, F(2), CRASH, 88)

END_BAR = 33
for clip in (harp, vibes, bass, clarinet, kit, cymbals):
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
GAIN = {"harp": 6.0, "vibes": 6.0, "bass": -2.0, "clarinet": 12.0, "drums": 0.0}
score = f"""schema: ambition.musicir.v3
id: history_tomb_robbery_papyri
title: The Tomb Robbery Papyri
description: >-
  The pyramid tomb of the History dimension, where a king meant to stay for
  ever and the robbers got in anyway: a heist in the dark, as trip-hop. A
  slow swung beat, an upright bass on its toes, a harp that counts the
  steps, soft vibraphone and a low clarinet. D minor, 84 BPM. Generated by
  dev/compose_history_tomb_robbery_papyri.py: edit that, not this file.
notes:
  - 'Form: intro 1-4, creep 5-12, heist 13-24, vault 25-28, outro 29-32; the A7 of bar 32 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (harp, vibes, bass, drums), tune (clarinet).'
seed: 1110
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.3, density: 0.3, loopable: true, role: 'the harp and the bass'}}
  - {{id: creep, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'the beat comes in'}}
  - {{id: heist, from: {{bar: 13, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.65, density: 0.65, loopable: true, role: 'the clarinet tune'}}
  - {{id: vault, from: {{bar: 25, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.35, density: 0.3, loopable: true, role: 'no beat, finger cymbals'}}
  - {{id: outro, from: {{bar: 29, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'the beat, A7 to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: harp, group: harp, program: orchestral_harp, volume: 104, pan: 52, expression: 106, {vcsl("Chordophones/Composite Chordophones/Concert Harp")}}}
  - {{name: vibes, group: vibes, program: vibraphone, volume: 96, pan: 84, expression: 100, {vcsl("Idiophones/Struck Idiophones/Vibraphone - Soft Mallets")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 114, pan: 64, expression: 114, {sfz("bass.upright")}}}
  - {{name: clarinet, group: clarinet, program: clarinet, volume: 104, pan: 64, expression: 108, {sfz("vpo.clarinet_solo_perf")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 116, pan: 64, expression: 114, {sfz("drums.muldjord")}}}
  - {{name: cymbals, group: drums, is_drum: true, volume: 92, pan: 80, expression: 96, {vcsl("Idiophones/Struck Idiophones/Finger Cymbals")}}}
parts:
{part("harp_part", "harp", harp)}
{part("vibes_part", "vibes", vibes)}
{part("bass_part", "bass", bass)}
{part("clarinet_part", "clarinet", clarinet)}
{part("kit_part", "kit", kit)}
{part("cymbals_part", "cymbals", cymbals)}
processing:
  groups:
{chain("harp", 120, 0.22, 2.0)}
{chain("vibes", 200, 0.3, 2.4)}
{chain("bass", 35, 0, 0)}
{chain("clarinet", 140, 0.24, 2.0)}
{chain("drums", 30, 0.1, 1.0)}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: lowpass, cutoff_hz: 9000}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.5, attack_ms: 12.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.15}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [harp, vibes, bass, drums]
    tune: [clarinet]
  sections:
    - {{id: song, form: [intro, creep, heist, vault, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

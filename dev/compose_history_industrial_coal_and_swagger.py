"""Coal and Swagger: the Industrial Age room of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_industrial_coal_and_swagger.py scores/active/history_industrial_coal_and_swagger.music.yaml

The Industrial Age is the dominant power of its time, sure of itself and
very loud, so its cue is cheeky: electro-swing. A swung big-band hook on
muted trumpets over a walking upright bass and a stride piano, a clarinet
that answers back, and in the middle the factory takes over: four on the
floor, a synth bass, an anvil on the backbeat and the brass chopped into
stabs, like a machine that learned to dance. Every melody is original.

128 BPM, 4/4, swung eighths. G minor. Form, 48 bars, about 1:30. The whole
file loops; bar 48's turnaround leads to bar 1:
  intro    1-4    piano vamp, bass, brushes
  swing    5-20   the trumpet hook, the clarinet answers
  factory  21-28  the machine: kick, synth bass, anvil, brass stabs
  swagger  29-44  the hook with the whole band and a sax counter-line
  outro    45-48  the vamp, and the turnaround to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 128
OUT = Path(sys.argv[1])
rng = random.Random(1830)  # the Liverpool and Manchester Railway opens

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
#: General MIDI drum notes, as the Muldjord kit maps them.
KICK, SNARE, SIDE, HAT, PEDAL_HAT, OPEN_HAT, CRASH, RIDE = 36, 38, 37, 42, 44, 46, 49, 51
#: VCSL Anvil: three strikes.
ANVIL_HI, ANVIL_MID = 60, 61
#: The swing: the second eighth of each beat lands two thirds of the way in.
SWING = F(2, 3)


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


def T(n: int) -> F:
    """The first beat of bar n, in beats."""
    return F((n - 1) * 4)


def sw(beat) -> F:
    """A position in eighths (0, 0.5, 1, ...) moved to its swung place."""
    b = F(beat).limit_denominator(8)
    whole = b.numerator // b.denominator
    part = b - whole
    return whole + (SWING if part == F(1, 2) else part)


SECTION = {n: ("intro" if n <= 4 else "swing" if n <= 20 else "factory" if n <= 28 else "swagger" if n <= 44 else "outro")
           for n in range(1, 49)}

#: One chord a bar. The swing sections take a minor blues with a Neapolitan
#: lift; the factory sits on one chord, as a machine would.
A_PROG = ["Gm", "Gm", "Cm", "Cm", "Gm", "Eb7", "D7", "Gm", "Gm", "Gm", "Cm", "Cm", "Eb7", "D7", "Gm", "D7"]
PROG = (["Gm", "Gm", "Cm", "D7"] + A_PROG + ["Gm"] * 8 + A_PROG + ["Gm", "Cm", "Eb7", "D7"])
assert len(PROG) == 48
CHORD = {
    "Gm": ["G", "Bb", "D"], "Cm": ["C", "Eb", "G"], "Eb7": ["Eb", "G", "Bb", "Db"], "D7": ["D", "F#", "A", "C"],
}
ROOT = {"Gm": "G", "Cm": "C", "Eb7": "Eb", "D7": "D"}

piano = Clip(0.004, 4)
bass = Clip(0.003, 3)
trumpet = Clip(0.006, 4)
clarinet = Clip(0.008, 4)
sax = Clip(0.008, 4)
bones = Clip(0.004, 3)
synth_bass = Clip(0.0, 2)
kit = Clip(0.003, 5)
anvil = Clip(0.0, 3)


def voicing(chord: str, octave: int) -> list[int]:
    """The chord's tones stacked upward from its root in `octave`."""
    out = []
    for p in CHORD[chord]:
        pitch = midi(f"{p}{octave}")
        while out and pitch <= out[-1]:
            pitch += 12
        out.append(pitch)
    return out


# ---- The rhythm section --------------------------------------------------------------------------
for n in range(1, 49):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    root = ROOT[chord]
    if section == "factory":
        # The machine: a synth bass in straight eighths, root and octave.
        for k in range(8):
            synth_bass.note(t + F(k, 2), F(2, 5), f"{root}{2 if k % 2 == 0 else 3}", 92 if k % 2 == 0 else 78)
        continue
    # Stride piano: a low root on 1 and 3, the chord on 2 and 4, a swung pickup.
    loud = {"intro": 70, "swing": 74, "swagger": 80, "outro": 70}[section]
    piano.note(t, F(3, 4), f"{root}2", loud)
    piano.note(t + 1, F(1, 2), voicing(chord, 3), loud - 6)
    piano.note(t + 2, F(3, 4), f"{ROOT[chord]}2" if n % 2 else f"{CHORD[chord][2]}2", loud - 4)
    piano.note(t + 3, F(1, 2), voicing(chord, 3), loud - 6)
    if n % 4 == 0:
        piano.note(t + sw(F(7, 2)), F(1, 4), voicing(chord, 4), loud - 10)
    # Walking bass: root, a chord tone, the fifth, a step into the next bar.
    nxt = ROOT[PROG[n % 48]]
    tones = CHORD[chord]
    walk = [f"{root}2", f"{tones[1]}2", f"{tones[2]}2", None]
    target = midi(f"{nxt}2")
    walk[3] = target + (1 if (target - midi(walk[2])) < 0 else -1)
    for b, p in enumerate(walk):
        bass.note(t + b, F(9, 10), p, 88 if b == 0 else 80)

# ---- The hook ----------------------------------------------------------------------------------------
#: Eight bars of the trumpet hook, in (eighth position, length in beats, note): a
#: cocky call, a fall, and a laugh at the end of each phrase.
HOOK = [
    [(0, 0.5, "D5"), (0.5, 0.5, "G5"), (1, 1, "Bb5"), (2.5, 0.5, "A5"), (3, 1, "G5")],
    [(0.5, 0.5, "F5"), (1, 0.5, "G5"), (1.5, 1.5, "D5")],
    [(0, 0.5, "Eb5"), (0.5, 0.5, "G5"), (1, 1, "C6"), (2.5, 0.5, "Bb5"), (3, 1, "G5")],
    [(0, 2, "A5"), (2.5, 0.5, "F#5"), (3, 0.5, "G5"), (3.5, 0.5, "A5")],
    [(0, 0.5, "Bb5"), (0.5, 0.5, "A5"), (1, 0.5, "G5"), (1.5, 0.5, "F5"), (2, 1, "G5"), (3, 0.5, "D5")],
    [(0, 1.5, "Eb5"), (1.5, 0.5, "F5"), (2, 1, "G5"), (3, 1, "Bb5")],
    [(0, 1, "A5"), (1, 0.5, "C6"), (1.5, 0.5, "A5"), (2, 1, "F#5"), (3, 0.5, "D5")],
    [(0, 2, "G5"), (2.5, 0.5, "D5"), (3, 0.5, "G5")],
]
#: The clarinet's answers: a quick run in the gap of every other bar.
ANSWER = {
    1: [(2, 0.5, "D5"), (2.5, 0.5, "F5"), (3, 0.5, "G5"), (3.5, 0.5, "Bb5")],
    3: [(2, 0.5, "G5"), (2.5, 0.5, "F5"), (3, 0.5, "Eb5"), (3.5, 0.5, "D5")],
    5: [(3, 0.5, "Bb4"), (3.5, 0.5, "C5")],
    7: [(1, 0.5, "Bb5"), (1.5, 0.5, "A5"), (2, 0.5, "G5"), (2.5, 0.5, "F#5"), (3, 1, "G5")],
}


def play_hook(first_bar: int, vel: int, clip: Clip, octave_shift: int = 0):
    for k, bar in enumerate(HOOK):
        for pos, length, name in bar:
            p = midi(name) + 12 * octave_shift
            clip.note(T(first_bar + k) + sw(pos), F(length) * F(9, 10), p, vel + (6 if pos == 0 else 0))


for first in (5, 13):
    play_hook(first, 84, trumpet, -1)
    for k, run in ANSWER.items():
        for pos, length, name in run:
            clarinet.note(T(first + k) + sw(pos), F(length) * F(9, 10), name, 76)
for first in (29, 37):
    play_hook(first, 92, trumpet, -1)
    play_hook(first, 78, sax, -2)
    # The trombones punch the chord on the "and" of 2 and on 4.
    for k in range(8):
        chord = PROG[first + k - 1]
        bones.note(T(first + k) + sw(F(3, 2)), F(1, 3), voicing(chord, 3), 86)
        bones.note(T(first + k) + 3, F(1, 3), voicing(chord, 3), 80)

# ---- The factory --------------------------------------------------------------------------------------
#: The brass chopped into stabs: the hook's first two bars, cut to eighths.
for n in range(21, 29):
    t = T(n)
    if n % 2 == 1:
        for pos, name in ((0, "G4"), (0.5, "G4"), (1.5, "Bb4"), (2.5, "D5"), (3, "C5")):
            bones.note(t + F(pos), F(1, 4), [midi(name) - 12, midi(name)], 90)
    else:
        for pos, name in ((0.5, "F4"), (1, "G4"), (2, "D4")):
            bones.note(t + F(pos), F(1, 4), [midi(name) - 12, midi(name)], 84)
    if n >= 25:
        trumpet.note(t + 3, F(1, 2), "D5", 80)
        trumpet.note(t + F(7, 2), F(1, 2), "G5", 86)

# ---- The drums --------------------------------------------------------------------------------------
for n in range(1, 49):
    t, section = T(n), SECTION[n]
    if section == "factory":
        for b in range(4):
            kit.note(t + b, F(1, 2), KICK, 104)
            kit.note(t + b + F(1, 2), F(1, 4), OPEN_HAT if b % 2 else HAT, 70)
        anvil.note(t + 1, F(1, 2), ANVIL_HI, 88)
        anvil.note(t + 3, F(1, 2), ANVIL_MID, 92)
        kit.note(t + 1, F(1, 4), SNARE, 78)
        kit.note(t + 3, F(1, 4), SNARE, 84)
        continue
    loud = {"intro": 58, "swing": 66, "swagger": 76, "outro": 60}[section]
    # A swing ride: 1, 2 and the swung "and", 3, 4 and the "and".
    for pos in (0, 1, 1.5, 2, 3, 3.5):
        kit.note(t + sw(pos), F(1, 4), RIDE, loud - (8 if pos % 1 else 0))
    kit.note(t + 1, F(1, 4), PEDAL_HAT, loud - 8)
    kit.note(t + 3, F(1, 4), PEDAL_HAT, loud - 8)
    kit.note(t, F(1, 2), KICK, loud + 6)
    kit.note(t + 2, F(1, 2), KICK, loud)
    if section != "intro":
        kit.note(t + 1, F(1, 4), SNARE, loud + 4)
        kit.note(t + 3, F(1, 4), SNARE, loud + 8)
    if n % 8 == 4 or n in (20, 28, 44, 48):
        # A fill into the next phrase: swung snare eighths.
        for pos in (2, 2.5, 3, 3.5):
            kit.note(t + sw(pos), F(1, 4), SNARE, loud + 6)
    if n in (5, 29, 37):
        kit.note(t, F(1), CRASH, loud + 16)

END_BAR = 49
for clip in (piano, bass, trumpet, clarinet, sax, bones, synth_bass, kit, anvil):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def surge(patch: str) -> str:
    return f"instrument_backend: {{kind: surge, patch: '{patch}'}}"


def curve(points: dict[int, float]) -> str:
    body = ", ".join(f"{k}: {v}" for k, v in sorted(points.items()))
    return f"tuning_correction: {{mode: curve, interpolation: linear, max_abs_cents: 50, points: {{{body}}}}}, "


#: The staccato brass samples run flat in places. Measured with `cue
#: tuning_audit` on the notes this cue plays (2026-11-04): trumpet D4 -10,
#: D#4 -6, F4 -9, D5 -7; trombone F#3 -21.
TRUMPET_TUNING = {60: 0, 62: 10, 63: 6, 64: 7, 65: 9, 67: 4, 74: 7, 79: 0}
BONES_TUNING = {52: 0, 54: 21, 55: 0}
#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"piano": -3.0, "bass": -3.0, "brass": 5.0, "reeds": 6.0, "synth": -21.0, "drums": -2.0, "anvil": 8.0}
score = f"""schema: ambition.musicir.v3
id: history_industrial_coal_and_swagger
title: Coal and Swagger
description: >-
  The Industrial Age of the History dimension, the dominant power of its
  time, sure of itself and very loud: electro-swing. A swung hook on
  trumpets over a walking upright bass and a stride piano, a clarinet that
  answers back; in the middle the factory takes over with four on the floor,
  a synth bass, an anvil on the backbeat and the brass chopped into stabs.
  G minor, 128 BPM, swung. Generated by
  dev/compose_history_industrial_coal_and_swagger.py: edit that, not this
  file.
notes:
  - 'Form: intro 1-4, swing 5-20, factory 21-28, swagger 29-44, outro 45-48; the D7 of bar 48 turns around to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (piano, bass, drums), tune (brass, reeds), machine (synth, anvil).'
seed: 1830
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: G minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.4, density: 0.4, loopable: true, role: 'the vamp'}}
  - {{id: swing, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.65, density: 0.6, loopable: true, role: 'the hook and the clarinet'}}
  - {{id: factory, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.85, density: 0.75, loopable: true, role: 'the machine'}}
  - {{id: swagger, from: {{bar: 29, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'the whole band'}}
  - {{id: outro, from: {{bar: 45, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.45, density: 0.4, loopable: true, role: 'the vamp and the turnaround'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: piano, group: piano, program: honky_tonk_piano, volume: 104, pan: 52, expression: 108, {sfz("freepats.upright_piano_kw")}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 112, pan: 64, expression: 112, {sfz("bass.upright")}}}
  - {{name: trumpet, group: brass, program: muted_trumpet, volume: 108, pan: 70, expression: 112, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: bones, group: brass, program: trombone, volume: 104, pan: 58, expression: 108, {curve(BONES_TUNING)}{sfz("orchestra.trombones_staccato")}}}
  - {{name: clarinet, group: reeds, program: clarinet, volume: 104, pan: 76, expression: 108, {sfz("vpo.clarinet_solo_perf")}}}
  - {{name: sax, group: reeds, program: tenor_sax, volume: 104, pan: 54, expression: 108, {sfz("winds.tenor_sax")}}}
  - {{name: synth_bass, group: synth, program: synth_bass_1, volume: 104, pan: 64, expression: 108, {surge("Basses/FM Bass 2")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 118, pan: 64, expression: 116, {sfz("drums.muldjord")}}}
  - {{name: anvil, group: anvil, is_drum: true, volume: 104, pan: 76, expression: 106, {vcsl("Idiophones/Struck Idiophones/Anvil")}}}
parts:
{part("piano_part", "piano", piano)}
{part("bass_part", "bass", bass)}
{part("trumpet_part", "trumpet", trumpet)}
{part("bones_part", "bones", bones)}
{part("clarinet_part", "clarinet", clarinet)}
{part("sax_part", "sax", sax)}
{part("synth_bass_part", "synth_bass", synth_bass)}
{part("kit_part", "kit", kit)}
{part("anvil_part", "anvil", anvil)}
processing:
  groups:
    piano:
      chain:
        - {{processor: highpass, cutoff_hz: 60}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: {GAIN["piano"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    reeds:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["reeds"]}}}
    synth:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["synth"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
    anvil:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: {GAIN["anvil"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 120.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [piano, bass, drums]
    tune: [brass, reeds]
    machine: [synth, anvil]
  sections:
    - {{id: song, form: [intro, swing, factory, swagger, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

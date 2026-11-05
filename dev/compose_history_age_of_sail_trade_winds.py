"""Trade Winds, Bad Intentions: the Age of Sail room of the History
dimension. Writes its MusicIR v3 score:

    python3 dev/compose_history_age_of_sail_trade_winds.py scores/active/history_age_of_sail_trade_winds.music.yaml

The Age of Sail is Europe's empires going to sea: bold, greedy, and very
pleased with itself, so its cue is cheeky: ska. A sea-shanty hook on a horn
section over the offbeat skank of a guitar and a bubbling organ, a bass
that bounces, and in the middle the cannon: half time, toms and timpani,
the horns in B minor. Every melody is original.

160 BPM, 4/4. D major. Form, 48 bars, about 1:12. The whole file loops;
bar 48's A leads to bar 1:
  intro    1-4    drums and the skank
  hook     5-20   the horns' shanty, the organ bubbles
  cannon   21-28  half time: toms, timpani, the horns in B minor
  chorus   29-44  the hook with sax, the whole band
  outro    45-48  the skank, and A to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 160
OUT = Path(sys.argv[1])
rng = random.Random(1600)  # the English East India Company is chartered

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
#: General MIDI drum notes, as the Muldjord kit maps them.
KICK, SNARE, SIDE, HAT, PEDAL_HAT, OPEN_HAT, CRASH, RIDE = 36, 38, 37, 42, 44, 46, 49, 51
HI_TOM, MID_TOM, FLOOR_TOM = 50, 47, 41


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


SECTION = {n: ("intro" if n <= 4 else "hook" if n <= 20 else "cannon" if n <= 28 else "chorus" if n <= 44 else "outro")
           for n in range(1, 49)}
HOOK_PROG = ["D", "A", "Bm", "G", "D", "A", "G", "A"]
CANNON_PROG = ["Bm", "Bm", "G", "F#", "Bm", "Bm", "G", "A"]
PROG = ["D", "D", "G", "A"] + HOOK_PROG * 2 + CANNON_PROG + HOOK_PROG * 2 + ["D", "G", "D", "A"]
assert len(PROG) == 48
CHORD = {"D": ["D", "F#", "A"], "A": ["A", "C#", "E"], "Bm": ["B", "D", "F#"], "G": ["G", "B", "D"],
         "F#": ["F#", "A#", "C#"]}
NOTE["A#"] = 10
ROOT = {k: v[0] for k, v in CHORD.items()}


def voicing(chord: str, octave: int) -> list[int]:
    """The chord's tones stacked upward from its root in `octave`."""
    out = []
    for p in CHORD[chord]:
        pitch = midi(f"{p}{octave}")
        while out and pitch <= out[-1]:
            pitch += 12
        out.append(pitch)
    return out


guitar = Clip(0.003, 4)
organ = Clip(0.003, 3)
bass = Clip(0.003, 3)
trumpet = Clip(0.005, 4)
bones = Clip(0.005, 4)
sax = Clip(0.006, 4)
kit = Clip(0.003, 5)
timpani = Clip(0.0, 2)

# ---- The rhythm section -------------------------------------------------------------------------------
for n in range(1, 49):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    root = ROOT[chord]
    if section == "cannon":
        # Half time: the guitar and organ hold the chord; the bass on 1 and 3.
        guitar.note(t, F(2), voicing(chord, 4), 70)
        organ.note(t, F(4), voicing(chord, 3), 62)
        bass.note(t, F(3, 2), f"{root}2", 96)
        bass.note(t + 2, F(3, 2), f"{root}2", 88)
        continue
    loud = {"intro": 74, "hook": 78, "chorus": 84, "outro": 74}[section]
    # The skank: the chord on every offbeat, short.
    for b in range(4):
        guitar.note(t + b + F(1, 2), F(1, 4), voicing(chord, 4), loud)
    # The organ bubble: low chord on the offbeats, a lighter one on the "e".
    if section in ("hook", "chorus"):
        for b in range(4):
            organ.note(t + b + F(1, 2), F(1, 4), voicing(chord, 3), loud - 14)
            organ.note(t + b + F(3, 4), F(1, 8), voicing(chord, 3), loud - 22)
    # The bass bounces: root, octave, fifth, a step to the next root.
    nxt = ROOT[PROG[n % 48]]
    fifth = CHORD[chord][2]
    line = [(0, f"{root}2"), (F(3, 2), f"{root}3"), (2, f"{fifth}2"), (3, f"{root}2"), (F(7, 2), None)]
    for pos, p in line:
        if p is None:
            target = midi(f"{nxt}2")
            p = target + (2 if midi(f"{root}2") > target else -2)
        bass.note(t + F(pos), F(2, 5), p, 94 if pos == 0 else 84)

# ---- The hook: a shanty for the horns -------------------------------------------------------------
#: (beat, length in beats, note) for eight bars: a rolling call, a swagger,
#: and a laugh at the end.
HOOK = [
    [(0, 1, "A4"), (1, 0.5, "D5"), (1.5, 0.5, "D5"), (2, 1, "D5"), (3, 0.5, "E5"), (3.5, 0.5, "F#5")],
    [(0, 1.5, "E5"), (1.5, 0.5, "C#5"), (2, 1, "A4"), (3, 1, "C#5")],
    [(0, 1, "D5"), (1, 0.5, "F#5"), (1.5, 0.5, "F#5"), (2, 1, "F#5"), (3, 0.5, "E5"), (3.5, 0.5, "D5")],
    [(0, 1.5, "B4"), (1.5, 0.5, "D5"), (2, 2, "G4")],
    [(0, 1, "A4"), (1, 0.5, "D5"), (1.5, 0.5, "D5"), (2, 1, "D5"), (3, 0.5, "F#5"), (3.5, 0.5, "A5")],
    [(0, 1.5, "G5"), (1.5, 0.5, "E5"), (2, 1, "C#5"), (3, 1, "E5")],
    [(0, 0.5, "D5"), (0.5, 0.5, "E5"), (1, 0.5, "F#5"), (1.5, 0.5, "G5"), (2, 1, "B5"), (3, 0.5, "A5"), (3.5, 0.5, "G5")],
    [(0, 1, "F#5"), (1, 1, "E5"), (2, 1.5, "C#5"), (3.5, 0.5, "E5")],
]
#: The cannon's horns in B minor: stabs, with timpani under them.
CANNON = [
    [(0, 0.5, "B4"), (1.5, 0.5, "B4"), (3, 1, "D5")],
    [(0, 0.5, "C#5"), (0.5, 0.5, "D5"), (1, 1, "F#5")],
    [(0, 0.5, "G5"), (1.5, 0.5, "F#5"), (3, 1, "D5")],
    [(0, 1, "C#5"), (1, 1, "A#4"), (2, 2, "F#4")],
    [(0, 0.5, "B4"), (1.5, 0.5, "B4"), (3, 1, "D5")],
    [(0, 0.5, "E5"), (0.5, 0.5, "F#5"), (1, 1, "B5")],
    [(0, 0.5, "G5"), (1, 0.5, "F#5"), (2, 0.5, "E5"), (3, 0.5, "D5")],
    [(0, 2, "C#5"), (2, 1, "E5"), (3, 1, "A4")],
]


D_MAJOR = [midi(f"{p}2") % 12 for p in ("D", "E", "F#", "G", "A", "B", "C#")]


def third_below(p: int) -> int:
    """The note a diatonic third under `p` in D major."""
    step = D_MAJOR.index(p % 12)
    return p - (p % 12 - D_MAJOR[(step - 2) % 7]) % 12


def play(rows, first_bar, clip, vel, shift=0, harmony=False):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            p = midi(name) + shift
            pitches = [p, third_below(p)] if harmony else [p]
            clip.note(T(first_bar + k) + F(pos), F(length) * F(9, 10), pitches, vel + (6 if pos == 0 else 0))


for first in (5, 13):
    play(HOOK, first, trumpet, 82, -12)
    play(HOOK, first, bones, 74, -24)
play(CANNON, 21, trumpet, 86, -12)
play(CANNON, 21, bones, 82, -24)
for first in (29, 37):
    play(HOOK, first, trumpet, 90, -12)
    play(HOOK, first, bones, 80, -24)
    play(HOOK, first, sax, 80, -12, harmony=True)

# ---- The drums ----------------------------------------------------------------------------------------
for n in range(1, 49):
    t, section = T(n), SECTION[n]
    if section == "cannon":
        kit.note(t, F(1, 2), KICK, 100)
        kit.note(t + 2, F(1, 2), SNARE, 96)
        for b, tom in ((1, HI_TOM), (F(3, 2), MID_TOM), (3, FLOOR_TOM), (F(7, 2), FLOOR_TOM)):
            kit.note(t + b, F(1, 4), tom, 84)
        timpani.note(t, F(1), midi(f"{ROOT[PROG[n - 1]]}2"), 100)
        if n % 2 == 0:
            timpani.note(t + 3, F(1, 2), midi(f"{ROOT[PROG[n - 1]]}2"), 86)
        continue
    loud = {"intro": 70, "hook": 76, "chorus": 84, "outro": 70}[section]
    # A ska beat: kick on 1 and 3, the snare's rim on 2 and 4, hats on the offbeats.
    kit.note(t, F(1, 2), KICK, loud + 8)
    kit.note(t + 2, F(1, 2), KICK, loud + 2)
    kit.note(t + 1, F(1, 4), SNARE if section == "chorus" else SIDE, loud + 4)
    kit.note(t + 3, F(1, 4), SNARE if section == "chorus" else SIDE, loud + 6)
    for b in range(4):
        kit.note(t + b + F(1, 2), F(1, 4), OPEN_HAT if b == 3 and n % 2 == 0 else HAT, loud - 8)
    if n in (4, 20, 28, 44, 48):
        for k, tom in enumerate((HI_TOM, HI_TOM, MID_TOM, FLOOR_TOM)):
            kit.note(t + 2 + F(k, 2), F(1, 4), tom, loud + 6)
    if n in (5, 29, 37):
        kit.note(t, F(1), CRASH, loud + 16)

END_BAR = 49
for clip in (guitar, organ, bass, trumpet, bones, sax, kit, timpani):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def curve(points: dict[int, float]) -> str:
    body = ", ".join(f"{k}: {v}" for k, v in sorted(points.items()))
    return f"tuning_correction: {{mode: curve, interpolation: linear, max_abs_cents: 50, points: {{{body}}}}}, "


#: Measured with `cue tuning_audit` on the notes these cues play
#: (2026-11-04): the Swagbass is 7 to 11 cents sharp from G1 to D3; the
#: staccato trumpets are 6 to 10 cents flat from C4 to F4, and D5 7 flat;
#: the staccato trombones' F#3 is 21 cents flat.
SWAG_TUNING = "tuning_correction: {mode: global, cents: -9.0}, "
TRUMPET_TUNING = {55: 0, 60: 10, 61: 10, 62: 10, 63: 6, 64: 8, 65: 9, 67: 4, 74: 7, 79: 0}
BONES_TUNING = {52: 0, 54: 21, 55: 0}


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def surge(patch: str) -> str:
    return f"instrument_backend: {{kind: surge, patch: '{patch}'}}"


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"guitar": 5.5, "organ": -14.0, "bass": 4.0, "brass": 7.0, "sax": 5.0, "drums": 1.0}
#: Shinyguitar's acoustic programs are silent while CC100 (pickup to microphone
#: blend) is 0. The guitars set it, and every sampled backend here is not
#: optional, so a silent one stops the render instead of falling back to General MIDI.
score = f"""schema: ambition.musicir.v3
id: history_age_of_sail_trade_winds
title: Trade Winds, Bad Intentions
description: >-
  The Age of Sail of the History dimension: Europe's empires go to sea,
  bold, greedy and very pleased with themselves, so the cue is ska. A
  sea-shanty hook on a horn section over the offbeat skank of a guitar and
  a bubbling organ; in the middle, the cannon: half time, toms and timpani,
  the horns in B minor. D major, 160 BPM. Generated by
  dev/compose_history_age_of_sail_trade_winds.py: edit that, not this file.
notes:
  - 'Form: intro 1-4, hook 5-20, cannon 21-28, chorus 29-44, outro 45-48; the A of bar 48 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (guitar, organ, bass, drums), tune (brass, sax).'
seed: 1600
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.5, density: 0.4, loopable: true, role: 'drums and the skank'}}
  - {{id: hook, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.75, density: 0.7, loopable: true, role: 'the horns shanty'}}
  - {{id: cannon, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.85, density: 0.6, loopable: true, role: 'half time, toms and timpani'}}
  - {{id: chorus, from: {{bar: 29, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'the hook with sax'}}
  - {{id: outro, from: {{bar: 45, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.5, density: 0.4, loopable: true, role: 'the skank, A to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: guitar, group: guitar, program: clean_guitar, volume: 104, pan: 50, expression: 108, controls: {{100: 126}}, {sfz("guitar.clean")}}}
  - {{name: organ, group: organ, program: drawbar_organ, volume: 100, pan: 88, expression: 104, {surge("Keys/Organ 1")}}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 114, pan: 64, expression: 114, {SWAG_TUNING}{sfz("bass.swag")}}}
  - {{name: trumpet, group: brass, program: trumpet, volume: 108, pan: 72, expression: 112, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: bones, group: brass, program: trombone, volume: 104, pan: 56, expression: 108, {curve(BONES_TUNING)}{sfz("orchestra.trombones_staccato")}}}
  - {{name: sax, group: sax, program: tenor_sax, volume: 104, pan: 64, expression: 108, {sfz("winds.tenor_sax")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 118, pan: 64, expression: 116, {sfz("drums.muldjord")}}}
  - {{name: timpani, group: drums, is_drum: true, volume: 108, pan: 64, expression: 110, {sfz("orchestra.timpani")}}}
parts:
{part("guitar_part", "guitar", guitar)}
{part("organ_part", "organ", organ)}
{part("bass_part", "bass", bass)}
{part("trumpet_part", "trumpet", trumpet)}
{part("bones_part", "bones", bones)}
{part("sax_part", "sax", sax)}
{part("kit_part", "kit", kit)}
{part("timpani_part", "timpani", timpani)}
processing:
  groups:
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: {GAIN["guitar"]}}}
    organ:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: gain, gain_db: {GAIN["organ"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    sax:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: {GAIN["sax"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
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
    bed: [guitar, organ, bass, drums]
    tune: [brass, sax]
  sections:
    - {{id: song, form: [intro, hook, cannon, chorus, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

"""No Return: the fort of the Door of No Return in the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_atlantic_no_return.py scores/active/history_atlantic_no_return.music.yaml

The fort on the Gold Coast is a sober room: the castle of the trading
companies, its dungeon and the door to the sea, through which people were
forced onto the ships of the Atlantic slave trade. The region cues of the
History dimension are walks and dances; none of them is right here. This cue
is quiet and slow, and it does not try to make the room sad for the player:
it keeps still, and leaves room for the words on the walls.

D Aeolian at 56 BPM, 4/4. A low drone of celli and basses; a solo cello
sings a plain lament over D minor, B flat, G minor and A; the voices hum
the chords and then take the tune; a frame drum keeps a slow heartbeat for
a few bars only. At the start and at the end a kalimba plays a few single
notes, from the Africa floor's own instrument, and stops.

Form, 40 bars, about 2:51. The whole file loops:
  still    1-8    the drone, and a few kalimba notes
  lament   9-24   the solo cello, the hummed chords
  voices   25-32  the upper voices take the tune; the cello holds; the heartbeat
  door     33-40  the drone again, the last kalimba notes, back to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 56
OUT = Path(sys.argv[1])
rng = random.Random(1866)  # the year of the last recorded slave voyage to the Americas

NOTE = {"C": 0, "C#": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
#: The kalimba's measured offsets in cents (from dev/compose_history_africa_first_footsteps.py,
#: which measured them on the same VCSL sample).
KALIMBA_TUNING = {59: 9, 60: 9, 61: 10, 62: 10, 63: 0, 72: 0, 73: -19, 74: -19, 75: -27, 76: -27, 77: 0, 84: 0}
F_HAND, F_HIT = 60, 61


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


cello = Clip(0.01, 3)
celli = Clip(0.0, 2)
basses = Clip(0.0, 2)
hum = Clip(0.01, 2)
voices = Clip(0.01, 2)
kalimba = Clip(0.008, 3)
frame = Clip(0.006, 3)
harmony: dict[int, str] = {}

# ---- Harmony -----------------------------------------------------------------------------
#: The chord tones of each chord, for the hummed voices (low to high), and its root.
CHORD = {"Dm": ["D3", "F3", "A3"], "Bb": ["D3", "F3", "Bb3"], "Gm": ["D3", "G3", "Bb3"], "A": ["C#3", "E3", "A3"]}
ROOT = {"Dm": "D2", "Bb": "Bb1", "Gm": "G1", "A": "A1"}
FIFTH = {"Dm": "A2", "Bb": "F2", "Gm": "D2", "A": "E2"}
RING = ["Dm", "Bb", "Gm", "A"]

# ---- The tune ----------------------------------------------------------------------------
#: (beat in the bar, length in beats, note), one list per bar: sixteen bars, four rings of
#: the chords. It rises to B flat once, and comes home low.
TUNE = [
    [(0, 2, "A3"), (2, 1, "D4"), (3, 1, "E4")],
    [(0, 3, "F4"), (3, 1, "D4")],
    [(0, 2, "G4"), (2, 1, "F4"), (3, 1, "E4")],
    [(0, 2, "E4"), (2, 2, "C#4")],
    [(0, 2, "A4"), (2, 1, "G4"), (3, 1, "F4")],
    [(0, 2, "F4"), (2, 2, "D4")],
    [(0, 1, "Bb3"), (1, 1, "D4"), (2, 2, "G4")],
    [(0, 4, "A3")],
    [(0, 2, "D4"), (2, 1, "F4"), (3, 1, "A4")],
    [(0, 3, "Bb4"), (3, 1, "A4")],
    [(0, 2, "G4"), (2, 1, "Bb4"), (3, 1, "A4")],
    [(0, 2, "A4"), (2, 2, "E4")],
    [(0, 2, "F4"), (2, 1, "E4"), (3, 1, "D4")],
    [(0, 2, "D4"), (2, 1, "C4"), (3, 1, "Bb3")],
    [(0, 2, "Bb3"), (2, 1, "A3"), (3, 1, "G3")],
    [(0, 4, "A3")],
]


def sing(clip: Clip, first_bar: int, bars: range, shift: int, vel: int, legato: F = F(19, 20)):
    """The tune's bars `bars` from `first_bar`, `shift` semitones up."""
    for k, i in enumerate(bars):
        for beat, length, name in TUNE[i]:
            # A little swell to the long notes, a little less to the short.
            clip.note(T(first_bar + k) + beat, F(length) * legato, midi(name) + shift, vel + (4 if length >= 2 else -2))


# ---- The drone and the chords ------------------------------------------------------------
for n in range(1, 41):
    if 9 <= n <= 32:
        harmony[n] = RING[(n - 9) % 4]
    else:
        harmony[n] = "Dm"

for n in range(1, 41):
    chord = harmony[n]
    if n <= 8 or n >= 33:
        # The drone: D and A, the celli held two bars at a time, the basses under them.
        if n % 2 == 1:
            soft = 46 if n <= 8 else 50 - 2 * (n - 33)
            celli.note(T(n), 8 * F(19, 20), ["D3", "A3"], soft)
            basses.note(T(n), 8 * F(19, 20), "D2", soft - 4)
    else:
        loud = 54 if n < 25 else 60
        celli.note(T(n), 4 * F(19, 20), [FIFTH[chord], CHORD[chord][1]], loud)
        basses.note(T(n), 4 * F(19, 20), ROOT[chord], loud - 4)
        if n >= 13:
            hum.note(T(n), 4 * F(19, 20), CHORD[chord], 44 if n < 25 else 50)

# ---- The voices --------------------------------------------------------------------------
sing(cello, 9, range(0, 16), 0, 70)
# The upper voices take the first eight bars of the tune an octave up; the cello holds long
# notes under them, the third of each chord.
sing(voices, 25, range(0, 8), 12, 56)
for k, n in enumerate(range(25, 33)):
    third = {"Dm": "F3", "Bb": "D3", "Gm": "Bb2", "A": "C#3"}[harmony[n]]
    cello.note(T(n), 4 * F(19, 20), third, 62)

# ---- The heartbeat -----------------------------------------------------------------------
for n in range(25, 33):
    frame.note(T(n), F(1, 2), F_HIT, 58 - (n - 25))
    frame.note(T(n) + 1, F(1, 2), F_HAND, 44 - (n - 25))

# ---- The kalimba: a few single notes, at the start and the end -------------------------------
for n, beat, name, vel in ((2, 0, "A4", 58), (3, 2, "D5", 54), (4, 1, "F5", 50), (6, 0, "E5", 52), (7, 2, "D5", 48),
                           (34, 0, "A4", 54), (35, 2, "D5", 50), (37, 1, "F5", 46), (38, 3, "E5", 42), (39, 2, "D5", 40)):
    kalimba.note(T(n) + beat, F(5, 3), name, vel)

END_BAR = 41
progression = [harmony[n] for n in range(1, END_BAR)]

# No note is written across the loop seam.
for clip in (cello, celli, basses, hum, voices, kalimba, frame):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def tuning(table: dict) -> str:
    points = ", ".join(f"{k}: {v}" for k, v in sorted(table.items()))
    return f"tuning_correction: {{mode: curve, interpolation: nearest, max_abs_cents: 40, points: {{{points}}}}}"


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"cello": 0.0, "strings": -2.0, "hum": -6.0, "voices": -3.0, "kalimba": 6.0, "frame": -4.0}

PLUCKED = "Idiophones/Plucked Idiophones"
DRUMS = "Membranophones/Struck Membranophones"
score = f"""schema: ambition.musicir.v3
id: history_atlantic_no_return
title: No Return
description: >-
  The fort of the Door of No Return in the History dimension: the castle on
  the Gold Coast where people were held before the ships of the Atlantic
  slave trade. Quiet and slow, D Aeolian at 56 BPM: a drone of celli and
  basses, a solo cello that sings a plain lament over D minor, B flat, G
  minor and A, voices that hum and then take the tune, a slow heartbeat on a
  frame drum for a few bars, and a few single kalimba notes at the start and
  the end. It keeps still and leaves room for the words on the walls.
  Generated by dev/compose_history_atlantic_no_return.py: edit that, not
  this file.
notes:
  - 'Form: still 1-8, lament 9-24, voices 25-32, door 33-40; the drone of bar 39-40 hands to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (the strings group: celli and basses; the hum), tune (cello, voices), colour (kalimba, frame drum).'
seed: 1866
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D aeolian
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: still, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.15, density: 0.15, loopable: true, role: 'the drone and a few kalimba notes'}}
  - {{id: lament, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'the solo cello over the hummed chords'}}
  - {{id: voices, from: {{bar: 25, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.45, density: 0.45, loopable: true, role: 'the voices take the tune; the heartbeat'}}
  - {{id: door, from: {{bar: 33, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.15, density: 0.15, loopable: true, role: 'the drone again and the last kalimba notes'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: cello, group: cello, program: cello, volume: 104, pan: 64, expression: 106, {sfz("strings.cello")}}}
  - {{name: celli, group: strings, program: string_ensemble_1, volume: 98, pan: 64, expression: 100, {sfz("strings.celli")}}}
  - {{name: basses, group: strings, program: contrabass, volume: 100, pan: 64, expression: 100, {sfz("strings.basses")}}}
  - {{name: hum, group: hum, program: choir_aahs, volume: 92, pan: 64, expression: 96, {sfz("vpo.choir_male")}}}
  - {{name: voices, group: voices, program: choir_aahs, volume: 96, pan: 64, expression: 100, {sfz("vpo.choir")}}}
  - {{name: kalimba, group: kalimba, program: kalimba, volume: 100, pan: 64, expression: 104, {tuning(KALIMBA_TUNING)}, {vcsl(PLUCKED + "/Kalimba, Kenya")}}}
  - {{name: frame, group: frame, volume: 100, pan: 64, expression: 100, is_drum: true, {vcsl(DRUMS + "/Frame Drum")}}}
parts:
{part("cello_part", "cello", cello)}
{part("celli_part", "celli", celli)}
{part("basses_part", "basses", basses)}
{part("hum_part", "hum", hum)}
{part("voices_part", "voices", voices)}
{part("kalimba_part", "kalimba", kalimba)}
{part("frame_part", "frame", frame)}
processing:
  groups:
    cello:
      chain:
        - {{processor: highpass, cutoff_hz: 50}}
        - {{processor: compressor, threshold_db: -26.0, ratio: 2.0, attack_ms: 20.0, release_ms: 160.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.2}}
        - {{processor: gain, gain_db: {GAIN["cello"]}}}
        - {{processor: balance, position: -0.1}}
    strings:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: lowpass, cutoff_hz: 4000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.4}}
        - {{processor: gain, gain_db: {GAIN["strings"]}}}
    hum:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - {{processor: reverb, wet: 0.36, decay_seconds: 3.6}}
        - {{processor: gain, gain_db: {GAIN["hum"]}}}
    voices:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.36, decay_seconds: 3.6}}
        - {{processor: gain, gain_db: {GAIN["voices"]}}}
        - {{processor: balance, position: 0.1}}
    kalimba:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.34, decay_seconds: 3.4}}
        - {{processor: gain, gain_db: {GAIN["kalimba"]}}}
        - {{processor: balance, position: 0.15}}
    frame:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: {GAIN["frame"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -20.0, ratio: 2.0, attack_ms: 20.0, release_ms: 160.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      # A held, quiet cue has a low crest: normalized to -1.5 dB of peak it measured -15.8
      # LUFS, louder than the walking cues (-18.6). This room should be the quietest of the
      # History floor, so its peak sits lower.
      - {{processor: limiter, target_peak_db: -6.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [strings, hum]
    tune: [cello, voices]
    colour: [kalimba, frame]
  sections:
    - {{id: song, form: [still, lament, voices, door], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

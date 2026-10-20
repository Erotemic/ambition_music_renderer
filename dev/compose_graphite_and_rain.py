"""Graphite and Rain: a lofi beat to study or relax to. Writes its MusicIR v3
score:

    python3 dev/compose_graphite_and_rain.py scores/active/graphite_and_rain.music.yaml

Jon, 2026-10-19: "a lowfi beat to study and or relax to." Composed from
first principles: D-flat major at 76 BPM, a boom-bap beat with swung,
laid-back sixteenths on a dry kit, ninth and thirteenth chords on a Rhodes
that lean on the ii-V and never quite land on the tonic, an upright bass, a
nylon-string guitar with the tune, a flute that answers it in the second
half, and rain under everything. The Rhodes is resampled and wobbled a
little, like a worn tape.

Form, 4/4 at 76 BPM:
  intro    1-4    the Rhodes alone in the rain.
  first    5-20   the beat, the bass, the guitar's tune.          (loop start)
  second   21-36  a new turn of the chords; the flute takes the tune.
  hush     37-44  the kick drops out; rim, hats and the Rhodes.
  return   45-60  the tune again, the flute an octave above it, and home to the top.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 76
OUT = Path(sys.argv[1])
rng = random.Random(4096)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}

#: The swing: the second sixteenth of each eighth lands this far into it (0.5
#: is straight; 0.58 is a lazy hip-hop swing).
SWING = 0.58
#: How far behind the beat the snare and the tune sit (beats).
LAID_BACK = 0.03


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def swung(beat: float) -> float:
    """`beat` on the swung sixteenth grid."""
    eighth, rest = divmod(beat, 0.5)
    if abs(rest - 0.25) < 1e-6:
        rest = 0.5 * SWING
    return eighth * 0.5 + rest


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
            at += F(rng.uniform(0, self.drift)).limit_denominator(960)
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


rhodes = Clip(drift=0.02, vel_jitter=5)
bass = Clip(drift=0.02, vel_jitter=4)
kit = Clip(drift=0.012, vel_jitter=6)
hats = Clip(drift=0.012, vel_jitter=8)
guitar = Clip(drift=0.025, vel_jitter=5)
flute = Clip(drift=0.02, vel_jitter=4)
rain = Clip()

# ---- Chords: rootless voicings in the middle of the Rhodes ---------------------
VOICING = {
    "Gbmaj9": ["Bb3", "Db4", "F4", "Ab4"],
    "Fm9": ["Ab3", "C4", "Eb4", "G4"],
    "Ebm9": ["Gb3", "Bb3", "Db4", "F4"],
    "Ab13": ["Gb3", "C4", "F4", "Bb4"],
    "Dbmaj9": ["F3", "Ab3", "C4", "Eb4"],
    "Bbm9": ["Ab3", "C4", "Db4", "F4"],
    "Gb6/9": ["Bb3", "Eb4", "Ab4", "Db5"],
    "Absus": ["Gb3", "Bb3", "Db4", "Eb4"],
}
ROOT = {"Gbmaj9": "Gb2", "Fm9": "F2", "Ebm9": "Eb2", "Ab13": "Ab2", "Dbmaj9": "Db2", "Bbm9": "Bb2",
        "Gb6/9": "Gb2", "Absus": "Ab2"}
FIRST = ["Gbmaj9", "Fm9", "Ebm9", "Ab13"]
SECOND = ["Dbmaj9", "Bbm9", "Ebm9", "Ab13", "Gb6/9", "Fm9", "Ebm9", "Absus"]


def comp(n: int, name: str, figure: int, vel=62):
    """One bar of Rhodes: the chord on one, a lazy re-hit, and every other
    bar a push into the next chord on the last swung sixteenth."""
    t = bar(n)
    notes = VOICING[name]
    if figure == 0:
        rhodes.note(t, 1.6, notes, vel + 6)
        rhodes.note(t + swung(2.25), 1.4, notes[1:], vel - 4)
    elif figure == 1:
        rhodes.note(t, 2.6, notes, vel + 4)
        rhodes.note(t + swung(2.75), 1.1, notes[:3], vel - 8)
    else:  # the hush: one long chord, the top voice moving
        rhodes.note(t, 3.8, notes[:3], vel)
        rhodes.note(t + 2, 1.8, notes[3], vel - 6)


def walk(n: int, name: str, nxt: str, busy: bool, vel=82):
    """Upright bass: the root on one, a fifth or octave, and a step into the
    next chord's root on four."""
    t = bar(n)
    root = midi(ROOT[name])
    target = midi(ROOT[nxt])
    bass.note(t, 1.7 if busy else 3.6, root, vel)
    if busy:
        bass.note(t + swung(1.75), 0.6, root + 7, vel - 12)
        bass.note(t + 2.5, 0.9, root + 12 if root + 12 <= midi("C4") else root, vel - 8)
        approach = target - 1 if target - 1 > root else target + 2
        bass.note(t + swung(3.5), 0.45, approach, vel - 10)


KICK, SNARE, RIM, HAT, OPEN_HAT, RIDE = 36, 38, 37, 42, 46, 51


def beat(n: int, style: str):
    """Boom-bap: kick on one and the swung 'and' of two-and-three, the snare
    on two and four a little late, swung sixteenth hats that breathe."""
    t = bar(n)
    if style in ("full", "fill"):
        for o, v in ((0, 96), (swung(1.75), 70), (2.5, 88)):
            kit.note(t + o, 0.2, KICK, v)
        if n % 2 == 0:
            kit.note(t + swung(3.75), 0.15, KICK, 62)
    for o in (1, 3):
        kit.note(t + o + LAID_BACK, 0.2, RIM if style == "hush" else SNARE, 86 if style == "hush" else 92)
    if style != "hush":
        for o in (swung(1.25), swung(2.75)):  # ghost notes
            kit.note(t + o, 0.1, SNARE, 34)
    for i in range(16):
        o = swung(0.25 * i)
        accent = 66 if i % 4 == 0 else (54 if i % 2 == 0 else 40)
        if style == "hush" and i % 2:
            continue
        hats.note(t + o, 0.1, OPEN_HAT if (i == 14 and n % 4 == 0 and style != "hush") else HAT, accent)
    if style == "fill":
        for i, o in enumerate((3.0, swung(3.25), 3.5, swung(3.75))):
            kit.note(t + o + LAID_BACK, 0.12, SNARE, 50 + 10 * i)


# ---- The tune -------------------------------------------------------------------------
# (beat, length, note) per bar; a rest is a bar with nothing in it.
TUNE = [
    [(0.5, 0.5, "Ab4"), (1.0, 0.5, "Bb4"), (1.5, 1.5, "Db5")],
    [(0.0, 0.75, "C5"), (0.75, 0.25, "Ab4"), (1.0, 1.0, "Bb4"), (2.0, 1.0, "Ab4")],
    [(0.0, 0.5, "Gb4"), (0.5, 0.5, "F4"), (1.0, 1.0, "Db4")],
    [(2.0, 0.5, "Eb4"), (2.5, 0.5, "F4"), (3.0, 1.0, "Ab4")],
    [(0.0, 1.5, "Bb4"), (1.5, 0.5, "Ab4"), (2.0, 1.0, "F4"), (3.0, 1.0, "Ab4")],
    [(0.0, 2.0, "G4"), (2.0, 0.5, "Ab4"), (2.5, 0.5, "G4"), (3.0, 1.0, "Eb4")],
    [(0.0, 0.5, "Db4"), (0.5, 0.5, "Eb4"), (1.0, 1.0, "Gb4"), (2.0, 2.0, "Bb4")],
    [(0.0, 3.0, "Ab4")],
]
# The second half's tune: over Db, Bbm, Ebm, Ab; longer notes, higher up.
ANSWER = [
    [(0.0, 1.0, "F5"), (1.0, 0.5, "Eb5"), (1.5, 1.5, "C5")],
    [(0.5, 0.5, "Db5"), (1.0, 0.5, "F5"), (1.5, 2.0, "Ab5")],
    [(0.0, 1.0, "Gb5"), (1.0, 1.0, "F5"), (2.0, 1.0, "Db5"), (3.0, 1.0, "Bb4")],
    [(0.0, 2.5, "C5"), (2.5, 0.5, "Bb4"), (3.0, 1.0, "Ab4")],
    [(0.0, 1.5, "Bb4"), (1.5, 0.5, "Db5"), (2.0, 2.0, "Eb5")],
    [(0.0, 0.5, "F5"), (0.5, 0.5, "Eb5"), (1.0, 1.0, "C5"), (2.0, 2.0, "Ab4")],
    [(0.0, 1.0, "Gb4"), (1.0, 1.0, "Bb4"), (2.0, 1.0, "Db5"), (3.0, 1.0, "F5")],
    [(0.0, 3.5, "Eb5")],
]


def sing(clip: Clip, n: int, phrase, vel=80, octave=0):
    for k, notes in enumerate(phrase):
        for at, length, name in notes:
            clip.note(bar(n + k) + swung(at) + LAID_BACK, length * 0.94, midi(name) + 12 * octave, vel + (6 if at == 0 else 0))


harmony: dict[int, str] = {}


def rain_bed(n0: int, n1: int, vel=40):
    """Rain: two long overlapping drones of the soundfont's rain, so it never stops."""
    for n in range(n0, n1, 4):
        rain.note(bar(n), 16.5 if n + 4 < n1 else (n1 - n) * 4.0, ["C4"], vel)
        rain.note(bar(n) + 8, 16.5 if n + 6 < n1 else max(0.5, (n1 - n - 2) * 4.0), ["G4"], vel - 6)


# Intro, bars 1-4: the Rhodes alone in the rain.
for k in range(4):
    n = 1 + k
    comp(n, FIRST[k], 1, vel=58)
    harmony[n] = FIRST[k]
bass.note(bar(4) + 3.0, 0.9, midi("Ab2"), 70)

# First, bars 5-20: the beat, the bass, the guitar's tune twice.
for k in range(16):
    n = 5 + k
    name = FIRST[k % 4]
    comp(n, name, k % 2)
    walk(n, name, FIRST[(k + 1) % 4], busy=k >= 4)
    beat(n, "fill" if k in (7, 15) else "full")
    harmony[n] = name
sing(guitar, 5, TUNE)
sing(guitar, 13, TUNE, vel=84)

# Second, bars 21-36: the new turn; the flute takes the tune.
for k in range(16):
    n = 21 + k
    name = SECOND[k % 8]
    comp(n, name, k % 2)
    walk(n, name, SECOND[(k + 1) % 8], busy=True)
    beat(n, "fill" if k in (7, 15) else "full")
    harmony[n] = name
sing(flute, 21, ANSWER, vel=74)
sing(flute, 29, ANSWER, vel=78)
# The guitar answers between the flute's phrases, low and short.
for n, lick in ((22, [(2.5, 0.5, "Db4"), (3.0, 0.5, "Eb4"), (3.5, 0.5, "F4")]),
                (26, [(2.5, 0.5, "Ab3"), (3.0, 1.0, "Bb3")]),
                (30, [(2.5, 0.5, "F4"), (3.0, 0.5, "Ab4"), (3.5, 0.5, "Bb4")]),
                (34, [(3.0, 1.0, "C4")])):
    sing(guitar, n, [lick], vel=68)

# Hush, bars 37-44: no kick; rim, hats and the Rhodes's long chords.
for k in range(8):
    n = 37 + k
    name = FIRST[k % 4]
    comp(n, name, 2, vel=58)
    walk(n, name, FIRST[(k + 1) % 4], busy=False, vel=74)
    beat(n, "hush")
    harmony[n] = name
sing(guitar, 41, [TUNE[0], TUNE[1], TUNE[2], []], vel=66)

# Return, bars 45-60: the tune, the flute an octave above it the second time.
for k in range(16):
    n = 45 + k
    name = FIRST[k % 4]
    comp(n, name, k % 2)
    walk(n, name, FIRST[(k + 1) % 4], busy=True)
    beat(n, "fill" if k in (7, 15) else "full")
    harmony[n] = name
sing(guitar, 45, TUNE, vel=82)
sing(guitar, 53, TUNE, vel=82)
sing(flute, 53, TUNE, vel=66, octave=1)

rain_bed(1, 61, 42)

END_BAR = 61
progression = [harmony.get(n, "Gbmaj9") for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


NAKED = "instrument_backend: {kind: sfz, library_ref: drums.naked, settings: {render_timeout_s: 900}}"

score = f"""schema: ambition.musicir.v3
id: graphite_and_rain
title: Graphite and Rain
description: >-
  A lofi beat to study or relax to: D-flat major at 76 BPM, a laid-back
  boom-bap on a dry kit with swung sixteenths, ninth and thirteenth chords on
  a worn Rhodes, an upright bass, a nylon-string guitar with the tune, a
  flute that answers it, and rain. Composed from first principles (Jon,
  2026-10-19). Generated by dev/compose_graphite_and_rain.py: edit that, not
  this file.
notes:
  - 'The chords lean on the ii-V of D-flat and never quite land on it, so the loop keeps going.'
  - 'The intro plays once; the loop is bars 5-60, and its last chord (A-flat sus) leads back to G-flat at bar 5.'
  - 'The rain is the General MIDI soundfont''s rain effect, filtered and quiet.'
seed: 4096
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: Db major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.3, density: 0.25, role: 'the Rhodes alone in the rain'}}
  - {{id: first, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.5, density: 0.5, loopable: true, role: 'the beat; the guitar has the tune'}}
  - {{id: second, from: {{bar: 21, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'a new turn; the flute takes the tune'}}
  - {{id: hush, from: {{bar: 37, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'no kick; rim, hats, long chords'}}
  - {{id: return, from: {{bar: 45, beat: 1}}, to: {{bar: 61, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'the tune again, the flute above it'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: rhodes, group: rhodes, program: electric_piano_1, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, library_ref: epiano.rhodes}}}}
  - {{name: bass, group: bass, program: acoustic_bass, volume: 110, pan: 64, expression: 112, mix_gain_db: 4.0, instrument_backend: {{kind: sfz, library_ref: bass.upright}}}}
  - {{name: kit, group: drums, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: hats, group: hats, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: guitar, group: guitar, program: nylon_guitar, volume: 104, pan: 64, expression: 108}}
  - {{name: flute, group: flute, program: flute, volume: 96, pan: 64, expression: 100, instrument_backend: {{kind: sfz, library_ref: vpo.flute_solo_perf}}}}
  - {{name: rain, group: rain, program: fx_rain, volume: 90, pan: 64, expression: 96}}
parts:
{part("rhodes_part", "rhodes", rhodes)}
{part("bass_part", "bass", bass)}
{part("kit_part", "kit", kit)}
{part("hats_part", "hats", hats)}
{part("guitar_part", "guitar", guitar)}
{part("flute_part", "flute", flute)}
{part("rain_part", "rain", rain)}
processing:
  groups:
    rhodes:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - processor: pedalboard
          effects:
            - {{effect: chorus, rate_hz: 0.45, depth: 0.12, mix: 0.35}}
            - {{effect: resample, target_sample_rate: 22050}}
        - {{processor: lowpass, cutoff_hz: 5200}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 20.0, release_ms: 150.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: -0.15}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 38}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 90, q: 0.8, db: 2.0}}
            - {{type: peak, hz: 700, q: 1.0, db: -1.5}}
        - {{processor: lowpass, cutoff_hz: 2400}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 25.0, release_ms: 140.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -2.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - processor: pedalboard
          effects:
            - {{effect: resample, target_sample_rate: 24000}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 80, q: 1.0, db: 2.0}}
            - {{type: peak, hz: 3000, q: 1.0, db: -2.0}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.0, attack_ms: 15.0, release_ms: 90.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: 0.0}}
    hats:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: gain, gain_db: 12.0}}
        - {{processor: balance, position: 0.2}}
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 110}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 15.0, release_ms: 120.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: -4.2}}
        - {{processor: balance, position: 0.2}}
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: 10.0}}
        - {{processor: balance, position: -0.25}}
    rain:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 4500}}
        - {{processor: gain, gain_db: 4.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 32}}
      - {{processor: lowpass, cutoff_hz: 9000}}
      - {{processor: compressor, threshold_db: -20.0, ratio: 2.5, attack_ms: 20.0, release_ms: 150.0, makeup_db: 2.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.08}}
      - {{processor: limiter, target_peak_db: -2.0, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [rhodes, bass, rain]
    beat: [drums, hats]
    tune: [guitar, flute]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [first, second, hush, return], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

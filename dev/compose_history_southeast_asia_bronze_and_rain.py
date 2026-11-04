"""Bronze and Rain: the Southeast Asia floor of the History dimension
(Sulawesi, the Austronesian islands, Dong Son). Writes its MusicIR v3 score:

    python3 dev/compose_history_southeast_asia_bronze_and_rain.py scores/active/history_southeast_asia_bronze_and_rain.music.yaml

Southeast Asia's own music is the music of bronze: the drums of Dong Son,
and later the gong-chime orchestras of Java and Bali. This cue takes the
idea of a gamelan, not its notes: a cycle of sixteen beats that the big
gong closes, smaller gongs inside it, a core melody one note to a beat,
two parts that interlock above it into one fast line, and a bamboo flute
that floats free over the top. The samples are Western (a marimba, a
vibraphone, a glockenspiel, a recorder), so the scale is the pelog-like
five notes E F G B C of twelve-tone tuning, not a real pelog. Every melody
is original.

84 BPM, 4/4; one gong cycle is four bars. Form, 48 bars, about 2:17. The
whole file loops; the gong at the end of bar 48 is the downbeat of bar 1:
  bronze   1-8    the gongs and the core melody; the drum and the slit drum
  rain     9-24   the interlocking parts come in, quick as rain on leaves
  flute    25-40  the flute's tune over the core; the interlocking thins
  bronze   41-48  everything once more, then the gongs alone, back to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 84
OUT = Path(sys.argv[1])
rng = random.Random(40)  # the year of the Trung sisters' rising

NOTE = {"C": 0, "C#": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
#: VCSL Gong 1: 60 the big gong, 61 a smaller one. VCSL Slit Drum: 60 the high
#: tongue, 61 the low. VCSL Frame Drum: 60 the hand (soft), 61 the hit.
GONG, KEMPUL = 60, 61
SLIT_HI, SLIT_LO = 60, 61
F_HAND, F_HIT = 60, 61
#: The scale, low to high, in one octave: degrees 0..4.
SCALE = [4, 5, 7, 11, 12]  # E F G B C


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def degree_pitch(k: int, base: int) -> int:
    """Scale degree `k` (any integer: it wraps by octaves) above the E of `base`."""
    octave, step = divmod(k, len(SCALE))
    return base + 12 * octave + SCALE[step] - SCALE[0]


def degree_of(pitch: int, base: int) -> int:
    rel = pitch - base
    octave, within = divmod(rel, 12)
    return octave * len(SCALE) + [s - SCALE[0] for s in SCALE].index(within)


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


core = Clip(0.004, 3)       # the marimba: the core melody, one note to a beat
kenong = Clip(0.004, 2)     # the vibraphone: the marks at the end of each bar
polos = Clip(0.003, 3)      # the glockenspiel, first part of the interlocking
sangsih = Clip(0.003, 3)    # the glockenspiel, second part
flute = Clip(0.012, 3)
gong = Clip(0.0, 2)
drum = Clip(0.006, 4)
slit = Clip(0.006, 3)

# ---- The core melody ------------------------------------------------------------------------
#: Two cycles of sixteen beats, A and B, each ending on E, the gong tone.
CYCLE_A = ["G4", "F4", "E4", "F4", "G4", "B4", "C5", "B4", "G4", "F4", "G4", "B4", "C5", "B4", "G4", "E4"]
CYCLE_B = ["B4", "C5", "B4", "G4", "F4", "G4", "F4", "E4", "F4", "G4", "B4", "C5", "B4", "G4", "F4", "E4"]
CYCLES = [CYCLE_A, CYCLE_A, CYCLE_A, CYCLE_B, CYCLE_A, CYCLE_B, CYCLE_A, CYCLE_B, CYCLE_A, CYCLE_B, CYCLE_A, CYCLE_A]
E4 = midi("E4")

#: section of each bar
SECTION = {n: ("bronze" if n <= 8 else "rain" if n <= 24 else "flute" if n <= 40 else "close") for n in range(1, 49)}

beats: list[tuple[F, int]] = []   # (time, pitch) of each core note
for c, cycle in enumerate(CYCLES):
    for i, name in enumerate(cycle):
        beats.append((T(1 + 4 * c) + i, midi(name)))

for k, (t, pitch) in enumerate(beats):
    n = int(t // 4) + 1
    vel = {"bronze": 66, "rain": 70, "flute": 60, "close": 68}[SECTION[n]]
    if n >= 45:
        vel -= 3 * (n - 44)
    if n >= 47:
        continue  # the last two bars are the gongs alone
    core.note(t, F(9, 10), pitch, vel + (6 if k % 4 == 3 else 0))
    # The kenong: on the last beat of each bar, the core note, a little longer.
    if k % 4 == 3:
        kenong.note(t, F(3, 2), pitch, vel - 10)

# ---- The gongs ------------------------------------------------------------------------------
for c in range(len(CYCLES)):
    first = 1 + 4 * c
    # Two strokes of the smaller gong inside the cycle; the big gong closes it.
    gong.note(T(first + 1) + 1, 3, KEMPUL, 54)
    gong.note(T(first + 2) + 1, 3, KEMPUL, 50)
    gong.note(T(first + 3) + 3, 4, GONG, 84 if c not in (0, 11) else 76)

# ---- The interlocking parts ------------------------------------------------------------------
#: Over each beat, four quick notes that lead to the NEXT core note, two octaves up; the
#: first part takes the 1st and 3rd, the second part the 2nd and 4th, so that only
#: together are they one line.
GLOCK_BASE = E4 + 24
for k, (t, pitch) in enumerate(beats):
    n = int(t // 4) + 1
    section = SECTION[n]
    if section not in ("rain", "flute", "close") or n >= 45:
        continue
    if section == "flute" and k % 2:
        continue  # in the flute's section they play only every other beat
    nxt = beats[(k + 1) % len(beats)][1]
    goal = degree_of(nxt, E4)
    figure = [goal + 1, goal, goal - 1, goal]
    vel = 58 if section == "rain" else 50
    for i, d in enumerate(figure):
        clip = polos if i % 2 == 0 else sangsih
        clip.note(t + F(i, 4), F(1, 4), degree_pitch(d, GLOCK_BASE), vel + (4 if i == 3 else 0))

# ---- The flute ------------------------------------------------------------------------------
#: (beat in the bar, length in beats, note), sixteen bars from bar 25; it ends on E with the gong.
TUNE = [
    [(0, 3, "B4"), (3, 1, "C5")],
    [(0, 2, "E5"), (2, 2, "C5")],
    [(0, 1, "B4"), (1, 1, "C5"), (2, 2, "B4")],
    [(0, 4, "G4")],
    [(0, 2, "F4"), (2, 1, "G4"), (3, 1, "B4")],
    [(0, 3, "C5"), (3, 1, "B4")],
    [(0, 2, "G4"), (2, 2, "F4")],
    [(0, 4, "E4")],
    [(0, 2, "G4"), (2, 2, "B4")],
    [(0, 3, "E5"), (3, 1, "F5")],
    [(0, 2, "E5"), (2, 1, "C5"), (3, 1, "B4")],
    [(0, 4, "C5")],
    [(0, 2, "B4"), (2, 2, "G4")],
    [(0, 1, "F4"), (1, 1, "G4"), (2, 2, "B4")],
    [(0, 2, "G4"), (2, 2, "F4")],
    [(0, 4, "E4")],
]
for k, bar in enumerate(TUNE):
    for beat, length, name in bar:
        flute.note(T(25 + k) + beat, F(length) * F(19, 20), name, 70 + (4 if length >= 2 else 0))

# ---- The drums ------------------------------------------------------------------------------
for n in range(1, 47):
    section = SECTION[n]
    loud = {"bronze": 50, "rain": 62, "flute": 54, "close": 60}[section]
    t = T(n)
    drum.note(t, F(1, 2), F_HIT, loud)
    drum.note(t + F(3, 2), F(1, 4), F_HAND, loud - 12)
    drum.note(t + 2, F(1, 2), F_HAND, loud - 8)
    drum.note(t + F(7, 2), F(1, 4), F_HIT, loud - 10)
    if section == "rain" and n % 2 == 0:
        drum.note(t + F(11, 4), F(1, 4), F_HAND, loud - 16)
    # The slit drum: the low tongue at the start of each cycle, the high one before the gong.
    if n % 4 == 1 and section in ("bronze", "close"):
        slit.note(t, F(1, 2), SLIT_LO, 66)
    if n % 4 == 0 and section != "flute":
        slit.note(t + F(5, 2), F(1, 4), SLIT_HI, 54)

END_BAR = 49
# No note is written across the loop seam, except that the big gong of bar 48 rings into
# bar 1 in the renderer's loop; its note ends at the seam here.
for clip in (core, kenong, polos, sangsih, flute, gong, drum, slit):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"core": -4.0, "kenong": 4.0, "glock": 4.0, "flute": 4.0, "gong": 0.0, "drums": 0.0}
STRUCK = "Idiophones/Struck Idiophones"
progression = ["Em"] * (END_BAR - 1)
score = f"""schema: ambition.musicir.v3
id: history_southeast_asia_bronze_and_rain
title: Bronze and Rain
description: >-
  The Southeast Asia floor of the History dimension: Sulawesi, the
  Austronesian islands and Dong Son. The idea of a gamelan, not its notes: a
  sixteen-beat cycle that the big gong closes, smaller gongs inside it, a
  marimba core melody one note to a beat, two glockenspiel parts that
  interlock into one quick line like rain on leaves, a recorder that floats
  free like a bamboo flute, and a frame drum and a slit drum. The pelog-like
  scale E F G B C, 84 BPM. Generated by
  dev/compose_history_southeast_asia_bronze_and_rain.py: edit that, not this
  file.
notes:
  - 'Form: bronze 1-8, rain 9-24, flute 25-40, bronze again 41-48; the gongs of bars 47-48 hand to bar 1.'
  - 'Every melody here is original. The scale is a twelve-tone stand-in for pelog, not a real pelog.'
  - 'Layered for a room: bed (core, kenong, gong), tune (flute, glock), colour (drums).'
seed: 40
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: E phrygian
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: bronze, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.35, density: 0.3, loopable: true, role: 'the gongs and the core melody'}}
  - {{id: rain, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.6, density: 0.7, loopable: true, role: 'the interlocking parts'}}
  - {{id: flute, from: {{bar: 25, beat: 1}}, to: {{bar: 41, beat: 1}}, energy: 0.5, density: 0.5, loopable: true, role: 'the flute over the core'}}
  - {{id: close, from: {{bar: 41, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.4, density: 0.35, loopable: true, role: 'everything once more, then the gongs alone'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: core, group: core, program: marimba, volume: 104, pan: 60, expression: 108, {vcsl(STRUCK + "/Marimba")}}}
  - {{name: kenong, group: kenong, program: vibraphone, volume: 98, pan: 70, expression: 102, {vcsl(STRUCK + "/Vibraphone - Soft Mallets")}}}
  - {{name: polos, group: glock, program: glockenspiel, volume: 96, pan: 44, expression: 100, {vcsl(STRUCK + "/Glockenspiel")}}}
  - {{name: sangsih, group: glock, program: glockenspiel, volume: 96, pan: 84, expression: 100, {vcsl(STRUCK + "/Glockenspiel")}}}
  - {{name: flute, group: flute, program: recorder, volume: 104, pan: 64, expression: 108, {vcsl("Aerophones/Edge-blown Aerophones/Baroque Tenor Recorder - Sustain")}}}
  - {{name: gong, group: gong, is_drum: true, volume: 104, pan: 64, expression: 106, {vcsl(STRUCK + "/Gong 1")}}}
  - {{name: drum, group: drums, is_drum: true, volume: 100, pan: 58, expression: 102, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
  - {{name: slit, group: drums, is_drum: true, volume: 100, pan: 72, expression: 104, {vcsl(STRUCK + "/Slit Drum")}}}
parts:
{part("core_part", "core", core)}
{part("kenong_part", "kenong", kenong)}
{part("polos_part", "polos", polos)}
{part("sangsih_part", "sangsih", sangsih)}
{part("flute_part", "flute", flute)}
{part("gong_part", "gong", gong)}
{part("drum_part", "drum", drum)}
{part("slit_part", "slit", slit)}
processing:
  groups:
    core:
      chain:
        - {{processor: highpass, cutoff_hz: 80}}
        - {{processor: reverb, wet: 0.26, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: {GAIN["core"]}}}
    kenong:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: reverb, wet: 0.32, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: {GAIN["kenong"]}}}
    glock:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: {GAIN["glock"]}}}
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: reverb, wet: 0.34, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: {GAIN["flute"]}}}
    gong:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 3.6}}
        - {{processor: gain, gain_db: {GAIN["gong"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.14}}
      # Struck metal and wood make a high crest, as in Sahul's cue: a fast limiter takes the
      # attack peaks down, so the cue normalizes near the other History cues.
      - {{processor: gain, gain_db: 3.0}}
      - processor: pedalboard
        effects:
          - {{effect: limiter, threshold_db: -6.0, release_ms: 60.0}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [core, kenong, gong]
    tune: [flute, glock]
    colour: [drums]
  sections:
    - {{id: song, form: [bronze, rain, flute, close], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

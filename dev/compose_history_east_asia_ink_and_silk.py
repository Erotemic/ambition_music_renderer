"""Ink and Silk: the courts of East Asia in the History dimension (Song
Hangzhou, Joseon Hanyang, Heian-kyō). Writes its MusicIR v3 score:

    python3 dev/compose_history_east_asia_ink_and_silk.py scores/active/history_east_asia_ink_and_silk.music.yaml

The three courts had their own music: the zithers (guzheng, gayageum,
koto), the bamboo flutes, the bells and the clapper that opens Korean
court music. This cue takes their manner, not their notes: a plucked zither
that bends into its notes, a flute that holds long tones, a slow drum, a
bell at the head of each phrase and a woodblock clapper at the seams. The
zither is a Vietnamese dan tranh, a cousin of all three; the flute is a
recorder, so the scale is the five notes G A C D E of twelve-tone tuning.
Every melody is original.

66 BPM, 4/4. Form, 40 bars, about 2:25. The whole file loops; the clapper
at the end of bar 40 hands to bar 1:
  ink      1-8    the zither alone, the drum under it
  silk     9-24   the flute's tune, the zither below in broken chords
  lantern  25-32  the zither takes the tune, the flute answers
  ink      33-40  the zither alone again, thinning; the bells
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 66
OUT = Path(sys.argv[1])
rng = random.Random(1446)  # the year of the Hunminjeongeum

NOTE = {"C": 0, "C#": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
#: VCSL Bass Drum 1: 60. VCSL Woodblock: 60 the high block, 62 the low.
DRUM = 60
BLOCK_HI, BLOCK_LO = 60, 62


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


zither = Clip(0.006, 4)     # the tune and its ornaments
harp = Clip(0.004, 3)       # the zither's low strings: broken chords
flute = Clip(0.012, 3)
bells = Clip(0.0, 2)
drum = Clip(0.004, 3)
block = Clip(0.0, 2)

SECTION = {n: ("ink" if n <= 8 else "silk" if n <= 24 else "lantern" if n <= 32 else "close") for n in range(1, 41)}
#: The scale, for the grace notes: the note a step below each note.
SCALE = ["G", "A", "C", "D", "E"]


def below(name: str) -> str:
    """The scale note a step under `name`: the zither bends up from it."""
    pitch, octave = name[:-1], int(name[-1])
    i = SCALE.index(pitch)
    return f"{SCALE[i - 1]}{octave - (1 if i == 0 else 0)}"


def pluck(clip: Clip, at, length, name: str, vel: int, *, bend: bool = False):
    """One zither note; with `bend`, a quick grace note a step under it first,
    as a player presses the string to slide into the note."""
    if bend:
        clip.note(at - F(1, 8), F(1, 8), below(name), vel - 18)
    clip.note(at, length, name, vel)


# ---- The tunes: (beat in the bar, length in beats, note, bend) -------------------------------
#: The zither's eight bars, used at the start and, a little changed, at the end.
INK = [
    [(0, 2, "D5", False), (2, 1, "E5", True), (3, 1, "D5", False)],
    [(0, 3, "A4", True), (3, 1, "C5", False)],
    [(0, 1, "D5", False), (1, 1, "C5", False), (2, 2, "A4", False)],
    [(0, 4, "G4", True)],
    [(0, 2, "E5", True), (2, 1, "G5", False), (3, 1, "E5", False)],
    [(0, 2, "D5", False), (2, 2, "C5", True)],
    [(0, 1, "A4", False), (1, 1, "C5", False), (2, 1, "A4", False), (3, 1, "G4", False)],
    [(0, 4, "D4", True)],
]
#: The flute's sixteen bars: long tones, few of them.
SILK = [
    [(0, 4, "G4")], [(0, 2, "A4"), (2, 2, "C5")], [(0, 4, "D5")], [(0, 3, "C5"), (3, 1, "A4")],
    [(0, 4, "G4")], [(0, 2, "E4"), (2, 2, "G4")], [(0, 4, "A4")], [(0, 4, "A4")],
    [(0, 2, "C5"), (2, 2, "D5")], [(0, 4, "E5")], [(0, 2, "G5"), (2, 2, "E5")], [(0, 4, "D5")],
    [(0, 3, "C5"), (3, 1, "D5")], [(0, 2, "A4"), (2, 2, "G4")], [(0, 4, "E4")], [(0, 4, "G4")],
]
#: The zither's tune in the lantern section, eight bars, quicker.
LANTERN = [
    [(0, 1, "G5", True), (1, 1, "E5", False), (2, 1, "D5", False), (3, 1, "E5", False)],
    [(0, 2, "G5", False), (2, 2, "A5", True)],
    [(0, 1, "G5", False), (1, 1, "E5", False), (2, 2, "D5", True)],
    [(0, 3, "C5", False), (3, 1, "D5", False)],
    [(0, 1, "E5", True), (1, 1, "D5", False), (2, 1, "C5", False), (3, 1, "A4", False)],
    [(0, 2, "C5", True), (2, 2, "D5", False)],
    [(0, 1, "E5", False), (1, 1, "D5", False), (2, 1, "C5", False), (3, 1, "A4", False)],
    [(0, 4, "G4", True)],
]
#: The flute's answers in the lantern section: one long note in each even bar.
ANSWER = {26: "D5", 28: "G4", 30: "A4", 32: "D4"}

for k, bar in enumerate(INK):
    for beat, length, name, bend in bar:
        pluck(zither, T(1 + k) + beat, F(length) * F(9, 10), name, 76, bend=bend)
for k, bar in enumerate(INK):
    # The close: the same tune an octave lower in its second half, softer each bar.
    for beat, length, name, bend in bar:
        n = 33 + k
        if k >= 4:
            name = f"{name[:-1]}{int(name[-1]) - 1}"
        pluck(zither, T(n) + beat, F(length) * F(9, 10), name, 74 - 3 * k, bend=bend)
for k, bar in enumerate(SILK):
    for beat, length, name in bar:
        flute.note(T(9 + k) + beat, F(length) * F(19, 20), name, 72 + (4 if length >= 4 else 0))
for k, bar in enumerate(LANTERN):
    for beat, length, name, bend in bar:
        pluck(zither, T(25 + k) + beat, F(length) * F(9, 10), name, 80, bend=bend)
for n, name in ANSWER.items():
    flute.note(T(n), F(4) * F(19, 20), name, 66)

# ---- The broken chords under the flute ---------------------------------------------------------
#: One open chord a bar (a root, its fifth and its octave), as the low strings.
#: The dan tranh's lowest sample is B2, so the G and A chords start an octave up.
CHORDS = {0: ("G3", "D4", "G4"), 1: ("A3", "E4", "A4"), 2: ("C3", "G3", "C4"), 3: ("D3", "A3", "D4")}
ROOTS = [0, 1, 3, 2, 0, 0, 1, 1, 2, 3, 2, 3, 2, 1, 0, 0]
for k, r in enumerate(ROOTS):
    n = 9 + k
    lo, mid, hi = CHORDS[r]
    for beat, name, vel in ((0, lo, 60), (1, mid, 50), (2, hi, 52), (3, mid, 48)):
        harp.note(T(n) + beat, F(3, 2), name, vel)
for n in range(25, 33):
    lo, mid, hi = CHORDS[[0, 1, 2, 3, 2, 2, 1, 0][n - 25]]
    harp.note(T(n), F(2), lo, 54)
    harp.note(T(n) + 2, F(2), mid, 46)

# ---- The bells, the drum and the clapper ---------------------------------------------------------
#: A bell at the head of each phrase of eight bars.
for n, name in ((1, "G4"), (9, "D5"), (17, "A4"), (25, "G4"), (33, "D5")):
    bells.note(T(n), F(4), name, 58)
for n in range(1, 41):
    section = SECTION[n]
    loud = {"ink": 54, "silk": 58, "lantern": 64, "close": 52}[section]
    if n >= 37:
        loud -= 3 * (n - 36)
    drum.note(T(n), F(1), DRUM, loud)
    if section in ("silk", "lantern") and n % 2 == 0:
        drum.note(T(n) + 3, F(1, 2), DRUM, loud - 14)
    if section == "lantern":
        drum.note(T(n) + 2, F(1, 2), DRUM, loud - 10)
        block.note(T(n) + F(7, 2), F(1, 4), BLOCK_HI, 46)
# The clapper: one sharp stroke at each seam, as the bak opens and closes a Korean court piece.
for n in (8, 24, 32, 40):
    block.note(T(n) + 3, F(1, 2), BLOCK_LO, 72)

END_BAR = 41
for clip in (zither, harp, flute, bells, drum, block):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"zither": 4.0, "harp": 7.0, "flute": 0.0, "bells": 4.0, "drums": -7.0}
STRUCK = "Idiophones/Struck Idiophones"
ZITHER = "Chordophones/Zithers/Dan Tranh - Normal"


def curve(points: dict[int, float]) -> str:
    body = ", ".join(f"{k}: {v}" for k, v in sorted(points.items()))
    return f"tuning_correction: {{mode: curve, interpolation: linear, max_abs_cents: 50, points: {{{body}}}}}, "


#: The Dan Tranh samples carry the instrument's own tuning. Measured with
#: `cue tuning_audit` on the notes this cue plays (2026-11-04): D3 +16, A3 +7,
#: D4 +39 and E4 +10 cents sharp, G4 11 flat at a soft touch; the others
#: within 5. Each bad key is pinned between keys at 0, so the correction does
#: not spread to its neighbours.
ZITHER_TUNING = {47: 0, 49: 0, 50: -16, 51: 0, 56: 0, 57: -7, 58: 0, 61: 0, 62: -39, 63: 0, 64: -10, 65: 0, 66: 0,
                 67: 8, 68: 0, 84: 0}
#: The tenor recorder is about 9 cents flat from C5 up.
FLUTE_TUNING = {60: 0, 70: 0, 72: 9, 79: 9, 86: 9}
progression = ["G"] * (END_BAR - 1)
score = f"""schema: ambition.musicir.v3
id: history_east_asia_ink_and_silk
title: Ink and Silk
description: >-
  The courts of East Asia in the History dimension: Song Hangzhou, Joseon
  Hanyang and Heian-kyō. The manner of their court and chamber music, not
  its notes: a plucked zither that bends into its notes, a flute of long
  tones, a slow drum, a bell at the head of each phrase and a woodblock
  clapper at the seams. The five notes G A C D E, 66 BPM. Generated by
  dev/compose_history_east_asia_ink_and_silk.py: edit that, not this file.
notes:
  - 'Form: ink 1-8, silk 9-24, lantern 25-32, ink again 33-40; the clapper of bar 40 hands to bar 1.'
  - 'Every melody here is original. The zither is a dan tranh, a cousin of the guzheng, gayageum and koto.'
  - 'Layered for a room: bed (harp, drums), tune (zither, flute), colour (bells).'
seed: 1446
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: G major pentatonic
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: ink, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.3, density: 0.3, loopable: true, role: 'the zither alone'}}
  - {{id: silk, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.45, density: 0.5, loopable: true, role: 'the flute over broken chords'}}
  - {{id: lantern, from: {{bar: 25, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.6, density: 0.6, loopable: true, role: 'the zither tune, the flute answers'}}
  - {{id: close, from: {{bar: 33, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.3, density: 0.3, loopable: true, role: 'the zither alone, thinning'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: zither, group: zither, program: koto, volume: 108, pan: 54, expression: 110, {curve(ZITHER_TUNING)}{vcsl(ZITHER)}}}
  - {{name: harp, group: harp, program: koto, volume: 100, pan: 76, expression: 102, {curve(ZITHER_TUNING)}{vcsl(ZITHER)}}}
  - {{name: flute, group: flute, program: shakuhachi, volume: 104, pan: 64, expression: 108, {curve(FLUTE_TUNING)}{vcsl("Aerophones/Edge-blown Aerophones/Baroque Tenor Recorder - SusVib")}}}
  - {{name: bells, group: bells, program: tubular_bells, volume: 96, pan: 70, expression: 100, {vcsl(STRUCK + "/Tubular Bells 1")}}}
  - {{name: drum, group: drums, is_drum: true, volume: 104, pan: 60, expression: 104, {vcsl("Membranophones/Struck Membranophones/Bass Drum 1")}}}
  - {{name: block, group: drums, is_drum: true, volume: 96, pan: 70, expression: 100, {vcsl(STRUCK + "/Woodblock")}}}
parts:
{part("zither_part", "zither", zither)}
{part("harp_part", "harp", harp)}
{part("flute_part", "flute", flute)}
{part("bells_part", "bells", bells)}
{part("drum_part", "drum", drum)}
{part("block_part", "block", block)}
processing:
  groups:
    zither:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: {GAIN["zither"]}}}
    harp:
      chain:
        - {{processor: highpass, cutoff_hz: 70}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.8}}
        - {{processor: gain, gain_db: {GAIN["harp"]}}}
    flute:
      chain:
        - {{processor: highpass, cutoff_hz: 180}}
        - {{processor: reverb, wet: 0.36, decay_seconds: 3.2}}
        - {{processor: gain, gain_db: {GAIN["flute"]}}}
    bells:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.36, decay_seconds: 3.6}}
        - {{processor: gain, gain_db: {GAIN["bells"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.2}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.14}}
      - {{processor: gain, gain_db: 3.0}}
      - processor: pedalboard
        effects:
          - {{effect: limiter, threshold_db: -6.0, release_ms: 60.0}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [harp, drums]
    tune: [zither, flute]
    colour: [bells]
  sections:
    - {{id: song, form: [ink, silk, lantern, close], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

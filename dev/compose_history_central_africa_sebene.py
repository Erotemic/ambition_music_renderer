"""Sebene: Kongo and Ndongo in the History dimension. Writes its MusicIR
v3 score:

    python3 dev/compose_history_central_africa_sebene.py scores/active/history_central_africa_sebene.music.yaml

The cue is Congolese rumba, the music of Kinshasa and Brazzaville (on
UNESCO's list since 2021), out of time by four centuries and proud of it.
A rumba first: a slow guitar song over a soft beat. Then the sebene, the
fast part where the guitars run in bright interlocking lines over the
cavacha (a running snare and hi-hat), and a likembe (thumb piano) answers.
Every melody is original.

132 BPM, 4/4. C major. Form, 48 bars, about 1:27. The whole file loops;
bar 48's G leads to bar 1:
  intro     1-4    likembe alone, then the bass
  rumba     5-12   the guitar song, a soft beat
  sebene    13-28  the cavacha; the lead guitar's runs; the brass
  likembe   29-32  the drums drop; the likembe solo
  sebene    33-44  the runs again, all in
  outro     45-48  the cavacha, and G to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 132
OUT = Path(sys.argv[1])
rng = random.Random(1526)  # Afonso's letters

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


def T(n: int) -> F:
    """The first beat of bar n, in beats."""
    return F((n - 1) * 4)


SECTION = {}
for n in range(1, 49):
    SECTION[n] = ("intro" if n <= 4 else "rumba" if n <= 12 else "sebene" if n <= 28 else "likembe" if n <= 32
                  else "sebene2" if n <= 44 else "outro")
LOOP = ["C", "F", "G", "F"]
PROG = LOOP * 12
CHORD = {"C": ["C", "E", "G"], "F": ["F", "A", "C"], "G": ["G", "B", "D"]}
#: The likembe has no sample of its own on F#4, B4, F#5 or A5: its lines keep off them.
LIKEMBE_OK = {60, 62, 64, 65, 67, 69, 72, 74, 76, 77, 79}

rhythm = Clip(0.002, 4)
lead = Clip(0.003, 4)
bass = Clip(0.003, 4)
likembe = Clip(0.003, 5)
brass = Clip(0.004, 4)
kit = Clip(0.002, 5)


def tones(chord: str, octave: int) -> list[int]:
    out = []
    for p in CHORD[chord]:
        x = midi(f"{p}{octave}")
        while out and x <= out[-1]:
            x += 12
        out.append(x)
    return out


# ---- The likembe: a ring of plucked notes, two bars a phrase ------------------------------------
RING = {"C": [72, 67, 76, 67, 74, 67, 76, 79], "F": [72, 69, 77, 69, 74, 69, 77, 72],
        "G": [74, 67, 79, 67, 74, 67, 77, 76]}
for n in range(1, 49):
    chord, section = PROG[n - 1], SECTION[n]
    if section in ("rumba",):
        continue
    vel = 84 if section in ("intro", "likembe") else 66
    for e, p in enumerate(RING[chord]):
        assert p in LIKEMBE_OK, p
        likembe.note(T(n) + F(e, 2), F(1, 2), p, vel + (8 if e % 4 == 0 else 0))

# ---- The rhythm guitar and the bass ---------------------------------------------------------------
for n in range(1, 49):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    root = midi(f"{CHORD[chord][0]}2")
    fifth = midi(f"{CHORD[chord][2]}2")
    if section == "intro":
        if n >= 3:
            bass.note(t, F(2), root, 88)
            bass.note(t + 2, F(2), fifth, 80)
        continue
    if section == "rumba":
        # The rumba: a lilting bass and a strummed guitar on 1, the "and" of 2, and 4.
        bass.note(t, F(3, 2), root, 92)
        bass.note(t + F(3, 2), F(1, 2), fifth, 80)
        bass.note(t + 2, F(1), root + 12, 84)
        bass.note(t + 3, F(1), fifth, 80)
        for pos in (0, F(3, 2), 3):
            rhythm.note(t + pos, F(1, 2), tones(chord, 4), 72)
        continue
    if section == "likembe":
        bass.note(t, F(1), root, 90)
        bass.note(t + 2, F(1), fifth, 82)
        continue
    # The sebene: the bass walks in eighths; the rhythm guitar picks the chord in sixteenths.
    for e, off in enumerate((0, 0, 7, 12, 0, 7, 12, 7)):
        bass.note(t + F(e, 2), F(2, 5), root + off, 94 if e % 4 == 0 else 82)
    ch = tones(chord, 4)
    for s in range(16):
        rhythm.note(t + F(s, 4), F(1, 6), ch[[0, 2, 1, 2][s % 4]] + (12 if s % 8 >= 4 else 0), 70 if s % 4 == 0 else 58)

# ---- The lead guitar: the song, then the sebene's runs ---------------------------------------------
SONG = [
    [(0, 1.5, "E5"), (1.5, 0.5, "D5"), (2, 1, "C5"), (3, 1, "E5")],
    [(0, 1, "F5"), (1, 0.5, "A5"), (1.5, 0.5, "G5"), (2, 2, "F5")],
    [(0, 1, "D5"), (1, 0.5, "E5"), (1.5, 0.5, "F5"), (2, 1, "G5"), (3, 1, "B4")],
    [(0, 3, "C5"), (3, 1, "A4")],
    [(0, 1.5, "E5"), (1.5, 0.5, "G5"), (2, 1, "C6"), (3, 1, "B5")],
    [(0, 1, "A5"), (1, 0.5, "G5"), (1.5, 0.5, "F5"), (2, 2, "A5")],
    [(0, 1, "G5"), (1, 0.5, "F5"), (1.5, 0.5, "E5"), (2, 1, "D5"), (3, 1, "B4")],
    [(0, 2, "C5"), (2, 2, "D5")],
]
#: A run of the sebene: two bars, sixteenths falling and climbing over C F, then G F.
RUN_A = ["G5", "E5", "C5", "E5", "G5", "C6", "G5", "E5", "A5", "F5", "C5", "F5", "A5", "C6", "A5", "F5"]
RUN_B = ["B5", "G5", "D5", "G5", "B5", "D6", "B5", "G5", "C6", "A5", "F5", "A5", "C6", "A5", "G5", "E5"]


def play(rows, first_bar, clip, vel, shift=0):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            clip.note(T(first_bar + k) + F(pos), F(length) * F(9, 10), midi(name) + shift, vel + (6 if pos == 0 else 0))


play(SONG, 5, lead, 82)
for n in list(range(13, 29, 2)) + list(range(33, 45, 2)):
    for k, run in enumerate((RUN_A, RUN_B)):
        for s, name in enumerate(run):
            if s % 2 == 1 and n % 4 == 1 and k == 1:
                continue
            lead.note(T(n + k) + F(s, 4), F(1, 5), name, 80 + (8 if s % 4 == 0 else 0))
# The brass: stabs on the "and" of 4 in the sebene, every other bar.
for n in list(range(13, 29)) + list(range(33, 45)):
    if n % 2 == 0:
        brass.note(T(n) + F(7, 2), F(1, 3), tones(PROG[n % 48], 4), 88)

# ---- The drums: a soft rumba, then the cavacha ------------------------------------------------------
for n in range(1, 49):
    t, section = T(n), SECTION[n]
    if section == "intro" or section == "likembe":
        if section == "likembe":
            for b in range(4):
                kit.note(t + b + F(1, 2), F(1, 8), HAT, 58)
        continue
    if section == "rumba":
        kit.note(t, F(1, 2), KICK, 84)
        kit.note(t + F(3, 2), F(1, 2), KICK, 72)
        kit.note(t + 2 + F(1, 2), F(1, 4), SIDE, 78)
        kit.note(t + 3, F(1, 2), KICK, 76)
        for e in range(8):
            kit.note(t + F(e, 2), F(1, 8), HAT, 50 + (8 if e % 2 == 0 else 0))
        continue
    loud = {"sebene": 88, "sebene2": 94, "outro": 86}[section]
    # The cavacha: the snare (or its rim) on every eighth, accents on the off-beats; the kick on the beat.
    for e in range(8):
        kit.note(t + F(e, 2), F(1, 4), SNARE if e % 2 else SIDE, loud - (4 if e % 2 else 14))
    for b in range(4):
        kit.note(t + b, F(1, 2), KICK, loud + (8 if b in (0, 2) else 0))
    for s in range(16):
        kit.note(t + F(s, 4), F(1, 8), HAT, loud - 26 + (8 if s % 2 == 0 else 0))
    if n in (13, 33, 45):
        kit.note(t, F(2), CRASH, loud + 12)

END_BAR = 49
for clip in (rhythm, lead, bass, likembe, brass, kit):
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


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, optional: false, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def surge(patch: str) -> str:
    return f"instrument_backend: {{kind: surge, patch: '{patch}'}}"


#: The Kenyan kalimba's own tuning, measured for `history_atlantic_no_return`.
KALIMBA_TUNING = {59: 9, 60: 9, 61: 10, 62: 10, 63: 0, 72: 0, 73: -19, 74: -19, 75: -27, 76: -27, 77: 0, 84: 0}
#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"rhythm": 7.5, "lead": 8.5, "bass": 3.0, "likembe": 10.0, "brass": 8.0, "drums": 0.0}
#: Shinyguitar's acoustic programs are silent while CC100 (pickup to microphone
#: blend) is 0. The guitars set it, and every sampled backend here is not
#: optional, so a silent one stops the render instead of falling back to General MIDI.
score = f"""schema: ambition.musicir.v3
id: history_central_africa_sebene
title: Sebene
description: >-
  Kongo and Ndongo in the History dimension: Congolese rumba, four
  centuries early and proud of it. A slow rumba song first; then the
  sebene, where bright guitars run in interlocking lines over the cavacha
  (a running snare and hi-hat), and a likembe (thumb piano) answers.
  C major, 132 BPM. Generated by dev/compose_history_central_africa_sebene.py:
  edit that, not this file.
notes:
  - 'Form: intro 1-4, rumba 5-12, sebene 13-28, likembe 29-32, sebene 33-44, outro 45-48; the G of bar 48 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (rhythm, bass, likembe, drums), tune (lead, brass).'
seed: 1526
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: C major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.35, density: 0.3, loopable: true, role: 'likembe, then bass'}}
  - {{id: rumba, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.55, density: 0.5, loopable: true, role: 'the guitar song'}}
  - {{id: sebene, from: {{bar: 13, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.9, density: 0.9, loopable: true, role: 'the cavacha and the runs'}}
  - {{id: likembe, from: {{bar: 29, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.45, density: 0.4, loopable: true, role: 'the likembe solo'}}
  - {{id: sebene2, from: {{bar: 33, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the runs, all in'}}
  - {{id: outro, from: {{bar: 45, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.8, density: 0.8, loopable: true, role: 'the cavacha, G to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: rhythm, group: rhythm, program: clean_guitar, volume: 100, pan: 48, expression: 104, controls: {{100: 126}}, {sfz("guitar.clean")}}}
  - {{name: lead, group: lead, program: clean_guitar, volume: 104, pan: 80, expression: 108, controls: {{100: 126}}, {sfz("guitar.clean")}}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 114, pan: 64, expression: 114, {SWAG_TUNING}{sfz("bass.swag")}}}
  - {{name: likembe, group: likembe, program: kalimba, volume: 104, pan: 64, expression: 106, {curve(KALIMBA_TUNING)}{vcsl("Idiophones/Plucked Idiophones/Kalimba, Kenya")}}}
  - {{name: brass, group: brass, program: brass_section, volume: 104, pan: 70, expression: 108, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 116, pan: 64, expression: 114, {sfz("drums.muldjord")}}}
parts:
{part("rhythm_part", "rhythm", rhythm)}
{part("lead_part", "lead", lead)}
{part("bass_part", "bass", bass)}
{part("likembe_part", "likembe", likembe)}
{part("brass_part", "brass", brass)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    rhythm:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["rhythm"]}}}
    lead:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: {GAIN["lead"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    likembe:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["likembe"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.08, decay_seconds: 0.9}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 110.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.15}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [rhythm, bass, likembe, drums]
    tune: [lead, brass]
  sections:
    - {{id: song, form: [intro, rumba, sebene, likembe, sebene2, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

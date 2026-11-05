"""Floating World: Edo and Meiji Tokyo in the History dimension. Writes
its MusicIR v3 score:

    python3 dev/compose_history_japan_floating_world.py scores/active/history_japan_floating_world.music.yaml

Edo's 'floating world' (ukiyo) was the city's pleasure quarter, its
theatre and its prints: a good time, and it knew it. Its cue is city pop,
Tokyo's own sound a century later: glossy major-seventh chords on electric
piano, a cutting guitar, a busy bass, brass stabs and a bright synth hook;
and a shamisen, Edo's instrument, answers the hook and takes the bridge.
Every melody is original.

112 BPM, 4/4. E major. Form, 40 bars, about 1:26. The whole file loops;
bar 40's B11 leads to bar 1:
  intro    1-4    electric piano and shamisen
  verse    5-12   the band, the guitar cuts
  chorus   13-20  the synth hook, brass, the shamisen answers
  bridge   21-28  half time: the shamisen's solo
  chorus   29-36  the hook again, all in
  outro    37-40  the groove, and B11 to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 112
OUT = Path(sys.argv[1])
rng = random.Random(1831)  # the Great Wave

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
for n in range(1, 41):
    SECTION[n] = ("intro" if n <= 4 else "verse" if n <= 12 else "chorus" if n <= 20 else "bridge" if n <= 28
                  else "chorus2" if n <= 36 else "outro")
VERSE = ["Emaj7", "C#m7", "Amaj7", "B11"]
CHORUS = ["Amaj7", "G#m7", "F#m7", "B11", "Amaj7", "G#m7", "C#m7", "B11"]
BRIDGE = ["C#m7", "C#m7", "Amaj7", "Amaj7", "F#m7", "F#m7", "B11", "B11"]
PROG = ["Emaj7", "C#m7", "Amaj7", "B11"] + VERSE * 2 + CHORUS + BRIDGE + CHORUS + ["Emaj7", "C#m7", "Amaj7", "B11"]
assert len(PROG) == 40
#: Voicings for the electric piano, in the middle of the keyboard.
VOICE = {"Emaj7": ["G#3", "B3", "D#4", "F#4"], "C#m7": ["G#3", "B3", "E4"], "Amaj7": ["G#3", "C#4", "E4"],
         "B11": ["A3", "C#4", "E4", "F#4"], "G#m7": ["F#3", "B3", "D#4"], "F#m7": ["E3", "A3", "C#4"]}
ROOT = {"Emaj7": "E", "C#m7": "C#", "Amaj7": "A", "B11": "B", "G#m7": "G#", "F#m7": "F#"}

keys = Clip(0.004, 4)
guitar = Clip(0.002, 5)
bass = Clip(0.003, 4)
lead = Clip(0.004, 4)
brass = Clip(0.004, 4)
shamisen = Clip(0.004, 5)
kit = Clip(0.002, 5)

# ---- The rhythm section ---------------------------------------------------------------------------
#: The bass: (sixteenth, length in sixteenths, semitones over the root).
BASS_BAR = [(0, 3, 0), (3, 1, 12), (4, 2, 0), (6, 1, 7), (8, 2, 10), (10, 1, 12), (11, 1, 7), (12, 2, 5), (14, 2, 7)]
for n in range(1, 41):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    root = midi(f"{ROOT[chord]}1")
    if root < midi("E1"):
        root += 12
    if section == "intro":
        keys.note(t, F(4), VOICE[chord], 70)
        continue
    if section == "bridge":
        keys.note(t, F(4), VOICE[chord], 66)
        bass.note(t, F(3, 2), root, 96)
        bass.note(t + 2 + F(1, 2), F(1), root + 7, 84)
        continue
    for s, length, off in BASS_BAR:
        bass.note(t + F(s, 4), F(length, 4) * F(4, 5), root + off, 98 if s in (0, 8) else 84)
    # The electric piano pushes: the chord on the "and" of 4 of the bar before, held.
    keys.note(t, F(3, 2), VOICE[chord], 72)
    keys.note(t + F(5, 2), F(3, 2), VOICE[chord], 66)
    # The cutting guitar: short chords on the sixteenths, accents on 2 and 4.
    v = [midi(p) + 12 for p in VOICE[chord][:3]]
    for s in range(16):
        if s % 4 == 3:
            continue
        guitar.note(t + F(s, 4), F(1, 8), v, 80 if s in (4, 12) else 58)

# ---- The hook and the brass -----------------------------------------------------------------------
#: (beat, length, note) over Amaj7 G#m7 F#m7 B11 Amaj7 G#m7 C#m7 B11.
HOOK = [
    [(0, 0.5, "E5"), (0.5, 0.5, "F#5"), (1, 1, "G#5"), (2.5, 0.5, "B5"), (3, 1, "G#5")],
    [(0, 1.5, "F#5"), (1.5, 0.5, "D#5"), (2, 2, "B4")],
    [(0, 0.5, "C#5"), (0.5, 0.5, "E5"), (1, 1, "F#5"), (2.5, 0.5, "A5"), (3, 1, "G#5")],
    [(0, 3, "F#5")],
    [(0, 0.5, "E5"), (0.5, 0.5, "F#5"), (1, 1, "G#5"), (2.5, 0.5, "B5"), (3, 1, "C#6")],
    [(0, 1.5, "B5"), (1.5, 0.5, "G#5"), (2, 2, "D#5")],
    [(0, 0.5, "E5"), (0.5, 0.5, "G#5"), (1, 1, "B5"), (2, 1, "G#5"), (3, 1, "E5")],
    [(0, 2, "F#5"), (2, 2, "D#5")],
]
#: The shamisen answers in the gaps of the hook: (bar offset, beat, length, note).
ANSWER = [(3, 3, 0.25, "B4"), (3, 3.25, 0.25, "C#5"), (3, 3.5, 0.5, "E5"),
          (7, 2.5, 0.25, "B4"), (7, 2.75, 0.25, "A4"), (7, 3, 0.5, "F#4"), (7, 3.5, 0.5, "B4")]


def play(rows, first_bar, clip, vel, shift=0):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            clip.note(T(first_bar + k) + F(pos), F(length) * F(9, 10), midi(name) + shift, vel + (6 if pos == 0 else 0))


for first, vel in ((13, 86), (29, 92)):
    play(HOOK, first, lead, vel)
    for k, beat, length, name in ANSWER:
        shamisen.note(T(first + k) + F(beat), F(length), name, 90)
    # The brass: stabs on the "and" of 2 and on 4, a sixth under the hook's chord.
    for k in range(8):
        chord = PROG[first + k - 1]
        tones = [midi(p) + 12 for p in VOICE[chord][:3]]
        brass.note(T(first + k) + F(3, 2), F(1, 3), tones, vel)
        brass.note(T(first + k) + 3, F(1, 3), tones, vel - 6)
# The intro: the shamisen alone over the piano, a phrase in each bar.
for n, phrase in ((1, ["B4", "E5", "F#5"]), (2, ["G#5", "F#5", "E5"]), (3, ["C#5", "E5", "A5"]), (4, ["G#5", "F#5"])):
    for k, name in enumerate(phrase):
        shamisen.note(T(n) + 2 + F(k, 2), F(1, 2), name, 82)
#: The bridge: the shamisen's solo, plucked and quick (beat, length, note).
SOLO = [
    [(0, 0.5, "G#4"), (0.5, 0.5, "B4"), (1, 0.5, "C#5"), (1.5, 0.5, "E5"), (2, 1, "G#5"), (3, 0.5, "F#5"), (3.5, 0.5, "E5")],
    [(0, 1, "C#5"), (1.5, 0.25, "E5"), (1.75, 0.25, "F#5"), (2, 1, "G#5"), (3, 1, "B5")],
    [(0, 0.5, "A5"), (0.5, 0.5, "G#5"), (1, 0.5, "E5"), (1.5, 0.5, "C#5"), (2, 2, "E5")],
    [(0, 0.25, "C#5"), (0.25, 0.25, "E5"), (0.5, 0.5, "F#5"), (1, 1, "A5"), (2.5, 0.5, "G#5"), (3, 1, "E5")],
    [(0, 0.5, "F#5"), (0.5, 0.5, "A5"), (1, 0.5, "C#6"), (1.5, 0.5, "B5"), (2, 1, "A5"), (3, 1, "F#5")],
    [(0, 1.5, "E5"), (1.5, 0.5, "F#5"), (2, 2, "C#5")],
    [(0, 0.5, "B4"), (0.5, 0.5, "D#5"), (1, 0.5, "F#5"), (1.5, 0.5, "A5"), (2, 1, "B5"), (3, 0.5, "A5"), (3.5, 0.5, "F#5")],
    [(0, 2, "E5"), (2, 1, "D#5"), (3, 1, "B4")],
]
play(SOLO, 21, shamisen, 92)

# ---- The drums ----------------------------------------------------------------------------------------
for n in range(1, 41):
    t, section = T(n), SECTION[n]
    if section == "intro":
        if n >= 3:
            for e in range(8):
                kit.note(t + F(e, 2), F(1, 8), HAT, 56 + (8 if e % 2 == 0 else 0))
        if n == 4:
            for s in (12, 13, 14, 15):
                kit.note(t + F(s, 4), F(1, 4), SNARE, 70 + 4 * (s - 12))
        continue
    if section == "bridge":
        kit.note(t, F(1, 2), KICK, 92)
        kit.note(t + 2, F(1, 2), SIDE, 84)
        for b in range(4):
            kit.note(t + b, F(1, 4), RIDE, 66)
        continue
    loud = {"verse": 84, "chorus": 90, "chorus2": 94, "outro": 84}[section]
    for s, vel in ((0, 12), (6, 0), (10, 4)):
        kit.note(t + F(s, 4), F(1, 2), KICK, loud + vel)
    kit.note(t + 1, F(1, 2), SNARE, loud + 10)
    kit.note(t + 3, F(1, 2), SNARE, loud + 12)
    for s in range(0, 16, 2):
        kit.note(t + F(s, 4), F(1, 8), OPEN_HAT if s == 14 and n % 2 == 0 else HAT, loud - 16 + (8 if s % 4 == 0 else 0))
    if n in (5, 13, 29, 37):
        kit.note(t, F(2), CRASH, loud + 12)
    if n in (12, 20, 28, 36):
        for k, s in enumerate((12, 13, 14, 15)):
            kit.note(t + F(s, 4), F(1, 4), SNARE, loud + 2 * k)

END_BAR = 41
for clip in (keys, guitar, bass, lead, brass, shamisen, kit):
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
    return f"instrument_backend: {{kind: sfz, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def surge(patch: str) -> str:
    return f"instrument_backend: {{kind: surge, patch: '{patch}'}}"


#: The Surge lead measures 9.8 cents flat (`cue tuning_audit`, 2026-11-05).
#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"keys": 0.0, "guitar": -3.0, "bass": 4.0, "lead": -13.0, "brass": 6.0, "shamisen": -5.0, "drums": 0.0}
score = f"""schema: ambition.musicir.v3
id: history_japan_floating_world
title: Floating World
description: >-
  Edo and Meiji Tokyo in the History dimension. Edo's floating world was its
  pleasure quarter, its theatre and its prints; its cue is city pop, Tokyo's
  sound a century later: major-seventh chords on electric piano, a cutting
  guitar, a busy bass, brass stabs and a bright synth hook, and a shamisen
  that answers the hook and takes the bridge. E major, 112 BPM. Generated by
  dev/compose_history_japan_floating_world.py: edit that, not this file.
notes:
  - 'Form: intro 1-4, verse 5-12, chorus 13-20, bridge 21-28, chorus 29-36, outro 37-40; the B11 of bar 40 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (keys, guitar, bass, drums), tune (lead, brass, shamisen).'
seed: 1831
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: E major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.35, density: 0.3, loopable: true, role: 'electric piano and shamisen'}}
  - {{id: verse, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.65, density: 0.7, loopable: true, role: 'the band'}}
  - {{id: chorus, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.85, density: 0.85, loopable: true, role: 'the synth hook'}}
  - {{id: bridge, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.6, density: 0.5, loopable: true, role: 'the shamisen solo'}}
  - {{id: chorus2, from: {{bar: 29, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'the hook, all in'}}
  - {{id: outro, from: {{bar: 37, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.65, density: 0.7, loopable: true, role: 'the groove, B11 to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: keys, group: keys, program: electric_piano_1, volume: 104, pan: 72, expression: 106, {sfz("epiano.rhodes")}}}
  - {{name: guitar, group: guitar, program: clean_guitar, volume: 98, pan: 50, expression: 102, {sfz("guitar.clean")}}}
  - {{name: bass, group: bass, program: slap_bass_1, volume: 114, pan: 64, expression: 114, {SWAG_TUNING}{sfz("bass.swag")}}}
  - {{name: lead, group: lead, program: lead_square, volume: 100, pan: 64, expression: 104, tuning_correction: {{mode: global, cents: 9.8}}, {surge("Leads/Classic Lead 2")}}}
  - {{name: brass, group: brass, program: brass_section, volume: 104, pan: 76, expression: 108, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: shamisen, group: shamisen, program: shamisen, volume: 108, pan: 54, expression: 110, instrument_backend: {{kind: soundfont, renderer: fluidsynth-cli, library_ref: japan.shamisen}}}}
  - {{name: kit, group: drums, is_drum: true, volume: 116, pan: 64, expression: 114, {sfz("drums.muldjord")}}}
parts:
{part("keys_part", "keys", keys)}
{part("guitar_part", "guitar", guitar)}
{part("bass_part", "bass", bass)}
{part("lead_part", "lead", lead)}
{part("brass_part", "brass", brass)}
{part("shamisen_part", "shamisen", shamisen)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    keys:
      chain:
        - {{processor: highpass, cutoff_hz: 110}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["keys"]}}}
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 240}}
        - {{processor: gain, gain_db: {GAIN["guitar"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    lead:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {GAIN["lead"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    shamisen:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["shamisen"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
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
    bed: [keys, guitar, bass, drums]
    tune: [lead, brass, shamisen]
  sections:
    - {{id: song, form: [intro, verse, chorus, bridge, chorus2, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

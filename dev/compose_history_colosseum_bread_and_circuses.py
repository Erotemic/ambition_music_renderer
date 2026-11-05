"""Bread and Circuses: the Colosseum room of the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_colosseum_bread_and_circuses.py scores/active/history_colosseum_bread_and_circuses.music.yaml

The Colosseum is the empire putting on a show for fifty thousand people,
so its cue is arena rock: power chords, a riff the crowd could shout, and
a brass fanfare where the emperor would come in. In the middle the crowd
takes over: half time, floor toms, and a guitar solo over the top. Every
melody is original.

138 BPM, 4/4. E minor. Form, 48 bars, about 1:23. The whole file loops;
bar 48's B leads to bar 1:
  intro    1-4    toms and the fanfare
  riff     5-12   the riff, the whole band
  verse    13-20  palm-muted eighths, the lead answers
  chorus   21-28  open chords, the fanfare as the hook
  arena    29-36  half time: floor toms, the guitar solo
  chorus   37-44  the hook again, louder
  outro    45-48  the riff, and B to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 138
OUT = Path(sys.argv[1])
rng = random.Random(80)  # the amphitheatre opens, 80 CE

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: General MIDI drum notes, as the Muldjord kit maps them.
KICK, SNARE, HAT, PEDAL_HAT, OPEN_HAT, CRASH, RIDE = 36, 38, 42, 44, 46, 49, 51
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


SECTION = {}
for n in range(1, 49):
    SECTION[n] = ("intro" if n <= 4 else "riff" if n <= 12 else "verse" if n <= 20 else "chorus" if n <= 28
                  else "arena" if n <= 36 else "chorus2" if n <= 44 else "outro")
RIFF_PROG = ["E", "E", "C", "D"] * 2
VERSE_PROG = ["E", "G", "D", "A", "E", "G", "D", "B"]
CHORUS_PROG = ["C", "D", "E", "E", "C", "D", "B", "B"]
ARENA_PROG = ["E", "E", "C", "C", "A", "A", "B", "B"]
PROG = (["E", "E", "E", "B"] + RIFF_PROG + VERSE_PROG + CHORUS_PROG + ARENA_PROG + CHORUS_PROG
        + ["E", "C", "D", "B"])
assert len(PROG) == 48
#: Power chords: the root, fifth and octave.
FIFTH = {"E": "B", "G": "D", "D": "A", "A": "E", "C": "G", "B": "F#"}


def power(root: str, octave: int = 2) -> list[int]:
    r = midi(f"{root}{octave}")
    if r < midi("E2"):
        r += 12
    return [r, r + 7, r + 12]


rhythm = Clip(0.003, 4)
lead = Clip(0.004, 5)
bass = Clip(0.003, 3)
trumpet = Clip(0.005, 4)
bones = Clip(0.005, 4)
kit = Clip(0.003, 5)

# ---- The rhythm guitar and the bass -------------------------------------------------------------------
#: The riff: a figure in eighths, (eighth index, length in eighths, offset in semitones from the root).
RIFF = [(0, 1, 0), (1, 1, 0), (2, 1, 12), (3, 1, 0), (4, 1, 10), (5, 1, 0), (6, 2, 7)]
for n in range(1, 49):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    pc = power(chord)
    low = midi(f"{chord}1") if midi(f"{chord}1") >= midi("E1") else midi(f"{chord}2")
    if section == "intro":
        if n == 4:
            rhythm.note(t, F(4), pc, 96)
            bass.note(t, F(4), low, 96)
        continue
    if section in ("riff", "outro"):
        for e, length, off in RIFF:
            rhythm.note(t + F(e, 2), F(length, 2) * F(9, 10), [pc[0] + off, pc[0] + off + 7], 100)
            bass.note(t + F(e, 2), F(length, 2) * F(9, 10), low + (off % 12), 98)
    elif section == "verse":
        # Palm-muted eighths: short, low, steady.
        for e in range(8):
            rhythm.note(t + F(e, 2), F(1, 5), pc[:2], 84 + (8 if e % 2 == 0 else 0))
            bass.note(t + F(e, 2), F(2, 5), low, 90)
    elif section in ("chorus", "chorus2"):
        loud = 100 if section == "chorus" else 108
        rhythm.note(t, F(3, 2), pc, loud)
        rhythm.note(t + F(3, 2), F(1, 2), pc, loud - 10)
        rhythm.note(t + 2, F(2), pc, loud - 4)
        for e in range(8):
            bass.note(t + F(e, 2), F(2, 5), low, 96)
    else:  # arena: half time, the chord rings for the bar
        rhythm.note(t, F(4), pc, 92)
        bass.note(t, F(3, 2), low, 100)
        bass.note(t + F(3, 2), F(1, 2), low, 90)
        bass.note(t + 2, F(2), low, 96)

# ---- The fanfare: brass, where the emperor comes in ----------------------------------------------------
#: (beat, length in beats, note) for four bars.
FANFARE = [
    [(0, 0.5, "E4"), (0.5, 0.5, "E4"), (1, 1, "B4"), (2, 1.5, "G4"), (3.5, 0.5, "A4")],
    [(0, 1, "B4"), (1, 0.5, "A4"), (1.5, 0.5, "G4"), (2, 2, "F#4")],
    [(0, 0.5, "E4"), (0.5, 0.5, "E4"), (1, 1, "B4"), (2, 1, "D5"), (3, 1, "C5")],
    [(0, 1.5, "B4"), (1.5, 0.5, "A4"), (2, 2, "B4")],
]
#: The chorus hook over C D E E / C D B B: the fanfare raised to a shout.
HOOK = [
    [(0, 1, "G4"), (1, 1, "E4"), (2, 1, "G4"), (3, 1, "C5")],
    [(0, 1.5, "A4"), (1.5, 0.5, "F#4"), (2, 2, "D5")],
    [(0, 0.5, "E5"), (0.5, 0.5, "E5"), (1, 1, "B4"), (2, 1.5, "G4"), (3.5, 0.5, "A4")],
    [(0, 3, "B4"), (3, 1, "D5")],
    [(0, 1, "E5"), (1, 1, "C5"), (2, 1, "G4"), (3, 1, "C5")],
    [(0, 1.5, "D5"), (1.5, 0.5, "C5"), (2, 2, "A4")],
    [(0, 1, "B4"), (1, 0.5, "C5"), (1.5, 0.5, "D5"), (2, 2, "D#5")],
    [(0, 2, "F#5"), (2, 1, "D#5"), (3, 1, "B4")],
]


def play(rows, first_bar, clip, vel, shift=0):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            clip.note(T(first_bar + k) + F(pos), F(length) * F(9, 10), midi(name) + shift, vel + (6 if pos == 0 else 0))


play(FANFARE, 1, trumpet, 92)
play(FANFARE, 1, bones, 84, -12)
play(HOOK, 21, trumpet, 92)
play(HOOK, 21, bones, 84, -12)
play(HOOK, 37, trumpet, 98)
play(HOOK, 37, bones, 90, -12)
play(HOOK, 37, lead, 92, 12)

# ---- The lead guitar ----------------------------------------------------------------------------------
#: The verse answer: a two-bar lick played in each pair of bars' second half.
LICK = [(2, 0.5, "B4"), (2.5, 0.5, "D5"), (3, 0.5, "E5"), (3.5, 0.5, "G5")]
for n in range(13, 21, 2):
    for pos, length, name in LICK:
        lead.note(T(n + 1) + F(pos), F(length) * F(9, 10), name, 88)
#: The solo over E E C C A A B B: climbing, a bend held, a run down.
SOLO = [
    [(0, 1, "E5"), (1, 0.5, "G5"), (1.5, 0.5, "A5"), (2, 2, "B5")],
    [(0, 0.5, "A5"), (0.5, 0.5, "G5"), (1, 0.5, "E5"), (1.5, 0.5, "G5"), (2, 2, "E5")],
    [(0, 1, "G5"), (1, 0.5, "A5"), (1.5, 0.5, "B5"), (2, 2, "C6")],
    [(0, 0.5, "B5"), (0.5, 0.5, "A5"), (1, 0.5, "G5"), (1.5, 0.5, "E5"), (2, 2, "G5")],
    [(0, 1, "A5"), (1, 0.5, "C6"), (1.5, 0.5, "E6"), (2, 2, "D6")],
    [(0, 0.5, "C6"), (0.5, 0.5, "B5"), (1, 0.5, "A5"), (1.5, 0.5, "E5"), (2, 2, "A5")],
    [(0, 3, "B5"), (3, 0.25, "A5"), (3.25, 0.25, "G5"), (3.5, 0.25, "F#5"), (3.75, 0.25, "E5")],
    [(0, 0.5, "D#5"), (0.5, 0.5, "F#5"), (1, 1, "A5"), (2, 2, "B5")],
]
play(SOLO, 29, lead, 96)

# ---- The drums ----------------------------------------------------------------------------------------
for n in range(1, 49):
    t, section = T(n), SECTION[n]
    if section == "intro":
        for b in range(4):
            kit.note(t + b, F(1, 2), FLOOR_TOM, 90 + (10 if b == 0 else 0))
            kit.note(t + b + F(1, 2), F(1, 4), MID_TOM, 72)
        if n == 4:
            for k, tom in enumerate((HI_TOM, HI_TOM, MID_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM, SNARE, SNARE)):
                kit.note(t + F(k, 2), F(1, 4), tom, 92 + k)
        continue
    if section == "arena":
        # Half time: the kick on 1, the snare on 3, floor toms under the solo.
        kit.note(t, F(1, 2), KICK, 104)
        kit.note(t + 2, F(1, 2), SNARE, 104)
        for b in (0, 1, 2, 3):
            kit.note(t + b + F(1, 2), F(1, 4), FLOOR_TOM, 80)
        kit.note(t, F(1, 2), RIDE, 82)
        kit.note(t + 2, F(1, 2), RIDE, 78)
        if n == 29:
            kit.note(t, F(2), CRASH, 108)
        continue
    loud = {"riff": 92, "verse": 84, "chorus": 96, "chorus2": 102, "outro": 92}[section]
    kit.note(t, F(1, 2), KICK, loud + 10)
    kit.note(t + F(3, 2), F(1, 2), KICK, loud)
    kit.note(t + 2, F(1, 2), KICK, loud + 4)
    kit.note(t + 1, F(1, 2), SNARE, loud + 8)
    kit.note(t + 3, F(1, 2), SNARE, loud + 10)
    cym = HAT if section == "verse" else RIDE if section in ("chorus", "chorus2") else OPEN_HAT
    for e in range(8):
        kit.note(t + F(e, 2), F(1, 4), cym, loud - 10 + (6 if e % 2 == 0 else 0))
    if n in (5, 13, 21, 37, 45):
        kit.note(t, F(2), CRASH, loud + 14)
    if n in (12, 20, 28, 44, 48):
        for k, tom in enumerate((SNARE, SNARE, HI_TOM, HI_TOM, MID_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM)):
            kit.note(t + 2 + F(k, 4), F(1, 4), tom, loud + 2 + k)

END_BAR = 49
for clip in (rhythm, lead, bass, trumpet, bones, kit):
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


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"rhythm": -6.0, "lead": 6.0, "bass": 3.0, "brass": 5.0, "drums": 0.0}
score = f"""schema: ambition.musicir.v3
id: history_colosseum_bread_and_circuses
title: Bread and Circuses
description: >-
  The Colosseum of the History dimension: the empire puts on a show for
  fifty thousand people, so the cue is arena rock. Power chords, a riff the
  crowd could shout, and a brass fanfare where the emperor would come in;
  in the middle, half time on the floor toms and a guitar solo. E minor,
  138 BPM. Generated by dev/compose_history_colosseum_bread_and_circuses.py:
  edit that, not this file.
notes:
  - 'Form: intro 1-4, riff 5-12, verse 13-20, chorus 21-28, arena 29-36, chorus 37-44, outro 45-48; the B of bar 48 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (rhythm, bass, drums), tune (lead, brass).'
seed: 80
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: E minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.6, density: 0.4, loopable: true, role: 'toms and the fanfare'}}
  - {{id: riff, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.8, density: 0.7, loopable: true, role: 'the riff'}}
  - {{id: verse, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.65, density: 0.6, loopable: true, role: 'palm-muted, the lead answers'}}
  - {{id: chorus, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.9, density: 0.8, loopable: true, role: 'the fanfare hook'}}
  - {{id: arena, from: {{bar: 29, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.85, density: 0.6, loopable: true, role: 'half time, the solo'}}
  - {{id: chorus2, from: {{bar: 37, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 1.0, density: 0.9, loopable: true, role: 'the hook, louder'}}
  - {{id: outro, from: {{bar: 45, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.8, density: 0.7, loopable: true, role: 'the riff, B to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: rhythm, group: rhythm, program: distortion_guitar, volume: 108, pan: 46, expression: 110, {sfz("guitar.fsbs_distorted_1")}}}
  - {{name: lead, group: lead, program: overdrive_guitar, volume: 104, pan: 76, expression: 108, {sfz("guitar.fsbs_distorted_1")}}}
  - {{name: bass, group: bass, program: picked_bass, volume: 114, pan: 64, expression: 114, {SWAG_TUNING}{sfz("bass.swag")}}}
  - {{name: trumpet, group: brass, program: trumpet, volume: 108, pan: 72, expression: 112, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: bones, group: brass, program: trombone, volume: 104, pan: 56, expression: 108, {curve(BONES_TUNING)}{sfz("orchestra.trombones_staccato")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 118, pan: 64, expression: 116, {sfz("drums.muldjord")}}}
parts:
{part("rhythm_part", "rhythm", rhythm)}
{part("lead_part", "lead", lead)}
{part("bass_part", "bass", bass)}
{part("trumpet_part", "trumpet", trumpet)}
{part("bones_part", "bones", bones)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    rhythm:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: gain, gain_db: {GAIN["rhythm"]}}}
    lead:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: {GAIN["lead"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -16.0, ratio: 3.0, attack_ms: 8.0, release_ms: 120.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.15}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [rhythm, bass, drums]
    tune: [lead, brass]
  sections:
    - {{id: song, form: [intro, riff, verse, chorus, arena, chorus2, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

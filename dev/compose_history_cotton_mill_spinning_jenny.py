"""Spinning Jenny: the cotton mill room of the History dimension. Writes
its MusicIR v3 score:

    python3 dev/compose_history_cotton_mill_spinning_jenny.py scores/active/history_cotton_mill_spinning_jenny.music.yaml

A Lancashire cotton mill in 1820: a thousand spindles, one beat, and the
owner's profit in every turn. The cue is machine funk: everything locks to
the sixteenth like a mill locks to its shaft. A muted guitar scratches, the
electric piano stabs, the bass pops, and the shuttles (woodblocks) fly in
threes across the fours. In the middle the shaft stops and starts again.
Every melody is original.

108 BPM, 4/4. A minor (Dorian). Form, 40 bars, about 1:29. The whole file
loops; bar 40's E7#9 leads to bar 1:
  intro      1-4    the shuttles and the hats
  groove     5-12   the band locks in
  hook       13-20  the lead's tune
  stoppage   21-28  the shaft stops: bass and shuttles, then all back
  hook       29-36  the tune with brass stabs
  outro      37-40  the groove, and E7#9 to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 108
OUT = Path(sys.argv[1])
rng = random.Random(1764)  # Hargreaves's spinning jenny

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: General MIDI drum notes, as the Muldjord kit maps them.
KICK, SNARE, SIDE, HAT, PEDAL_HAT, OPEN_HAT, CRASH, RIDE = 36, 38, 37, 42, 44, 46, 49, 51
#: VCSL Woodblock: three blocks, high to low.
BLOCK_HI, BLOCK_MID, BLOCK_LO = 60, 61, 62


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
    SECTION[n] = ("intro" if n <= 4 else "groove" if n <= 12 else "hook" if n <= 20 else "stoppage" if n <= 28
                  else "hook2" if n <= 36 else "outro")
GROOVE = ["Am7", "Am7", "D9", "D9"]
HOOK_PROG = ["Am7", "Am7", "D9", "D9", "Fmaj7", "Em7", "Dm7", "E7#9"]
PROG = (["Am7", "Am7", "Am7", "E7#9"] + GROOVE * 2 + HOOK_PROG + ["Am7"] * 6 + ["D9", "E7#9"] + HOOK_PROG
        + ["Am7", "D9", "Am7", "E7#9"])
assert len(PROG) == 40
#: Voicings for the electric piano: rootless, in the middle of the keyboard.
VOICE = {"Am7": ["G3", "C4", "E4"], "D9": ["F#3", "C4", "E4"], "Fmaj7": ["A3", "C4", "E4"],
         "Em7": ["G3", "B3", "D4"], "Dm7": ["F3", "A3", "C4"], "E7#9": ["G#3", "D4", "G4"]}
ROOT = {"Am7": "A", "D9": "D", "Fmaj7": "F", "Em7": "E", "Dm7": "D", "E7#9": "E"}

keys = Clip(0.003, 4)
guitar = Clip(0.002, 5)
bass = Clip(0.003, 4)
lead = Clip(0.004, 4)
trumpet = Clip(0.004, 4)
kit = Clip(0.002, 5)
shuttle = Clip(0.001, 6)

# ---- The bass: a popped line on the sixteenths --------------------------------------------------------
#: (sixteenth, length in sixteenths, semitones over the root, accent)
BASS_BAR = [(0, 2, 0, 1), (3, 1, 12, 0), (4, 1, 0, 0), (6, 1, 10, 1), (7, 1, 12, 0), (10, 2, 7, 1),
            (12, 1, 0, 0), (13, 1, 3, 0), (14, 2, 5, 1)]
for n in range(1, 41):
    chord, section = PROG[n - 1], SECTION[n]
    if section == "intro" and n < 3:
        continue
    t = T(n)
    root = midi(f"{ROOT[chord]}1")
    if root < midi("E1"):
        root += 12
    for s, length, off, acc in BASS_BAR:
        bass.note(t + F(s, 4), F(length, 4) * F(4, 5), root + off, 100 if acc else 84)

# ---- The guitar scratches, the electric piano stabs ---------------------------------------------------
for n in range(1, 41):
    chord, section = PROG[n - 1], SECTION[n]
    t = T(n)
    if section == "intro" or (section == "stoppage" and n < 27):
        continue
    v = [midi(p) + 12 for p in VOICE[chord]]
    for s in range(16):
        # The scratch: every sixteenth, the backbeats louder, a few rests.
        if s in (3, 11) and n % 2:
            continue
        accent = s in (4, 12) or s % 4 == 2
        guitar.note(t + F(s, 4), F(1, 8), v[:2] if s % 2 else v, 82 if accent else 62)
    # The stabs: on the "and" of 1, on 3, on the "a" of 4.
    for pos, length, vel in ((F(1, 2), F(1, 4), 88), (F(2), F(1, 4), 84), (F(15, 4), F(1, 4), 80)):
        keys.note(t + pos, length, VOICE[chord], vel)

# ---- The shuttles: three sixteenths apart, across the four -------------------------------------------
for n in range(1, 41):
    t, section = T(n), SECTION[n]
    for k in range(6):
        s = 3 * k if n % 3 == 1 else (3 * k + 1 if n % 3 == 2 else 3 * k + 2)
        if s >= 16:
            continue
        block = BLOCK_HI if k % 2 == 0 else BLOCK_MID
        shuttle.note(t + F(s, 4), F(1, 8), block, 84 if section in ("intro", "stoppage") else 70)
    shuttle.note(t + 3, F(1, 4), BLOCK_LO, 78)

# ---- The hook: a lead tune ----------------------------------------------------------------------------
#: (beat, length in beats, note) over Am7 Am7 D9 D9 Fmaj7 Em7 Dm7 E7#9.
HOOK = [
    [(0, 0.5, "E5"), (0.75, 0.25, "G5"), (1, 0.5, "A5"), (2, 0.5, "G5"), (2.5, 0.5, "E5"), (3.5, 0.5, "D5")],
    [(0, 1, "E5"), (1.5, 0.5, "C5"), (2, 0.5, "D5"), (2.5, 1.5, "A4")],
    [(0, 0.5, "F#5"), (0.75, 0.25, "A5"), (1, 0.5, "B5"), (2, 0.5, "A5"), (2.5, 0.5, "F#5"), (3.5, 0.5, "E5")],
    [(0, 1, "F#5"), (1.5, 0.5, "E5"), (2, 2, "D5")],
    [(0, 0.5, "C5"), (0.5, 0.5, "E5"), (1, 0.5, "A5"), (1.5, 0.5, "G5"), (2, 1, "E5")],
    [(0, 0.5, "B4"), (0.5, 0.5, "D5"), (1, 0.5, "G5"), (1.5, 0.5, "F#5"), (2, 1, "D5")],
    [(0, 0.5, "A4"), (0.5, 0.5, "C5"), (1, 0.5, "F5"), (1.5, 0.5, "E5"), (2, 1, "C5"), (3, 1, "D5")],
    [(0, 1.5, "G#4"), (1.5, 0.5, "B4"), (2, 1, "D5"), (3, 0.5, "G5"), (3.5, 0.5, "E5")],
]


def play(rows, first_bar, clip, vel, shift=0, chord=False):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            p = midi(name) + shift
            clip.note(T(first_bar + k) + F(pos), F(length) * F(9, 10), [p, p - 5] if chord else p,
                      vel + (6 if pos == 0 else 0))


play(HOOK, 13, lead, 86)
play(HOOK, 29, lead, 92)
# The brass in the second hook: stabs on the tune's long notes, a fourth under.
for k, bar in enumerate(HOOK):
    for pos, length, name in bar:
        if length >= 1:
            trumpet.note(T(29 + k) + F(pos), F(1, 2), [midi(name) - 12, midi(name) - 17], 92)
for n in (12, 20, 28, 36):
    for k, name in enumerate(("A4", "C5", "D5", "E5")):
        trumpet.note(T(n) + 3 + F(k, 4), F(1, 5), [midi(name) - 12, midi(name) - 17], 90 + 2 * k)

# ---- The drums ----------------------------------------------------------------------------------------
for n in range(1, 41):
    t, section = T(n), SECTION[n]
    if section == "intro":
        for s in range(16):
            kit.note(t + F(s, 4), F(1, 8), HAT, 60 + (14 if s % 4 == 0 else 0))
        if n == 4:
            for s in (8, 10, 12, 13, 14, 15):
                kit.note(t + F(s, 4), F(1, 4), SNARE, 70 + 4 * (s - 8))
        continue
    if section == "stoppage" and n < 27:
        # The shaft stops: only the kick, as a pulse.
        kit.note(t, F(1, 2), KICK, 92)
        kit.note(t + 2, F(1, 2), KICK, 86)
        continue
    loud = {"groove": 84, "hook": 88, "stoppage": 84, "hook2": 94, "outro": 84}[section]
    for s, vel in ((0, 12), (6, 2), (10, 6)):
        kit.note(t + F(s, 4), F(1, 2), KICK, loud + vel)
    kit.note(t + 1, F(1, 2), SNARE, loud + 10)
    kit.note(t + 3, F(1, 2), SNARE, loud + 12)
    kit.note(t + F(7, 4), F(1, 4), SNARE, loud - 30)  # the ghost note
    for s in range(16):
        cym = OPEN_HAT if s == 14 and n % 2 == 0 else HAT
        kit.note(t + F(s, 4), F(1, 8), cym, loud - 18 + (10 if s % 2 == 0 else 0))
    if n in (5, 13, 27, 29, 37):
        kit.note(t, F(2), CRASH, loud + 12)

END_BAR = 41
for clip in (keys, guitar, bass, lead, trumpet, kit, shuttle):
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


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"keys": 0.0, "guitar": 3.5, "bass": 3.0, "lead": -16.0, "brass": 8.0, "drums": 0.0, "shuttle": 15.0}
#: Shinyguitar's acoustic programs are silent while CC100 (pickup to microphone
#: blend) is 0. The guitars set it, and every sampled backend here is not
#: optional, so a silent one stops the render instead of falling back to General MIDI.
score = f"""schema: ambition.musicir.v3
id: history_cotton_mill_spinning_jenny
title: Spinning Jenny
description: >-
  The cotton mill of the History dimension: a thousand spindles, one beat,
  and the owner's profit in every turn. Machine funk, locked to the
  sixteenth: a scratching guitar, electric piano stabs, a popping bass and
  the shuttles (woodblocks) in threes across the fours; in the middle the
  shaft stops and starts again. A minor, 108 BPM. Generated by
  dev/compose_history_cotton_mill_spinning_jenny.py: edit that, not this file.
notes:
  - 'Form: intro 1-4, groove 5-12, hook 13-20, stoppage 21-28, hook 29-36, outro 37-40; the E7#9 of bar 40 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (keys, guitar, bass, drums, shuttle), tune (lead, brass).'
seed: 1764
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: A minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.4, density: 0.4, loopable: true, role: 'the shuttles and the hats'}}
  - {{id: groove, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.7, density: 0.8, loopable: true, role: 'the band locks in'}}
  - {{id: hook, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.8, density: 0.85, loopable: true, role: 'the lead tune'}}
  - {{id: stoppage, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.5, density: 0.4, loopable: true, role: 'the shaft stops and starts'}}
  - {{id: hook2, from: {{bar: 29, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.95, density: 0.95, loopable: true, role: 'the tune with brass'}}
  - {{id: outro, from: {{bar: 37, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.7, density: 0.8, loopable: true, role: 'the groove, E7#9 to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: keys, group: keys, program: electric_piano_1, volume: 104, pan: 76, expression: 108, {sfz("epiano.rhodes")}}}
  - {{name: guitar, group: guitar, program: muted_guitar, volume: 100, pan: 50, expression: 104, controls: {{100: 126}}, {sfz("guitar.clean")}}}
  - {{name: bass, group: bass, program: slap_bass_1, volume: 114, pan: 64, expression: 114, {SWAG_TUNING}{sfz("bass.swag")}}}
  - {{name: lead, group: lead, program: lead_square, volume: 100, pan: 64, expression: 104, {surge("Leads/Classic Lead 1")}}}
  - {{name: trumpet, group: brass, program: brass_section, volume: 106, pan: 70, expression: 110, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 116, pan: 64, expression: 114, {sfz("drums.muldjord")}}}
  - {{name: shuttle, group: shuttle, is_drum: true, volume: 100, pan: 88, expression: 104, {vcsl("Idiophones/Struck Idiophones/Woodblock")}}}
parts:
{part("keys_part", "keys", keys)}
{part("guitar_part", "guitar", guitar)}
{part("bass_part", "bass", bass)}
{part("lead_part", "lead", lead)}
{part("trumpet_part", "trumpet", trumpet)}
{part("kit_part", "kit", kit)}
{part("shuttle_part", "shuttle", shuttle)}
processing:
  groups:
    keys:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["keys"]}}}
    guitar:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: gain, gain_db: {GAIN["guitar"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    lead:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: {GAIN["lead"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.06, decay_seconds: 0.8}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
    shuttle:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: gain, gain_db: {GAIN["shuttle"]}}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: compressor, threshold_db: -16.0, ratio: 2.5, attack_ms: 10.0, release_ms: 100.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [keys, guitar, bass, drums, shuttle]
    tune: [lead, brass]
  sections:
    - {{id: song, form: [intro, groove, hook, stoppage, hook2, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

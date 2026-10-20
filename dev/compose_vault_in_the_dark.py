"""Vault in the Dark: dark synth in D minor, for exploring with a secret.
Writes its MusicIR v3 score:

    python3 dev/compose_vault_in_the_dark.py scores/active/vault_in_the_dark.music.yaml

Born as audition F5 for the Ambition theme (dev/compose_ambition_theme_f.py,
hook "5"). Jon, 2026-10-20: "Write F5, Vault in the Dark as its own song, but
it's not the main theme. It's neat though and I want to keep it."

D minor (Aeolian) at 110 BPM in a half-time swagger:
  - THE ENGINE: a sixteenth-note synth-bass pulse that never stops.
  - THE HARMONY: i bVI bIII bVII (Dm Bb F C): power, not longing.
  - THE HOOK: two sixteenth pickups vault into a held note, a hole, a falling
    answer; the held notes go A, Bb, A, G, and in the reveal climb D, E, F.

Form, 4/4 at 110 BPM:
  dark      1-4    the pulse alone, a drone, a heartbeat kick.        (plays once)
  whisper   5-12   the hook, low and filtered; bells answer.          (loop start)
  reveal    13-20  the hook an octave up with synth brass; the climb to F.
  vault     21-28  inside: Gm Eb Bb C | Gm Eb Bb A, a slow line over the
                   engine, half-time; A pulls back to D minor.
  drop      29-32  brass stabs of the vault over the engine.
  reveal_2  33-40  the hook and the climb again, with bells on the held notes.
  fade      41-44  the whisper again, thinning; C back to D minor at bar 5.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 110
OUT = Path(sys.argv[1])
rng = random.Random(1105)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


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


def T(n: int) -> float:
    return (n - 1) * 4.0


whisper = Clip(0.002, 3)
lead = Clip(0.002, 3)
lead_low = Clip(0.002, 3)
brass = Clip(0.002, 3)
pulse = Clip(0.001, 4)
sub = Clip()
pad = Clip()
air = Clip()
bells = Clip(0.002, 3)
kit = Clip(0.002, 3)
harmony: dict[int, str] = {}

# ---- Harmony ---------------------------------------------------------------------------
TONES = {
    "Dm": ["D4", "F4", "A4"], "G/D": ["D4", "G4", "B4"], "Bb": ["D4", "F4", "Bb4"], "C": ["E4", "G4", "C5"],
    "D5": ["D4", "A4", "D5"], "Gm/D": ["D4", "G4", "Bb4"],
    # the line cliche: a voice falls D C# C B over the D minor
    "DmMaj7": ["D4", "F4", "A4", "C#5"], "Dm7": ["D4", "F4", "A4", "C5"], "Dm6": ["D4", "F4", "A4", "B4"],
    "Bbmaj7": ["D4", "F4", "A4", "Bb4"], "Gm": ["D4", "G4", "Bb4"], "A7": ["C#4", "E4", "G4", "A4"],
    "F": ["C4", "F4", "A4"], "A": ["C#4", "E4", "A4"], "Bbm": ["Db4", "F4", "Bb4"], "F#m": ["C#4", "F#4", "A4"],
    "Eb": ["Eb4", "G4", "Bb4"], "Eb/D": ["Eb4", "G4", "Bb4"],
}
#: the pulse's notes: (pedal, upper) -- the pedal stays D except under the cadence
PULSE = {"Dm": ("D2", "A2"), "G/D": ("D2", "B2"), "Bb": ("Bb1", "F2"), "C": ("C2", "G2"), "D5": ("D2", "A2"),
         "Gm/D": ("D2", "Bb2"), "DmMaj7": ("D2", "C#3"), "Dm7": ("D2", "C3"), "Dm6": ("D2", "B2"),
         "Bbmaj7": ("Bb1", "F2"), "Gm": ("G1", "D2"), "A7": ("A1", "E2"),
         "F": ("F1", "C2"), "A": ("A1", "E2"), "Bbm": ("Bb1", "F2"), "F#m": ("F#1", "C#2"), "Eb": ("Eb2", "Bb2"),
         "Eb/D": ("D2", "Eb3")}
SUB = {"Dm": "D1", "G/D": "D1", "Bb": "Bb0", "C": "C1", "D5": "D1", "Gm/D": "D1", "DmMaj7": "D1", "Dm7": "D1",
       "Dm6": "D1", "Bbmaj7": "Bb0", "Gm": "G0", "A7": "A0", "F": "F1", "A": "A0", "Bbm": "Bb0", "F#m": "F#1",
       "Eb": "Eb1", "Eb/D": "D1"}
WHISPER_CH = ["Dm", "G/D", "Dm", "G/D", "Dm", "G/D", "Dm", "G/D"]
REVEAL_CH = ["Dm", "G/D", "Dm", "G/D", "Bb", "C", "D5", "D5"]


def engine(n: int, chord: str, vel=60):
    """The sixteenth pulse: pedal, pedal, upper, pedal; an octave pop on the and of two and four."""
    lo, hi = (midi(x) for x in PULSE[chord])
    for i in range(16):
        p = (lo, lo, hi, lo)[i % 4]
        if i in (6, 14):
            p = lo + 12
        pulse.note(T(n) + 0.25 * i, 0.2, p, vel + (12 if i % 4 == 0 else 0) + (6 if i in (6, 14) else 0))


KICK, CLAP, SNARE, E_SNARE, HAT, OPEN_HAT, CRASH, LOW_TOM, MID_TOM, HI_TOM, RIDE = 36, 39, 38, 40, 42, 46, 49, 45, 47, 50, 51


def drums(n: int, style: str, crash=False, fill=False):
    t = T(n)
    if crash:
        kit.note(t, 0.8, CRASH, 96)
    if style == "heartbeat":
        kit.note(t, 0.1, KICK, 80)
        kit.note(t + 0.75, 0.1, KICK, 60)
        return
    # half time: the kick on one and the and of two, the backbeat on three
    for at, v in ((0, 100), (1.5, 88), (2.75, 70) if style == "reveal" else (0, 0)):
        if v:
            kit.note(t + at, 0.1, KICK, v)
    kit.note(t + 2, 0.1, CLAP, 84 if style != "whisper" else 66)
    if style != "whisper":
        kit.note(t + 2, 0.1, SNARE, 96)
    for i in range(16):
        if style == "whisper" and i % 2:
            continue
        kit.note(t + 0.25 * i, 0.05, HAT, (54 if i % 4 == 0 else 34) + (8 if style == "reveal" else 0))
    if style == "reveal":
        kit.note(t + 3.5, 0.3, OPEN_HAT, 60)
    if fill:
        for i, d in enumerate((SNARE, SNARE, HI_TOM, MID_TOM, MID_TOM, LOW_TOM, LOW_TOM, SNARE)):
            kit.note(t + 2 + 0.25 * i, 0.08, d, 70 + 5 * i)



# ---- The hook ---------------------------------------------------------------------------
HOOK = [
    [(0.5, .25, "D5"), (0.75, .25, "F5"), (1.0, 1.25, "A5"), (2.5, .25, "G5"), (2.75, .25, "F5"), (3.0, .5, "E5"), (3.5, .5, "D5")],
    [(0.5, .25, "D5"), (0.75, .25, "F5"), (1.0, 1.25, "Bb5"), (2.5, .25, "A5"), (2.75, .25, "F5"), (3.0, 1.0, "D5")],
    [(0.5, .25, "C5"), (0.75, .25, "F5"), (1.0, 1.25, "A5"), (2.5, .25, "G5"), (2.75, .25, "F5"), (3.0, .5, "E5"), (3.5, .5, "C5")],
    [(0.5, .25, "C5"), (0.75, .25, "E5"), (1.0, 3.0, "G5")],
]
#: the reveal's second half, over Bb C Dm Dm: the held notes climb D, E, F
CLIMB = [
    [(0.5, .25, "F5"), (0.75, .25, "Bb5"), (1.0, 1.25, "D6"), (2.5, .25, "C6"), (2.75, .25, "Bb5"), (3.0, 1.0, "F5")],
    [(0.5, .25, "G5"), (0.75, .25, "C6"), (1.0, 1.25, "E6"), (2.5, .25, "D6"), (2.75, .25, "C6"), (3.0, 1.0, "G5")],
    [(0.5, .25, "A5"), (0.75, .25, "D6"), (1.0, 3.0, "F6")],
    [(0.0, 4.0, "D6")],
]
#: the vault: a slow line over Gm Eb Bb C | Gm Eb Bb A
VAULT_LINE = [
    [(0.0, 2.0, "Bb5"), (2.0, 2.0, "A5")],
    [(0.0, 3.0, "G5"), (3.0, 1.0, "Bb5")],
    [(0.0, 2.0, "F5"), (2.0, 2.0, "D6")],
    [(0.0, 4.0, "E6")],
    [(0.0, 2.0, "D6"), (2.0, 2.0, "C6")],
    [(0.0, 2.0, "Bb5"), (2.0, 2.0, "G5")],
    [(0.0, 3.0, "F5"), (3.0, 1.0, "D5")],
    [(0.0, 2.0, "E5"), (2.0, 2.0, "C#6")],
]
HOOK_CH = ["Dm", "Bb", "F", "C"]
REVEAL_CH = HOOK_CH + ["Bb", "C", "Dm", "Dm"]
VAULT_CH = ["Gm", "Eb", "Bb", "C", "Gm", "Eb", "Bb", "A"]
DROP_STABS = [(0.5, "D5"), (0.75, "F5"), (1.0, "A5")]
DROP_LAND = {"Dm": "D5", "Bb": "D5", "F": "C5", "C": "E5"}


def sing(clip: Clip, n0: int, phrase, vel=90, octave=0):
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            long = dur >= 1.0
            clip.note(T(n0 + k) + at, dur * (0.96 if long else 0.85), midi(name) + 12 * octave, vel + (6 if long else 0))


def bed(n: int, chord: str, pulse_vel: int, sub_vel: int, pad_vel: int, air_too=False):
    harmony[n] = chord
    engine(n, chord, vel=pulse_vel)
    sub.note(T(n), 3.9, midi(SUB[chord]), sub_vel)
    tones = [midi(x) for x in TONES[chord]]
    pad.note(T(n), 3.95, [p - 12 for p in tones] + ([tones[0]] if air_too else []), pad_vel)
    if air_too:
        air.note(T(n), 3.95, [p + 24 for p in tones], 44)  # above the lead, out of its register
    return tones


def whisper_section(n0: int):
    for k, chord in enumerate(HOOK_CH * 2):
        n = n0 + k
        bed(n, chord, 62, 76, 52)
        drums(n, "whisper", fill=k == 7)
    sing(whisper, n0, HOOK + HOOK, vel=80, octave=-1)
    for k in (1, 3, 5, 7):  # bells answer each bar's held note, an octave over the whisper
        held = max(HOOK[k % 4], key=lambda x: x[1])
        bells.note(T(n0 + k) + 3.0, 0.4, midi(held[2]), 46)


def reveal_section(n0: int, bells_too=False):
    for k, chord in enumerate(REVEAL_CH):
        n = n0 + k
        tones = bed(n, chord, 74, 86, 62, air_too=True)
        for at, dur in ((0, 0.5), (1.5, 0.4), (2.5, 1.2)):  # synth brass, under the lead's octave double
            brass.note(T(n) + at, dur, [x - 12 for x in tones], 92 if at == 0 else 80)
        drums(n, "reveal", crash=k in (0, 4), fill=k == 7)
    sing(lead, n0, HOOK, vel=100)
    sing(lead_low, n0, HOOK, vel=78, octave=-1)
    sing(lead, n0 + 4, CLIMB, vel=104)
    sing(lead_low, n0 + 4, CLIMB, vel=80, octave=-1)
    if bells_too:
        for k, notes in enumerate(HOOK + CLIMB):
            held = max(notes, key=lambda x: x[1])
            bells.note(T(n0 + k) + held[0], 0.6, midi(held[2]) + 12, 48)


# ---- Dark, 1-4 ---------------------------------------------------------------------------
for n in range(1, 5):
    harmony[n] = "Dm"
    engine(n, "Dm", vel=36 + 6 * n)
    drums(n, "heartbeat")
air.note(T(1), 15.8, [midi("D3"), midi("A3")], 54)
sub.note(T(3), 7.8, midi("D1"), 70)

whisper_section(5)
reveal_section(13)

# ---- Vault, 21-28: inside -----------------------------------------------------------------
for k, chord in enumerate(VAULT_CH):
    n = 21 + k
    bed(n, chord, 66, 80, 58, air_too=True)
    drums(n, "whisper", crash=k == 0, fill=k == 7)
sing(lead, 21, VAULT_LINE, vel=86)
for k, notes in enumerate(VAULT_LINE):  # the whisper hums each bar's first note an octave down, a beat late
    at, dur, name = notes[0]
    whisper.note(T(21 + k) + 0.5, dur - 0.6, midi(name) - 12, 70)
for i in range(16):  # bar 28: the snare builds into the drop
    kit.note(T(28) + 0.25 * i, 0.05, SNARE, 50 + 3 * i)

# ---- Drop, 29-32: stabs of the vault over the engine ------------------------------------------
for k, chord in enumerate(HOOK_CH):
    n = 29 + k
    harmony[n] = chord
    engine(n, chord, vel=80)
    sub.note(T(n), 3.9, midi(SUB[chord]), 88)
    drums(n, "reveal", crash=k == 0, fill=k == 3)
    for at, name in DROP_STABS:
        brass.note(T(n) + at, 0.35, [midi(name), midi(name) - 12], 96)
    land = DROP_LAND[chord]
    brass.note(T(n) + 3.0, 0.6, [midi(land), midi(land) - 12], 100)

reveal_section(33, bells_too=True)

# ---- Fade, 41-44: the whisper again, thinning, back to D minor at bar 5 --------------------
for k, chord in enumerate(HOOK_CH):
    n = 41 + k
    bed(n, chord, 64 - 2 * k, 78 - 2 * k, 52)
    drums(n, "whisper", fill=k == 3)
sing(whisper, 41, HOOK, vel=80, octave=-1)
bells.note(T(42) + 3.0, 0.4, midi("Bb5"), 46)
bells.note(T(44) + 3.0, 0.4, midi("G5"), 46)

END_BAR = 45
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


DELAY = round(60000 / BPM * 0.75)  # a dotted eighth
score = f"""schema: ambition.musicir.v3
id: vault_in_the_dark
title: Vault in the Dark
description: >-
  Dark synth in D minor at 110 BPM in a half-time swagger, for exploring
  with a secret. A sixteenth-note synth-bass pulse never stops under Dm Bb F
  C; the hook vaults from two sixteenth pickups into a held note and answers
  downward. Whispered low and filtered, then revealed an octave up with
  synth brass and a climb to the top F; inside the vault a slow line over Gm
  Eb Bb C; a drop of brass stabs; the reveal again with bells; the whisper
  to close the loop. Born as Ambition theme audition F5 (Jon, 2026-10-20:
  "It's neat though and I want to keep it"). Generated by
  dev/compose_vault_in_the_dark.py: edit that, not this file.
notes:
  - 'The intro plays once; the loop is bars 5-44, ending on C, back to D minor at bar 5.'
  - 'Layered for a level: bed (pulse, sub, pads), drums, tune (whisper, lead, bells) and power (brass).'
seed: 1105
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: dark, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.25, density: 0.3, role: 'the pulse alone'}}
  - {{id: whisper, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.5, density: 0.5, loopable: true, role: 'the hook, low and filtered'}}
  - {{id: reveal, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.95, density: 0.9, loopable: true, role: 'the hook revealed; the climb to F'}}
  - {{id: vault, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.6, density: 0.55, loopable: true, role: 'inside: a slow line over Gm Eb Bb C'}}
  - {{id: drop, from: {{bar: 29, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.8, density: 0.6, loopable: true, role: 'brass stabs over the engine'}}
  - {{id: reveal_2, from: {{bar: 33, beat: 1}}, to: {{bar: 41, beat: 1}}, energy: 1.0, density: 0.95, loopable: true, role: 'the reveal again, bells on the held notes'}}
  - {{id: fade, from: {{bar: 41, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.4, density: 0.4, loopable: true, role: 'the whisper, thinning'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: whisper, group: whisper, program: lead_saw, volume: 96, pan: 64, expression: 100, controls: {{1: 6}}}}
  - {{name: lead, group: lead, program: lead_saw, volume: 100, pan: 66, expression: 110, controls: {{1: 10}}}}
  - {{name: lead_low, group: lead, program: lead_fifths, volume: 80, pan: 58, expression: 90}}
  - {{name: brass, group: brass, program: synth_brass_1, volume: 96, pan: 64, expression: 104}}
  - {{name: pulse, group: pulse, program: synth_bass_2, volume: 100, pan: 64, expression: 104}}
  - {{name: sub, group: sub, program: synth_bass_1, volume: 96, pan: 64, expression: 100}}
  - {{name: pad, group: pads, program: pad_halo, volume: 76, pan: 52, expression: 86}}
  - {{name: air, group: pads, program: fx_atmosphere, volume: 64, pan: 76, expression: 80}}
  - {{name: bells, group: bells, program: fx_crystal, volume: 60, pan: 40, expression: 78}}
  - {{name: kit, group: drums, is_drum: true, volume: 108, pan: 64, expression: 112}}
parts:
{part("whisper_part", "whisper", whisper)}
{part("lead_part", "lead", lead)}
{part("lead_low_part", "lead_low", lead_low)}
{part("brass_part", "brass", brass)}
{part("pulse_part", "pulse", pulse)}
{part("sub_part", "sub", sub)}
{part("pad_part", "pad", pad)}
{part("air_part", "air", air)}
{part("bells_part", "bells", bells)}
{part("kit_part", "kit", kit)}
processing:
  groups:
    whisper:
      chain:
        - {{processor: highpass, cutoff_hz: 100}}
        - {{processor: lowpass, cutoff_hz: 1800}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {DELAY}, feedback: 0.3, mix: 0.22}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: 4.0}}
    lead:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.6, attack_ms: 9.0, release_ms: 92.0, knee_db: 6.0}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {DELAY}, feedback: 0.24, mix: 0.14}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 2.0}}
        - {{processor: gain, gain_db: 0.0}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: lowpass, cutoff_hz: 6500}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.5, attack_ms: 6.0, release_ms: 90.0}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: -4.0}}
        - {{processor: balance, position: -0.15}}
    pulse:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - {{processor: lowpass, cutoff_hz: 2200}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 3.0, attack_ms: 5.0, release_ms: 70.0, makeup_db: 1.0}}
        - {{processor: gain, gain_db: -2.0}}
    sub:
      chain:
        - {{processor: highpass, cutoff_hz: 28}}
        - {{processor: lowpass, cutoff_hz: 180}}
        - {{processor: gain, gain_db: -4.0}}
    pads:
      chain:
        - {{processor: highpass, cutoff_hz: 110}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -3.0}}
    bells:
      chain:
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: 0.3}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: compressor, threshold_db: -18.0, ratio: 2.5, attack_ms: 8.0, release_ms: 80.0, makeup_db: 1.0}}
        - {{processor: reverb, wet: 0.08, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: -1.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 3.0, attack_ms: 10.0, release_ms: 100.0, makeup_db: 1.4}}
      - {{processor: stereo_width, amount: 0.15}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  # Exploring plays everything; the power layer (brass) can drop out for calm.
  layers:
    bed: [pulse, sub, pads]
    drums: [drums]
    tune: [whisper, lead, bells]
    power: [brass]
  sections:
    - {{id: intro, form: [dark]}}
    - {{id: song, form: [whisper, reveal, vault, drop, reveal_2, fade], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

"""Nine Rooftops, No Footsteps: a ninja song. Writes its MusicIR v3 score:

    python3 dev/compose_nine_rooftops.py scores/active/nine_rooftops.music.yaml

Jon, 2026-10-19: "Now a ninja themed song." Composed from first principles:
D in the miyako-bushi scale (D, E-flat, G, A, B-flat) at 144 BPM. A shamisen
ostinato in sixteenths accented three-three-two drives a taiko ensemble (a
big drum, toms, a tight frame drum, log drums); the shakuhachi has the tune;
a koto (a dan tranh zither) and staccato strings answer it. The harmony is
open fifths and the E-flat above the root: no thirds to rest on.

Form, 4/4 at 144 BPM:
  intro      1-8    the shakuhachi alone over a low D; the clappers speed up.
  the run    9-24   shamisen, drums, cellos; the tune from bar 17.      (loop start)
  rooftops   25-40  D, E-flat, G minor, A: the koto and violins take the tune.
  stillness  41-48  nearly nothing: the flute, the koto trembling, a big drum now and then.
  the strike 49-64  everyone; the tune on flute and violins, the gong. Back to the top.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 144
OUT = Path(sys.argv[1])
rng = random.Random(909)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def midi(name: str) -> int:
    pitch, octave = name[:-1], int(name[-1])
    return 12 * (octave + 1) + NOTE[pitch]


def frac(beats) -> str:
    ticks = round(F(beats) * 960)
    value = F(ticks, 3840)
    return f"{value.numerator}/{value.denominator}"


def bar(n: int) -> float:
    return (n - 1) * 4.0


class Clip:
    def __init__(self, drift: float = 0.0, vel_jitter: int = 0):
        self.events: list[tuple] = []
        self.bends: list[tuple] = []
        self.drift = drift
        self.vel_jitter = vel_jitter

    def note(self, when, dur, pitches, vel):
        when = F(when).limit_denominator(960)
        if self.drift and when > 0:
            when += F(rng.uniform(0, self.drift)).limit_denominator(960)
        vel = max(1, min(127, int(vel + (rng.randint(-self.vel_jitter, self.vel_jitter) if self.vel_jitter else 0))))
        if isinstance(pitches, (int, str)):
            pitches = [pitches]
        self.events.append((when, F(dur).limit_denominator(960), [p if isinstance(p, int) else midi(p) for p in pitches], vel))

    def yaml(self, clip_id: str, indent: str) -> str:
        lines = [f"{indent}- id: {clip_id}", f"{indent}  at: {{bar: 1, beat: 1}}", f"{indent}  events:"]
        for when, dur, pitches, vel in sorted(self.events, key=lambda e: (e[0], e[2])):
            pitch = pitches[0] if len(pitches) == 1 else "[" + ", ".join(str(p) for p in pitches) + "]"
            lines.append(f"{indent}    - [{frac(when)}, {frac(dur)}, {pitch}, {vel}]")
        if self.bends:
            lines.append(f"{indent}  automation:")
            for i, (when, value) in enumerate(sorted(self.bends)):
                lines.append(f"{indent}    - {{id: {clip_id}_tune_{i:04d}, at: {frac(when)}, pitch_bend: {value}}}")
        return "\n".join(lines)


#: How far each key of the shamisen SoundFont sounds from equal temperament
#: (cents, measured from a render of every key; the same at every velocity).
#: Its samples were recorded a little off, each by its own amount.
SHAMISEN_CENTS = {48: -3, 49: -4, 50: -13, 51: -14, 52: -13, 53: 5, 54: -3, 55: -6, 56: -7, 57: -16, 58: -16,
                  59: -8, 60: 10, 61: 10, 62: -24, 63: -22, 64: 2, 65: -18, 66: -19, 67: -26, 68: -26, 69: -10,
                  70: -15, 71: -8, 72: -26, 73: -31, 74: -24, 75: -23, 76: 10, 77: 2, 78: 2, 79: -23, 80: -18}
#: Pitch-bend units a cent (a bend range of two semitones).
BEND_PER_CENT = 8192 / 200


def pluck(when, dur, pitch, vel):
    """A shamisen note, bent in tune just before it sounds (the line is one
    note at a time, so the bend never moves a note that is still ringing)."""
    shamisen.note(when, dur, pitch, vel)
    shamisen.bends.append((F(when).limit_denominator(960) - F(1, 32), round(-SHAMISEN_CENTS[pitch] * BEND_PER_CENT)))


shamisen = Clip(0.006, 6)
koto = Clip(0.01, 6)
flute = Clip(0.012, 4)
celli = Clip(0.006, 5)
basses = Clip(0.01, 3)
violins = Clip(0.008, 5)
odaiko = Clip(0.006, 5)
toms = Clip(0.006, 6)
shime = Clip(0.004, 8)
logs = Clip(0.006, 6)
clap = Clip()
gong = Clip()

# ---- Harmony: open fifths and the flat second ---------------------------------
CHORD = {"D5": ("D", ["D", "A"]), "Eb": ("Eb", ["Eb", "G", "Bb"]), "Gm": ("G", ["G", "Bb", "D"]),
         "Asus": ("A", ["A", "D"])}
RUN = ["D5"] * 4
ROOFTOPS = ["D5", "Eb", "Gm", "Asus"]
harmony: dict[int, str] = {}


def root(chord: str, low: int) -> int:
    p = low
    while p % 12 != NOTE[CHORD[chord][0]]:
        p += 1
    return p


def stack(chord: str, low: int, count: int) -> list[int]:
    pcs = {NOTE[t] for t in CHORD[chord][1]}
    out, p = [], low
    while len(out) < count:
        if p % 12 in pcs:
            out.append(p)
        p += 1
    return out


#: Three-three-two accents over a bar of sixteenths.
ACCENTS = {0, 3, 6, 8, 11, 14}
#: The shamisen's figure over D: intervals above the root, in the scale.
FIGURE = [0, 0, 12, 0, 7, 0, 8, 7, 0, 0, 12, 0, 5, 7, 1, 0]


def ostinato(n: int, vel=84):
    """Shamisen sixteenths. Over D the figure; over the other chords the root,
    its octave and the chord's next tone."""
    chord = harmony[n]
    r = root(chord, midi("D3") if chord == "D5" else midi("C3"))
    if chord == "D5":
        steps = FIGURE
    else:
        top = stack(chord, r + 1, 1)[0] - r
        steps = [0, 0, 12, 0, top, 0, 12, top, 0, 0, 12, 0, top, 12, top, 0]
    for i, s in enumerate(steps):
        pluck(bar(n) + 0.25 * i, 0.22, r + s, vel + (12 if i in ACCENTS else -6))


def pulse(n: int, vel=84):
    """Cellos in staccato eighths on the root, the octave on the off-beats of
    three and four; the basses hold the root."""
    chord = harmony[n]
    r = root(chord, midi("C2"))
    for i in range(8):
        celli.note(bar(n) + 0.5 * i, 0.4, r + (12 if i in (5, 7) else 0) + 12, vel + (10 if i in (0, 3, 6) else 0))
    basses.note(bar(n), 3.9, r, vel - 8)


def taiko(n: int, style: str):
    """The big drum on one and the 'and' of three; toms on the off-beats; the
    shime in sixteenths; log drums answering on the last beat."""
    t = bar(n)
    odaiko.note(t, 0.8, 60, 108)
    odaiko.note(t + 2.5, 0.6, 60, 92)
    if n % 2 == 0:
        odaiko.note(t + 3.5, 0.4, 60, 84)
    if style in ("run", "strike"):
        for o, k, v in ((1.0, 60, 92), (1.75, 61, 74), (3.0, 60, 96), (3.25, 61, 70)):
            toms.note(t + o, 0.3, k, v)
        for i in range(16):
            shime.note(t + 0.25 * i, 0.12, 64 if i in ACCENTS else 65, 78 if i in ACCENTS else 50)
        for o, k in ((3.5, 60), (3.75, 61)):
            logs.note(t + o, 0.2, k, 80)
    elif style == "rooftops":
        for o, k, v in ((1.0, 61, 80), (3.0, 60, 90)):
            toms.note(t + o, 0.3, k, v)
        for i in range(0, 16, 2):
            shime.note(t + 0.25 * i, 0.12, 64 if i in ACCENTS else 65, 70 if i in ACCENTS else 46)
        for o in (0.75, 2.25):
            logs.note(t + o, 0.2, 61, 70)


def play(clip: Clip, n: int, phrase, vel=84, transpose=0, length=0.95):
    """`phrase`: one list a bar of (beat, length, note)."""
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            clip.note(bar(n + k) + at, dur * length, midi(name) + transpose, vel + (6 if at == 0 else 0))


# ---- The tune -------------------------------------------------------------------
TUNE = [
    [(0, 1.5, "A4"), (1.5, 0.5, "Bb4"), (2, 2, "A4")],
    [(0, 0.5, "G4"), (0.5, 0.5, "A4"), (1, 1, "D5"), (2, 2, "Bb4")],
    [(0, 1, "A4"), (1, 0.5, "G4"), (1.5, 0.5, "Eb4"), (2, 2, "D4")],
    [(2.5, 0.5, "D4"), (3, 0.5, "Eb4"), (3.5, 0.5, "G4")],
    [(0, 1.5, "A4"), (1.5, 0.5, "D5"), (2, 1, "Eb5"), (3, 1, "D5")],
    [(0, 0.5, "Bb4"), (0.5, 0.5, "A4"), (1, 1, "G4"), (2, 2, "A4")],
    [(0, 0.75, "Bb4"), (0.75, 0.25, "A4"), (1, 0.5, "G4"), (1.5, 0.5, "Eb4"), (2, 1, "G4"), (3, 1, "A4")],
    [(0, 3, "D4")],
]
# The koto's answer: quick pairs and a fall, in the bars the tune holds.
ANSWER = {0: [(2.5, 0.25, "D5"), (2.75, 0.25, "Eb5"), (3, 1, "D5")],
          2: [(2.5, 0.25, "Bb4"), (2.75, 0.25, "A4"), (3, 0.5, "G4"), (3.5, 0.5, "D4")],
          5: [(2.5, 0.25, "G5"), (2.75, 0.25, "A5"), (3, 1, "D5")],
          7: [(1.5, 0.5, "A4"), (2, 0.5, "G4"), (2.5, 0.5, "Eb4"), (3, 1, "D4")]}
# The intro's call: slow, with long breaths between.
CALL = [
    [(0, 3, "A4")], [(0, 0.5, "Bb4"), (0.5, 3, "A4")], [], [(0, 1, "G4"), (1, 1, "Eb4"), (2, 2, "D4")],
    [(0, 3.5, "D5")], [(0, 1, "Eb5"), (1, 2.5, "D5")], [], [],
]

# ---- Intro, bars 1-8 ---------------------------------------------------------------
for n in range(1, 9):
    harmony[n] = "D5"
basses.note(bar(1), 31.8, "D2", 62)
celli.note(bar(5), 15.8, "A2", 50)
play(flute, 1, CALL, vel=72)
for n in (2, 4, 6):
    koto.note(bar(n) + 2.5, 1.5, stack("D5", midi("D4"), 2), 58)
odaiko.note(bar(1), 2.0, 60, 70)
odaiko.note(bar(5), 2.0, 60, 80)
gong.note(bar(1), 8.0, 62, 60)  # a scraped gong under the first breath
# The clappers: slow, then faster and faster into the run.
t, gap = bar(7), 0.9
while t < bar(9) - 0.12:
    clap.note(t, 0.1, 60, min(110, 70 + int(40 * (t - bar(7)) / 8)))
    t += gap
    gap = max(0.125, gap * 0.8)

# ---- The run, bars 9-24 -------------------------------------------------------------
for k in range(16):
    n = 9 + k
    harmony[n] = "D5"
    ostinato(n)
    pulse(n, vel=80)
    taiko(n, "run")
    if k < 8:
        koto.note(bar(n), 0.5, stack("D5", midi("D4"), 3), 72)
        koto.note(bar(n) + 2.5, 0.5, stack("D5", midi("A3"), 2), 64)
play(flute, 17, TUNE, vel=84)
for k, lick in ANSWER.items():
    play(koto, 17 + k, [lick], vel=74)
gong.note(bar(9), 6.0, 60, 92)

# ---- Rooftops, bars 25-40 ------------------------------------------------------------
for k in range(16):
    n = 25 + k
    harmony[n] = ROOFTOPS[k % 4]
    ostinato(n, vel=78)
    pulse(n, vel=76)
    taiko(n, "rooftops")
    violins.note(bar(n), 3.8, stack(harmony[n], midi("D4"), 2), 58)
play(koto, 25, TUNE, vel=82)
play(violins, 33, TUNE, vel=76, transpose=12, length=0.5)  # spiccato: the tune clipped short
play(koto, 33, TUNE, vel=80)
gong.note(bar(33), 5.0, 61, 78)

# ---- Stillness, bars 41-48 -------------------------------------------------------------
for k in range(8):
    n = 41 + k
    harmony[n] = "D5" if k % 4 != 2 else "Eb"
    basses.note(bar(n), 3.9, root(harmony[n], midi("C2")), 60)
    koto.note(bar(n), 3.8, stack(harmony[n], midi("D4"), 2), 50)
    if k % 2 == 0:
        odaiko.note(bar(n), 1.5, 60, 90)
play(flute, 41, [TUNE[0], TUNE[1], [], [], TUNE[4], TUNE[5], [], []], vel=70)
for i in range(16):  # the shime rolls into the strike
    shime.note(bar(48) + 0.25 * i, 0.12, 64, 50 + 4 * i)
odaiko.note(bar(48) + 3.5, 0.4, 60, 100)

# ---- The strike, bars 49-64 --------------------------------------------------------------
for k in range(16):
    n = 49 + k
    harmony[n] = "D5" if k < 8 else ROOFTOPS[k % 4]
    ostinato(n, vel=88)
    pulse(n, vel=86)
    taiko(n, "strike")
play(flute, 49, TUNE, vel=90)
play(violins, 49, TUNE, vel=80, transpose=12, length=0.5)
play(flute, 57, TUNE, vel=92)
play(violins, 57, TUNE, vel=84, transpose=12, length=0.5)
for k, lick in ANSWER.items():
    play(koto, 49 + k, [lick], vel=78)
    play(koto, 57 + k, [lick], vel=80)
gong.note(bar(49), 6.0, 60, 100)
gong.note(bar(57), 6.0, 60, 92)

END_BAR = 65
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz'}}"


PARTS = [("shamisen", shamisen), ("koto", koto), ("flute", flute), ("celli", celli), ("basses", basses),
         ("violins", violins), ("odaiko", odaiko), ("toms", toms), ("shime", shime), ("logs", logs),
         ("clap", clap), ("gong", gong)]


def group(name: str, chain: list[str], gain: float, pan: float = 0.0) -> str:
    lines = [f"    {name}:", "      chain:"] + [f"        - {c}" for c in chain]
    lines.append(f"        - {{processor: gain, gain_db: {gain}}}")
    if pan:
        lines.append(f"        - {{processor: balance, position: {pan}}}")
    return "\n".join(lines)


HALL = "{processor: reverb, wet: 0.18, decay_seconds: 2.0}"
groups = "\n".join([
    group("shamisen", ["{processor: highpass, cutoff_hz: 110}", "{processor: reverb, wet: 0.12, decay_seconds: 1.4}"], -22.0, -0.2),
    group("koto", ["{processor: highpass, cutoff_hz: 140}", HALL], 18.0, 0.25),
    group("flute", ["{processor: highpass, cutoff_hz: 200}", "{processor: reverb, wet: 0.3, decay_seconds: 2.8}"], -10.0),
    group("strings", ["{processor: highpass, cutoff_hz: 35}", HALL], -2.0),
    group("violins", ["{processor: highpass, cutoff_hz: 160}", HALL], 10.0, -0.15),
    group("drums", ["{processor: highpass, cutoff_hz: 30}", "{processor: reverb, wet: 0.16, decay_seconds: 1.8}"], 0.0),
    group("gong", ["{processor: reverb, wet: 0.25, decay_seconds: 3.0}"], 0.0, 0.1),
])
SHAMISEN = "instrument_backend: {kind: soundfont, renderer: fluidsynth-cli, library_ref: japan.shamisen}"

score = f"""schema: ambition.musicir.v3
id: nine_rooftops
title: Nine Rooftops, No Footsteps
description: >-
  A ninja song: D in the miyako-bushi scale at 144 BPM. A shamisen ostinato
  accented three-three-two drives a taiko ensemble; the shakuhachi has the
  tune, a koto and staccato strings answer it; open fifths and the flat
  second, no thirds to rest on. Composed from first principles (Jon,
  2026-10-19). Generated by dev/compose_nine_rooftops.py: edit that, not
  this file.
notes:
  - 'The intro plays once; the loop is bars 9-64, and it ends on the drive that starts it.'
  - 'The koto is a dan tranh, the Vietnamese zither of the same family; the shamisen is the Yukinisuzume SoundFont.'
seed: 909
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 9, beat: 1}}, energy: 0.25, density: 0.2, role: 'the flute alone; the clappers speed up'}}
  - {{id: run, from: {{bar: 9, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.75, density: 0.65, loopable: true, role: 'shamisen and drums; the tune from bar 17'}}
  - {{id: rooftops, from: {{bar: 25, beat: 1}}, to: {{bar: 41, beat: 1}}, energy: 0.65, density: 0.55, loopable: true, role: 'the koto and violins take the tune'}}
  - {{id: stillness, from: {{bar: 41, beat: 1}}, to: {{bar: 49, beat: 1}}, energy: 0.25, density: 0.2, loopable: true, role: 'nearly nothing'}}
  - {{id: strike, from: {{bar: 49, beat: 1}}, to: {{bar: 65, beat: 1}}, energy: 0.95, density: 0.8, loopable: true, role: 'everyone; the gong'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: shamisen, group: shamisen, program: 106, volume: 104, pan: 64, expression: 110, {SHAMISEN}}}
  - {{name: koto, group: koto, program: koto, volume: 100, pan: 64, expression: 106, {vcsl("Chordophones/Zithers/Dan Tranh - Normal")}}}
  - {{name: flute, group: flute, program: shakuhachi, volume: 100, pan: 64, expression: 106}}
  - {{name: celli, group: strings, program: cello, volume: 104, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: strings.celli_staccato}}}}
  - {{name: basses, group: strings, program: contrabass, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, library_ref: strings.basses}}}}
  - {{name: violins, group: violins, program: string_ensemble_1, volume: 100, pan: 64, expression: 106, instrument_backend: {{kind: sfz, library_ref: strings.violins_1_staccato}}}}
  - {{name: odaiko, group: drums, volume: 114, pan: 64, expression: 116, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Bass Drum 1")}}}
  - {{name: toms, group: drums, volume: 108, pan: 64, expression: 110, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Legacy Toms")}}}
  - {{name: shime, group: drums, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl("Membranophones/Struck Membranophones/Frame Drum")}}}
  - {{name: logs, group: drums, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Slit Drum")}}}
  - {{name: clap, group: drums, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Woodblock")}}}
  - {{name: gong, group: gong, volume: 104, pan: 64, expression: 106, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Gong 1")}}}
parts:
{chr(10).join(part(f"{name}_part", name, clip) for name, clip in PARTS)}
processing:
  groups:
{groups}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.0, attack_ms: 15.0, release_ms: 140.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: limiter, target_peak_db: -1.5, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    band: [shamisen, koto, flute]
    orchestra: [strings, violins]
    drums: [drums, gong]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [run, rooftops, stillness, strike], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

"""Reef Break: Tonga, Samoa, Aotearoa and Waitangi in the History dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_history_pacific_island_reggae.py scores/active/history_pacific_island_reggae.music.yaml

The cue is Pacific reggae, the island sound of Aotearoa, Fiji, Samoa and
Tonga since Herbs in the late 1970s: a one-drop beat, the guitar's skank on
2 and 4, an organ that bubbles on the off-beats, a horn section that
answers the tune, and a pātē (a slit log drum of the islands) that rolls
in the intro and in the dub break. The eighths swing. It is centuries early
and does not care. Every melody is original.

80 BPM, 4/4, swung. G major. Form, 32 bars, about 1:36. The whole file
loops; bar 32's D leads to bar 1:
  intro    1-4    the pātē alone, then the bass
  verse    5-12   the one-drop; skank and organ; the tune
  chorus   13-20  the horns answer the tune
  dub      21-24  bass and drums, the pātē, an echo of the skank
  chorus2  25-30  steppers: the kick on every beat, all in
  outro    31-32  G, then D to bar 1
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 80
OUT = Path(sys.argv[1])
rng = random.Random(1840)  # Waitangi

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



def sw(pos) -> F:
    """A position in the bar with its off-beat eighths swung to two thirds of the beat."""
    pos = F(pos).limit_denominator(16)
    whole = pos.numerator // pos.denominator
    return F(whole) + F(2, 3) if pos - whole == F(1, 2) else pos


SECTION = {}
for n in range(1, 33):
    SECTION[n] = ("intro" if n <= 4 else "verse" if n <= 12 else "chorus" if n <= 20 else "dub" if n <= 24
                  else "chorus2" if n <= 30 else "outro")
PROG = (["G", "C", "D", "C"] * 3 + ["Em", "C", "G", "D"] * 2 + ["G", "C", "G", "C"]
        + ["Em", "C", "G", "D", "Em", "C"] + ["G", "D"])
assert len(PROG) == 32
CHORD = {"G": ["G", "B", "D"], "C": ["C", "E", "G"], "D": ["D", "F#", "A"], "Em": ["E", "G", "B"]}
SLIT_HI, SLIT_LO = 60, 61  # VCSL Slit Drum: 60 the high tongue, 61 the low tongue

skank = Clip(0.002, 4)
organ = Clip(0.002, 4)
bass = Clip(0.003, 4)
lead = Clip(0.004, 5)
trumpet = Clip(0.003, 4)
bones = Clip(0.003, 4)
kit = Clip(0.002, 5)
slit = Clip(0.003, 6)


def tones(chord: str, octave: int) -> list[int]:
    out = []
    for p in CHORD[chord]:
        x = midi(f"{p}{octave}")
        while out and x <= out[-1]:
            x += 12
        out.append(x)
    return out


def root(chord: str, octave: int) -> int:
    return midi(f"{CHORD[chord][0]}{octave}")


# ---- The pātē: a rolling sixteenth pattern, high and low tongues ----------------------------------------
ROLL = [SLIT_HI, SLIT_HI, SLIT_LO, SLIT_HI, SLIT_HI, SLIT_LO, SLIT_HI, SLIT_LO,
        SLIT_HI, SLIT_HI, SLIT_LO, SLIT_HI, SLIT_LO, SLIT_HI, SLIT_LO, SLIT_LO]
for n in range(1, 33):
    t, section = T(n), SECTION[n]
    if section in ("intro", "dub"):
        for b in range(4):
            for s in range(4):
                key = ROLL[(b * 4 + s) % 16]
                slit.note(t + b + F(s, 4), F(1, 5), key, 92 if s == 0 else 70 if key == SLIT_LO else 62)
    elif n % 4 == 0:
        # A short roll into the next phrase.
        for s in range(8):
            slit.note(t + 2 + F(s, 4), F(1, 5), ROLL[s], 66 + 2 * s)

# ---- The skank, the organ's bubble and the bass ----------------------------------------------------------
for n in range(1, 33):
    chord, section, t = PROG[n - 1], SECTION[n], T(n)
    r, five = root(chord, 2), midi(f"{CHORD[chord][2]}2")
    if five < r:
        five += 12
    if section == "intro":
        if n >= 3:
            bass.note(t, F(2), r, 88)
            bass.note(t + 2, F(2), five, 80)
        continue
    # The one-drop bass: the root held, a pickup, the fifth, the octave.
    for pos, length, p, vel in ((0, F(5, 4), r, 96), (F(3, 2), F(1, 4), r, 80), (2, F(3, 4), five, 88),
                                (3, F(1, 2), r + 12, 84), (F(7, 2), F(1, 4), five, 78)):
        bass.note(t + sw(pos), length, p, vel)
    ch = tones(chord, 4)
    if section == "dub":
        # Only an echo of the skank: one chop on 2, repeating and fading.
        if n % 2 == 1:
            for k in range(5):
                skank.note(t + 1 + F(3 * k, 4), F(1, 6), ch, 80 - 12 * k)
        continue
    for beat in (1, 3):
        skank.note(t + beat, F(1, 4), ch, 82)
    for beat in range(4):
        organ.note(t + beat + F(2, 3), F(1, 5), [p - 12 for p in ch], 74 if beat % 2 else 66)

# ---- The tune: the verse, and the chorus that the horns answer --------------------------------------------
VERSE = [
    [(0, 1, "B4"), (1, 0.5, "D5"), (1.5, 0.5, "E5"), (2, 2, "D5")],
    [(0, 1, "E5"), (1, 1, "G5"), (2, 1, "E5"), (3, 1, "C5")],
    [(0, 1.5, "D5"), (1.5, 0.5, "F#5"), (2, 1, "A5"), (3, 1, "F#5")],
    [(0, 3, "E5"), (3, 1, "D5")],
    [(0, 1, "B4"), (1, 0.5, "D5"), (1.5, 0.5, "G5"), (2, 2, "B5")],
    [(0, 1, "A5"), (1, 1, "G5"), (2, 1, "E5"), (3, 1, "G5")],
    [(0, 1, "F#5"), (1, 1, "E5"), (2, 1, "D5"), (3, 1, "A4")],
    [(0, 3, "E5"), (3, 1, "F#5")],
]
CHORUS = [
    [(0, 1.5, "G5"), (1.5, 0.5, "F#5"), (2, 1, "E5")],
    [(0, 1.5, "E5"), (1.5, 0.5, "D5"), (2, 1, "C5")],
    [(0, 1, "D5"), (1, 1, "G5"), (2, 1.5, "B5")],
    [(0, 2, "A5"), (2, 1, "F#5"), (3, 1, "D5")],
    [(0, 1.5, "G5"), (1.5, 0.5, "A5"), (2, 1, "B5")],
    [(0, 1.5, "C6"), (1.5, 0.5, "B5"), (2, 1, "G5")],
    [(0, 1, "B5"), (1, 1, "A5"), (2, 1.5, "G5")],
    [(0, 3, "A5"), (3, 1, "D5")],
]
OUTRO = [[(0, 2, "B4"), (2, 2, "D5")], [(0, 1, "F#5"), (1, 1, "A5"), (2, 2, "D5")]]


def play(rows, first_bar, clip, vel, shift=0):
    for k, bar in enumerate(rows):
        for pos, length, name in bar:
            clip.note(T(first_bar + k) + sw(pos), F(length).limit_denominator(4) * F(9, 10), midi(name) + shift, vel + (6 if pos == 0 else 0))


play(VERSE, 5, lead, 84)
play(CHORUS, 13, lead, 88)
play(CHORUS[:6], 25, lead, 92)
play(OUTRO, 31, lead, 84)

# The horns answer on the swung "and" of 3, on 4, and on its "and".
for n in list(range(13, 21)) + list(range(25, 31)):
    chord, t = PROG[n - 1], T(n)
    ch = tones(chord, 4)
    top = [p for p in ch if 62 <= p <= 74] or [ch[1]]
    for k, pos in enumerate((F(5, 2), 3, F(7, 2))):
        if n % 2 == 0 and k == 2:
            continue
        trumpet.note(t + sw(pos), F(1, 4), top[-2:], 92 if k == 1 else 84)
        bones.note(t + sw(pos), F(1, 4), root(chord, 3), 88 if k == 1 else 80)

# ---- The drums: the one-drop, then steppers --------------------------------------------------------------
for n in range(1, 33):
    t, section = T(n), SECTION[n]
    if section == "intro":
        if n == 4:
            kit.note(t + 3, F(1, 4), SNARE, 70)
            kit.note(t + sw(F(7, 2)), F(1, 4), SNARE, 82)
        continue
    loud = {"verse": 86, "chorus": 92, "dub": 88, "chorus2": 96, "outro": 90}[section]
    # The one drop: kick and rim together on 3, and nothing on 1.
    kit.note(t + 2, F(1, 2), KICK, loud + 8)
    kit.note(t + 2, F(1, 4), SIDE, loud)
    if section == "chorus2":
        for b in (0, 1, 3):
            kit.note(t + b, F(1, 2), KICK, loud)
    for e in range(8):
        kit.note(t + sw(F(e, 2)), F(1, 8), HAT, loud - 30 + (10 if e % 2 == 0 else 0))
    if n % 4 == 0:
        kit.note(t + sw(F(7, 2)), F(1, 4), OPEN_HAT, loud - 20)
    if n in (5, 13, 25):
        kit.note(t, F(2), CRASH, loud + 6)

END_BAR = 33
for clip in (skank, organ, bass, lead, trumpet, bones, kit, slit):
    clip.events = [(t, min(d, T(END_BAR) - t), ps, v) for t, d, ps, v in clip.events]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


def curve(points: dict[int, float]) -> str:
    body = ", ".join(f"{k}: {v}" for k, v in sorted(points.items()))
    return f"tuning_correction: {{mode: curve, interpolation: linear, max_abs_cents: 50, points: {{{body}}}}}, "


#: Measured with `cue tuning_audit` (2026-11-04): the Swagbass is 7 to 11
#: cents sharp; the staccato trumpets are 6 to 10 cents flat from C4 to F4;
#: the staccato trombones' F#3 is 21 cents flat; Surge's Classic Lead 2 is
#: about 10 cents flat.
SWAG_TUNING = "tuning_correction: {mode: global, cents: -9.0}, "
LEAD_TUNING = "tuning_correction: {mode: global, cents: 9.8}, "
TRUMPET_TUNING = {55: 0, 60: 10, 61: 10, 62: 10, 63: 6, 64: 8, 65: 9, 67: 4, 74: 7, 79: 0}
BONES_TUNING = {52: 0, 54: 21, 55: 0}


def sfz(ref: str) -> str:
    return f"instrument_backend: {{kind: sfz, optional: false, library_ref: {ref}}}"


def vcsl(path: str) -> str:
    return f"instrument_backend: {{kind: sfz, optional: false, sfz_glob: '**/VCSL-1.2.2-RC/{path}.sfz', settings: {{fold_to_range: false}}}}"


def surge(patch: str) -> str:
    return f"instrument_backend: {{kind: surge, patch: '{patch}'}}"


#: group gains in dB, set from the section levels that dev/measure_stems.py reads.
GAIN = {"skank": 10.5, "organ": -14.0, "bass": 6.0, "lead": -16.0, "brass": 7.0, "drums": 0.0, "slit": 8.0}
#: Shinyguitar's acoustic programs are silent while CC100 (pickup to microphone
#: blend) is 0. The guitars set it, and every sampled backend here is not
#: optional, so a silent one stops the render instead of falling back to General MIDI.
score = f"""schema: ambition.musicir.v3
id: history_pacific_island_reggae
title: Reef Break
description: >-
  Tonga, Samoa, Aotearoa and Waitangi in the History dimension: Pacific
  reggae, the island sound since Herbs. A one-drop beat, the skank on 2
  and 4, a bubbling organ, horns that answer the tune, and a pātē (a slit
  log drum) that rolls in the intro and the dub break. G major, 80 BPM,
  swung. Generated by dev/compose_history_pacific_island_reggae.py: edit
  that, not this file.
notes:
  - 'Form: intro 1-4, verse 5-12, chorus 13-20, dub 21-24, chorus2 25-30, outro 31-32; the D of bar 32 leads to bar 1.'
  - 'Every melody here is original.'
  - 'Layered for a room: bed (skank, organ, bass, drums, slit), tune (lead, brass).'
seed: 1840
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: G major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.35, density: 0.4, loopable: true, role: 'the pātē, then the bass'}}
  - {{id: verse, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.6, density: 0.6, loopable: true, role: 'the one-drop and the tune'}}
  - {{id: chorus, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.8, density: 0.8, loopable: true, role: 'the horns answer'}}
  - {{id: dub, from: {{bar: 21, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.5, density: 0.5, loopable: true, role: 'bass, drums, pātē and echo'}}
  - {{id: chorus2, from: {{bar: 25, beat: 1}}, to: {{bar: 31, beat: 1}}, energy: 1.0, density: 0.9, loopable: true, role: 'steppers, all in'}}
  - {{id: outro, from: {{bar: 31, beat: 1}}, to: {{bar: {END_BAR}, beat: 1}}, energy: 0.7, density: 0.6, loopable: true, role: 'G, then D to bar 1'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(PROG)}]
instruments:
  - {{name: skank, group: skank, program: clean_guitar, volume: 100, pan: 44, expression: 104, controls: {{100: 126}}, {sfz("guitar.clean")}}}
  - {{name: organ, group: organ, program: drawbar_organ, volume: 100, pan: 86, expression: 104, {surge("Keys/Organ 1")}}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 116, pan: 64, expression: 116, {SWAG_TUNING}{sfz("bass.swag")}}}
  - {{name: lead, group: lead, program: lead_square, volume: 100, pan: 64, expression: 104, {LEAD_TUNING}{surge("Leads/Classic Lead 2")}}}
  - {{name: trumpet, group: brass, program: trumpet, volume: 108, pan: 74, expression: 112, {curve(TRUMPET_TUNING)}{sfz("orchestra.trumpets_staccato")}}}
  - {{name: bones, group: brass, program: trombone, volume: 104, pan: 54, expression: 108, {curve(BONES_TUNING)}{sfz("orchestra.trombones_staccato")}}}
  - {{name: kit, group: drums, is_drum: true, volume: 116, pan: 64, expression: 114, {sfz("drums.muldjord")}}}
  - {{name: slit, group: slit, volume: 104, pan: 40, expression: 106, is_drum: true, {vcsl("Idiophones/Struck Idiophones/Slit Drum")}}}
parts:
{part("skank_part", "skank", skank)}
{part("organ_part", "organ", organ)}
{part("bass_part", "bass", bass)}
{part("lead_part", "lead", lead)}
{part("trumpet_part", "trumpet", trumpet)}
{part("bones_part", "bones", bones)}
{part("kit_part", "kit", kit)}
{part("slit_part", "slit", slit)}
processing:
  groups:
    skank:
      chain:
        - {{processor: highpass, cutoff_hz: 220}}
        - {{processor: reverb, wet: 0.16, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: {GAIN["skank"]}}}
    organ:
      chain:
        - {{processor: highpass, cutoff_hz: 160}}
        - {{processor: gain, gain_db: {GAIN["organ"]}}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 32}}
        - {{processor: gain, gain_db: {GAIN["bass"]}}}
    lead:
      chain:
        - {{processor: highpass, cutoff_hz: 200}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: {GAIN["lead"]}}}
    brass:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["brass"]}}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: {GAIN["drums"]}}}
    slit:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - {{processor: reverb, wet: 0.18, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: {GAIN["slit"]}}}
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
    bed: [skank, organ, bass, drums, slit]
    tune: [lead, brass]
  sections:
    - {{id: song, form: [intro, verse, chorus, dub, chorus2, outro], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, about {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

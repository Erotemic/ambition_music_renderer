"""The Fire Escape: a lofi beat to study or relax to, led by a tenor sax.
Writes its MusicIR v3 score:

    python3 dev/compose_the_fire_escape.py scores/active/the_fire_escape.music.yaml

Jon, 2026-10-19: "another lofi song to study and or relax to that leans into
the sax. The trick is make sure it isn't elevator music." Composed from first
principles. What keeps it out of the elevator:

  - The sax plays a HOOK, not a solo: one four-bar phrase that comes round
    like a chopped sample, with rests the band does not fill. Smooth jazz
    noodles; a beat loops.
  - Minor, with an altered dominant: C minor, Cm9 - Abmaj7(#11) - Fm9 -
    G7(b9 b13). The G7 is sour on purpose and the loop never sits on a
    pretty major seventh for long.
  - The drums are drunk: a heavy swing, the kick a hair early, the snare
    late, eighth hats that drift. Dusty, resampled, not polished.
  - An upright piano chopped into short stabs, a round sub bass, and the
    record itself: dust, surface hiss and the odd woody tick.

Form, 4/4 at 82 BPM:
  intro    1-4    the piano alone, and the record.
  hook     5-20   the beat; the sax hook four times, the last time pushed up.   (loop start)
  bridge   21-36  the turn to F minor; the sax sparse and low, the ride for the hats.
  break    37-44  no bass; rim and kick; the piano plays the hook, the sax answers.
  return   45-60  the hook again, the piano doubling its tail; home to G7 and the top.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 82
OUT = Path(sys.argv[1])
rng = random.Random(2077)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}

#: The swing: the second sixteenth of each eighth lands this far into it.
SWING = 0.62
#: The snare and the sax sit this far behind the beat; the kick this far ahead (beats).
LATE = 0.05
EARLY = 0.015


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


def bar(n: int) -> float:
    return (n - 1) * 4.0


keys = Clip(drift=0.02, vel_jitter=5)
bass = Clip(drift=0.015, vel_jitter=4)
kit = Clip(drift=0.02, vel_jitter=6)
hats = Clip(drift=0.03, vel_jitter=9)
sax = Clip(drift=0.025, vel_jitter=4)
ticks = Clip()
crackle = Clip()
hiss = Clip()

# ---- Chords: rootless voicings in the middle of the piano -----------------------
VOICING = {
    "Cm9": ["Bb3", "D4", "Eb4", "G4"],
    "Abmaj7#11": ["G3", "C4", "D4", "Eb4"],
    "Fm9": ["Ab3", "C4", "Eb4", "G4"],
    "G7alt": ["F3", "Ab3", "B3", "Eb4"],
    "Bb13": ["Ab3", "C4", "D4", "G4"],
    "Ebmaj9": ["G3", "Bb3", "D4", "F4"],
    "Dm7b5": ["Ab3", "C4", "D4", "F4"],
    "Gsusb9": ["F3", "Ab3", "C4", "D4"],
}
ROOT = {"Cm9": "C2", "Abmaj7#11": "Ab1", "Fm9": "F1", "G7alt": "G1", "Bb13": "Bb1", "Ebmaj9": "Eb2",
        "Dm7b5": "D2", "Gsusb9": "G1"}
HOOK_CHORDS = ["Cm9", "Abmaj7#11", "Fm9", "G7alt"]
BRIDGE_CHORDS = ["Fm9", "Bb13", "Ebmaj9", "Abmaj7#11", "Dm7b5", "G7alt", "Cm9", "Gsusb9"]


def chop(n: int, name: str, figure: int, vel=60):
    """One bar of piano cut like a sample: a short stab on one, a swung
    re-hit, a longer chord on the 'and' of three; every other bar the next
    chord is pushed in early."""
    t = bar(n)
    notes = VOICING[name]
    if figure == 0:
        keys.note(t, 0.7, notes, vel + 6)
        keys.note(t + swung(1.75), 0.4, notes[1:], vel - 6)
        keys.note(t + 2.5, 1.3, notes, vel)
    elif figure == 1:
        keys.note(t, 1.4, notes, vel + 4)
        keys.note(t + swung(2.25), 0.5, notes[2:], vel - 8)
        keys.note(t + 3.0, 0.4, notes[:2], vel - 10)
    else:  # the break: one held chord, its top voice a beat later
        keys.note(t, 3.8, notes[:3], vel)
        keys.note(t + 1, 2.8, notes[3], vel - 8)


def sub(n: int, name: str, nxt: str, busy: bool, vel=86):
    """Round bass: the root held, a pickup on the swung 'a' of two, the root
    again on the 'and' of three, and a slide into the next bar."""
    t = bar(n)
    root = midi(ROOT[name])
    target = midi(ROOT[nxt])
    bass.note(t - EARLY if n > 1 else t, 1.6, root, vel)
    if busy:
        bass.note(t + swung(1.75), 0.35, root + 12, vel - 18)
        bass.note(t + 2.5, 1.0, root, vel - 6)
        if n % 2 == 0:
            bass.note(t + swung(3.75), 0.25, target + (1 if target < root else -1), vel - 14)
    else:
        bass.note(t + 2.5, 1.3, root, vel - 8)


KICK, SNARE, RIM, HAT, OPEN_HAT, RIDE, STICKS = 36, 38, 37, 42, 46, 51, 31


def groove(n: int, style: str):
    """The kick a hair early on one, the 'a' of one and the 'and' of three;
    the snare late on two and four; eighth hats (or the ride) that drift."""
    t = bar(n)
    if style in ("hook", "bridge", "fill"):
        for o, v in ((0, 100), (swung(0.75), 72), (2.5, 90)):
            kit.note(t + o - EARLY, 0.2, KICK, v)
        if n % 2 == 1:
            kit.note(t + swung(3.25) - EARLY, 0.15, KICK, 64)
    elif style == "break":
        kit.note(t, 0.2, KICK, 90)
    for o in (1, 3):
        kit.note(t + o + LATE, 0.2, RIM if style == "break" else SNARE, 84 if style == "break" else 96)
    if style != "break":
        kit.note(t + swung(1.75) + LATE, 0.1, SNARE, 30)
    cymbal = RIDE if style == "bridge" else HAT
    for i in range(8):
        o = 0.5 * i
        accent = 70 if i % 2 == 0 else 48
        hats.note(t + o, 0.1, OPEN_HAT if (i == 7 and n % 4 == 0 and style == "hook") else cymbal, accent)
        if style == "hook" and i in (3, 6) and n % 2 == 0:
            hats.note(t + swung(o + 0.25), 0.08, HAT, 36)
    if style == "fill":
        for i, o in enumerate((3.0, swung(3.25), 3.5, swung(3.75))):
            kit.note(t + o + LATE, 0.12, SNARE, 46 + 12 * i)


# ---- The sax ----------------------------------------------------------------------
# (beat, length, note) per bar; a rest is a bar with nothing in it.
HOOK = [
    [(0.0, 0.75, "Eb4"), (0.75, 0.25, "F4"), (1.0, 0.5, "G4"), (1.5, 1.5, "Bb4"), (3.5, 0.5, "G4")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "C5"), (2.0, 1.75, "G4")],
    [(0.0, 0.5, "Ab4"), (0.5, 0.5, "G4"), (1.0, 0.5, "F4"), (1.5, 1.0, "Eb4"), (2.75, 0.25, "C4"), (3.0, 1.0, "Eb4")],
    [(0.0, 0.75, "Ab4"), (0.75, 0.25, "G4"), (1.0, 0.5, "F4"), (1.5, 0.5, "Eb4"), (2.0, 1.75, "B3")],
]
# The fourth time round the hook climbs: the same rhythm, its peaks a step up.
HOOK_UP = [
    [(0.0, 0.75, "Eb4"), (0.75, 0.25, "G4"), (1.0, 0.5, "Bb4"), (1.5, 1.5, "C5"), (3.5, 0.5, "Bb4")],
    [(0.0, 1.5, "Eb5"), (1.5, 0.5, "D5"), (2.0, 1.75, "G4")],
    HOOK[2],
    [(0.0, 0.75, "Ab4"), (0.75, 0.25, "G4"), (1.0, 0.5, "F4"), (1.5, 0.5, "D4"), (2.0, 1.75, "B3")],
]
# Over the bridge: low, breathy, long tones and space.
BRIDGE = [
    [(0.5, 0.5, "C4"), (1.0, 0.5, "Eb4"), (1.5, 2.0, "G4")],
    [(0.0, 0.5, "F4"), (0.5, 0.5, "G4"), (1.0, 0.5, "Ab4"), (1.5, 0.5, "G4"), (2.0, 1.5, "D4")],
    [(0.5, 0.5, "Bb3"), (1.0, 0.5, "D4"), (1.5, 0.5, "F4"), (2.0, 2.0, "G4")],
    [(0.0, 0.75, "Bb4"), (0.75, 0.25, "C5"), (1.0, 1.5, "D5"), (2.5, 0.5, "C5"), (3.0, 1.0, "G4")],
    [(0.0, 1.0, "Ab4"), (1.0, 0.5, "F4"), (1.5, 0.5, "D4"), (2.0, 1.0, "C4"), (3.0, 0.5, "D4"), (3.5, 0.5, "F4")],
    [(0.0, 1.5, "Ab4"), (1.5, 0.5, "G4"), (2.0, 0.5, "F4"), (2.5, 0.5, "Eb4"), (3.0, 1.0, "B3")],
    [(0.0, 2.0, "D4"), (2.0, 0.5, "Eb4"), (2.5, 1.25, "C4")],
    [(2.0, 0.5, "F4"), (2.5, 0.5, "G4"), (3.0, 1.0, "Ab4")],
]
# The break: the sax answers the piano's hook with one held note each time.
ANSWERS = [
    [], [(2.5, 1.5, "G4")], [], [(2.0, 1.75, "B3")],
    [], [(2.5, 1.5, "D5")], [], [(2.0, 0.5, "F4"), (2.5, 0.5, "Eb4"), (3.0, 1.0, "D4")],
]


def play(clip: Clip, n: int, phrase, vel=80, octave=0, late=LATE, length=0.94):
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            clip.note(bar(n + k) + swung(at) + late, dur * length, midi(name) + 12 * octave,
                      vel + (6 if at == 0 else 0))


harmony: dict[int, str] = {}


MARACAS, CABASA = 70, 69


def vinyl(n0: int, n1: int, per_bar=42):
    """The record: dust (many tiny toneless ticks, mostly faint, now and then
    a pop), the surface hiss under it, and a rare woody tick."""
    for n in range(n0, n1):
        for _ in range(per_bar):
            v = min(30, int(rng.expovariate(1 / 9)) + 3)
            crackle.note(bar(n) + rng.uniform(0, 3.98), 0.02, rng.choice((CABASA, MARACAS)), v)
        for _ in range(rng.randint(0, 2)):
            crackle.note(bar(n) + rng.uniform(0, 3.98), 0.02, CABASA, rng.randint(40, 62))
        if rng.random() < 0.45:
            ticks.note(bar(n) + rng.uniform(0, 3.95), 0.05, STICKS, rng.randint(8, 22))
    for n in range(n0, n1, 4):
        hiss.note(bar(n), min(16.0, (n1 - n) * 4.0), 60, 50)


# Intro, bars 1-4: the piano alone, and the record.
for k in range(4):
    n = 1 + k
    chop(n, HOOK_CHORDS[k], k % 2, vel=54)
    harmony[n] = HOOK_CHORDS[k]
bass.note(bar(4) + 3.0, 0.9, midi("G1"), 72)

# Hook, bars 5-20: the beat; the sax hook four times, the fourth pushed up.
for k in range(16):
    n = 5 + k
    name = HOOK_CHORDS[k % 4]
    chop(n, name, k % 2)
    sub(n, name, HOOK_CHORDS[(k + 1) % 4], busy=k >= 4)
    groove(n, "fill" if k in (7, 15) else "hook")
    harmony[n] = name
play(sax, 5, HOOK, vel=78)
play(sax, 9, HOOK, vel=80)
play(sax, 13, HOOK, vel=82)
play(sax, 17, HOOK_UP, vel=86)

# Bridge, bars 21-36: the turn to F minor; the sax low and sparse, the ride.
for k in range(16):
    n = 21 + k
    name = BRIDGE_CHORDS[k % 8]
    chop(n, name, k % 2)
    sub(n, name, BRIDGE_CHORDS[(k + 1) % 8], busy=True)
    groove(n, "fill" if k == 15 else "bridge")
    harmony[n] = name
play(sax, 21, BRIDGE, vel=74)
# Second time round, the sax sits out four bars and the piano fills them.
play(keys, 29, [[(2.5, 0.5, "C5"), (3.0, 0.5, "Bb4"), (3.5, 0.5, "G4")],
                [(2.0, 0.5, "F4"), (2.5, 0.5, "G4"), (3.0, 1.0, "D5")],
                [(2.5, 0.5, "Bb4"), (3.0, 1.0, "G4")],
                [(2.0, 0.5, "C5"), (2.5, 1.0, "D5")]], vel=58, late=0.0)
play(sax, 33, BRIDGE[4:], vel=80)

# Break, bars 37-44: no bass; rim and kick; the piano plays the hook, the sax answers.
for k in range(8):
    n = 37 + k
    name = HOOK_CHORDS[k % 4]
    chop(n, name, 2, vel=52)
    groove(n, "break")
    harmony[n] = name
play(keys, 37, HOOK, vel=62, late=0.0, length=0.8)
play(keys, 41, HOOK, vel=60, late=0.0, length=0.8)
play(sax, 37, ANSWERS, vel=70)
bass.note(bar(44) + 3.0, 0.9, midi("G1"), 74)

# Return, bars 45-60: the hook again; the piano doubles its tail an octave up.
for k in range(16):
    n = 45 + k
    name = HOOK_CHORDS[k % 4]
    chop(n, name, k % 2)
    sub(n, name, HOOK_CHORDS[(k + 1) % 4], busy=True)
    groove(n, "fill" if k in (7, 15) else "hook")
    harmony[n] = name
play(sax, 45, HOOK, vel=82)
play(sax, 49, HOOK_UP, vel=86)
play(sax, 53, HOOK, vel=80)
play(sax, 57, HOOK, vel=76)
for n in (54, 58):
    play(keys, n, [HOOK[1]], vel=52, octave=1, late=0.0, length=0.6)

vinyl(1, 61)

END_BAR = 61
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


NAKED = "instrument_backend: {kind: sfz, library_ref: drums.naked, settings: {render_timeout_s: 900}}"
TENOR = "instrument_backend: {kind: sfz, sfz_glob: '**/Reed Aerophones/Tenor Saxophone - Vibrato.sfz'}"

score = f"""schema: ambition.musicir.v3
id: the_fire_escape
title: The Fire Escape
description: >-
  A lofi beat to study or relax to, led by a tenor sax: C minor at 82 BPM, a
  drunk boom-bap on a dusty kit, an upright piano chopped into stabs, a round
  sub bass and the crackle of a record. The sax plays a hook that comes round like a
  sample rather than a solo, over Cm9, Abmaj7(#11), Fm9 and an altered G7.
  Composed from first principles (Jon, 2026-10-19). Generated by
  dev/compose_the_fire_escape.py: edit that, not this file.
notes:
  - 'Not elevator music: a looped hook with rests, minor chords and a sour altered dominant, drums that lean off the grid.'
  - 'The intro plays once; the loop is bars 5-60, and its last chord (G7 altered) leads back to C minor at bar 5.'
  - 'The record is General MIDI: maraca and cabasa ticks for the dust, the rain effect high-passed for the hiss, the kit''s sticks for the odd tick.'
seed: 2077
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: C minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.3, density: 0.25, role: 'the piano alone, and the record'}}
  - {{id: hook, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.55, density: 0.5, loopable: true, role: 'the beat; the sax hook'}}
  - {{id: bridge, from: {{bar: 21, beat: 1}}, to: {{bar: 37, beat: 1}}, energy: 0.5, density: 0.5, loopable: true, role: 'the turn to F minor; the sax low; the ride'}}
  - {{id: break, from: {{bar: 37, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.35, density: 0.35, loopable: true, role: 'no bass; the piano has the hook, the sax answers'}}
  - {{id: return, from: {{bar: 45, beat: 1}}, to: {{bar: 61, beat: 1}}, energy: 0.6, density: 0.55, loopable: true, role: 'the hook again, home to G7'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: keys, group: keys, program: acoustic_grand_piano, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, library_ref: freepats.upright_piano_kw}}}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 110, pan: 64, expression: 112, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndBlueBasses/Programs/04-babyblue_warm.sfz'}}}}
  - {{name: kit, group: drums, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: hats, group: hats, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: sax, group: sax, program: tenor_sax, volume: 100, pan: 64, expression: 106, {TENOR}}}
  - {{name: ticks, group: ticks, volume: 100, pan: 64, expression: 100, is_drum: true}}
  - {{name: crackle, group: crackle, volume: 100, pan: 64, expression: 100, is_drum: true}}
  - {{name: hiss, group: hiss, program: fx_rain, volume: 90, pan: 64, expression: 96}}
parts:
{part("keys_part", "keys", keys)}
{part("bass_part", "bass", bass)}
{part("kit_part", "kit", kit)}
{part("hats_part", "hats", hats)}
{part("sax_part", "sax", sax)}
{part("ticks_part", "ticks", ticks)}
{part("crackle_part", "crackle", crackle)}
{part("hiss_part", "hiss", hiss)}
processing:
  groups:
    keys:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - processor: pedalboard
          effects:
            - {{effect: resample, target_sample_rate: 16000}}
            - {{effect: chorus, rate_hz: 0.3, depth: 0.08, mix: 0.25}}
        - {{processor: lowpass, cutoff_hz: 4200}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.5, attack_ms: 10.0, release_ms: 120.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 3.0}}
        - {{processor: balance, position: -0.2}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 32}}
        - {{processor: lowpass, cutoff_hz: 900}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 80, q: 0.8, db: 2.5}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 25.0, release_ms: 140.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -6.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 40}}
        - processor: pedalboard
          effects:
            - {{effect: resample, target_sample_rate: 20000}}
            - {{effect: distortion, drive_db: 4.0}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 70, q: 1.0, db: 2.5}}
            - {{type: peak, hz: 3000, q: 1.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 6500}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.5, attack_ms: 12.0, release_ms: 80.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -3.0}}
    hats:
      chain:
        - {{processor: highpass, cutoff_hz: 350}}
        - processor: pedalboard
          effects:
            - {{effect: resample, target_sample_rate: 20000}}
        - {{processor: lowpass, cutoff_hz: 6500}}
        - {{processor: gain, gain_db: 15.0}}
        - {{processor: balance, position: 0.25}}
    sax:
      chain:
        - {{processor: highpass, cutoff_hz: 140}}
        - processor: pedalboard
          effects:
            - {{effect: distortion, drive_db: 3.0}}
            - {{effect: resample, target_sample_rate: 24000}}
        - {{processor: lowpass, cutoff_hz: 5500}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 15.0, release_ms: 120.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.22, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: -4.3}}
        - {{processor: balance, position: 0.1}}
    ticks:
      chain:
        - {{processor: highpass, cutoff_hz: 3000}}
        - {{processor: lowpass, cutoff_hz: 8000}}
        - {{processor: gain, gain_db: 0.0}}
    crackle:
      chain:
        - {{processor: highpass, cutoff_hz: 1800}}
        - processor: pedalboard
          effects:
            - {{effect: resample, target_sample_rate: 22050}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: gain, gain_db: -6.3}}
    hiss:
      chain:
        - {{processor: highpass, cutoff_hz: 2500}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: gain, gain_db: 14.2}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 30}}
      - {{processor: lowpass, cutoff_hz: 9000}}
      - {{processor: compressor, threshold_db: -20.0, ratio: 2.5, attack_ms: 20.0, release_ms: 150.0, makeup_db: 2.0, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.08}}
      - {{processor: limiter, target_peak_db: -2.0, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  layers:
    bed: [keys, bass, ticks, crackle, hiss]
    beat: [drums, hats]
    tune: [sax]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [hook, bridge, break, return], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

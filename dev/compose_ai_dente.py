"""AI Dente: reggae for exploring and fighting in the Noodle dimension.
Writes its MusicIR v3 score:

    python3 dev/compose_ai_dente.py scores/active/ai_dente.music.yaml

Jon, 2026-10-20: "another Reggae tune for the noodle dimension that is more
suitable for exploration and combat, no holy aspect this time." So no choir,
no celesta, no harp. ("AI Dente", A-eye: Jon's pun on al dente.)

What sets it apart from its two siblings (Pastafarian, G major, guitar-led;
It Was Revealed to Me in a Dream, D major, holy):
  - A minor, Aeolian (Am G F G), a bridge that turns hard (Dm Am F E).
  - The tune is on a noodly guitar (Pastafarian's lead sound, an octave lower);
    a second guitar answers it and takes the bridge. Jon picked it from a reel
    of four leads after rejecting a distorted rock organ.
  - Rockers drums while exploring: the kick on one and three, the cross-stick
    on three, eighth hats; a busier, driving one-bar bass.
  - A short dub break: bass and drums, the guitar thrown into the echo.

Built for a level, in LAYERS the game mixes (the `playback` block):
  bed     skank, organ bubble, bass         always
  drums   rockers                           exploring
  tune    the lead guitar, the answers      exploring
  combat  steppers drums with rolls, crunch guitar on every off-beat, horn
          stabs and a horn call, a dub siren
Every layer runs through every bar of the loop, so a fight can bring the
combat layer up anywhere and take it away again.

Form, 4/4 at 80 BPM:
  intro    1-4    a siren, the organ chords, a roll.
  theme    5-20   rockers; the lead sings the theme, the guitar answers.    (loop start)
  bridge   21-28  Dm Am F E: the guitar takes the lead.
  dub      29-32  bass and drums; echoes.
  theme_2  33-48  the theme, the second guitar doubling the lead an octave down; on E.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 80
OUT = Path(sys.argv[1])
#: The lead sings the theme an octave below where it is written, so its held
#: notes stay at or below A5.
LEAD_OCTAVE = -1
rng = random.Random(4242)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: Pitch-bend units a cent: the Shiny guitar bends 200 cents; General MIDI bends 200 too.
BEND_PER_CENT = 8192 / 200


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
        self.bends: list[tuple] = []
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
        if self.bends:
            lines.append(f"{indent}  automation:")
            seen = {}
            for when, value in sorted(self.bends):
                seen[frac(when)] = value
            for i, (when, value) in enumerate(seen.items()):
                lines.append(f"{indent}    - {{id: {clip_id}_bend_{i:04d}, at: {when}, pitch_bend: {value}}}")
        return "\n".join(lines)


def bar(n: int) -> float:
    return (n - 1) * 4.0


lead = Clip(drift=0.003, vel_jitter=3)
guitar = Clip(drift=0.004, vel_jitter=4)
skank = Clip(drift=0.002, vel_jitter=4)
bubble_organ = Clip(drift=0.002, vel_jitter=4)
bass = Clip(drift=0.003, vel_jitter=3)
kit = Clip(drift=0.003, vel_jitter=4)
hats = Clip(drift=0.004, vel_jitter=6)
war_kit = Clip(drift=0.003, vel_jitter=4)
crunch = Clip(drift=0.002, vel_jitter=4)
trumpets = Clip(drift=0.004, vel_jitter=3)
trombones = Clip(drift=0.004, vel_jitter=3)
siren = Clip()

# ---- Harmony ------------------------------------------------------------------------
SKANK = {"Am": ["A3", "C4", "E4"], "G": ["B3", "D4", "G4"], "F": ["A3", "C4", "F4"], "Dm": ["A3", "D4", "F4"], "E": ["B3", "E4", "G#4"],
         "Em": ["B3", "E4", "G4"]}
BUBBLE = {"Am": ["E3", "A3", "C4"], "G": ["D3", "G3", "B3"], "F": ["F3", "A3", "C4"], "Dm": ["F3", "A3", "D4"], "E": ["E3", "G#3", "B3"],
          "Em": ["E3", "G3", "B3"]}
ROOT = {"Am": "A1", "G": "G1", "F": "F1", "Dm": "D2", "E": "E1", "Em": "E1"}
THEME = ["Am", "G", "F", "G"] * 4
BRIDGE = ["Dm", "Am", "F", "E", "Dm", "Am", "F", "E"]
DUB = ["Am", "Am", "F", "E"]
harmony: dict[int, str] = {}


def skank_bar(n, name, vel=74):
    """The chop on two and four, and the 'chk' after four (rockers)."""
    t = bar(n)
    for o in (1.0, 3.0):
        skank.note(t + o, 0.15, SKANK[name], vel)
    skank.note(t + 3.25, 0.1, SKANK[name], vel - 16)


def bubble(n, name, vel=56):
    t = bar(n)
    for k in range(4):
        bubble_organ.note(t + k + 0.5, 0.2, BUBBLE[name], vel)
        bubble_organ.note(t + k + 0.75, 0.16, BUBBLE[name], vel - 14)


def bassline(n, name, nxt, vel=94, dub=False):
    """Rockers: a driving one-bar riff that still leaves the hole after three;
    the dub's is a few long notes."""
    t = bar(n)
    r = midi(ROOT[name])
    fifth, octave = r + 7, r + 12
    minor = name in ("Am", "Dm", "Em")
    third = r + (3 if minor else 4)
    nxt_r = midi(ROOT[nxt])
    # into the next root from the nearest A minor scale tone on the side it comes from
    scale = (9, 11, 0, 2, 4, 5, 7)
    step = 1 if nxt_r < r else -1
    approach = nxt_r + step
    while approach % 12 not in scale:
        approach += step
    if dub:
        bass.note(t, 1.4, r, vel + 2)
        bass.note(t + 2.5, 0.45, fifth, vel - 6)
        bass.note(t + 3.0, 0.9, octave if name != "E" else r, vel - 2)
        return
    bass.note(t, 0.45, r, vel + 2)
    bass.note(t + 0.5, 0.45, r, vel - 8)
    bass.note(t + 0.75, 0.2, third, vel - 12)
    bass.note(t + 1.0, 0.45, fifth, vel - 4)
    bass.note(t + 1.5, 0.45, octave, vel - 6)
    bass.note(t + 2.0, 0.7, fifth, vel)
    bass.note(t + 3.0, 0.45, third, vel - 6)
    bass.note(t + 3.5, 0.45, approach, vel - 10)


KICK, SNARE, XSTICK, HAT, OPEN_HAT, HI_TOM, MID_TOM, FLOOR_TOM, CRASH = 36, 38, 37, 42, 46, 50, 47, 41, 49


def rockers(n, sparse=False):
    """The kick on one and three, the cross-stick on three, eighth hats."""
    t = bar(n)
    kit.note(t, 0.2, KICK, 96)
    kit.note(t + 2.0, 0.2, KICK, 104)
    kit.note(t + 2.0, 0.2, XSTICK, 92)
    if not sparse:
        kit.note(t + 1.0, 0.15, XSTICK, 46)
    for k in range(4):
        if sparse and k % 2 == 0:
            continue
        hats.note(t + k, 0.1, HAT, 62)
        hats.note(t + k + 0.5, 0.1, OPEN_HAT if (k == 3 and n % 4 == 0) else HAT, 44)


def war_drums(n, last_of_phrase=False, crash=False):
    t = bar(n)
    if crash:
        war_kit.note(t, 0.4, CRASH, 100)
    for k in range(4):
        war_kit.note(t + k, 0.2, KICK, 106 if k % 2 == 0 else 98)
        for s in range(4):
            war_kit.note(t + k + s * 0.25, 0.06, HAT, (58, 30, 46, 30)[s])
    for o in (1.0, 3.0):
        if last_of_phrase and o == 3.0:
            continue
        war_kit.note(t + o, 0.2, SNARE, 102)
    if last_of_phrase:
        for i in range(8):
            war_kit.note(t + 2.0 + i * 0.25, 0.1, SNARE if i < 4 else (HI_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM)[i - 4], 70 + 5 * i)


def war_bar(n, name):
    t = bar(n)
    r = midi(ROOT[name]) + 12
    power = [r, r + 7, r + 12]
    crunch.note(t, 0.3, power, 100)
    for b in range(4):
        crunch.note(t + b + 0.5, 0.22, power, 92 if b % 2 else 84)
    stab = [midi(x) + 12 for x in SKANK[name]]
    for o in (1.5, 3.0):
        trumpets.note(t + o, 0.28, stab, 92)
        trombones.note(t + o, 0.28, [p - 12 for p in stab], 90)


#: The horn call that answers every fourth bar of a fight.
HORN_CALL = [(0.0, 0.5, "E5"), (0.5, 0.5, "A5"), (1.0, 0.5, "G5"), (1.5, 1.5, "E5"), (3.0, 0.25, "D5"), (3.25, 0.25, "C5"), (3.5, 0.5, "B4")]


def horn_call(n):
    t = bar(n)
    for at, dur, name in HORN_CALL:
        trumpets.note(t + at, dur * 0.9, midi(name), 96)
        trombones.note(t + at, dur * 0.9, midi(name) - 12, 92)


def dub_siren(n):
    """The dub siren: a square wave whooping up and down through two bars."""
    t = bar(n)
    siren.note(t, 7.6, midi("A5"), 70)
    for i in range(33):
        at = t + i * 0.25
        phase = (i % 8) / 8
        cents = -200 + 800 * min(phase, 1 - phase)  # -200 up to +200 cents and back, every two beats
        siren.bends.append((F(at).limit_denominator(960), max(-8191, min(8191, round(cents * BEND_PER_CENT)))))
    siren.bends.append((F(t + 8.0).limit_denominator(960), 0))


# ---- The tune ------------------------------------------------------------------------
def slide(clip: Clip, at: float, cents: float, over: float = 0.18):
    start = round(-cents * BEND_PER_CENT)
    clip.bends.append((F(at).limit_denominator(960) - F(1, 64), max(-8191, start)))
    for i in (1, 2, 3):
        clip.bends.append((F(at + over * i / 3).limit_denominator(960), round(start * (1 - i / 3))))


def sing(clip: Clip, n: int, phrase, vel=84, octave=0, length=0.95):
    for k, notes in enumerate(phrase):
        for note in notes:
            at, dur, name = note[:3]
            orn = note[3] if len(note) > 3 else ""
            when = bar(n + k) + at
            pitch = midi(name) + 12 * octave
            assert clip is not guitar or pitch <= midi("A5"), f"guitar note {name} above A5"
            if orn == "h":
                clip.note(when - 0.08, 0.08, pitch - 1, vel - 16)
            clip.note(when, dur * length, pitch, vel + (5 if at in (0.0, 1.0, 2.0, 3.0) else 0))
            if clip is guitar and orn in ("s", "v"):
                slide(clip, when, 200 if orn == "s" else 100)


THEME_TUNE = [
    [(0.5, 0.5, "E5"), (1.0, 0.5, "A5"), (1.5, 0.5, "G5"), (2.0, 1.0, "E5"), (3.0, 0.5, "D5"), (3.5, 0.5, "C5")],
    [(0.0, 1.5, "D5"), (1.5, 0.5, "B4"), (2.0, 0.5, "G4"), (2.5, 1.5, "D5")],
    [(0.5, 0.5, "C5"), (1.0, 0.5, "F5"), (1.5, 0.5, "E5"), (2.0, 1.0, "C5"), (3.0, 0.5, "A4"), (3.5, 0.5, "C5")],
    [(0.0, 2.0, "B4"), (2.5, 0.5, "D5"), (3.0, 1.0, "G5")],
    [(0.5, 0.5, "E5"), (1.0, 0.5, "A5"), (1.5, 0.5, "B5"), (2.0, 1.0, "C6"), (3.0, 0.5, "B5"), (3.5, 0.5, "A5")],
    [(0.0, 1.0, "G5"), (1.0, 0.5, "D5"), (1.5, 0.5, "E5"), (2.0, 2.0, "D5")],
    [(0.0, 0.5, "A5"), (0.5, 0.5, "G5"), (1.0, 0.5, "F5"), (1.5, 0.5, "E5"), (2.0, 1.0, "C5"), (3.0, 1.0, "D5")],
    [(0.0, 2.0, "E5"), (2.5, 0.5, "D5"), (3.0, 0.5, "B4"), (3.5, 0.5, "G4")],
]
#: The second guitar's answers in the gaps of the lead's phrases.
ANSWERS = [
    [], [(3.0, 0.25, "E5"), (3.25, 0.25, "G5"), (3.5, 0.5, "A5", "s")], [], [(1.0, 0.25, "D5"), (1.25, 0.25, "E5"), (1.5, 0.5, "G5", "v")],
    [], [(3.0, 0.5, "B4", "s"), (3.5, 0.5, "A4")], [], [(1.0, 0.25, "G4"), (1.25, 0.25, "A4"), (1.5, 0.5, "B4", "s")],
]
#: The bridge: the guitar's lead, A minor pentatonic with the leading tone on E.
BRIDGE_LINE = [
    [(0.0, 0.5, "D5"), (0.5, 0.5, "F5"), (1.0, 1.5, "A5", "s"), (2.5, 0.25, "G5"), (2.75, 0.25, "F5"), (3.0, 1.0, "D5")],
    [(0.0, 0.25, "E5"), (0.25, 0.25, "D5"), (0.5, 0.25, "C5"), (0.75, 0.25, "A4"), (1.0, 1.0, "C5", "v"), (2.0, 0.5, "E5"), (2.5, 1.5, "A4", "s")],
    [(0.5, 0.25, "A4"), (0.75, 0.25, "C5"), (1.0, 0.5, "F5"), (1.5, 0.5, "E5"), (2.0, 1.0, "C5", "s"), (3.0, 0.5, "A4"), (3.5, 0.5, "G4")],
    [(0.0, 1.0, "G#4", "v"), (1.0, 0.25, "B4"), (1.25, 0.25, "D5"), (1.5, 0.25, "E5"), (1.75, 0.25, "G#5"), (2.0, 2.0, "E5", "s")],
    [(0.0, 0.5, "F5"), (0.5, 0.5, "D5"), (1.0, 1.0, "A5", "s"), (2.0, 0.25, "G5"), (2.25, 0.25, "F5"), (2.5, 0.25, "E5"), (2.75, 0.25, "D5"), (3.0, 1.0, "F5", "v")],
    [(0.0, 1.5, "E5", "s"), (1.5, 0.5, "C5"), (2.0, 0.5, "A4"), (2.5, 0.5, "C5"), (3.0, 1.0, "E5")],
    [(0.0, 0.25, "F5"), (0.25, 0.25, "E5"), (0.5, 0.25, "C5"), (0.75, 0.25, "A4"), (1.0, 0.5, "F4"), (1.5, 0.5, "A4", "h"), (2.0, 2.0, "C5", "s")],
    [(0.0, 0.5, "B4"), (0.5, 0.5, "G#4"), (1.0, 0.5, "E4"), (1.5, 0.5, "G#4"), (2.0, 0.5, "B4"), (2.5, 0.5, "D5"), (3.0, 1.0, "E5", "s")],
]
THROWS = [[(1.5, 0.75, "E5", "s")], [(3.0, 0.75, "A4", "v")], [(1.5, 0.5, "C5")], [(2.0, 0.5, "G#4", "s"), (3.0, 0.5, "B4")]]


def section(n0, chords, *, war_phrase=4, drums=True, dub=False):
    for k, name in enumerate(chords):
        n = n0 + k
        nxt = chords[(k + 1) % len(chords)]
        harmony[n] = name
        if not dub:
            skank_bar(n, name)
            bubble(n, name)
        bassline(n, name, nxt, dub=dub)
        if drums:
            rockers(n, sparse=dub)
        war_drums(n, last_of_phrase=k % war_phrase == war_phrase - 1, crash=k == 0)
        war_bar(n, name)
        if k % 4 == 3:
            horn_call(n)
        if k % 8 == 0:
            dub_siren(n)


# Intro, bars 1-4: a siren, the organ chords, a roll.
for k, name in enumerate(["Am", "G", "F", "E"]):
    n = 1 + k
    harmony[n] = name
    bubble(n, name, vel=50)
    if k >= 2:
        skank_bar(n, name, vel=66)
dub_siren(1)
for i in range(8):
    kit.note(bar(4) + 2.0 + i * 0.25, 0.1, SNARE, 50 + 6 * i)

section(5, THEME)
sing(lead, 5, THEME_TUNE + THEME_TUNE[:7] + [[(0.0, 2.0, "E5"), (2.5, 0.5, "B4"), (3.0, 1.0, "E5")]], vel=86, octave=LEAD_OCTAVE)
sing(guitar, 5, ANSWERS + ANSWERS, vel=80)

section(21, BRIDGE, war_phrase=8)
sing(guitar, 21, BRIDGE_LINE, vel=88)
for k, name in enumerate(BRIDGE):  # the organ comps the bridge in long chords
    bubble_organ.note(bar(21 + k), 3.6, BUBBLE[name], 44)

section(29, DUB, dub=True)
sing(guitar, 29, THROWS, vel=84)

section(33, THEME)
sing(lead, 33, THEME_TUNE + THEME_TUNE[:7] + [[(0.0, 2.0, "E5"), (2.5, 0.5, "G#5"), (3.0, 1.0, "B5")]], vel=90, octave=LEAD_OCTAVE)
sing(guitar, 33, THEME_TUNE[:4], vel=78, octave=LEAD_OCTAVE - 1)
sing(guitar, 37, ANSWERS[4:], vel=80)
sing(guitar, 41, THEME_TUNE[:4], vel=80, octave=LEAD_OCTAVE - 1)
sing(guitar, 45, ANSWERS[4:7] + [[(1.0, 0.25, "G#4"), (1.25, 0.25, "B4"), (1.5, 0.5, "E5", "s")]], vel=82)
harmony[48] = "E"

END_BAR = 49
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


NAKED = "instrument_backend: {kind: sfz, library_ref: drums.naked, settings: {render_timeout_s: 900}}"
SHINY = "controls: {100: 0, 107: 0}, instrument_backend: {kind: sfz, sfz_glob: '**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz', settings: {fold_to_range: false}}"
EMILY = "instrument_backend: {kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {fold_to_range: false}}"
ECHO = round(60000 / BPM * 0.75)  # a dotted eighth
score = f"""schema: ambition.musicir.v3
id: ai_dente
title: AI Dente
description: >-
  Reggae for exploring and fighting in the Noodle dimension, with no holy
  side: A minor at 80 BPM, rockers drums, a skank, an organ bubble and a
  driving bass. A noodly guitar leads the theme; a second
  guitar answers it and takes the bridge (Dm Am F E). A short dub
  break throws the guitar into the echo. Fights bring in the combat layer:
  steppers drums with rolls, crunch guitar on every off-beat, horn stabs, a
  horn call and a dub siren (Jon, 2026-10-20; the title is his pun).
  Generated by dev/compose_ai_dente.py: edit that, not this file.
notes:
  - 'The intro plays once; the loop is bars 5-48, ending on E, back to A minor at bar 5.'
  - 'Layered for a level: bed, drums, tune and combat; the combat layer runs through every bar of the loop.'
  - 'No choir, celesta or harp: those belong to the holy tune.'
  - 'No held guitar note above A5.'
seed: 4242
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: A minor
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.4, density: 0.35, role: 'a siren, the organ chords, a roll'}}
  - {{id: theme, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.6, density: 0.6, loopable: true, role: 'rockers; the lead sings, the guitar answers'}}
  - {{id: bridge, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.7, density: 0.65, loopable: true, role: 'the guitar takes the lead'}}
  - {{id: dub, from: {{bar: 29, beat: 1}}, to: {{bar: 33, beat: 1}}, energy: 0.45, density: 0.35, loopable: true, role: 'bass and drums; echoes'}}
  - {{id: theme_2, from: {{bar: 33, beat: 1}}, to: {{bar: 49, beat: 1}}, energy: 0.65, density: 0.65, loopable: true, role: 'the theme, the second guitar under the lead; on E'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: lead, group: lead, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
  - {{name: guitar, group: guitar, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
  - {{name: skank, group: skank, program: clean_guitar, volume: 100, pan: 64, expression: 108, {SHINY}}}
  - {{name: bubble_organ, group: bubble, program: drawbar_organ, volume: 92, pan: 64, expression: 100}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 112, pan: 64, expression: 114, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndBlueBasses/Programs/04-babyblue_warm.sfz'}}}}
  - {{name: kit, group: drums, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: hats, group: hats, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: war_kit, group: war_drums, volume: 120, pan: 64, expression: 118, is_drum: true, {NAKED}}}
  - {{name: crunch, group: crunch, program: distortion_guitar, volume: 108, pan: 64, expression: 112, {EMILY}}}
  - {{name: trumpets, group: horns, program: trumpet, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trumpets_sustain}}}}
  - {{name: trombones, group: horns, program: trombone, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trombones_sustain}}}}
  - {{name: siren, group: siren, program: lead_square, volume: 90, pan: 64, expression: 96}}
parts:
{part("lead_part", "lead", lead)}
{part("guitar_part", "guitar", guitar)}
{part("skank_part", "skank", skank)}
{part("bubble_part", "bubble_organ", bubble_organ)}
{part("bass_part", "bass", bass)}
{part("kit_part", "kit", kit)}
{part("hats_part", "hats", hats)}
{part("war_kit_part", "war_kit", war_kit)}
{part("crunch_part", "crunch", crunch)}
{part("trumpets_part", "trumpets", trumpets)}
{part("trombones_part", "trombones", trombones)}
{part("siren_part", "siren", siren)}
processing:
  groups:
    lead:
      chain:
        - processor: pedalboard
          effects:
            - {{effect: gain, gain_db: 8.0}}
            - {{effect: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 8.0, release_ms: 110.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gxts9#ts9sim
          binary: lv2apply
          channel_mode: dual_mono
          wet_mix: 0.4
          params: {{fslider0_: -6.0, fslider1_: 620.0, fslider2_: 0.6, BYPASS: 1.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.5
          params: {{P6v: 0.7, Middle: 0.7, Bass: 0.5, Treble: 0.56, WET_DRY: 55.0, GAIN: -4.0}}
        - {{processor: highpass, cutoff_hz: 110}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 800, q: 0.8, db: 1.5}}
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 5600}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.28, mix: 0.2}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: 0.0}}
        - {{processor: balance, position: 0.15}}
    guitar:
      chain:
        - processor: pedalboard
          effects:
            - {{effect: gain, gain_db: 8.0}}
            - {{effect: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 8.0, release_ms: 110.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gxts9#ts9sim
          binary: lv2apply
          channel_mode: dual_mono
          wet_mix: 0.4
          params: {{fslider0_: -6.0, fslider1_: 620.0, fslider2_: 0.6, BYPASS: 1.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.5
          params: {{P6v: 0.7, Middle: 0.7, Bass: 0.5, Treble: 0.56, WET_DRY: 55.0, GAIN: -4.0}}
        - {{processor: highpass, cutoff_hz: 110}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 800, q: 0.8, db: 1.5}}
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
            - {{type: peak, hz: 4920, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 5600}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 7.0, release_ms: 90.0}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.28, mix: 0.2}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.6}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: -0.2}}
    skank:
      chain:
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_redeye#chump
          binary: lv2apply
          channel_mode: dual_mono
          params: {{Gain: 0.3, Tone: 0.7, Volume: 0.5}}
        - {{processor: highpass, cutoff_hz: 260}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 2400, q: 1.0, db: 3.0}}
        - {{processor: lowpass, cutoff_hz: 6500}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.5, attack_ms: 4.0, release_ms: 80.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 0.9}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: -0.45}}
    bubble:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - processor: pedalboard
          effects:
            - {{effect: chorus, rate_hz: 5.5, depth: 0.12, mix: 0.3}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.4}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: lowpass, cutoff_hz: 850}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 90, q: 0.8, db: 3.0}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 20.0, release_ms: 130.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -3.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 65, q: 1.0, db: 2.5}}
            - {{type: peak, hz: 3500, q: 1.0, db: -2.0}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.0, attack_ms: 12.0, release_ms: 90.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.1, decay_seconds: 1.0}}
        - {{processor: gain, gain_db: 4.0}}
    hats:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: gain, gain_db: 19.0}}
        - {{processor: balance, position: 0.3}}
    war_drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 60, q: 1.0, db: 3.0}}
            - {{type: peak, hz: 3500, q: 1.0, db: -1.5}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.5, attack_ms: 10.0, release_ms: 80.0, makeup_db: 2.0}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: -1.0}}
    crunch:
      chain:
        - processor: pedalboard
          effects:
            - {{effect: gain, gain_db: 10.0}}
            - {{effect: compressor, threshold_db: -24.0, ratio: 2.4, attack_ms: 8.0, release_ms: 110.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gxts9#ts9sim
          binary: lv2apply
          channel_mode: dual_mono
          wet_mix: 0.5
          params: {{fslider0_: -4.0, fslider1_: 680.0, fslider2_: 0.66, BYPASS: 1.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.6
          params: {{P6v: 0.74, Middle: 0.66, Bass: 0.5, Treble: 0.58, WET_DRY: 60.0, GAIN: -2.0}}
        - {{processor: highpass, cutoff_hz: 100}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
            - {{type: peak, hz: 4920, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 6000}}
        - {{processor: gain, gain_db: -9.5}}
        - {{processor: balance, position: 0.55}}
    horns:
      chain:
        - {{processor: highpass, cutoff_hz: 120}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 1400, q: 0.9, db: 1.5}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.2, attack_ms: 12.0, release_ms: 110.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.2, decay_seconds: 1.8}}
        - {{processor: gain, gain_db: -1.0}}
        - {{processor: balance, position: -0.2}}
    siren:
      chain:
        - {{processor: highpass, cutoff_hz: 300}}
        - {{processor: lowpass, cutoff_hz: 4500}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.45, mix: 0.4}}
        - {{processor: reverb, wet: 0.3, decay_seconds: 2.4}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: 0.3}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 20.0, release_ms: 150.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.1}}
      - {{processor: limiter, target_peak_db: -2.0, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  # Exploring plays bed, drums and tune; a fight brings in combat (each layer
  # runs through every bar of the loop).
  layers:
    bed: [skank, bubble, bass]
    drums: [drums, hats]
    tune: [lead, guitar]
    combat: [war_drums, crunch, horns, siren]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [theme, bridge, dub, theme_2], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

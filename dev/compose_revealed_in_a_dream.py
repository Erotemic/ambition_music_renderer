"""It Was Revealed to Me in a Dream: holy reggae for exploring the Noodle
dimension, with a combat layer. Writes its MusicIR v3 score:

    python3 dev/compose_revealed_in_a_dream.py scores/active/it_was_revealed_to_me_in_a_dream.music.yaml

Jon, 2026-10-20: "one with a more "holy" vibe called "it was revealed to me in
a dream", but also built for platformer exploration with some combat. Still
Reggae." The choir is allowed here: it is the holy vibe (Pastafarian, the
plain Noodle-dimension tune, has none).

Holy: plagal "amen" cadences (G to D), a choir humming the chords, celesta and
harp like light through a window, the noodly lead guitar slow and echoing.
Reggae: a one drop, the skank on two and four, the organ bubble, a deep bass.

Built for a level, in LAYERS the game mixes (the `playback` block):
  bed     skank, organ bubble, bass         always
  drums   the one drop                      exploring
  holy    choir pads, celesta, harp         exploring
  tune    the lead guitar                   exploring
  combat  steppers drums, crunch guitar on every off-beat, horn stabs and a
          horn call, the choir crying out on the downbeats
Every layer runs through every bar of the loop, so a fight can bring the
combat layer up anywhere and take it away again.

Form, 4/4 at 72 BPM, D major:
  intro       1-4    the dream: harp, celesta, the choir swelling in; no beat.
  theme       5-20   the one drop; the lead sings the theme.             (loop start)
  revelation  21-28  the choir sings, Bm G D Em G A, and the amen, G D.
  theme_2     29-44  the theme again, the men's choir under it; home on D.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 72
OUT = Path(sys.argv[1])
rng = random.Random(1225)

NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
        "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
#: Pitch-bend units a cent: the Shiny guitar bends 200 cents.
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


lead = Clip(drift=0.004, vel_jitter=4)
skank = Clip(drift=0.002, vel_jitter=4)
organ = Clip(drift=0.002, vel_jitter=4)
bass = Clip(drift=0.003, vel_jitter=3)
kit = Clip(drift=0.003, vel_jitter=4)
hats = Clip(drift=0.004, vel_jitter=6)
choir_f = Clip(vel_jitter=2)
choir_m = Clip(vel_jitter=2)
celesta = Clip(drift=0.004, vel_jitter=5)
harp = Clip(drift=0.004, vel_jitter=6)
# the combat layer
war_kit = Clip(drift=0.003, vel_jitter=4)
crunch = Clip(drift=0.002, vel_jitter=4)
trumpets = Clip(drift=0.004, vel_jitter=3)
trombones = Clip(drift=0.004, vel_jitter=3)
war_choir = Clip(vel_jitter=2)

# ---- Harmony ------------------------------------------------------------------------
SKANK = {"D": ["A3", "D4", "F#4"], "G": ["B3", "D4", "G4"], "Bm": ["B3", "D4", "F#4"], "A": ["A3", "C#4", "E4"],
         "Em": ["B3", "E4", "G4"], "Asus": ["A3", "D4", "E4"]}
ORGAN = {"D": ["F#3", "A3", "D4"], "G": ["G3", "B3", "D4"], "Bm": ["F#3", "B3", "D4"], "A": ["E3", "A3", "C#4"],
         "Em": ["G3", "B3", "E4"], "Asus": ["E3", "A3", "D4"]}
#: The choir hums each chord: the women high, the men low (root and fifth).
#: (The women's samples start at G4.)
CHOIR_HI = {"D": ["A4", "D5"], "G": ["G4", "B4"], "Bm": ["B4", "D5"], "A": ["A4", "C#5"], "Em": ["G4", "B4"], "Asus": ["A4", "D5"]}
CHOIR_LO = {"D": ["D3", "A3"], "G": ["G2", "D3"], "Bm": ["B2", "F#3"], "A": ["A2", "E3"], "Em": ["E3", "B3"], "Asus": ["A2", "E3"]}
ROOT = {"D": "D2", "G": "G1", "Bm": "B1", "A": "A1", "Em": "E2", "Asus": "A1"}
FIFTH = {"D": "A2", "G": "D2", "Bm": "F#2", "A": "E2", "Em": "B2", "Asus": "E2"}
TONES = {"D": ["D", "F#", "A"], "G": ["G", "B", "D"], "Bm": ["B", "D", "F#"], "A": ["A", "C#", "E"], "Em": ["E", "G", "B"],
         "Asus": ["A", "D", "E"]}
THEME = ["D", "G", "Bm", "A", "D", "G", "Em", "A", "D", "G", "Bm", "A", "G", "A", "D", "D"]
REVELATION = ["Bm", "G", "D", "Em", "G", "A", "G", "D"]
harmony: dict[int, str] = {}


def skank_bar(n, name, vel=72):
    t = bar(n)
    for o in (1.0, 3.0):
        skank.note(t + o, 0.16, SKANK[name], vel)


def bubble(n, name, vel=58):
    t = bar(n)
    for k in range(4):
        organ.note(t + k + 0.5, 0.2, ORGAN[name], vel)
        organ.note(t + k + 0.75, 0.16, ORGAN[name], vel - 14)


def bassline(n, name, nxt, vel=92):
    """One drop: beat one empty, the weight on three with the drop, a step into the next root."""
    t = bar(n)
    r, f = midi(ROOT[name]), midi(FIFTH[name])
    nxt_r = midi(ROOT[nxt])
    approach = nxt_r - (1 if nxt_r % 12 in (2, 7) else 2)  # D major: a half step up into D and G
    bass.note(t + 0.5, 0.45, r, vel - 6)
    bass.note(t + 1.0, 0.9, r, vel)
    bass.note(t + 2.0, 1.0, f, vel + 2)
    bass.note(t + 3.0, 0.45, r + 12, vel - 8)
    bass.note(t + 3.5, 0.45, approach, vel - 10)


KICK, SNARE, XSTICK, HAT, OPEN_HAT, HI_TOM, MID_TOM, FLOOR_TOM, CRASH, RIDE, CHINA = 36, 38, 37, 42, 46, 50, 47, 41, 49, 51, 52


def one_drop(n):
    t = bar(n)
    kit.note(t + 2.0, 0.2, KICK, 102)
    kit.note(t + 2.0, 0.2, XSTICK, 90)
    for k in range(4):
        hats.note(t + k, 0.1, HAT, 62)
        hats.note(t + k + 0.5, 0.1, OPEN_HAT if (k == 3 and n % 4 == 0) else HAT, 42)


def war_drums(n, last_of_phrase=False, crash=False):
    """The combat layer's steppers: a kick on every beat, the snare on two and
    four, sixteenth hats; a tom fill at the end of a phrase."""
    t = bar(n)
    if crash:
        war_kit.note(t, 0.4, CRASH, 100)
    for k in range(4):
        war_kit.note(t + k, 0.2, KICK, 104 if k % 2 == 0 else 96)
        for s in range(4):
            war_kit.note(t + k + s * 0.25, 0.06, HAT, (58, 30, 44, 30)[s])
    for o in (1.0, 3.0):
        if last_of_phrase and o == 3.0:
            continue
        war_kit.note(t + o, 0.2, SNARE, 100)
    if last_of_phrase:
        for i, drum in enumerate((HI_TOM, HI_TOM, MID_TOM, MID_TOM, FLOOR_TOM, FLOOR_TOM)):
            war_kit.note(t + 3.0 + i / 6, 0.12, drum, 84 + 4 * i)


def war_bar(n, name, k):
    """Crunch power chords on every off-beat, horn stabs on the 'and' of two and
    on four, and the choir crying out on the downbeat of every other bar."""
    t = bar(n)
    r = midi(ROOT[name]) + 12
    power = [r, r + 7, r + 12]
    for b in range(4):
        crunch.note(t + b + 0.5, 0.22, power, 92 if b % 2 else 84)
    crunch.note(t, 0.3, power, 100)
    stab = [midi(x) + 12 for x in SKANK[name]]
    for o in (1.5, 3.0):
        trumpets.note(t + o, 0.28, stab, 92)
        trombones.note(t + o, 0.28, [p - 12 for p in stab], 90)
    if k % 2 == 0:
        war_choir.note(t, 1.6, [midi(x) for x in CHOIR_LO[name]] + [midi(x) + 12 for x in CHOIR_HI[name]], 104)


#: The horn call that answers every fourth bar of a fight.
HORN_CALL = [(0.0, 0.5, "A4"), (0.5, 0.5, "D5"), (1.0, 0.5, "F#5"), (1.5, 1.5, "A5"), (3.0, 0.25, "G5"), (3.25, 0.25, "F#5"), (3.5, 0.5, "E5")]


def horn_call(n, transpose=0):
    t = bar(n)
    for at, dur, name in HORN_CALL:
        trumpets.note(t + at, dur * 0.9, midi(name) + transpose, 96)
        trombones.note(t + at, dur * 0.9, midi(name) + transpose - 12, 92)


def choir_pad(n, name, vel=56, men=True):
    t = bar(n)
    choir_f.note(t + 0.05, 3.7, CHOIR_HI[name], vel)
    if men:
        choir_m.note(t + 0.05, 3.7, CHOIR_LO[name], vel - 4)


def harp_rise(n, name, vel=60, octaves=(3, 4, 5)):
    """A harp arpeggio up through the chord in eighths."""
    t = bar(n)
    notes = [midi(p + str(o)) for o in octaves for p in TONES[name]]
    notes = sorted(set(n_ for n_ in notes if midi("D3") <= n_ <= midi("A5")))[:8]
    for i, p in enumerate(notes):
        harp.note(t + 0.5 * i, 1.6, p, vel - i)


def sparkle(n, name, vel=48):
    """Two celesta notes high on the chord, like light."""
    t = bar(n)
    tones = TONES[name]
    celesta.note(t + 1.5, 1.0, midi(tones[2] + "6") if tones[2] in ("A", "B") else midi(tones[2] + "5"), vel)
    celesta.note(t + 3.0, 1.0, midi(tones[0] + "6"), vel - 6)


# ---- The lead guitar ---------------------------------------------------------------
def slide(at: float, cents: float, over: float = 0.2):
    start = round(-cents * BEND_PER_CENT)
    lead.bends.append((F(at).limit_denominator(960) - F(1, 64), max(-8191, start)))
    for i in (1, 2, 3):
        lead.bends.append((F(at + over * i / 3).limit_denominator(960), round(start * (1 - i / 3))))


def sing(clip: Clip, n: int, phrase, vel=84, octave=0, length=0.95):
    for k, notes in enumerate(phrase):
        for note in notes:
            at, dur, name = note[:3]
            orn = note[3] if len(note) > 3 else ""
            when = bar(n + k) + at
            pitch = midi(name) + 12 * octave
            assert clip is not lead or pitch <= midi("A5"), f"lead note {name} above A5"
            if orn == "h":
                clip.note(when - 0.08, 0.08, pitch - 1, vel - 16)
            clip.note(when, dur * length, pitch, vel + (5 if at in (0.0, 1.0, 2.0, 3.0) else 0))
            if clip is lead and orn in ("s", "v"):
                slide(when, 200 if orn == "s" else 100)


THEME_TUNE = [
    [(0.5, 0.5, "F#4"), (1.0, 1.0, "A4", "s"), (2.0, 0.5, "B4"), (2.5, 1.5, "A4")],
    [(0.0, 0.5, "G4"), (0.5, 0.5, "A4"), (1.0, 1.5, "B4", "s"), (2.5, 0.5, "D5"), (3.0, 1.0, "B4")],
    [(0.0, 1.5, "D5", "v"), (1.5, 0.5, "C#5"), (2.0, 1.0, "B4"), (3.0, 0.5, "A4"), (3.5, 0.5, "F#4")],
    [(0.0, 2.0, "E4", "s"), (2.5, 0.5, "F#4"), (3.0, 0.5, "G4"), (3.5, 0.5, "A4")],
    [(0.0, 1.0, "D5", "s"), (1.0, 0.5, "C#5"), (1.5, 0.5, "D5"), (2.0, 1.5, "F#5", "s"), (3.5, 0.5, "E5")],
    [(0.0, 0.5, "D5"), (0.5, 0.5, "B4"), (1.0, 1.5, "D5"), (2.5, 0.5, "E5"), (3.0, 1.0, "G5", "s")],
    [(0.0, 1.0, "F#5"), (1.0, 0.5, "E5"), (1.5, 0.5, "D5"), (2.0, 1.0, "B4"), (3.0, 1.0, "E5", "v")],
    [(0.0, 2.5, "C#5", "s"), (2.5, 0.5, "B4"), (3.0, 1.0, "A4")],
    [(0.5, 0.5, "F#4"), (1.0, 1.0, "A4", "s"), (2.0, 0.5, "B4"), (2.5, 0.5, "D5"), (3.0, 1.0, "F#5", "h")],
    [(0.0, 0.5, "G5"), (0.5, 0.5, "F#5"), (1.0, 1.5, "D5", "s"), (2.5, 0.5, "B4"), (3.0, 1.0, "D5")],
    [(0.0, 1.5, "F#5", "v"), (1.5, 0.5, "E5"), (2.0, 1.0, "D5"), (3.0, 0.5, "C#5"), (3.5, 0.5, "B4")],
    [(0.0, 2.0, "A4", "s"), (2.5, 0.5, "C#5"), (3.0, 0.5, "D5"), (3.5, 0.5, "E5")],
    [(0.0, 0.5, "B4"), (0.5, 0.5, "D5"), (1.0, 1.5, "G5", "s"), (2.5, 0.5, "F#5"), (3.0, 1.0, "E5")],
    [(0.0, 1.0, "E5"), (1.0, 0.5, "F#5"), (1.5, 0.5, "G5"), (2.0, 2.0, "A5", "s")],
    [(0.0, 3.0, "F#5", "v"), (3.0, 0.5, "E5"), (3.5, 0.5, "D5")],
    [(0.0, 2.0, "D5", "s")],
]
#: The revelation: the choir's line (the women; the men an octave below).
REVELATION_LINE = [
    [(0.0, 2.0, "B4"), (2.0, 2.0, "D5")],
    [(0.0, 3.0, "D5"), (3.0, 1.0, "B4")],
    [(0.0, 2.0, "A4"), (2.0, 2.0, "F#5")],
    [(0.0, 4.0, "E5")],
    [(0.0, 2.0, "D5"), (2.0, 2.0, "B4")],
    [(0.0, 2.0, "C#5"), (2.0, 2.0, "E5")],
    [(0.0, 4.0, "D5")],
    [(0.0, 4.0, "D5")],
]
#: The lead's answers in the choir's long notes.
REVELATION_ANSWERS = [
    [(3.0, 0.25, "F#5"), (3.25, 0.25, "E5"), (3.5, 0.5, "D5", "s")],
    [],
    [(3.0, 0.5, "A5", "s"), (3.5, 0.5, "F#5")],
    [(2.0, 0.25, "G5"), (2.25, 0.25, "F#5"), (2.5, 0.25, "E5"), (2.75, 0.25, "B4"), (3.0, 1.0, "E5", "v")],
    [],
    [(3.0, 0.25, "C#5"), (3.25, 0.25, "E5"), (3.5, 0.5, "A5", "s")],
    [(2.0, 0.5, "B4"), (2.5, 0.5, "G4"), (3.0, 1.0, "B4", "s")],
    [(1.0, 0.25, "D5"), (1.25, 0.25, "E5"), (1.5, 0.25, "F#5"), (1.75, 0.25, "A5"), (2.0, 2.0, "F#5", "s")],
]


def section(n0, chords, *, pads=True, men=True, war_phrase=4, drop=True, harp_every=0, sparkles=False):
    for k, name in enumerate(chords):
        n = n0 + k
        nxt = chords[(k + 1) % len(chords)]
        harmony[n] = name
        skank_bar(n, name)
        bubble(n, name)
        bassline(n, name, nxt)
        if drop:
            one_drop(n)
        if pads:
            choir_pad(n, name, men=men)
        if harp_every and k % harp_every == 0:
            harp_rise(n, name, vel=52)
        if sparkles and k % 2 == 1:
            sparkle(n, name)
        war_drums(n, last_of_phrase=k % war_phrase == war_phrase - 1, crash=k == 0)
        war_bar(n, name, k)
        if k % 4 == 3:
            horn_call(n)


# Intro, bars 1-4: the dream -- harp, celesta, the choir swelling in; no beat.
for k, name in enumerate(["D", "G", "Bm", "A"]):
    n = 1 + k
    harmony[n] = name
    harp_rise(n, name, vel=64 - 4 * (k % 2))
    sparkle(n, name, vel=50)
    choir_f.note(bar(n) + 0.05, 3.7, CHOIR_HI[name], 40 + 6 * k)
    if k >= 2:
        choir_m.note(bar(n) + 0.05, 3.7, CHOIR_LO[name], 38 + 6 * k)
kit.note(bar(4) + 3.0, 0.2, XSTICK, 70)
kit.note(bar(4) + 3.5, 0.2, XSTICK, 80)

# Theme, bars 5-20: the one drop; the lead sings.
section(5, THEME, men=False, harp_every=4, sparkles=True)
sing(lead, 5, THEME_TUNE, vel=84)

# Revelation, bars 21-28: the choir sings, the lead answers; the amen G to D.
section(21, REVELATION, pads=False, war_phrase=8, harp_every=2)
sing(choir_f, 21, REVELATION_LINE, vel=78)
sing(choir_m, 21, REVELATION_LINE, vel=72, octave=-1)
sing(lead, 21, REVELATION_ANSWERS, vel=80)

# Theme again, bars 29-44: the men's choir under the lead; home on D.
section(29, THEME, men=True, harp_every=4, sparkles=True)
sing(lead, 29, THEME_TUNE, vel=88)

END_BAR = 45
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


NAKED = "instrument_backend: {kind: sfz, library_ref: drums.naked, settings: {render_timeout_s: 900}}"
SHINY = "controls: {100: 0, 107: 0}, instrument_backend: {kind: sfz, sfz_glob: '**/Shinyguitar/Shinyguitar/Programs/electric_one.sfz', settings: {fold_to_range: false}}"
EMILY = "instrument_backend: {kind: sfz, sfz_glob: '**/Emilyguitar/Emilyguitar/emily_basic.sfz', settings: {fold_to_range: false}}"
VPO = "instrument_backend: {{kind: sfz, sfz_glob: '**/Virtual-Playing-Orchestra3/{path}.sfz', settings: {{fold_to_range: false}}}}"
ECHO = round(60000 / BPM * 0.75)  # a dotted eighth

score = f"""schema: ambition.musicir.v3
id: it_was_revealed_to_me_in_a_dream
title: It Was Revealed to Me in a Dream
description: >-
  Holy reggae for exploring the Noodle dimension, with a combat layer: D major
  at 72 BPM. A one drop, a skank on two and four, the organ bubble and a deep
  bass carry a slow, echoing noodle-guitar theme. A choir hums the chords,
  celesta and harp catch the light, and the revelation lets the choir sing
  and end on an amen (G to D). Fights bring in the combat layer: steppers
  drums, crunch guitar on every off-beat, horn stabs and a horn call, and the
  choir crying out (Jon, 2026-10-20). Generated by
  dev/compose_revealed_in_a_dream.py: edit that, not this file.
notes:
  - 'The intro plays once; the loop is bars 5-44, home on D, back to D at bar 5.'
  - 'Layered for a level: bed, drums, holy, tune and combat; the combat layer runs through every bar of the loop.'
  - 'The choir is the holy vibe: the plain Noodle-dimension tune (Pastafarian) has none.'
  - 'No held lead guitar note above A5.'
seed: 1225
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D major
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: intro, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.3, density: 0.3, role: 'the dream: harp, celesta, the choir swelling'}}
  - {{id: theme, from: {{bar: 5, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.55, density: 0.55, loopable: true, role: 'the one drop; the lead sings'}}
  - {{id: revelation, from: {{bar: 21, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.6, density: 0.5, loopable: true, role: 'the choir sings; the amen'}}
  - {{id: theme_2, from: {{bar: 29, beat: 1}}, to: {{bar: 45, beat: 1}}, energy: 0.6, density: 0.6, loopable: true, role: 'the theme with the men''s choir; home on D'}}
harmony:
  every_bars: 1
  cycle: false
  progression: [{", ".join(progression)}]
instruments:
  - {{name: lead, group: lead, program: clean_guitar, volume: 104, pan: 64, expression: 112, {SHINY}}}
  - {{name: skank, group: skank, program: clean_guitar, volume: 100, pan: 64, expression: 108, {SHINY}}}
  - {{name: organ, group: organ, program: drawbar_organ, volume: 92, pan: 64, expression: 100}}
  - {{name: bass, group: bass, program: fingered_bass, volume: 112, pan: 64, expression: 114, instrument_backend: {{kind: sfz, sfz_glob: '**/BlackAndBlueBasses/Programs/04-babyblue_warm.sfz'}}}}
  - {{name: kit, group: drums, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: hats, group: hats, volume: 118, pan: 64, expression: 116, is_drum: true, {NAKED}}}
  - {{name: choir_f, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {VPO.format(path="Vocals/choir-FEMALE-sustain")}}}
  - {{name: choir_m, group: choir, program: choir_aahs, volume: 100, pan: 64, expression: 104, {VPO.format(path="Vocals/choir-MALE-sustain")}}}
  - {{name: celesta, group: bells, program: celesta, volume: 96, pan: 64, expression: 100, {VPO.format(path="Keys/celesta")}}}
  - {{name: harp, group: harp, program: orchestral_harp, volume: 100, pan: 64, expression: 104, instrument_backend: {{kind: sfz, library_ref: folk.harp}}}}
  - {{name: war_kit, group: war_drums, volume: 120, pan: 64, expression: 118, is_drum: true, {NAKED}}}
  - {{name: crunch, group: crunch, program: distortion_guitar, volume: 108, pan: 64, expression: 112, {EMILY}}}
  - {{name: trumpets, group: horns, program: trumpet, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trumpets_sustain}}}}
  - {{name: trombones, group: horns, program: trombone, volume: 100, pan: 64, expression: 108, instrument_backend: {{kind: sfz, library_ref: orchestra.trombones_sustain}}}}
  - {{name: war_choir, group: war_choir, program: choir_aahs, volume: 104, pan: 64, expression: 110, {VPO.format(path="Vocals/choir-MIXED-sustain")}}}
parts:
{part("lead_part", "lead", lead)}
{part("skank_part", "skank", skank)}
{part("organ_part", "organ", organ)}
{part("bass_part", "bass", bass)}
{part("kit_part", "kit", kit)}
{part("hats_part", "hats", hats)}
{part("choir_f_part", "choir_f", choir_f)}
{part("choir_m_part", "choir_m", choir_m)}
{part("celesta_part", "celesta", celesta)}
{part("harp_part", "harp", harp)}
{part("war_kit_part", "war_kit", war_kit)}
{part("crunch_part", "crunch", crunch)}
{part("trumpets_part", "trumpets", trumpets)}
{part("trombones_part", "trombones", trombones)}
{part("war_choir_part", "war_choir", war_choir)}
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
          wet_mix: 0.35
          params: {{fslider0_: -7.0, fslider1_: 620.0, fslider2_: 0.58, BYPASS: 1.0}}
        - processor: lv2
          plugin_uri: http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st
          binary: lv2apply
          wet_mix: 0.45
          params: {{P6v: 0.7, Middle: 0.7, Bass: 0.5, Treble: 0.55, WET_DRY: 50.0, GAIN: -5.0}}
        - {{processor: highpass, cutoff_hz: 110}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 800, q: 0.8, db: 1.5}}
            - {{type: peak, hz: 3000, q: 0.8, db: -3.0}}
            - {{type: peak, hz: 4920, q: 3.0, db: -3.0}}
        - {{processor: lowpass, cutoff_hz: 5400}}
        - {{processor: compressor, threshold_db: -22.0, ratio: 2.0, attack_ms: 7.0, release_ms: 90.0}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO}, feedback: 0.3, mix: 0.22}}
        - {{processor: reverb, wet: 0.24, decay_seconds: 2.6}}
        - {{processor: gain, gain_db: -2.0}}
        - {{processor: balance, position: 0.15}}
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
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 5.0}}
        - {{processor: balance, position: -0.45}}
    organ:
      chain:
        - {{processor: highpass, cutoff_hz: 150}}
        - {{processor: lowpass, cutoff_hz: 5000}}
        - processor: pedalboard
          effects:
            - {{effect: chorus, rate_hz: 5.5, depth: 0.12, mix: 0.3}}
        - {{processor: reverb, wet: 0.12, decay_seconds: 1.2}}
        - {{processor: gain, gain_db: 8.0}}
        - {{processor: balance, position: 0.4}}
    bass:
      chain:
        - {{processor: highpass, cutoff_hz: 30}}
        - {{processor: lowpass, cutoff_hz: 800}}
        - processor: parametric_eq
          bands:
            - {{type: low_shelf, hz: 90, q: 0.8, db: 3.0}}
        - {{processor: compressor, threshold_db: -24.0, ratio: 3.0, attack_ms: 25.0, release_ms: 140.0, makeup_db: 2.0}}
        - {{processor: gain, gain_db: -3.0}}
    drums:
      chain:
        - {{processor: highpass, cutoff_hz: 35}}
        - processor: parametric_eq
          bands:
            - {{type: peak, hz: 65, q: 1.0, db: 2.5}}
            - {{type: peak, hz: 3500, q: 1.0, db: -2.0}}
        - {{processor: compressor, threshold_db: -20.0, ratio: 3.0, attack_ms: 12.0, release_ms: 90.0, makeup_db: 1.5}}
        - {{processor: reverb, wet: 0.14, decay_seconds: 1.4}}
        - {{processor: gain, gain_db: 5.0}}
    hats:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - {{processor: lowpass, cutoff_hz: 9000}}
        - {{processor: gain, gain_db: 19.0}}
        - {{processor: balance, position: 0.3}}
    choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7000}}
        - {{processor: reverb, wet: 0.4, decay_seconds: 3.6}}
        - {{processor: gain, gain_db: -1.0}}
        - {{processor: balance, position: -0.1}}
    bells:
      chain:
        - {{processor: highpass, cutoff_hz: 400}}
        - processor: pedalboard
          effects:
            - {{effect: delay, delay_ms: {ECHO * 2}, feedback: 0.3, mix: 0.25}}
        - {{processor: reverb, wet: 0.45, decay_seconds: 3.8}}
        - {{processor: gain, gain_db: 12.0}}
        - {{processor: balance, position: 0.35}}
    harp:
      chain:
        - {{processor: highpass, cutoff_hz: 100}}
        - {{processor: reverb, wet: 0.35, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: 10.0}}
        - {{processor: balance, position: -0.35}}
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
    war_choir:
      chain:
        - {{processor: highpass, cutoff_hz: 90}}
        - {{processor: lowpass, cutoff_hz: 7500}}
        - {{processor: reverb, wet: 0.35, decay_seconds: 3.0}}
        - {{processor: gain, gain_db: -10.0}}
  master:
    chain:
      - {{processor: highpass, cutoff_hz: 28}}
      - {{processor: compressor, threshold_db: -18.0, ratio: 2.2, attack_ms: 20.0, release_ms: 150.0, makeup_db: 1.5, knee_db: 6.0}}
      - {{processor: stereo_width, amount: 0.12}}
      - {{processor: limiter, target_peak_db: -2.0, drive: 0.9, normalize: true}}
  adaptive_sections:
    mode: composition_master
playback:
  # Exploring plays bed, drums, holy and tune; a fight brings in combat (each
  # layer runs through every bar of the loop).
  layers:
    bed: [skank, organ, bass]
    drums: [drums, hats]
    holy: [choir, bells, harp]
    tune: [lead]
    combat: [war_drums, crunch, horns, war_choir]
  sections:
    - {{id: intro, form: [intro]}}
    - {{id: song, form: [theme, revelation, theme_2], loop: true}}
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

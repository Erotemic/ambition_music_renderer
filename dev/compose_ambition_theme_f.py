"""Ambition: the game's theme as dark synth with a secret. Audition F.
Writes its MusicIR v3 score:

    python3 dev/compose_ambition_theme_f.py scores/experiments/ambition_theme_f.music.yaml

Jon, 2026-10-20, on audition E (synth-pop after Wrong Planet): "It has the same
baseline. I don't like the yearning. odd I know, for someone ambitious. I
almost want a feel of secret power."

So: restraint over longing. D Dorian at 110 BPM in a half-time swagger.
  - THE ENGINE: a sixteenth-note synth-bass pulse on a D pedal that never
    stops; the power is always running, quietly. (Not Wrong Planet's octave
    bounce.)
  - THE HARMONY: Dm to G/D, the Dorian colour: cool and uncanny, not sad. The
    power cadence (Bb C D) is held back for the reveal.
  - THE MOTIF: terse, rising a fourth (A to D) and landing on B natural, the
    Dorian sixth: a bright note hidden inside the minor. That is the secret.
    Its second time it climbs to G instead: the power stirring.

Form, 4/4 at 110 BPM (half-time drums):
  dark     1-4    the pulse alone, a drone, a heartbeat kick.
  whisper  5-12   the motif, low and filtered; bells answer; the kick and clap.
  reveal   13-20  the motif an octave up on a bright saw with synth brass,
                  big half-time drums; Bb C D at the top.
  drop     21-24  pulse, drums and brass stabs of the motif's opening.
  secret   25-28  back to the whisper; it ends on the B natural, held.
"""

from __future__ import annotations

import random
import sys
from fractions import Fraction as F
from pathlib import Path

BPM = 110
OUT = Path(sys.argv[1])
#: which hook: "" is the first draft; "1" "2" "3" are the hook auditions (Jon: "if you
#: find the right hook, maybe it could be. Audition 3 candidates.")
HOOK_ID = sys.argv[2] if len(sys.argv) > 2 else ""
rng = random.Random(1100)

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


# ---- The hooks ------------------------------------------------------------------------
#: Each: MOTIF (4 bars over Dm G/D Dm G/D), CLIMB (Bb C D5 D5), DROP (stabs of the
#: opening, then a landing note per chord at `land_at`), ENDING (bars 27-28, at
#: the whisper's pitch).
HOOKS = {
    # The first draft: up a fourth, onto the Dorian B natural.
    "": dict(
        motif=[
            [(0.0, .5, "A4"), (0.5, .5, "D5"), (1.0, 1.5, "E5"), (2.75, .25, "D5"), (3.0, 1.0, "F5")],
            [(0.0, .5, "E5"), (0.5, .5, "D5"), (1.0, 2.75, "B4")],
            [(0.0, .5, "A4"), (0.5, .5, "D5"), (1.0, 1.5, "E5"), (2.75, .25, "D5"), (3.0, 1.0, "F5")],
            [(0.0, .5, "E5"), (0.5, .5, "F5"), (1.0, 2.75, "G5")],
        ],
        climb=[
            [(0.0, .5, "F5"), (0.5, .5, "Bb5"), (1.0, 1.5, "A5"), (2.75, .25, "G5"), (3.0, 1.0, "F5")],
            [(0.0, .5, "G5"), (0.5, .5, "C6"), (1.0, 1.5, "B5"), (2.75, .25, "A5"), (3.0, 1.0, "G5")],
            [(0.0, .5, "A5"), (0.5, .5, "D6"), (1.0, 3.0, "E6")],
            [(0.0, 4.0, "D6")],
        ],
        drop=dict(stabs=[(0.0, "A4"), (0.5, "D5"), (1.0, "E5")], land_at=3.0, land={"Dm": "F5", "G/D": "B4", "Gm/D": "Bb4"}),
        ending=[(0.0, .45, "A3"), (0.5, .45, "D4"), (1.0, 6.8, "B3")],
    ),
    # 1, The Insistence: one 3+3+2 cell pressing on, its long note climbing G then A.
    "1": dict(
        motif=[
            [(0.0, .75, "D5"), (0.75, .75, "A4"), (1.5, .5, "D5"), (2.0, .75, "E5"), (2.75, .75, "F5"), (3.5, .5, "E5")],
            [(0.0, .75, "D5"), (0.75, .75, "B4"), (1.5, .5, "D5"), (2.0, 2.0, "G5")],
            [(0.0, .75, "D5"), (0.75, .75, "A4"), (1.5, .5, "D5"), (2.0, .75, "E5"), (2.75, .75, "F5"), (3.5, .5, "E5")],
            [(0.0, .75, "D5"), (0.75, .75, "B4"), (1.5, .5, "D5"), (2.0, 2.0, "A5")],
        ],
        climb=[
            [(0.0, .75, "F5"), (0.75, .75, "D5"), (1.5, .5, "F5"), (2.0, .75, "G5"), (2.75, .75, "A5"), (3.5, .5, "G5")],
            [(0.0, .75, "G5"), (0.75, .75, "E5"), (1.5, .5, "G5"), (2.0, .75, "A5"), (2.75, .75, "B5"), (3.5, .5, "A5")],
            [(0.0, .75, "A5"), (0.75, .75, "D5"), (1.5, .5, "A5"), (2.0, 2.0, "D6")],
            [(0.0, .75, "D6"), (0.75, .75, "A5"), (1.5, 2.5, "D6")],
        ],
        drop=dict(stabs=[(0.0, "D5"), (0.75, "A4"), (1.5, "D5")], land_at=2.0, land={"Dm": "F5", "G/D": "G5", "Gm/D": "G5"}),
        ending=[(0.0, .7, "D4"), (0.75, .7, "A3"), (1.5, .45, "D4"), (2.0, 5.8, "B3")],
    ),
    # 2, The Octave: sparse; each phrase leaps a whole octave and steps down.
    "2": dict(
        motif=[
            [(0.0, 1.0, "D4"), (1.0, 1.5, "D5"), (2.5, .5, "C5"), (3.0, 1.0, "A4")],
            [(0.0, 1.0, "B4"), (1.0, .5, "A4"), (1.5, 2.5, "D5")],
            [(0.0, 1.0, "D4"), (1.0, 1.5, "D5"), (2.5, .5, "C5"), (3.0, 1.0, "A4")],
            [(0.0, 1.0, "B4"), (1.0, .5, "C5"), (1.5, 2.5, "E5")],
        ],
        climb=[
            [(0.0, 1.0, "F4"), (1.0, 1.5, "F5"), (2.5, .5, "E5"), (3.0, 1.0, "D5")],
            [(0.0, 1.0, "G4"), (1.0, 1.5, "G5"), (2.5, .5, "F5"), (3.0, 1.0, "E5")],
            [(0.0, 1.0, "A4"), (1.0, 3.0, "A5")],
            [(0.0, 1.0, "D5"), (1.0, 3.0, "D6")],
        ],
        drop=dict(stabs=[(0.0, "D4"), (1.0, "D5")], land_at=3.0, land={"Dm": "A4", "G/D": "B4", "Gm/D": "Bb4"}),
        ending=[(0.0, 1.0, "D3"), (1.0, 1.5, "D4"), (2.5, .5, "C4"), (3.0, 4.8, "B3")],
    ),
    # 3, The Agent: up D F A to a held C#, the minor-major seventh; again over Bb and C.
    "3": dict(
        motif=[
            [(0.0, .5, "D5"), (0.5, .5, "F5"), (1.0, .5, "A5"), (1.5, 2.0, "C#6"), (3.5, .5, "A5")],
            [(0.0, 1.0, "B5"), (1.0, 1.0, "G5"), (2.0, 2.0, "D5")],
            [(0.0, .5, "D5"), (0.5, .5, "F5"), (1.0, .5, "A5"), (1.5, 2.0, "C#6"), (3.5, .5, "A5")],
            [(0.0, .5, "B5"), (0.5, .5, "A5"), (1.0, 1.0, "G5"), (2.0, 2.0, "E5")],
        ],
        climb=[
            [(0.0, .5, "D5"), (0.5, .5, "F5"), (1.0, .5, "A5"), (1.5, 2.5, "D6")],
            [(0.0, .5, "E5"), (0.5, .5, "G5"), (1.0, .5, "B5"), (1.5, 2.5, "E6")],
            [(0.0, .5, "D5"), (0.5, .5, "A5"), (1.0, 3.0, "D6")],
            [(0.0, .5, "A5"), (0.5, .5, "D6"), (1.0, 3.0, "C#6")],
        ],
        drop=dict(stabs=[(0.0, "D5"), (0.5, "F5"), (1.0, "A5")], land_at=3.0, land={"Dm": "C#5", "G/D": "B4", "Gm/D": "Bb4"}),
        ending=[(0.0, .45, "D4"), (0.5, .45, "F4"), (1.0, .45, "A4"), (1.5, 6.3, "C#5")],
    ),
}
HOOKS["4"] = dict(
    # 4, The Agent, accented: the line cliche D C# C B, each a held downbeat, an
    # arpeggio pickup into each; the reveal climbs Bbmaj7 Gm A7 and hangs on the
    # dominant, and the drop lets it out on D minor.
    motif=[
        [(0.0, 1.5, "D6"), (1.5, .5, "A5"), (2.0, .5, "F5"), (2.5, .5, "D5"), (3.0, .5, "F5"), (3.5, .5, "A5")],
        [(0.0, 2.5, "C#6"), (2.5, .5, "A5"), (3.0, .5, "F5"), (3.5, .5, "A5")],
        [(0.0, 1.5, "C6"), (1.5, .5, "A5"), (2.0, .5, "F5"), (2.5, .5, "D5"), (3.0, .5, "F5"), (3.5, .5, "A5")],
        [(0.0, 2.5, "B5"), (2.5, .5, "A5"), (3.0, 1.0, "F5")],
    ],
    climb=[
        [(0.0, 1.5, "D6"), (1.5, .5, "A5"), (2.0, .5, "F5"), (2.5, .5, "D5"), (3.0, .5, "F5"), (3.5, .5, "Bb5")],
        [(0.0, 2.5, "D6"), (2.5, .5, "Bb5"), (3.0, 1.0, "G5")],
        [(0.0, .5, "A5"), (0.5, .5, "C#6"), (1.0, .5, "E6"), (1.5, 2.5, "G6")],
        [(0.0, 1.0, "F6"), (1.0, 1.0, "E6"), (2.0, 2.0, "C#6")],
    ],
    whisper_ch=["Dm", "DmMaj7", "Dm7", "Dm6"] * 2,
    reveal_ch=["Dm", "DmMaj7", "Dm7", "Dm6", "Bbmaj7", "Gm", "A7", "A7"],
    drop_ch=["Dm", "DmMaj7", "Dm7", "Dm6"],
    secret_ch=["Dm", "DmMaj7", "DmMaj7", "DmMaj7"],
    drop=dict(stabs=[(0.0, "D5"), (0.5, "F5"), (1.0, "A5")], land_at=2.0,
              land={"Dm": "D6", "DmMaj7": "C#6", "Dm7": "C6", "Dm6": "B5"}),
    ending=[(0.0, .45, "D4"), (0.5, .45, "F4"), (1.0, .45, "A4"), (1.5, .5, "D5"), (4.0, 3.8, "C#5")],
)
HOOKS["5"] = dict(
    # 5, Vault in the Dark: Wrong Planet's vault (two sixteenths into a held note,
    # a hole, a falling answer) in D minor over i bVI bIII bVII: power, not longing.
    motif=[
        [(0.5, .25, "D5"), (0.75, .25, "F5"), (1.0, 1.25, "A5"), (2.5, .25, "G5"), (2.75, .25, "F5"), (3.0, .5, "E5"), (3.5, .5, "D5")],
        [(0.5, .25, "D5"), (0.75, .25, "F5"), (1.0, 1.25, "Bb5"), (2.5, .25, "A5"), (2.75, .25, "F5"), (3.0, 1.0, "D5")],
        [(0.5, .25, "C5"), (0.75, .25, "F5"), (1.0, 1.25, "A5"), (2.5, .25, "G5"), (2.75, .25, "F5"), (3.0, .5, "E5"), (3.5, .5, "C5")],
        [(0.5, .25, "C5"), (0.75, .25, "E5"), (1.0, 3.0, "G5")],
    ],
    climb=[
        [(0.5, .25, "F5"), (0.75, .25, "Bb5"), (1.0, 1.25, "D6"), (2.5, .25, "C6"), (2.75, .25, "Bb5"), (3.0, 1.0, "F5")],
        [(0.5, .25, "G5"), (0.75, .25, "C6"), (1.0, 1.25, "E6"), (2.5, .25, "D6"), (2.75, .25, "C6"), (3.0, 1.0, "G5")],
        [(0.5, .25, "A5"), (0.75, .25, "D6"), (1.0, 3.0, "F6")],
        [(0.0, 4.0, "D6")],
    ],
    whisper_ch=["Dm", "Bb", "F", "C"] * 2,
    reveal_ch=["Dm", "Bb", "F", "C", "Bb", "C", "Dm", "Dm"],
    drop_ch=["Dm", "Bb", "F", "C"],
    secret_ch=["Dm", "Bb", "Dm", "Dm"],
    drop=dict(stabs=[(0.5, "D5"), (0.75, "F5"), (1.0, "A5")], land_at=3.0, land={"Dm": "D5", "Bb": "D5", "F": "C5", "C": "E5"}),
    ending=[(0.5, .2, "D4"), (0.75, .2, "F4"), (1.0, 6.8, "A4")],
)
HOOKS["6"] = dict(
    # 6, Common Tone: the melody holds still while the harmony slides a mediant
    # under it (Dm to Bbm on F, Dm to F#m on A): the power is in what moves beneath.
    motif=[
        [(0.0, .5, "A4"), (0.5, .5, "D5"), (1.0, 3.0, "F5")],
        [(0.0, 2.5, "F5"), (2.5, .5, "Db5"), (3.0, 1.0, "Eb5")],
        [(0.0, .5, "D5"), (0.5, .5, "F5"), (1.0, 3.0, "A5")],
        [(0.0, 2.5, "A5"), (2.5, .5, "C#6"), (3.0, 1.0, "B5")],
    ],
    climb=[
        [(0.0, .5, "D5"), (0.5, .5, "G5"), (1.0, 3.0, "Bb5")],
        [(0.0, 3.0, "Bb5"), (3.0, 1.0, "G5")],
        [(0.0, .5, "F5"), (0.5, .5, "Bb5"), (1.0, 3.0, "D6")],
        [(0.0, 3.0, "E6"), (3.0, 1.0, "C#6")],
    ],
    whisper_ch=["Dm", "Bbm", "Dm", "F#m"] * 2,
    reveal_ch=["Dm", "Bbm", "Dm", "F#m", "Gm", "Eb", "Bb", "A"],
    drop_ch=["Dm", "Bbm", "Dm", "F#m"],
    secret_ch=["Dm", "Bbm", "Dm", "Dm"],
    drop=dict(stabs=[(0.0, "A4"), (0.5, "D5")], land_at=1.0, land={"Dm": "F5", "Bbm": "F5", "F#m": "A5"}),
    ending=[(0.0, .45, "A3"), (0.5, .45, "D4"), (1.0, 6.8, "A4")],
)
HOOKS["7"] = dict(
    # 7, Phrygian Step: D minor against Eb over a D pedal; the line climbs, then
    # falls back through the flat second; the reveal resolves Eb to D minor.
    motif=[
        [(0.0, 1.0, "A4"), (1.0, .5, "D5"), (1.5, .5, "E5"), (2.0, 2.0, "F5")],
        [(0.0, 1.0, "G5"), (1.0, .5, "F5"), (1.5, .5, "Eb5"), (2.0, 2.0, "Bb4")],
        [(0.0, 1.0, "A4"), (1.0, .5, "D5"), (1.5, .5, "E5"), (2.0, 2.0, "F5")],
        [(0.0, 1.0, "G5"), (1.0, .5, "A5"), (1.5, .5, "Bb5"), (2.0, 2.0, "C6")],
    ],
    climb=[
        [(0.0, 1.0, "D5"), (1.0, .5, "F5"), (1.5, .5, "G5"), (2.0, 2.0, "Bb5")],
        [(0.0, 1.0, "Bb5"), (1.0, .5, "G5"), (1.5, .5, "Bb5"), (2.0, 2.0, "Eb6")],
        [(0.0, 1.0, "F5"), (1.0, .5, "A5"), (1.5, .5, "Bb5"), (2.0, 2.0, "D6")],
        [(0.0, 4.0, "D6")],
    ],
    whisper_ch=["Dm", "Eb/D", "Dm", "C"] * 2,
    reveal_ch=["Dm", "Eb/D", "Dm", "C", "Bb", "Eb", "Dm", "Dm"],
    drop_ch=["Dm", "Eb/D", "Dm", "C"],
    secret_ch=["Dm", "Eb/D", "Dm", "Dm"],
    drop=dict(stabs=[(0.0, "A4"), (1.0, "D5"), (1.5, "E5")], land_at=2.0, land={"Dm": "F5", "Eb/D": "Eb5", "C": "E5"}),
    ending=[(0.0, 1.0, "A3"), (1.0, .5, "D4"), (1.5, .5, "Eb4"), (2.0, 5.8, "D4")],
)
HOOK = HOOKS[HOOK_ID]
WHISPER_CH = HOOK.get("whisper_ch", WHISPER_CH)
REVEAL_CH = HOOK.get("reveal_ch", REVEAL_CH)
MOTIF, CLIMB = HOOK["motif"], HOOK["climb"]

def sing(clip: Clip, n0: int, phrase, vel=90, octave=0):
    for k, notes in enumerate(phrase):
        for at, dur, name in notes:
            long = dur >= 1.0
            clip.note(T(n0 + k) + at, dur * (0.96 if long else 0.85), midi(name) + 12 * octave, vel + (6 if long else 0))


# ---- Dark, 1-4 ---------------------------------------------------------------------------
for n in range(1, 5):
    harmony[n] = "Dm"
    engine(n, "Dm", vel=36 + 6 * n)
    drums(n, "heartbeat")
air.note(T(1), 15.8, [midi("D3"), midi("A3")], 54)
sub.note(T(3), 7.8, midi("D1"), 70)

# ---- Whisper, 5-12 -------------------------------------------------------------------------
for k, chord in enumerate(WHISPER_CH):
    n = 5 + k
    harmony[n] = chord
    engine(n, chord, vel=62)
    sub.note(T(n), 3.9, midi(SUB[chord]), 76)
    pad.note(T(n), 3.95, [midi(x) - 12 for x in TONES[chord]], 52)
    drums(n, "whisper", fill=k == 7)
sing(whisper, 5, MOTIF + MOTIF, vel=80, octave=-1)
for n in (6, 8, 10, 12):  # bells answer the bar's held note, an octave over the whisper
    held = max(MOTIF[(n - 5) % 4], key=lambda x: x[1])
    bells.note(T(n) + 3.0, 0.4, midi(held[2]), 46)

# ---- Reveal, 13-20 --------------------------------------------------------------------------
for k, chord in enumerate(REVEAL_CH):
    n = 13 + k
    harmony[n] = chord
    engine(n, chord, vel=74)
    sub.note(T(n), 3.9, midi(SUB[chord]), 86)
    tones = [midi(x) for x in TONES[chord]]
    pad.note(T(n), 3.95, [p - 12 for p in tones] + [tones[0]], 62)
    air.note(T(n), 3.95, [p + 24 for p in tones], 44)  # above the lead, out of its register
    for at, dur in ((0, 0.5), (1.5, 0.4), (2.5, 1.2)):  # synth brass: the chord, punched, in the pulse's rhythm
        brass.note(T(n) + at, dur, [x - 12 for x in tones], 92 if at == 0 else 80)  # under the lead's octave double
    drums(n, "reveal", crash=k in (0, 4), fill=k == 7)
sing(lead, 13, MOTIF, vel=100)
sing(lead_low, 13, MOTIF, vel=78, octave=-1)
sing(lead, 17, CLIMB, vel=104)
sing(lead_low, 17, CLIMB, vel=80, octave=-1)

# ---- Drop, 21-24: the motif's opening as stabs over the engine ----------------------------
for k, chord in enumerate(HOOK.get("drop_ch", ["Dm", "G/D", "Dm", "Gm/D"])):
    n = 21 + k
    harmony[n] = chord
    engine(n, chord, vel=80)
    sub.note(T(n), 3.9, midi(SUB[chord]), 88)
    drums(n, "reveal", crash=k == 0, fill=k == 3)
    for at, name in HOOK["drop"]["stabs"]:
        brass.note(T(n) + at, 0.35, [midi(name), midi(name) - 12], 96)
    land = HOOK["drop"]["land"][chord]
    brass.note(T(n) + HOOK["drop"]["land_at"], 0.6, [midi(land), midi(land) - 12], 100)

# ---- Secret, 25-28: back to the whisper; it ends on B natural ------------------------------
for k, chord in enumerate(HOOK.get("secret_ch", ["Dm", "G/D", "Dm", "G/D"])):
    n = 25 + k
    harmony[n] = chord
    engine(n, chord, vel=58 - 4 * k)
    sub.note(T(n), 3.9, midi(SUB[chord]), 72 - 4 * k)
    pad.note(T(n), 3.95, [midi(x) - 12 for x in TONES[chord]], 50)
    if k < 2:
        drums(n, "whisper")
    else:
        drums(n, "heartbeat")
sing(whisper, 25, MOTIF[:2], vel=82, octave=-1)
for at, dur, name in HOOK["ending"]:  # the secret, kept
    whisper.note(T(27) + at, dur, midi(name), 84 if dur > 1 else 76)
bells.note(T(28) + 2.0, 1.8, midi(HOOK["ending"][-1][2]) + 24, 44)

END_BAR = 29
progression = [harmony[n] for n in range(1, END_BAR)]


def part(pid: str, instrument: str, clip: Clip) -> str:
    return "\n".join([f"  - id: {pid}", f"    instrument: {instrument}", "    voices:", f"      - id: {pid}_main",
                      "        clips:", clip.yaml(f"{pid}_all", "          ")])


DELAY = round(60000 / BPM * 0.75)  # a dotted eighth
score = f"""schema: ambition.musicir.v3
id: ambition_theme_f{HOOK_ID}
title: Ambition - audition F{HOOK_ID} (the theme, secret power{", hook " + HOOK_ID if HOOK_ID else ""})
description: >-
  The game's theme as dark synth with a secret: D Dorian at 110 BPM in a
  half-time swagger. A sixteenth-note synth-bass pulse on a D pedal never
  stops; Dm and G/D alternate, cool rather than sad. The motif rises a
  fourth and lands on B natural, the Dorian sixth hidden in the minor. It is
  whispered low and filtered, then revealed an octave up on a bright saw with
  synth brass and climbs Bb C D; a drop of brass stabs; and it ends back in
  the dark on the B natural. Generated by dev/compose_ambition_theme_f.py.
seed: 1100
timebase: {{ppq: 960}}
meter: 4/4
tempo: {BPM}
key: D dorian
end: {{bar: {END_BAR}, beat: 1}}
form:
  - {{id: dark, from: {{bar: 1, beat: 1}}, to: {{bar: 5, beat: 1}}, energy: 0.25, density: 0.3, role: 'the pulse alone'}}
  - {{id: whisper, from: {{bar: 5, beat: 1}}, to: {{bar: 13, beat: 1}}, energy: 0.5, density: 0.5, role: 'the motif, low and filtered'}}
  - {{id: reveal, from: {{bar: 13, beat: 1}}, to: {{bar: 21, beat: 1}}, energy: 0.95, density: 0.9, role: 'the motif revealed; Bb C D'}}
  - {{id: drop, from: {{bar: 21, beat: 1}}, to: {{bar: 25, beat: 1}}, energy: 0.8, density: 0.6, role: 'brass stabs over the engine'}}
  - {{id: secret, from: {{bar: 25, beat: 1}}, to: {{bar: 29, beat: 1}}, energy: 0.35, density: 0.3, role: 'back to the dark; the B natural kept'}}
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
        - {{processor: gain, gain_db: 2.0}}
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
"""
OUT.write_text(score)
print(f"wrote {OUT}: {END_BAR - 1} bars, {(END_BAR - 1) * 4 * 60 / BPM:.0f} s")

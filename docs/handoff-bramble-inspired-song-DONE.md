# Done: `between_objectives` — the Bramble-inspired cue

Composed 2026-07-02 (Fable 5 draft, Opus 4.8 finish) from
`handoff-bramble-inspired-song.md`. Original material; the Bramble/Stickerbush
*signature* only (maj7/add9/sus float, constant soft ostinato, patient bell/
flute lead), no transcription.

## What it is

`scores/active/between_objectives.music.yaml` — 76 bars, **3:39**, 84 BPM
halftime. The AI drifting with no gradient to climb: a dotted-eighth **kalimba
ostinato** that never stops (identity layer), a patient **solo flute** (Sonatina)
that enters late and breathes, answered by **bowed vibraphone** (VCSL), over
Dmaj7 / Gadd9 / Bm7 harmony that never hard-cadences — Asus4 stands in for the
V so the loop re-enters Dmaj7 with no leading tone. Bridge blooms into borrowed
bVI/bVII (Bbmaj7/Cadd9) with a tempo sag (84→78→84) that recovers before the
seam. Celesta doubles the flute in the final duet; Etherealwinds harp wakes up
in the bloom.

## Latest bundle (regenerate; audio is gitignored)

```
generated/between_objectives/.versioned/84d9170b1545045f/
  preview/between_objectives_84d9170b1545045f.runtime_state_default.ogg   <- listen here
  preview/…runtime_state_calm.ogg / …_tension.ogg / …full_soundtrack_preview.ogg
```
Regenerate from repo root:
```
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle between_objectives --backend=pretty-midi \
  --runtime_stem_gain_mode=shared --force --zip_report
```

## Acceptance bar — all met

- **lead_collision: 0 collisions, 0 exposed tensions.**
- **All 4 SFZ resolved**, zero silent-fallback lines in render_isolated.stderr
  (flute, bowed vibe, celesta, harp). No octave folds.
- **Loop seam 0.58 dB** (first vs last 2s RMS), both sides at the opening 84 BPM.
- **Lead is the 2nd-loudest stem** (-31.5 dB, tied with the warm sub-bass at
  -31.3, above everything else) — group gains set from measured native stems.
- Dissonance top hotspot pulled from 1.59 → 0.83; all remainders are
  low-scored pad-color-vs-melody (rules bless pad color).

## Marked blind decisions (only ears can judge)

1. **Lead/bass co-loudest.** The warm sub-bass and flute sit within 0.2 dB.
   For a floaty cue I wanted the bass felt, not dominant; if the flute should
   be clearly on top, drop `group_postprocess.bass.gain_db` a couple dB.
2. **pitch_stability wobble is a tool artifact, not detuning.** The lead stem
   scores 38 wobbles / 400-cent peak, BUT the flagged spans run 8.8s (longest
   authored note is 2.9s) — the monophonic tracker merges reverb-connected
   legato notes and reads melodic motion + flute vibrato as "wobble." The
   accepted `broken_transmitter` violin lead scores the same order (23 / 210c).
   Logged as a tool limitation in `dev/journals/code_smells.md`. The 400-cent
   moment is the fast D5-E5-F#5→A5 run at the phrase-3 peak — intentional.
3. **arp bed tops out on the 5th, not the octave** (`[0,7,19,…]`): an octave
   root sat a semitone under the pad's maj7 (D4 vs C#4) and read sour on the
   pluck. If you want the brighter octave sparkle back, the tradeoff is that
   maj7 rub.

## Fixes made to the toolchain this session

- `audit/lead_collision.py`: bar derivation floored float-accumulated beats, so
  a bar-56 note arriving as 223.99999999999997 was misattributed to the prior
  bar and flagged as a false exposed tension. Added a +1e-6 nudge at all three
  floor sites.
- `.gitignore`: `scores/active/reports/` (regenerated audit output).

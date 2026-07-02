# Handoff: compose a Bramble-Blast-inspired song

Written 2026-07-02 by the agent that composed `fable`, `broken_transmitter`,
and `gradient_ascent`. Everything below is hard-won this session; following
it should get a strong first render instead of five iterations.

## The brief

An original cue **inspired by** SSBB's Bramble Blast / DKC2's Stickerbush
Symphony — inspired means the *style signature*, not the melody. Do NOT
transcribe or approximate the original tune; Jon explicitly wants original
material from first principles (and dislikes compositions modeled on the
repo's existing cues too — read their YAML for **syntax idiom only**).

The style signature to capture:

- **Dreamy suspension**: harmony built on maj7/add9/sus chords that never
  fully cadence; the bittersweet floating feel comes from avoiding hard
  V→I resolutions. Think slow harmonic rhythm (1–2 bars per chord).
- **The syncopated arpeggio bed**: a soft, round synth arpeggio in constant
  gentle motion (offbeat 8ths/16ths), more felt than heard. This is the
  identity layer — it never stops.
- **A patient bell/flute-class lead** that enters late, sings a long-breathed
  melody with big rests, and hands off to an answering voice.
- **Warm sub-bass** with a slow bounce (dotted rhythms), never busy.
- **Airy percussion**: brushed/soft kit, rimshots, shaker — halftime feel,
  ~80–95 BPM.
- Wistful-but-warm. Major with borrowed color, not minor.

Length 3–4 min. It's a game cue: **must loop invisibly** (see rules below).
Suggested id: something on-theme for the game (player = an AI seeking
purpose; docs/planning has the storyline) — e.g. a "drifting between
objectives" mood — but the name is your call.

## Non-negotiable rules (Jon's ear, learned the hard way)

1. **Loop-safe form**: no cold-start opening, no true ending. The final bar
   must hand off to bar 0 at the same tempo and near-identical texture.
   Tempo flourish via `tempo.map` is *liked* — just return to the opening
   BPM before the seam. Verify: last-2s vs first-2s RMS within ~2 dB.
2. **No MIDI guitar leads**, and if any guitar lead layer is used anyway,
   set `position_scoop_scale: 0.0` + `pitch_scoop_cents: 0.0` (the fret
   scoop reads out-of-tune on sustained samples). Prefer bowed/blown/bell
   leads; for this style a flute, music_box/celesta-class, or soft square
   is right. Dual leads (prominent sustained voice + quieter double) work
   well.
3. **Dissonance in moderation**: two foreground melodies must never sit a
   second apart in the same register (the #1 complaint class). Arps rub any
   stepwise melody — keep the arp an octave away from the lead's register.
4. **Melodies must not SIT on tensions**: a phrase ending on the 9th/maj7
   over the bar chord for >1 beat reads as "off". Passing eighths are fine.
   With sus/add9 HARMONY (this style), put the color in the *chords* and
   keep held melody notes on chord tones.

## Authoring gotchas (each cost a render this session)

- **Motif `roots` cycle per `repeats`, NOT per `starts`.** A multi-start
  layer with a roots list silently uses only `roots[0]`. For per-placement
  roots: single start + `repeats: N` + `every_bars: M`.
- **Motif `intervals` are chromatic semitones from `root`.** Transposing a
  diatonic phrase means picking a root whose chromatic offsets stay in key
  (e.g. an A-major figure rooted on C# sprays E#s). Recheck every root
  against every bar it sounds over.
- **Instrument ranges**: the render warns `N/M notes ... octave-folded` —
  treat >5% folds as an authoring bug (wrong octave), not noise.
- **Fuzzy `library_ref` roulette**: 'black twang' matched a *green* program
  because the folder name contains "Black". Pin exact numbered filenames or
  absolute `sfz:` paths for anything ambiguous. `*_legato_map` SFZ programs
  are silent on detached notes. Shinyguitar needs `controls: {100: 64}`.
- **Set group gains from MEASURED stems, not guesses.** Render once, read
  `native_stems` rms_dbfs from the adaptive manifest (or
  `reports/stem_loudness_summary.txt`), set `group_postprocess.<g>.gain_db`
  to place the lead on top, re-render. GM patches vary wildly (calliope is
  ~-73 dBFS native; square/saw are hot).
- The bundle's "buried lead" warning is a *budget model* that can't see
  sample loudness — trust measured stems over it.
- Pedalboard chorus: depth ≥0.15 at slow rates reads as a pitch "bend-down"
  on sustained notes. Keep depth ≤0.06 or rate ≥1.5 Hz. Never author a
  bend that STARTS off-pitch.

## Instruments that work (all verified rendering on this machine)

- Sonatina solo violin (pin: `.../Strings - Performance/Violin Solo 1
  Sustain (looped).sfz`) — best sustained lead.
- Sonatina flutes/winds, Sonatina Celeste (whispered bells; VPO celesta
  needs vel ≥63). VCSL (`sfz/Versilian/VCSL/...`): tubular bells,
  glockenspiel, **bowed vibraphone** — strongly consider for this style.
- jRhodes (`epiano.rhodes`), FreePats upright/Salamander pianos.
- Karoryfer Meatbass (arco double bass; use `arco_looped_basic_map.sfz` by
  path), Growlybass, Etherealwinds Harp.
- GM synths via FluidR3 for pads/arps/soft leads (`pad_warm`, `pad_new_age`,
  `fx_crystal`, `lead_square`, `music_box`, `kalimba`) — no range problems,
  set levels from measurements.

## Workflow (in order — static checks are free, renders cost ~2 min)

```bash
cd tools/ambition_music_renderer   # venv at .venv/, uv-managed
# 1. write scores/active/<id>.music.yaml   (read gradient_ascent for idiom)
# 2. static gate, milliseconds each:
.venv/bin/python -m ambition_music_renderer.audit.lead_collision scores/active/<id>.music.yaml
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools .venv/bin/python -m ambition_music_renderer plugins validate_score scores/active/<id>.music.yaml
#    plus dissonance/sour/mix_balance via: .venv/bin/python -c "...audit_spec(spec)" or the audit CLI
# 3. render (from repo root):
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle <id> --backend=pretty-midi \
  --runtime_stem_gain_mode=shared --force --zip_report
# 4. read the bundle warnings + reports/, measure stems, iterate
# 5. rendered-audio pitch check on lead groups:
.venv/bin/python -m ambition_music_renderer audit pitch_stability generated/<id>/.versioned/<hash> --groups=<lead-groups>
# 6. loop-seam check: first/last 2s RMS + tempo map bar0 == final bar
```

Expression surfaces available: `tempo.map` (ritardando/accelerando),
`kind: notes` (literal events incl. per-note bends — use sparingly),
per-layer `dynamics` velocity curves (preferred over CC automation —
sfizz ignores `gain_ccN`), `controls:` CC init, per-group pedalboard
`effect_chain`. See README "Score file format".

Acceptance bar: `lead_collision` = 0 collisions; no exposed tension >1.5
beats on a *held* lead note unless deliberate; every SFZ resolves with no
silent-fallback lines in `reports/render_isolated.stderr.txt`; seam RMS
delta <2 dB at matching tempo; lead group is the loudest or second-loudest
measured stem. Commit the YAML (never the generated audio), leave the
bundle path for Jon, and flag anything only ears can judge as a marked
blind decision.

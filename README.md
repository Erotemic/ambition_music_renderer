# Ambition music renderer

Author-time renderer for generated Ambition music assets. Generated outputs are local until explicitly installed or published into runtime assets.

This package is the canonical code-only music generator for the project. Do not commit ad-hoc rendered `.ogg`, `.wav`, `.mid`, or temporary stem buffers unless a task explicitly says to publish runtime assets.

## Common commands

Run from the repo root unless noted:

```bash
PYTHONPATH=tools/ambition_music_renderer python -m ambition_music_renderer --help
PYTHONPATH=tools/ambition_music_renderer python -m ambition_music_renderer cue bundle for_emmy_forever_ago --backend pretty-midi --force --zip
PYTHONPATH=tools/ambition_music_renderer python -m ambition_music_renderer cue bundle for_emmy_forever_ago --backend pretty-midi --runtime-stem-gain-mode shared --force --zip
PYTHONPATH=tools/ambition_music_renderer python -m ambition_music_renderer cue bundle for_emmy_forever_ago --backend pretty-midi --runtime-stem-gain-mode shared --zip-report --force
./generate_audio_assets.sh --force
```

From the tool directory:

```bash
cd tools/ambition_music_renderer
python -m ambition_music_renderer --help
./render_first_goblin_transition_lab.sh
python transition_audit.py --help     # two-file transition seam
python audit_cue_balance.py --help    # sections within one cue
python level_report.py --help         # inter-cue catalog levels; --check fails on clipping
```

Use the package CLI and scripts in this directory for current music-renderer work. Older docs may mention retired paths under `tools/audio/`; those paths are stale and should not be copied into new instructions.

## Useful files

- `ambition_music_renderer/cli.py` - package CLI.
- `ambition_music_renderer/musicir_renderer.py` - main MusicIR renderer and renderer version.
- `ambition_music_renderer/cue_bundle.py` - one-command cue regeneration, diagnostics, reports, plots, and uploadable bundles.
- `scores/active/` - cues actively used or being prepared for runtime.
- `scores/examples/` - reference/example cues.
- `scores/archive/` - historical cues kept for reference.
- `render_first_goblin_transition_lab.sh` - local transition-lab helper.
- `install_first_goblin_tune_v2.py` - installer for the first-goblin tune asset path.
- `audit_cue_balance.py`, `transition_audit.py`, `level_report.py`, `spectral_compare.py`, `spectral_localize.py`, `arrangement_audit.py`, `dissonance_audit.py` - analysis helpers (`level_report.py` is the diff-friendly cross-catalog loudness/clipping report; `arrangement_audit.py` preflights group prominence, low-register density, and harmonic outliers; `dissonance_audit.py` finds score-level note clashes before audio is rendered and can emit human-readable markdown + plots).
- `goals.md` - design/planning notes for renderer direction.
- `MUSIC_RENDERER_REFACTOR_ROADMAP.md` - durable roadmap/checklist for the renderer cleanup.

## Dependencies and backends

The renderer can use multiple backends depending on local setup:

| Backend | What it is | When to use |
|---|---|---|
| `pretty-midi` | pyFluidSynth + SoundFont, internal reverb/chorus disabled | Preferred for production-quality local renders when available. |
| `fluidsynth-cli` | the `fluidsynth` binary + SoundFont | Useful when Python FluidSynth bindings misbehave. |
| `fallback` | additive synth fallback | Diagnostic/sketch fallback only; request explicitly with `--backend fallback`. Can contain synthetic bow/breath/noise artifacts. |
| `auto` | backend selection/fallback policy | Use only when fallback behavior is acceptable and explicitly reported. |
| `sfizz` / `sfizz-render` | optional `sfizz_render` CLI + SFZ instrument files | Use for better open sample instruments from YAML; requires `render.sfizz.default_sfz` or per-instrument `instrument_backend.sfz`. |

Optional pro-audio processing remains opt-in. `pyloudnorm` is part of the normal Python dependency set and enables `target_lufs` / `loudness.target_lufs` postprocess normalization. The `pro-audio` optional extra enables Pedalboard/VST3 effects without making GPL/Pedalboard part of the light renderer path. LV2/NAM/Guitarix are external command/plugin installs and are only invoked when YAML uses `external_effects` / `external_chain`.

Example optional processing block:

```yaml
postprocess:
  target_lufs: -16
  true_peak_db: -1.5
  pedalboard_effects:
    - {effect: compressor, threshold_db: -18, ratio: 2.5}
    - {effect: vst3, path: local/plugins/MyAmp.vst3, parameters: {}}

group_postprocess:
  guitars:
    highpass_hz: 80
    lowpass_hz: 9000
    external_effects:
      - kind: command
        command: [my-offline-amp, --input, "{input}", --output, "{output}"]
```

SoundFont preference is defined in the renderer code. Prefer high-quality MuseScore/FluidR3 style General MIDI SoundFonts when available. Override per-cue with `render.soundfont` in YAML or per invocation with a backend-specific CLI flag when supported. Normal authoring defaults should prefer `pretty-midi`; fallback should never appear because a prompt or lower-level script quietly picked it.


## One-command cue debug bundles

Use `cue bundle` when regenerating a song for review or for handoff to another
agent. It renders with retained debug stems, runs the useful reports, writes
spectrogram images when matplotlib is available, and packages an uploadable
bundle on request. Generated bundles remain ignored by git.

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer cue bundle <cue_id> \
  --backend pretty-midi \
  --force \
  --zip
```

For layered runtime-stem audits, add `--runtime-stem-gain-mode shared`. The
default `native` mode preserves historical raw stem levels; `shared` computes one
reference gain from the all-stem mix and applies it to every runtime stem so the
layered export is audible without destroying the stem balance via independent
normalization. Shared gain is capped by default (`render.runtime_stems.max_gain_db`
or `--runtime-stem-max-gain-db`) because a cue that needs 40+ dB of rescue gain
usually needs louder source instruments/layers, not louder exported noise.

Use `--zip-report` for compact chat/agent handoff zips; the on-disk bundle directory remains fully featured and keeps the generated audio for local audition. Report zips exclude
large OGG/WAV/NPY binaries but keep source YAML, manifests, logs, TSV/JSON level
reports, `spectral_fingerprint.json`, and JPEG spectrograms. Use `--zip` only when the recipient must audition audio directly from the zip. Add `--publish` only when
the generated `full.ogg` should be copied into the game asset tree. Add
`--include-scratch-stems` only for local handoff bundles; raw `.npy` stems are
useful but usually too large for chat upload.

The bundle also emits theory/debug reports that are easier for agents to reason
about than raw audio:

- `arrangement_audit_summary.txt/json/md` preflights the YAML before audio render: default-state group prominence, likely buried groups, bass/melody collision candidates, and long non-chord tones.
- `dissonance_hotspots_summary.txt/json/tsv` identifies bars/beats where
  overlapping note events create strong seconds, sevenths, tritones, or close
  register clusters, attributed back to layers/groups/instruments.
- `dissonance_hotspots.md` is the same hotspot information in a scan-friendly
  table for humans.
- `plots/dissonance_timeline.<fmt>` and `plots/dissonance_layer_pairs.<fmt>`
  visualize when clashes occur and which layer pairs are responsible.
- `state_mix_report_summary.txt/json/tsv` explains why adaptive previews may
  sound similar: `runtime_*` states are true weighted sums, while `audition_*`
  states are normalized for review and may collapse loudness differences.
- `spectral_fingerprint_summary.txt/json/tsv` summarizes low/mid/high/vhigh/air
  energy by stem without requiring an audio player.
- `stem_amplitude_summary.txt/json/tsv` and `stem_amplitude_envelope.tsv`
  show raw and state-weighted runtime stem levels, so mix balance can be read
  directly rather than inferred from spectrogram color.
- `plots/stem_amplitude_balance.<fmt>`, `plots/stem_amplitude_timeline.<fmt>`,
  and `plots/stem_amplitude_stack.<fmt>` visualize relative stem amplitude and
  how the stems layer through the cue.

## Reference-audio surface analysis

Use this when you have a reference MP3/OGG/WAV and want to mimic broad sonic
qualities such as loudness envelope, dynamic range, brightness, and onset
density. It does **not** do source separation or infer instrumentation. MP3
decode depends on the local `soundfile` / `ffmpeg` setup.

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer.reference_audio_audit path/to/reference.mp3 \
  --outdir /tmp/reference_audio_audit
```

Outputs include `reference_audio_summary.txt`, `reference_audio_audit.json`,
`reference_audio_envelope.tsv`, and optional loudness / brightness plots.

## Output and publish model

Rendering is a staging step. Publishing/installing is a separate decision.

Typical generated output for a cue includes:

```text
generated/<cue>/
  adaptive/<section>/
    <section>.full.ogg
    <section>.<stem>.ogg
  preview/
    full_soundtrack_preview.ogg
    runtime_minimal.ogg
    runtime_maximal.ogg
    runtime_state_<name>.ogg
    audition_minimal.ogg
    audition_maximal.ogg
    audition_state_<name>.ogg
  reports/
    stem_export_report.tsv
    manifest_audio_levels.tsv
    mix_diagnostics.txt
    spectral_fingerprint.json
    spectral_fingerprint.tsv
  <cue>.adaptive_manifest.json
```

`runtime_*` previews are true weighted stem sums with no upward audition
normalization. `audition_*` previews are the same mixes normalized for easier
composition review. Do not use audition files as evidence of in-game loudness.

Runtime assets live under:

```text
crates/ambition_gameplay_core/assets/audio/music/generated/<cue>/
```

For `first_goblin_tune_v2`, the top-level wrapper currently renders/installs the active cue path used by the sandbox. By default, prefer full-mix render/install for the cue the game actually loads. Use stem rendering when auditing or reviving stem-driven runtime playback.

## Score file format

Music scores are YAML files under `scores/`. At a high level:

- `tempo` / `meter` - BPM and beats per bar.
- `render` - sample rate, OGG quality, backend, SoundFont pin, and render-specific settings.
- `postprocess`, `stem_postprocess`, `group_postprocess` - EQ, reverb, limiter/compressor, stereo width, and related mastering controls at different mix levels.
- `constraints` - optional voicing rules such as minimizing motion or avoiding clusters.
- `instruments` - named instruments with group, GM program/drum settings, MIDI volume/pan/expression/modulation.
- `motifs` - reusable melodic/rhythmic patterns.
- `layer_templates` - reusable layer definitions.
- `playback` - runtime crossfade/loop behavior.
- `state_map` - gameplay states mapped to sections and optional stem gains.
- `sections` - cue sections with bar count, intensity, harmony, layers, and optional section postprocess.

Common layer kinds include:

- `pad_chords`
- `chord_hits`
- `bassline`
- `motif`
- `arpeggio`
- `pedal`
- `root_hits`
- `drums`
- `automation`
- `guitar_strum` - chord-symbol input compiled to plausible six-string down/up strums.
- `guitar_chug` - power-chord/palm-muted rhythm guitar with optional separate take definitions.
- `guitar_lead` - motif input compiled to monophonic guitar-like lead notes with position-aware scoops.

Most note-producing layers accept timing and velocity humanization. Motif layers can also carry pitch-bend curves for slides or bends. Guitar layers add a tiny custom performance compiler: it assigns notes to six strings, staggers strums physically, and makes double-tracking explicit as separate takes rather than generic stereo widening.

## Constraint flags

The renderer supports opt-in voicing constraints. They are off by default because there are legitimate musical reasons to break each rule.

Example:

```yaml
constraints:
  voice_leading: minimize_motion
  no_clusters: true
```

Per-layer overrides can use the same shape. Constraints currently apply to chord construction paths; do not assume every layer kind enforces them.

## Debugging transitions and balance

For adaptive cues, distinguish runtime problems from generated-audio problems before changing code:

1. Render/regenerate the cue.
2. Audit generated and installed OGGs with `audit_cue_balance.py`.
3. Run the game in the relevant room and capture music logs.
4. Confirm whether the runtime starts the next state at target gain or fades from silence.
5. Listen to adjacent generated files outside the game to decide if the seam exists before runtime touches them.

Useful future improvements tracked in `TODO.md`:

- level reports with LUFS / peak / RMS / duration,
- live in-engine gain HUD,
- equal-power crossfade experiments,
- mastered per-stem outputs if stem-driven playback returns,
- clearer staging vs production publish flow.

## Music-theory reference

When composing new YAML cues, prefer explicit, inspectable musical choices:

- Preserve common tones and minimize voice motion between adjacent chords when the texture wants smoothness.
- Avoid accidental parallel perfect fifths/octaves in classical-ish writing unless the style wants it.
- Keep bass instruments, harmonic body, and lead instruments separated enough that the mix remains readable.
- Use dynamic layering to intensify gameplay states: sparse intro -> loop body -> denser combat -> recap/outro.
- Modal color tones help cues feel intentional: Phrygian b2, Lydian #4, Mixolydian b7, harmonic-minor leading tone, etc.
- Humanization and anticipation/lay-back can make generated parts feel less mechanical; keep values small and deliberate.

## Agent rules

- Keep generated audio out of runtime assets unless the task explicitly installs/publishes it.
- Preserve conservative gain ranges in tune specs; the runtime renderer can clip if stems are too hot.
- Treat `first_goblin_tune_v2` as the current active adaptive-music lab, not as the final abstraction for all encounters.
- Update `docs/recipes/generated-music-workflow.md` and `docs/tools/generated-audio-tools.md` when the workflow changes.

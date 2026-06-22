# Ambition music renderer

Author-time renderer for generated Ambition music assets. Generated outputs are local until explicitly installed or published into runtime assets.

This package is the canonical code-only music generator for the project. Do not commit ad-hoc rendered `.ogg`, `.wav`, `.mid`, or temporary stem buffers unless a task explicitly says to publish runtime assets.

## Common commands

Run from the repo root unless noted. `uv run --project ~/code/ambition/tools/ambition_music_renderer` installs/runs the package with the renderer project metadata, so `PYTHONPATH=tools/ambition_music_renderer` should not be needed.

Recommended test command:

```bash
cd ~/code/ambition
uv run --project ~/code/ambition/tools/ambition_music_renderer pytest -q tools/ambition_music_renderer/tests
```

If you already activated the renderer environment, use `uv run --active`:

```bash
cd ~/code/ambition
source tools/ambition_music_renderer/.venv/bin/activate
uv run --active pytest -q tools/ambition_music_renderer/tests
```

Common CLI commands:

```bash
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer --help
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer cue_bundle for_emmy_forever_ago --backend=pretty-midi --force --zip
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer cue_bundle for_emmy_forever_ago --backend=pretty-midi --runtime_stem_gain_mode=shared --force --zip
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer cue_bundle for_emmy_forever_ago --backend=pretty-midi --runtime_stem_gain_mode=shared --zip_report --force
./generate_audio_assets.sh --force
```

Auxiliary analysis and maintenance helpers are exposed through the package modal CLI rather than top-level scripts:

```bash
cd ~/code/ambition
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer audit --help
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer audit transition --help
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer audit cue_balance --help
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer audit levels --check
```

Use the package CLI for current music-renderer work. Older docs may mention retired paths under `tools/audio/` or direct `python *.py` tool scripts; those paths are stale and should not be copied into new instructions.

Bundle report generation also calls these helpers through the packaged modal CLI. If a bundle run reports `can't open file .../audit_cue_balance.py`, `spectral_compare.py`, `spectral_localize.py`, or `transition_audit.py`, that checkout still has stale orchestration code; update to a build where `cue_bundle` invokes `python -m ambition_music_renderer audit ...` instead of root-level script paths.

## Package layout

- `ambition_music_renderer/cli.py` - light top-level modal CLI and repo path helpers.
- `ambition_music_renderer/render/` - render orchestration, bundle generation, worker entrypoints, MusicIR renderer internals, and compiled kernels.
  - `render/score_*.py` - score expansion split into core constants/context, theory helpers, event construction, and layer renderers.
  - `render/synth.py`, `render/effects.py`, `render/export.py`, and `render/group.py` - audio synthesis, post-process effects, export/metadata, and stem-group rendering.
  - `render/bundle_*.py` - cue bundle orchestration split into base config/path helpers, audio reports, spectral reports, adaptive reports, spectrograms, archive/zip helpers, and the main `bundle.py` workflow.
  - `render/musicir_renderer.py` and `render/bundle_reports.py` are compatibility facades; put new implementation code in the focused modules above.
- `ambition_music_renderer/audit/` - active diagnostics and reports exposed under `python -m ambition_music_renderer audit ...`.
- `ambition_music_renderer/legacy/` - quarantined older one-off helpers that are still callable but need a later rename/delete decision.
- `ambition_music_renderer/backends/` - optional plugin/SFZ/LV2/VST adapter code, imported only when requested.

## Useful files

- `ambition_music_renderer/render/score_layers.py` - MusicIR layer renderers and `build_score`.
- `ambition_music_renderer/render/effects.py` - filters, compressor, reverb wrappers, stereo widening, and limiting.
- `ambition_music_renderer/render/synth.py` - FluidSynth / pretty-midi audio rendering.
- `ambition_music_renderer/render/bundle.py` - one-command cue regeneration, diagnostics, reports, plots, and uploadable bundles.
- `ambition_music_renderer/render/isolated.py` and `render/group_worker.py` - adaptive stem render entrypoints.
- `ambition_music_renderer/audit/*.py` - active analysis helpers (`levels`, `cue_balance`, `arrangement`, `dissonance`, `spectral_localize`, `spectral_compare`, `transition`, etc.).
- `ambition_music_renderer/legacy/install_first_goblin_tune_v2.py` - quarantined legacy installer for the first-goblin tune asset path, exposed as `python -m ambition_music_renderer legacy install_first_goblin_tune_v2`.
- `scores/active/` - cues actively used or being prepared for runtime.
- `scores/examples/` - reference/example cues.
- `scores/archive/` - historical cues kept for reference.
- `render_first_goblin_transition_lab.sh` - local transition-lab helper.
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

Optional pro-audio processing remains opt-in. `pyloudnorm` is part of the normal Python dependency set and enables `target_lufs` / `loudness.target_lufs` postprocess normalization. `numba` is also part of the normal dependency set because the built-in Schroeder/Freeverb-style reverb uses compiled DSP kernels for its long comb/allpass feedback loops; set `AMBITION_MUSIC_RENDERER_DISABLE_NUMBA=1` only when debugging the pure-Python fallback. The `pro-audio` optional extra enables Pedalboard/VST3 effects without making Pedalboard part of the default renderer path. LV2/NAM/Guitarix are external command/plugin installs and are only invoked when YAML explicitly requests those optional backends.

Use the plugin diagnostics before authoring a score that depends on local plugins:

```bash
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer plugins doctor
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer plugins list_vst3
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer plugins list_lv2 --limit=40
uv run --project ~/code/ambition/tools/ambition_music_renderer python -m ambition_music_renderer plugins validate_score guitar_backend_demo
```

For new work, prefer the explicit `effect_chain` surface. Each step states the host family. This keeps the default render path lightweight while making DAW-like processing reproducible from YAML/Python.

```yaml
postprocess:
  target_lufs: -16
  true_peak_db: -1.5
  effect_chain:
    - kind: pedalboard
      effects:
        - {effect: compressor, threshold_db: -18, ratio: 2.5}
        - {effect: reverb, room_size: 0.18, wet_level: 0.08}

# VST3 effects are loaded through Pedalboard when the optional package and
# local plugin are installed. Relative paths are resolved against the score.
group_postprocess:
  guitars:
    highpass_hz: 80
    lowpass_hz: 9000
    effect_chain:
      - kind: vst3
        path: local/plugins/MyAmp.vst3
        parameters: {}

      # Simple LV2 file effects use lv2proc. Use `plugins list_lv2` and
      # `plugins lv2_info <URI>` to discover plugin URIs/ports locally.
      - kind: lv2proc
        plugin_uri: http://example.invalid/my-lv2-plugin
        params: {gain: 0.5}

      # NAM/Guitarix setups vary, so command adapters are first-class. The
      # renderer writes a WAV, substitutes placeholders, then reads the output.
      - kind: command
        command: [my-offline-amp, --input, "{input}", --output, "{output}", --sample-rate, "{sample_rate}"]
```

Legacy `pedalboard_effects`, `vst3_effects`, `external_effects`, and `external_chain` still work. Use `effect_chain` when combining multiple host families because ordering is explicit.

SoundFont preference is defined in the renderer code. Prefer high-quality MuseScore/FluidR3 style General MIDI SoundFonts when available. Override per-cue with `render.soundfont` in YAML or per invocation with a backend-specific CLI flag when supported. Normal authoring defaults should prefer `pretty-midi`; fallback should never appear because a prompt or lower-level script quietly picked it.


## One-command cue debug bundles

Use `cue_bundle` when regenerating a song for review or for handoff to another
agent. It renders with retained debug stems, runs the useful reports, writes
spectrogram images when matplotlib is available, and packages an uploadable
bundle on request. Generated bundles remain ignored by git.

```bash
uv run --project ~/code/ambition/tools/ambition_music_renderer \
python -m ambition_music_renderer cue_bundle <cue_id> \
  --backend=pretty-midi \
  --force \
  --zip
```

For layered runtime-stem audits, add `--runtime_stem_gain_mode=shared`. The
default `native` mode preserves historical raw stem levels; `shared` computes one
reference gain from the all-stem mix and applies it to every runtime stem so the
layered export is audible without destroying the stem balance via independent
normalization. Shared gain is capped by default (`render.runtime_stems.max_gain_db`
or `--runtime_stem_max_gain_db`) because a cue that needs 40+ dB of rescue gain
usually needs louder source instruments/layers, not louder exported noise.

Use `--zip_report` for compact chat/agent handoff zips; the on-disk bundle directory remains fully featured and keeps the generated audio for local audition. Report zips exclude
large OGG/WAV/NPY binaries but keep source YAML, manifests, logs, TSV/JSON level
reports, `spectral_fingerprint.json`, and JPEG spectrograms. Use `--zip` only when the recipient must audition audio directly from the zip. Add `--publish` only when
the generated `full.ogg` should be copied into the game asset tree. Add
`--include_scratch_stems` only for local handoff bundles; raw `.npy` stems are
useful but usually too large for chat upload.


### Profiling renders

Normal `cue_bundle` launches `render_isolated` as a subprocess so long renders are robust and worker failures are contained. That isolation is good for production, but it hides useful line-profiler call stacks. For profiling, either set `LINE_PROFILE=1` or pass `--profile_render`; both run `render_isolated` in-process and render serial worker groups by direct Python calls so line-profiler can see below the old process boundaries. `--profile_render` is a convenience flag that also enables `LINE_PROFILE=1`; it uses line profiler only and does not start cProfile.

Recommended short profiling command:

```bash
cd ~/code/ambition

LINE_PROFILE=1 uv run --project ~/code/ambition/tools/ambition_music_renderer \
python -m ambition_music_renderer cue_bundle for_emmy_forever_ago \
  --backend=pretty-midi \
  --runtime_stem_gain_mode=shared \
  --render_audio_mode=full-mix-only \
  --profile_render \
  --force \
  --zip_report
```

For an already-active renderer venv:

```bash
cd ~/code/ambition
source tools/ambition_music_renderer/.venv/bin/activate

LINE_PROFILE=1 uv run --active \
python -m ambition_music_renderer cue_bundle for_emmy_forever_ago \
  --backend=pretty-midi \
  --runtime_stem_gain_mode=shared \
  --render_audio_mode=full-mix-only \
  --profile_render \
  --force \
  --zip_report
```

Use `--render_in_process` without `--profile_render` only for debugging; the default subprocess path is still the safer production path. The profile surface includes the old process-boundary functions plus audio hotspots such as `simple_reverb`, `_comb_filter`, `_allpass_filter`, `_new_fluidsynth`, `_fluidsynth_stereo_samples`, filters, compressor, limiter, and OGG writing helpers. The comb/allpass bodies normally run through lazily imported Numba kernels, so line profiler should show those wrapper calls becoming small instead of spending minutes inside Python loops. To inspect a saved line-profiler file, use:

```bash
python -m line_profiler -rtmz profile_output.lprof
```

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
- `stem_loudness_summary.txt/json/tsv` reports per-stem native and runtime
  RMS/peak/headroom in dBFS and warns when one channel is wildly louder or
  quieter than the rest. Start here when a mix sounds obviously wrong.
- `plots/stem_loudness.<fmt>` is a single ranked stem/channel loudness plot
  that makes buried or overpowering stems visible at a glance.
- `stem_amplitude_summary.txt/json/tsv` and `stem_amplitude_envelope.tsv`
  show raw and state-weighted runtime stem levels, so mix balance can be read
  directly rather than inferred from spectrogram color.
- `plots/stem_loudness_timeline.<fmt>` is the main over-time balance plot:
  one fixed-dBFS line per stem across the full soundtrack timeline. It is
  generated from scratch stems when running fast `full-mix-only` bundles, so it
  remains available even when per-section per-stem OGGs are skipped.
- `plots/stem_amplitude_balance.<fmt>`, `plots/stem_amplitude_timeline.<fmt>`,
  and `plots/stem_amplitude_stack.<fmt>` visualize relative stem amplitude and
  how the stems layer through the cue. `stem_amplitude_timeline` is retained as
  the legacy filename for the same over-time diagnostic.
- Spectrogram plots use a fixed dB color range by default so two plots from the
  same bundle can be compared visually without local autoscaling hiding level
  mistakes.

## Reference-audio surface analysis

Use this when you have a reference MP3/OGG/WAV and want to mimic broad sonic
qualities such as loudness envelope, dynamic range, brightness, and onset
density. It does **not** do source separation or infer instrumentation. MP3
decode depends on the local `soundfile` / `ffmpeg` setup.

```bash
uv run --project ~/code/ambition/tools/ambition_music_renderer \
python -m ambition_music_renderer audit reference_audio path/to/reference.mp3 \
  --outdir=/tmp/reference_audio_audit
```

Outputs include `reference_audio_summary.txt`, `reference_audio_audit.json`,
`reference_audio_envelope.tsv`, and optional loudness / brightness plots.

## Output and publish model

Rendering is a staging step. Publishing/installing is a separate decision.

Typical generated output for a cue is versioned by the renderer/spec hash so old experiments do not sit beside current files:

```text
generated/<cue>/
  building -> .versioned/<hash-being-built>/
  latest -> .versioned/<latest-successful-hash>/
  .versioned/<hash>/
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
      stem_loudness_summary.txt
      stem_loudness.json
      stem_loudness.tsv
      spectral_fingerprint.json
      spectral_fingerprint.tsv
    plots/
      stem_loudness.jpg
      stem_loudness_timeline.jpg
      stem_amplitude_balance.jpg
      full_spectrogram.jpg
    <cue>.adaptive_manifest.json
```

Use `generated/<cue>/building/` while a render is in progress if you want to peek at intermediate stems. Use `generated/<cue>/latest/` for the most recent successful run. Explicit `--outdir` paths keep the caller-provided layout and do not get moved under `.versioned/`.

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
2. Audit generated and installed OGGs with `python -m ambition_music_renderer audit cue_balance`.
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

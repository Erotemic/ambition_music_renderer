# Music renderer refactor roadmap

This document is the durable handoff for the Ambition music-renderer cleanup.  It
should be updated whenever a patch moves the renderer closer to the intended end
state, so a new agent can recover the plan without relying on chat history.

## North star

The renderer should make every MusicIR cue reproducible, inspectable,
packageable, and publishable with a small number of ergonomic commands while
preserving existing songs and runtime behavior.

A healthy end-state workflow looks like this:

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer cue bundle for_emmy_forever_ago \
  --backend pretty-midi \
  --runtime-stem-gain-mode shared \
  --force \
  --publish \
  --zip
```

For compatibility, `--runtime-stem-gain-mode native` remains the default. Use
`shared` when auditing or preparing layered runtime stems; it applies one shared
reference gain across all stems instead of independently normalizing them. Shared
runtime gain is capped by default so the exporter does not turn a quiet/noisy
source into loud noisy stems; if diagnostics report a capped or very large gain,
fix the score source levels rather than raising the cap.

That command should answer:

- Which score file was rendered?
- Which normalized score model did the renderer actually consume?
- Which backend, SoundFont, renderer version, and hash produced the output?
- Which notes/layers/groups/stems were generated?
- Which stem buffers became which adaptive OGG files?
- Which state-map previews were generated and with which weights?
- Which files were published into game assets?
- Which reports and plots explain loudness, spectral issues, stem export, and
  transition seams?
- How can another person or agent rerun the same analysis?

## Policy invariants

These are not smells and should not be “fixed” away:

- Generated audio and debug artifacts should remain ignored by git by default.
- Publishing generated audio to runtime assets should be explicit.
- Existing score YAMLs must remain renderable while the schema evolves.
- Existing runtime behavior, especially `first_goblin_tune_v2`, must be preserved
  until a replacement path is proven in game.
- The fallback renderer must remain available for diagnostics and portability,
  but it should never surprise normal authoring workflows.

## First-order pain points

### Backend defaults are inconsistent

The package CLI already prefers `pretty-midi`, but lower-level isolated render
entry points historically defaulted to `fallback`.  This is confusing because the
fallback backend can add synthetic bow/breath/noise artifacts that are actively
misleading during composition/debugging.

Desired rule:

- Default backend: `pretty-midi`.
- `fallback`: explicit opt-in with `--backend fallback`.
- `auto`: acceptable only when its fallback behavior is explicit in docs/reports.

### Debug products are useful but scattered

The renderer already has useful diagnostics:

- `audit_cue_balance.py`
- `level_report.py`
- `spectral_compare.py`
- `spectral_localize.py`
- `transition_audit.py`
- scratch `*.npy` stems from `--keep-debug-stems`
- preview/state/adaptive OGGs

The pain is that they are not orchestrated into one provenance bundle.

### Generated output lacks a single provenance story

The renderer can emit adaptive files, full previews, in-game previews, manifests,
regen scripts, and scratch stems.  It is still too easy to listen to a file and
not know which YAML, backend, SoundFont, state weights, and postprocess chain
produced it.

### Stem export behavior is hard to audit

During debugging, it must be obvious whether a problem is in:

- the generated notes,
- scratch stem buffers,
- exported adaptive OGGs,
- preview/state mixes,
- master postprocess,
- publish/install logic, or
- Rust runtime mixing.

The bundle implementation adds `stem_export_report.tsv/json` to compare scratch
stems, adaptive audio, and preview audio levels/durations. It also writes
manifest-scoped audio levels and mix diagnostics so stale files from older render
hashes do not contaminate a handoff bundle.

### Game registration and Python generation are weakly coupled

Scores in `scores/active/` are not necessarily registered in the game, and
runtime music track registration currently lives elsewhere.  This is acceptable
for now but should become an explicit catalog/publish phase.

### Schema ergonomics are more important than the validator library

A Pydantic model would help, but the more important work is the domain model:

- buses/groups/stems,
- gameplay states,
- exports,
- render policy,
- debug policy,
- game catalog registration,
- provenance,
- compatibility mode for older cues.

Pydantic should be introduced after the desired model is clear enough to avoid
freezing accidental design.

## Intended architecture

### Command surface

Preferred authoring commands:

```bash
python -m ambition_music_renderer render <cue>
python -m ambition_music_renderer render-publish <cue> --force-render
python -m ambition_music_renderer cue bundle <cue> --force --zip
python -m ambition_music_renderer cue bundle <cue> --force --publish --zip
```

Future commands:

```bash
python -m ambition_music_renderer cue validate <cue>
python -m ambition_music_renderer cue inspect <cue>
python -m ambition_music_renderer catalog validate
python -m ambition_music_renderer catalog sync-sandbox
python -m ambition_music_renderer catalog publish-radio
```

### Preview semantics

Every adaptive render should distinguish:

- `runtime_<state>.ogg`: weighted state-map stem sum with no upward audition
  normalization. This is the truthful preview for layered runtime playback.
- `audition_<state>.ogg`: the same state-map stem sum normalized for comfortable
  listening and A/B comparison. This is useful for composition review but should
  not be used as evidence of runtime loudness.
- `full_soundtrack_preview.ogg`: the mastered full-cue authoring preview.

This split exists because the old `in_game_*` preview files were authoring
normalized and could hide the fact that native runtime stems were effectively
silent.

### Output layout

Keep runtime assets stable:

```text
crates/ambition_gameplay_core/assets/audio/music/generated/<cue_id>/
  full.ogg
```

Use ignored staging/debug outputs for generated products:

```text
tools/ambition_music_renderer/generated/<cue_id>/
  adaptive/
  preview/
  scratch_stems/
  reports/
  plots/
  <cue>_<hash>.adaptive_manifest.json
  regen.sh
```

Use ignored bundles for upload/share artifacts. The on-disk bundle directory is
always fully featured. `--zip` creates a full zip with manifest-referenced audio;
`--zip-report` creates a compact chat/agent zip that excludes OGG/WAV/NPY/MIDI
binaries while retaining source, manifests, numeric reports, logs, and
spectrogram images:

```text
tools/ambition_music_renderer/bundles/<cue_id>_<hash>_bundle/
  source/
  adaptive/                 # present on disk and in full zip
  preview/                  # present on disk and in full zip
  reports/
  plots/                    # JPEG by default for small report bundles
  bundle_manifest.json
  rerun_bundle.sh
```

Bundle zips should be ignored by git and uploaded manually when needed. Prefer
`--zip-report` for bulk catalog handoff bundles and use `--zip` only when the
recipient needs to audition audio directly from the archive.

### Future package organization

The current first patch does not split the renderer yet.  A later refactor should
move toward:

```text
ambition_music_renderer/
  musicir/       # schema, load, normalize, compatibility transforms
  score/         # harmony/layer/motif -> note events/MIDI
  render/        # render graph, backends, stems, export
  dsp/           # filters, dynamics, reverb, mastering
  debug/         # level, spectral, plots, bundle reports
  game/          # publish/catalog/sandbox integration
```

Do this only after bundle/provenance tests are in place.

## Progress checklist

### Phase 1: ergonomic debug bundle around current pipeline

- [x] Add durable refactor roadmap/checklist document.
- [x] Make isolated render defaults prefer `pretty-midi` over `fallback`.
- [x] Add `python -m ambition_music_renderer cue bundle <cue>`.
- [x] Add top-level `bundle <cue>` alias for convenience.
- [x] Bundle existing renderer outputs without moving runtime paths.
- [x] Keep `fallback` available by explicit `--backend fallback`.
- [x] Generate `stem_export_report.tsv/json` for scratch/adaptive/preview level comparison.
- [x] Generate manifest-scoped audio level reports that ignore stale preview/adaptive files.
- [x] Bundle only manifest-referenced audio files, not whole stale output directories.
- [x] Split state previews into runtime-native and audition-normalized families.
- [x] Add renderer mix diagnostics for raw all-stem sum vs mastered full preview.
- [x] Add explicit shared-gain runtime stem export mode behind `--runtime-stem-gain-mode shared`.
- [x] Run existing debug helpers from the bundle command and store logs.
- [x] Generate optional spectrogram images when matplotlib is available.
- [x] Generate stem-amplitude balance, timeline, and stack plots so mix levels are visible without interpreting spectrogram colorbars.
- [x] Prefer JPEG spectrogram plots for small handoff bundles; retain numeric spectral data in reports.
- [x] Generate an LLM-friendly `spectral_fingerprint.json/tsv` summary from scratch stems.
- [x] Add reference-audio surface analysis for loudness envelope, spectral balance, brightness, and onset-density targets.
- [x] Generate `state_mix_report.json/tsv/txt` so similar adaptive states are explicit.
- [x] Generate `dissonance_hotspots.json/tsv/txt` from expanded note events.
- [x] Add `dissonance_hotspots.md` plus timeline / layer-pair plots for human review.
- [x] Add `arrangement_audit` preflight reports for group prominence, bass collisions, and harmonic outliers.
- [x] Write `bundle_manifest.json` and `rerun_bundle.sh`.
- [x] Zip bundles on request with `--zip`.
- [x] Add `--zip-report` bundles that exclude OGG/WAV/NPY/MIDI binaries for chat/agent upload while leaving local audio generated.
- [x] Cap shared runtime stem gain by default so diagnostics cannot accidentally publish noise-lifted stems.
- [x] Rework Emmy after diagnostics showed a +47 dB shared gain requirement.
- [ ] Exercise the bundle command on a real cue with `pretty-midi` in a fully provisioned audio environment.
- [x] Re-run Emmy with `--runtime-stem-gain-mode shared` and compare runtime vs audition previews.
- [x] Re-space Emmy after dissonance audit showed accompaniment/lead clashes.
- [ ] Take a pass over active tunes whose diagnostics show huge master lift, capped shared gain, or quiet native stems.
- [ ] Decide whether to add a catalog-wide `bundle-reports` command after the per-cue `--zip-report` bundle proves stable.

### Phase 2: validation and provenance hardening

- [ ] Add a non-strict MusicIR compatibility loader that records warnings.
- [ ] Add schema/domain model notes before locking a Pydantic implementation.
- [ ] Add a normalized score JSON artifact that includes defaults and compatibility transforms.
- [ ] Report unknown YAML fields as warnings, not failures, in compatibility mode.
- [ ] Warn when a score pins `render.backend: fallback` without an explicit CLI override.
- [ ] Include SoundFont path/hash in the bundle manifest when available.
- [ ] Include renderer version and git revision in the bundle manifest.
- [x] Add note-event provenance: section, layer, instrument, group, bar/beat, pitch, velocity.
- [ ] Extend note-event provenance with motif ids and source chord/scale context.
- [x] Add a machine-readable spectral summary in addition to text logs.

### Phase 3: render graph consolidation

- [ ] Pick one canonical render graph for stems/full/preview generation.
- [ ] Demote `musicir_renderer.render_all()` or isolated rendering to a compatibility wrapper; avoid divergent semantics.
- [ ] Move backend code behind a clean backend interface.
- [x] Make preview mastering and runtime-style preview mastering explicit policy choices for isolated renders.
- [x] Stop representing normalized authoring previews as runtime-faithful `in_game_*` files.
- [ ] Gate or redesign full-preview normalization so near-silent raw mixes are reported before they become noisy masters.
- [ ] Add golden-structure tests for output manifests, not fragile golden waveform tests.

### Phase 4: catalog and game publishing

- [ ] Introduce an explicit music catalog source for game-facing tracks.
- [ ] Add `catalog validate` to verify every registered runtime track has a source score or intentional external source.
- [ ] Add `catalog sync-sandbox` or equivalent to update `sandbox.ron` safely.
- [ ] Preserve `first_goblin_tune_v2` full-section-mix compatibility until stem runtime is proven.
- [ ] Design Rust-side layered dynamic playback around buses/states/sections, not ad hoc files.
- [ ] Add a game-side debug HUD/log mode for active section/stem/state gains.

### Phase 5: MusicIR v2 design/migration

- [ ] Draft MusicIR v2 concepts before writing strict models.
- [ ] Promote buses/groups, exports, states, and debug policy to first-class schema fields.
- [ ] Provide a migration report for every active v1 cue.
- [ ] Port one cue to v2 and verify identical or intentionally changed behavior.
- [ ] Port the active catalog after compatibility tests pass.

## Current tests to keep passing

From repo root:

```bash
PYTHONPATH=tools/ambition_music_renderer pytest tools/ambition_music_renderer/tests
```

If audio dependencies are missing in the current environment, run the pure parser
and helper tests locally and execute the full render/bundle tests in the renderer
venv.

## Current first-iteration command examples

Render, debug, and zip an upload bundle:

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer cue bundle for_emmy_forever_ago \
  --backend pretty-midi \
  --force \
  --zip
```

Bundle an existing render without regenerating audio:

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer cue bundle for_emmy_forever_ago \
  --skip-render \
  --outdir tools/ambition_music_renderer/generated/for_emmy_forever_ago \
  --zip
```

Publish after rendering:

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer cue bundle for_emmy_forever_ago \
  --backend pretty-midi \
  --force \
  --publish \
  --zip
```

Include raw scratch stems only when the bundle is meant for local transfer rather
than chat upload:

```bash
PYTHONPATH=tools/ambition_music_renderer \
python -m ambition_music_renderer cue bundle for_emmy_forever_ago \
  --force \
  --zip \
  --include-scratch-stems
```


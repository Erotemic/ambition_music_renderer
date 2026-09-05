# Ambition music renderer

Author-time, data-driven music rendering for [Ambition](https://github.com/Erotemic/ambition).
This repository is normally checked out as the `tools/ambition_music_renderer`
submodule of the parent game repository.

Music is authored as compact MusicIR YAML. The renderer expands those scores
into MIDI/audio, applies instrument and mix processing, produces diagnostics,
and can explicitly publish generated assets into the consuming game. It is a
build/authoring tool, not a runtime generative-music system.

## Design contract

The durable rules are simple:

- **MusicIR YAML is the source of truth for music.** New cues and musical edits
  belong in scores, not cue-specific Python branches.
- **Renderer features are generic.** When a musical idea needs a capability
  MusicIR cannot express, add a reusable renderer/schema feature and test that
  feature independently of any one song.
- **Generated audio is disposable build output.** Commit scores, renderer code,
  tests, and reproducible configuration; keep generated OGG/WAV/MIDI/NumPy
  intermediates out of Git unless a task explicitly requires otherwise.
- **Composition comes before diagnostics.** Metrics can reveal clipping,
  buried stems, collisions, spectral imbalance, or broken transitions; they do
  not establish that a cue is catchy, expressive, or worth keeping.
- **Preview and runtime rendering should tell the same musical truth.** If the
  runtime path intentionally differs from the mastered review mix, make that
  difference explicit and auditable.
- **Publishing is consumer-declared.** The renderer does not guess the parent
  repository's crate or asset layout. The game supplies a destination with
  `AMBITION_MUSIC_PUBLISH_ROOT` or `--dest_root`.
- **Tests cover tooling, not individual songs.** A score can be a regression
  fixture when useful, but do not encode subjective song acceptance as a
  renderer unit test.

This README is the maintained documentation for the submodule. CLI Config
classes and `--help` are the source of truth for command-line flags. Historical
composition handoffs, machine-local instrument notebooks, and append-only task
logs do not belong in the live renderer documentation.

## Quick start

Commands below assume the usual parent checkout at `~/code/ambition`.

```bash
cd ~/code/ambition
source scripts/lib/asset_roots.sh

AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue list
```

### Lean composition render

For normal composition iteration, render the mastered full soundtrack and keep
extra audio products disabled:

```bash
cd ~/code/ambition
source scripts/lib/asset_roots.sh

AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle \
  <cue_id> \
  --backend=pretty-midi \
  --force \
  --render_audio_mode=simple-mix \
  --zip
```

The primary listening artifact is:

```text
generated/<cue_id>/latest/preview/<cue_id>_<hash>.full_soundtrack_preview.ogg
```

For fast score/form review in a MIDI player, export a MIDI preview separately:

```bash
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue midi <cue_id> --output /tmp/<cue_id>.mid
```

`render.metadata_markers` and section starts are written as Standard MIDI File
marker events, so players that expose MIDI markers can show the authored form.
The same markers are used as chapter metadata in rendered OGG previews.

`simple-mix` is the preferred starting point when judging composition. Add
more render products only when they answer a concrete debugging question.

For repeated A/B edits to one or two parts, enable the content-addressed stem
cache. The renderer hashes each *expanded* stem group's MIDI events, backend
configuration, and postprocess settings after score construction. Groups whose
render inputs are identical to an earlier sibling render are linked/copied from
the cache; only cache misses synthesize again. This is intentionally stricter
than comparing YAML blocks because shared humanization can make an earlier edit
perturb later note timing.

```bash
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle \
  <cue_id> \
  --backend=auto \
  --force \
  --render_audio_mode=simple-mix \
  --audition_stems \
  --stem_cache
```

With an explicit `--outdir`, the default cache is `<outdir-parent>/.stem_cache`,
so sibling variant directories share it. `--stem_cache_dir <path>` overrides
that location and also enables caching. The cache directory must stay outside
the render outdir because regeneration may remove the outdir. `--force` still
rebuilds the requested output directory but may satisfy content-identical stem
groups from an explicitly enabled cache.

A compact report archive can be requested independently:

```bash
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle \
  <cue_id> \
  --backend=pretty-midi \
  --render_audio_mode=simple-mix \
  --force \
  --zip_report
```

`--zip_report` omits OGG/WAV/NumPy/MIDI binaries. `--zip` creates the full
shareable bundle including manifest-referenced audio.

### Focused stem review

When the mastered mix reveals a balance problem, add full-length group audition
files without enabling the maximal runtime/audition preview set:

```bash
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle \
  <cue_id> \
  --backend=pretty-midi \
  --render_audio_mode=simple-mix \
  --audition_stems \
  --force \
  --zip_report
```

`--audition_stems` emits two full-length products per group. `review_stem_*`
keeps the version's relative stem level for cross-version recombination, while
`audition_stem_*` is normalized for comfortable solo inspection. The normalized
files are debugging artifacts, not evidence of runtime loudness.

### Standalone Stem Lab

Stem Lab is separate from the music review bank. It does not store ratings or
pairwise review decisions; it is a playback workspace for loading selected
render variants and routing each stem from a different version.

```bash
cd tools/ambition_music_renderer
./stem_lab.sh --cue <cue_id>
```

Only a small working set is loaded by default. Versions can be loaded/unloaded
from the on-disk library, an optional reference can be assigned, and each stem
can be routed from a different loaded version. A reusable bottom transport
provides start / play-pause / stop, scrubbing, and source switching while
preserving the playhead. A synchronized read-only piano roll visualizes the
expanded rendered notes and their section/bar timing. New renders retain an
immutable score snapshot and exact note-timeline artifact so that visualization
stays tied to the audio that produced it. See `docs/stem_lab.md` for the workflow
and the safety boundary for future editing.

## CLI map

The package exposes a modal CLI:

```bash
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer --help
```

The main command families are:

| Command | Purpose |
|---|---|
| `cue list` | List score ids discovered under `scores/`. |
| `cue render <cue>` | Render one cue without assembling a diagnostic bundle. |
| `cue bundle <cue>...` | Render, analyze, and package one or more cues. |
| `cue publish <cue>` | Publish the newest successful mastered preview. |
| `audit ...` | Inspect score structure, rendered audio, balance, pitch, transitions, and related diagnostics. |
| `plugins ...` | Inspect optional SFZ/LV2/VST3/CLAP infrastructure and validate score dependencies. |
| `radio ...` | Bulk convenience commands for the parent game's radio cue set. |
| `sandbox ...` | Legacy-named bulk preset for a small single-track cue set. |
| `legacy ...` | Quarantined helpers retained only until deletion safety is established. |

For one cue, `cue bundle -j/--jobs N` parallelizes stem-group rendering. For
multiple cue ids, `--jobs N` controls cue-level fan-out and `--render_jobs N`
controls per-cue stem workers.

Useful discovery commands:

```bash
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue bundle --help

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer audit --help

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins --help
```

## Interactive authoring tools

- `./review_music.sh` — existing render review/rating surface.
- `./stem_lab.sh` — cross-version stem routing and note inspection.
- `./instrument_inspector.sh` — standalone GM/SFZ instrument browser, full YAML-backed patch/effect editing, and disposable dry/processed probe auditioning.

The Instrument Inspector does not save MusicIR scores. It can load a score instrument as a starting point and export reusable YAML snippets, but applying those snippets to a composition remains an explicit separate step.

## Scores

Score lookup searches these directories in order as declared by `_paths.py`:

```text
scores/
  active/       current or candidate game cues
  examples/     reference scores and renderer examples
  archive/      intentionally retained historical scores
  experiments/  exploratory scores not promoted to active
```

`cue list --json` emits the discovered ids grouped by directory.

A score can be addressed by cue id or by YAML path.

## MusicIR overview

MusicIR is intentionally declarative. Common top-level fields include:

- `id` - cue identifier.
- `tempo` and `meter` - timing; `tempo.map` supports authored tempo changes.
- `render` - render/backend policy and renderer-specific settings.
- `postprocess` - final mix processing.
- `stem_postprocess` and `group_postprocess` - targeted mix processing.
- `constraints` - optional voicing constraints.
- `instruments` - named instruments, groups, MIDI controls, and optional
  per-instrument backend configuration.
- `motifs` - reusable pitch/rhythm material.
- `layer_templates` - reusable layer definitions.
- `playback` - loop/crossfade metadata.
- `state_map` - runtime states mapped to sections and stem weights.
- `sections` - ordered musical sections containing harmony and layers.

Current layer kinds are implemented in `render/score_layers.py`:

- `pad_chords`
- `arpeggio`
- `ostinato`
- `bassline`
- `motif`
- `chord_hits`
- `drums`
- `texture`
- `pedal`
- `root_hits`
- `guitar_strum`
- `guitar_chug`
- `sampled_chord`
- `guitar_lead`
- `notes`
- `automation`

`notes` is the literal-event escape hatch when a composed phrase is clearer as
explicit events than as a generative layer. Note-producing layers can use
phrase-level `dynamics`; layers can also carry CC automation. Guitar layers use
a small performance compiler for string assignment, strum staggering, chugs,
lead scoops, and explicit double-take authoring.
`sampled_chord` is for libraries that record a complete chord behind one root
key: it emits a classified keyswitch followed by exactly one root note, so it
must not be fed through ordinary chord voicing expansion. The switch is scheduled
before the humanized attack and released first; `keyswitch_lead_ms` (default 10)
and `keyswitch_duration_ms` (default 5) can tune that control pre-roll for a
library that needs a longer setup interval.

Prefer the highest-level construct that expresses the musical idea cleanly.
Use literal notes when they make the composition more legible, not as a signal
that the renderer needs another one-off algorithm.

## Rendering and instrument backends

The top-level render backend choices are:

| Backend | Role |
|---|---|
| `pretty-midi` | Preferred local render path using the configured SoundFont/FluidSynth stack. |
| `fluidsynth-cli` | FluidSynth command-line backend. |
| `fallback` | Built-in synthetic fallback for diagnostics and constrained environments. |
| `auto` | Renderer-selected fallback policy; use when fallback is acceptable. |

Per-instrument backends are separate from the top-level backend. An instrument
can request an SFZ/sample path or the built-in procedural FM synth while other
instruments in the same cue continue through the normal backend.

### SFZ instruments

Per-instrument SFZ configuration is resolved through `instrument_backend`.
Useful fields include `sfz`, `library_ref`, `prefer`, optional library roots,
and backend settings. Run plugin validation before depending on machine-local
sample libraries:

```bash
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins doctor

AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins list_sfz_libraries

AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins validate_score <cue_id>

# Render the real-library probes used before assigning a sampled instrument to
# a cue. This writes a machine-local JSON report; it does not modify a score.
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins smoke_sfz \
  --output /tmp/ambition-sfz-smoke.json
```

`plugins smoke_sfz` exercises the Emily, Black & Green, Shinyguitar, Growly,
Swag, Black & Blue, Fashionbass, Pastabass, Gogodze, Big Rusty, Naked Drums,
and Muldjord entry points. Its report includes recursive include/sample checks,
actual playable ranges and keyswitch ranges, startup CC state, per-probe
duration/RMS/peak/silence, low/mid/high velocity, repeated-strike, and explicit
keyswitch behavior, plus pitch error/confidence for pitched instruments. The probe
explicitly disables octave folding. `render_status`/the backward-compatible
`status` field answer whether the probes produced audio; `validation_status` is
stricter and reports `PITCH_UNRELIABLE` when a pitched library rendered but the
pitch measurement is not yet trustworthy. Top-level `ok_count` counts renderable
rows and `validated_count` counts rows that also passed the requested validation.

For deeper source audits, `ambition_music_renderer.audit.sfz_measurement` is a
reusable Python API. `sfz_regions` and `select_regions` expose effective
included-region/sample provenance, `raw_pitch_diagnostic` compares expected F0
with half- and double-frequency competitors, and `repeat_variation` measures
normalized attack-shape differences across repeated strikes.

#### Installed-library truth and remote handoffs

Library aliases and downloader entries describe instrument families the renderer
knows how to use; they are **not evidence that those libraries are installed on
the current machine**. The actual SFZ collection lives under the machine-local
`AMBITION_AUDIO_TOOLS_ROOT` (normally `/data/audio-tools`) and is intentionally
separate from the source tree. A source archive by itself therefore cannot tell
a local or remote agent which optional instruments are really available.

Treat these generated machine-local reports as the source of truth after running
`download_ambition_audio_tools.sh` or otherwise updating the audio-tools tree:

- `/data/audio-tools/SFZ_LIBRARY_SUMMARY.txt` - complete installed `.sfz` path list.
- `/data/audio-tools/REFERENCE_SFZ_LIBRARY_REPORT.txt` - reference-library inventory.
- `/data/audio-tools/SFZ_USAGE_CENSUS.json` - generated trigger/controller/keyswitch/sample metadata for remote agents and Instrument Inspector.
- `/data/audio-tools/SFZ_USAGE_CENSUS.md` - human-readable usage-census companion.
- `plugins list_sfz_libraries --json` - live resolver view, including `alias_hits`.
- `plugins validate_score <cue_id>` - final check that a score's requested roles resolve.

Generate the usage census after installing or changing SFZ libraries:

```bash
cd tools/ambition_music_renderer
./instrument_usage_census.sh
```

See `docs/instrument_usage_census.md` for the schema and handoff guidance.

For a remote/online-agent handoff, attach or paste `SFZ_LIBRARY_SUMMARY.txt` (or
the relevant filtered lines) alongside the source archive. An agent that only
has the repository/source archive must not infer installation from
`instrument_libraries.py`, the downloader catalog, aliases such as
`guitar.acoustic_warm`, or documentation examples. Those describe supported or
desired libraries, not machine state.

For example, to inspect installed guitar entry points without dumping thousands
of SFZ helper files:

```bash
grep -Ei \
  'guitar|acoustic|12.?string|twelve.?string|dread|jumbo|moonbeams' \
  /data/audio-tools/SFZ_LIBRARY_SUMMARY.txt
```

When selecting a patch from that output, prefer human-facing entry points such
as `Programs/*.sfz`. Paths under `modules/`, `includes/`, `maps_*`, or similar
implementation directories are usually building blocks for a top-level program,
not standalone instruments. Confirm the chosen entry point in the next bundle's
`instrument_resolution` report.

By default, optional per-instrument backend failures warn and fall back instead
of silently dropping a noted instrument. Set `render.strict_backends: true`
when a requested backend must succeed or fail the render.

### Procedural FM instruments

The renderer includes a generic oscillator-level FM path for timbres that are
awkward to express with General MIDI or SoundFonts. It is selected per
instrument:

```yaml
instrument_backend:
  kind: procedural_fm
  carrier:
    waveform: saw
    harmonics: 10
  fm:
    waveform: sine
    ratio: 0.25
    index: 0.10
  envelope:
    attack_ms: 6
    decay_ms: 70
    sustain: 0.85
    release_ms: 100
  saturation_drive: 1.15
  output_gain_db: -6
```

The procedural FM path is a reusable synth primitive, not a cue-specific hook.
Improve it generically if a composition exposes a real missing capability.

## Mix and effects

MusicIR separates musical authoring from mix stages:

- `stem_postprocess` controls named stems.
- `group_postprocess` controls instrument groups.
- `postprocess` controls the completed mix.

The built-in processing path covers common gain/filter/dynamics/reverb/width
operations. Optional external processing is expressed through ordered
`effect_chain` steps rather than parallel legacy effect lists. The Pedalboard
adapter exposes `gain`, `distortion`, `clipping`, `bitcrush`, `resample`, filters,
dynamics, modulation, delay/reverb, and VST3 hosting. Nonlinear chains should
use explicit gain staging when the rendered source is too quiet to drive the
nonlinearity directly. Individual Pedalboard effects may set `wet_mix: 0..1`
for deterministic parallel wet/dry blending even when the underlying plugin
does not provide its own mix control.

Any top-level `effect_chain` step may also set `wet_mix: 0..1`. This is useful
for LV2/VST/external processors whose native control surface has no dry/wet
parameter: the renderer processes the full step, then blends it against the
step input. LV2 steps may set `channel_mode: dual_mono` to run a mono pedal
independently over the left and right channels before returning stereo. The
LV2 adapter understands both `lv2proc`'s `-c port:value` controls and Lilv
`lv2apply`'s `-c port value` controls; set `binary: lv2apply` when a score wants
the Lilv host explicitly.

Set `report_levels: true` (and optionally `label`) on a Pedalboard chain to emit
per-effect RMS/peak levels and `shape_change_db` into the render stderr report.
`shape_change_db` measures the residual after removing the best scalar-gain
match between the effect input and output: very negative values mean the step
mostly changed level, while values closer to 0 dB mean the waveform/timbre was
materially reshaped. This makes both gain-staging mistakes and ineffectual
"distortion" settings visible before final normalization. The plugin commands
expose locally available VST3/LV2/CLAP infrastructure.

When changing balance, inspect rendered stems rather than trusting authored MIDI
volume or score gain values as proxies for perceived loudness. Different sample
libraries and synth paths can have very different native levels.

Prefer orchestration, register, rhythm, and texture for musical contrast. Use
gain riding when necessary to keep section playback level coherent; do not use
mastering or extra layers to disguise weak composition.

## Render audio modes

`cue bundle --render_audio_mode=...` controls how much audio the underlying
isolated renderer exports:

| Mode | Audio scope |
|---|---|
| `simple-mix` | Mastered full soundtrack preview only. Best default for composition iteration. |
| `full-mix-only` | Mastered full preview plus adaptive per-section full mixes; skips per-stem OGG export. |
| `full` | Full adaptive export, including per-stem/state review products. Use when those assets are actually needed. |

`--audition_stems` is orthogonal to those modes and adds one normalized
full-length audition OGG per rendered stem group.

Spectrogram generation is **off by default**. Enable `--spectrograms` for a
specific visual investigation. The heavier diagnostic set is also opt-in with
`--all_audits`. Full audits are render-product aware: with `simple-mix`,
score/static audits plus scratch-stem and mastered-preview spectral audits still
run, while adaptive-section balance/transition audits are recorded as
intentionally skipped because that mode does not export per-section OGGs. Use
`full-mix-only` when section-full transition/mastering audits are required, or
`full` when audits need per-section stem audio.

## Generated layout and bundles

Default generated renders are content-versioned:

```text
generated/<cue>/
  building -> .versioned/<hash-being-built>/
  latest   -> .versioned/<latest-successful-hash>/
  .versioned/<hash>/
    preview/
    adaptive/          # when requested by render mode
    reports/
    plots/             # when requested
    <cue>_<hash>.adaptive_manifest.json
```

`building` exists only while the default generated run is in progress. `latest`
points at the newest successful run. Explicit `--outdir` paths are respected as
given and do not use the versioned layout.

`cue bundle` also assembles a shareable bundle under the renderer's gitignored
`agent/` drop-zone by default. The bundle contains the normalized score,
manifest, reports, requested plots/audio, and a rerun script.

Useful bundle switches:

- `--zip` - complete bundle archive, including copied audio.
- `--zip_report` - compact report archive with binary audio/intermediates
  excluded.
- `--include_scratch_stems` - include raw NumPy scratch stems when a low-level
  rendering problem requires them.
- `--spectrograms` - generate spectrogram plots.
- `--all_audits` - run the heavier diagnostic set.
- `--skip_render` - analyze/package an existing render directory.

## Audits

Audits support composition and implementation review; they do not replace
listening. Discover exact arguments with `--help`.

```bash
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer audit arrangement --help

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer audit cue_balance --help

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer audit transition --help
```

Current audit families include arrangement, dissonance, lead collision, mix
balance, pitch stability, reference-audio surface analysis, shrill-note and
sour-note checks, cue balance, level reporting, spectral comparison/localizing,
and transition analysis.

A good debugging order is:

1. listen to the mastered full soundtrack preview;
2. decide whether the problem is composition, orchestration, timbre, or mix;
3. inspect only the reports/stems relevant to that hypothesis;
4. change the score or a generic renderer capability;
5. render again and listen before escalating to heavier diagnostics.

Do not declare a cue successful because it has a small RMS spread, many
automation events, irregular onset statistics, or a clean audit. Those are
implementation signals, not musical verdicts.

## Publishing into Ambition

Rendering is local staging. Publishing is explicit.

The renderer deliberately contains no hard-coded consuming crate name. From the
parent Ambition checkout, source the game's asset-root declaration before using
a publish command:

```bash
cd ~/code/ambition
source scripts/lib/asset_roots.sh

AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer cue publish <cue_id>
```

Equivalent render-and-publish workflows can use `cue render --publish`,
`cue bundle --publish`, or the bulk `radio` commands. Outside the parent helper
script, set `AMBITION_MUSIC_PUBLISH_ROOT` or pass `--dest_root` explicitly.
Publishing without a declared destination is an error by design.

If `preview/published.ogg` exists for a generated cue, `cue publish` treats it
as a manual pin; otherwise it selects the newest matching mastered full
soundtrack preview.

## Optional audio tools and plugins

Python dependencies are declared in `pyproject.toml`. Additional audio tools
and sample/plugin collections can be rooted with `AMBITION_AUDIO_TOOLS_ROOT`.
SFZ rendering, LV2 processors, Guitarix/NAM-style command adapters, VST3 hosts,
and similar facilities are optional and are probed only when a score requests
them.

Useful checks:

```bash
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins doctor

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins list_vst3

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins list_lv2 --limit=40
```

Keep machine-specific inventory contents out of this README; hand them to local
or remote agents through the generated inventory reports described under
**Installed-library truth and remote handoffs**. If an instrument library needs
a durable workaround, encode the resolution/fallback behavior in the generic
library tooling and cover it with a tooling test.

## Package map

```text
ambition_music_renderer/
  cli.py                  modal CLI and bulk orchestration
  _paths.py               score/generated/publish path contract
  render/                 MusicIR expansion, rendering, mix/export, bundles
  audit/                  score/audio diagnostics exposed by the CLI
  backends/               optional sample/plugin adapters
  legacy/                 quarantined helpers awaiting deletion decisions
scores/
  active/
  examples/
  archive/
  experiments/
tests/                     renderer/tooling tests
```

High-value implementation entry points:

- `render/score_layers.py` - MusicIR layer dispatch and score construction.
- `render/score_core.py` / `render/score_events.py` / `render/score_theory.py` -
  shared score semantics.
- `render/group.py` - group/instrument routing and backend fallback behavior.
- `render/synth.py` - SoundFont/fallback/procedural synthesis.
- `render/effects.py` - built-in and external effect processing.
- `render/isolated.py` - adaptive/full soundtrack render entry point.
- `render/bundle_options.py` - shared `cue bundle` option contract.
- `render/bundle.py` - render + diagnostics + shareable bundle workflow.
- `audit/*.py` - current audit implementations and their kwconf CLI schemas.

## Validation

Run tooling tests from the parent repository:

```bash
cd ~/code/ambition
uv run --project tools/ambition_music_renderer \
  pytest -q tools/ambition_music_renderer/tests
```

For a focused procedural-FM change:

```bash
cd ~/code/ambition
uv run --project tools/ambition_music_renderer \
  pytest -q tools/ambition_music_renderer/tests/test_procedural_fm.py
```

Before committing renderer changes:

```bash
cd ~/code/ambition
git -C tools/ambition_music_renderer diff --check
```

When a score depends on optional local infrastructure, also run:

```bash
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer plugins validate_score <cue_id>
```

## Maintaining this README

Keep this file aligned with the code that owns each contract:

- CLI flags: `cli.py`, `render/bundle_options.py`, and the audit/plugin Config
  classes.
- MusicIR layer kinds: `render/score_layers.py`.
- instrument routing: `render/group.py` and `render/synth.py`.
- generated layout: `render/generated_layout.py` and `render/isolated.py`.
- bundle contents: `render/bundle.py` and `render/bundle_archive.py`.
- publish semantics: `_paths.py` and the parent Ambition asset-root helper.

When behavior changes, update the owning code and this README in the same
change. Prefer deleting obsolete instructions to accumulating contradictory
historical guidance.

# Ambition music renderer architecture and roadmap

This document is the recovery point for the music-renderer architecture campaign.
Read it before making a cross-cutting change to MusicIR, instruments, generators,
render currentness, processing, or DAW interchange.

The project has two immediate product goals:

1. **Existing MusicIR v1 and v2 scores must remain regenerable from source.**
   They are not migration backlog. Their original source files are durable inputs
   for rebuilding game assets from scratch.
2. **New music should be pleasant for agents to author in MusicIR v3.** V3 should
   combine concise musical intent with an exact-event escape hatch, checked-in
   knowledge of the expected audio environment, and objective review evidence.

DAW round-trip work was reprioritized on 2026-09-07. The active order is a
DAW-neutral reconciliation core first, then Ardour-first workflow integration;
REAPER is the secondary DAW target. MusicIR remains the sole musical source of
truth throughout the round trip.

A future polished replacement for a v1/v2 tune is expected to be a new v3
composition, potentially with a different arrangement and sonic realization.
That does not require converting or deleting the original score.

## Non-negotiable compatibility contract

Do not remove v1 or v2 compilation merely because v3 can express the same final
notes. Existing scores must continue to compile through the canonical
`CompiledScore` boundary and render through the current backend architecture.

A refactor that touches shared compilation/rendering code should keep the
following gates available:

- generic frozen v1/v2 synthesis-contract fixtures;
- deterministic dependency-free PCM equivalence where applicable;
- whole-corpus compile/semantic comparison for broad compiler changes;
- render dependency/currentness tests when resource identity changes;
- the historical `build_score()` interception point until its compatibility
  tests and consumers are deliberately retired.

V1/v2 source syntax may be documented as legacy authoring syntax, but it is
**supported input syntax**, not deprecated data waiting to be rewritten.
Unknown-schema fallback and other compatibility quirks can eventually be made
stricter only through an explicit compatibility decision with corpus evidence.

## Architectural spine

The intended architecture is:

```text
MusicIR source
  |-- v1 procedural frontend (legacy scores, preserved)
  |-- v2 exact frontend      (legacy/exact scores, preserved)
  `-- v3 authoring graph     (new music)
             |
             v
      CompiledScore
             |
             +--> instrument resolution
             |       |
             |       v
             |  InstrumentResolutionPlan
             |
             +--> rendering / stems / processing
             +--> audits / timeline / inspector
             +--> cache and RenderDependencyFingerprint
             `--> DAW interchange
```

V3 has one additional semantic layer because it intentionally preserves
composition intent that disappears when the music is expanded:

```text
v3 YAML
   |
   v
NormalizedScoreGraph
   |-- exact clips/materials
   |-- generator clips
   |-- clip transforms + explicit techniques
   |-- key/harmony-relative pitch intent
   |-- controller/pitch-bend points and curves
   |-- composable sequence materials
   |-- form energy/density intent
   `-- stable source/provenance ids
   |
   v
CompiledScore
```

`NormalizedScoreGraph` answers "what did the composer ask for?".
`CompiledScore` answers "what exact notes, controllers, instruments, clock and
form are being handed to rendering?". They should not be collapsed into one
object.

## Current single-authority map

### Music compilation

`ambition_music_renderer.musicir.compile.compile_score()` is the canonical
MusicIR-to-renderer boundary. Shared consumers should accept `CompiledScore`
rather than dispatching on source schema or rereading raw YAML.

`CompiledScore` owns the canonical synthesis/form contract. PrettyMIDI remains
an internal synthesis representation during the migration. Its private
`_ambition_*` attributes and the tuple-returning `build_score()` API are
compatibility surfaces, not new extension points.

### V3 authoring graph

`musicir.graph.NormalizedScoreGraph` is the semantic source representation for
new v3 authoring. Stable score/part/voice/clip/event ids belong here. Those ids
are provenance, not musical inputs: renaming a clip may change the authoring
fingerprint but must not change the compiled-music fingerprint or generator
randomization.

### Expected instruments

`ambition_music_renderer/data/instrument_catalog.yaml` is the normative,
checked-in authoring contract for the standard Ambition sample environment. It
tells an agent what stable `library_ref` identities are expected to be
available after `download_ambition_audio_tools.sh`, how to request them, and
important patch/library nuances.

Missing catalog instruments on a normal workstation are setup defects. A
source-only agent should author against the catalog rather than avoiding a good
instrument because its own container does not have `/data/audio-tools`.

### Observed maintainer workstation

`ambition_music_renderer/data/audio_environment_snapshot.json` is a second,
deliberately different checked-in artifact. It records **what was actually
observed on the maintainer workstation at its capture time**:

- analyzed SFZ programs and useful parsed capabilities;
- stable alias resolutions;
- SoundFonts;
- CLAP/LV2/VST3 bundles;
- census health/count metadata.

It is plain JSON and can be read with the Python standard library or by any
agent directly from source. The compact reader is:

```bash
python -S dev/read_audio_environment_snapshot.py summary
python -S dev/read_audio_environment_snapshot.py aliases
python -S dev/read_audio_environment_snapshot.py soundfonts
python -S dev/read_audio_environment_snapshot.py plugins
python -S dev/read_audio_environment_snapshot.py emily
```

This snapshot is **observational**, not the supported-vocabulary authority. The
instrument catalog says what the standard environment is supposed to provide;
the snapshot records what the user's workstation was seen to contain. The live
`/data/audio-tools/SFZ_USAGE_CENSUS.json` remains the richest current-machine
evidence when a process actually has access to that disk.

Refresh the checked-in snapshot after materially changing the workstation audio
tree:

```bash
python -S dev/update_audio_environment_snapshot.py
```

The updater is stdlib-only. It intentionally strips the giant per-sample census
payload and rewrites workstation-root paths into portable relative paths. The
full machine census should not be copied into source control.

### Instrument realization

`instrument_resolution.py` owns compatibility spellings and the translation of
a stable instrument request plus a concrete machine environment into an
`InstrumentResolutionPlan`. Renderer, audits, inspector and cache logic should
consume that plan rather than independently searching SFZ filenames.

### V3 generator vocabulary

`ambition_music_renderer/data/generator_catalog.json` is the checked-in public
v3 generator registry. It owns:

- public names such as `harmony.arpeggio` and `guitar.strum`;
- the established v1 bridge implementation used today;
- whether harmony is required;
- accepted public parameters and defaults;
- concise descriptions, examples and implementation notes.

The v3 compiler validates `generate:` mappings against this catalog. It is not
merely documentation. A parameter absent from the catalog is not part of the
public v3 generator surface even if an older internal layer function happens to
accept it. Every checked-in generator example is compiled by a generic contract
test, so agent-facing examples are executable syntax rather than illustrative
pseudocode.

The package CLI exposes the same registry:

```bash
python -m ambition_music_renderer generators list
python -m ambition_music_renderer generators describe harmony.arpeggio
python -m ambition_music_renderer generators schema harmony.arpeggio
```

A source-only agent with no installed dependencies can read the JSON directly
or use:

```bash
python -S dev/read_generator_catalog.py list
python -S dev/read_generator_catalog.py describe guitar.strum
python -S dev/read_generator_catalog.py schema harmony.arpeggio
```

Bridge targets are tested against the established v1 `LAYER_RENDERERS`
implementation registry. Do not create a second v3 arpeggiator, guitar player,
drum sequencer, etc. merely to expose it under v3.

### Processing/effect vocabulary

`ambition_music_renderer/data/processing_catalog.json` is the checked-in public
processing authority. `processing.catalog` loads it; validation, plugin dispatch,
inspector templates, and source-only tooling consume the same names/metadata.
New v3 music should author explicit `processing:` chains. Historical flat
postprocess fields remain supported only through `processing.legacy`.

`processing.model.ProcessingPlan` is the normalized static DSP contract and
`processing.pipeline.apply_processing_plan()` is the execution boundary. Do not
add another table of effect aliases/defaults in a backend or GUI.

### Mastering policy and signal flow

`processing.mastering` owns the adaptive mastering policy and the distinction
between canonical pre-master section-bus processing and historical section-local
post-mastering. New v3 music defaults to `composition_master`; v1/v2 without an
explicit policy retain `legacy_section_postprocess` so old assets remain
regenerable. `render.isolated.adaptive_section_mastering_config()` is a
compatibility/reporting facade over this authority.

### Render currentness

`render.dependencies` owns static resource identity for rendered audio. The
render dependency fingerprint includes the compiled musical contract, resolved
sample/program dependencies, relevant processing resources, renderer source,
and relevant runtime/tool identity.

Do not return to a manually incremented renderer-version string as the cache
correctness mechanism. Do not hash all of `/data/audio-tools` as a shortcut;
only dependencies used by the cue should invalidate that cue/stem.

### DAW interchange (active staged round trip)

`musicir.interchange` owns exact-MIDI export and sidecar construction;
`musicir.interchange_reconcile` owns the reverse comparison/apply path. Exact
Standard MIDI is editable transport and the `.musicir-interchange.json` sidecar
preserves MusicIR source/provenance that MIDI cannot carry portably.

The reverse path compares edited performance against the saved baseline, rescales
DAW PPQ changes, and updates the smallest currently supported v3 source region:
one affected clip. Material/generated clips are lowered to exact events only when
that clip was hand-edited. DAW project files remain convenience surfaces rather
than another source of truth.

## V3 authoring model: current status

V3 is intended for **new music now**, while continuing to expand its high-level
vocabulary.

Currently supported:

- exact score clock with PPQ, meter maps, tempo maps, form and score end;
- exact events inline in clips;
- reusable exact event materials;
- v1-style motif material through the `melody.motif` generator;
- exact and generated clips in the same part/voice;
- stable source ids and compiled note provenance;
- score-level key/mode context, harmony progressions and exact harmony-change events;
- registered procedural generators backed by established v1 implementations;
- repeat placement and sequence materials composed from reusable event materials;
- common clip transforms applied after expansion to both exact and generated
  material: transpose, octave, velocity scale/offset, gate and time scale;
- explicit pitch expressions: absolute note/MIDI, semitone-relative,
  harmony-root, chord-tone, scale-degree, named GM percussion and guitar
  string/fret coordinates;
- backend-independent techniques/articulations with explicit gate semantics;
- clip-local CC and pitch-bend automation points **and deterministic curves** with stable provenance;
- form-level energy/density intent consumed by procedural clips;
- typed/ranged generator metadata and opt-in variation controls for drums, arpeggios and bass;
- exact-clock MIDI/sidecar export retained as a deferred interoperability seam.

Current generator bridge restriction: established v1 generators expand in a
fixed-tempo/fixed-meter local model, so a v3 generated clip must currently stay
inside a constant tempo/meter region and start on a bar boundary. Exact clips
have no such limitation. A later clock-domain generator migration can remove
this restriction without changing v3 source concepts.

## Roadmap

The ordering below favors getting agents productive in v3 while keeping old
assets reproducible. It intentionally does **not** include a campaign to convert
existing v1/v2 songs.

## Campaign progress map

The numbered product roadmap and the lettered implementation sections below now
line up as follows:

1. **V3 semantic vocabulary** — second major pass implemented: techniques,
   curves, key context, sequence materials, and form intent are available.
2. **Generator registry/introspection** — second major pass implemented: the
   checked-in catalog is executable, source-only readable, typed/ranged, and
   carries capability metadata.
3. **Validation and diagnostics** — first major pass implemented. V3 authoring
   mistakes now produce structured codes, YAML source paths, line/column
   coordinates, and repair hints before compilation where possible.
4. **Expansion/provenance inspection** — first major pass implemented. Read-only
   graph/expand/event-trace tools connect v3 source intent to compiled events,
   exact harmony context, and canonical instrument realization.
5. **Processing/effect authority** — first major pass implemented; one checked-in catalog and `ProcessingPlan` now own the static processing vocabulary.
6. **Mastering/signal-flow consolidation** — first major pass implemented; v3 uses one composition master while legacy v1/v2 section behavior remains available for regeneration.
7. **V3 completion follow-up** — explicit techniques, automation curves, score
   key context, sequence materials, and shared form energy/density are implemented.
8. **Generator capability hardening** — typed/ranged contracts plus opt-in drum,
   arpeggio, and bass variation controls are implemented; deeper musical behavior
   remains an ongoing composition-driven task.
9. **Instrument authoring knowledge/auditions** — checked-in family guidance,
   a derived source-only authoring index, and canonical v3 audition scores exist.
10. **Quality/regression evidence** — composition-quality reports, before/after
    audio comparison, deterministic-compilation checks, and render-manifest
    composition evidence are implemented.
11. **V3 new-composition workflow** — a packaged starter and multiple executable
    teaching scores exist; v3 is the default for new composition.
12. **Permanent legacy regeneration gate** — the complete committed legacy
    corpus is compiled as a smoke gate; generic frozen migration fixtures plus
    explicit pre/post corpus reports protect semantic behavior without checking
    named-song snapshots into the test suite.
13. **DAW note/controller round trip** — edited MIDI can be reconciled against
    an exact export baseline; note and clip-owned CC/pitch-bend edits can be
    applied by lowering only affected v3 clips, with recompilation verification.
14+. **Conductor round trip, Ardour integration, real cue authoring,
    generator/instrument improvement, legacy-internal isolation, and module
    decomposition** remain active work. Ardour is the primary DAW target; REAPER
    is secondary.

### Phase A — Permanent legacy regeneration gate

Status: established; maintain continuously. `dev/check_legacy_regeneration.py`
compiles the complete committed legacy corpus from source. Generic frozen
renderer fixtures remain the checked-in semantic contracts. For a broad compiler
refactor, use the script's optional JSON report on both the pre-change and
post-change trees and compare those reports as review evidence rather than
committing named-song snapshots.

Goals:

- all committed v1/v2 cues continue compiling;
- shared compiler/render refactors demonstrate semantic stability;
- dependency/resource changes invalidate the right generated assets;
- original source scores remain buildable even after v3 becomes the normal
  authoring language.

Future cleanup may isolate v1/v2 implementation code more cleanly, but it must
not remove the frontends required to regenerate assets.

### Phase B — Agent-ready v3 semantic vocabulary

Status: second major pass implemented. Common transforms, explicit pitch
semantics, score key/mode context, exact harmony resolution, explicit techniques,
exact automation points, deterministic automation curves, and composable sequence
materials are implemented. Form regions can carry bounded energy/density intent
that procedural clips consume without affecting literal clips.

Remaining high-value work is composition-driven rather than schema-blocking:

1. map more technique intent to instrument-specific keyswitch/controller/alternate
   patch realizations as the checked-in catalog gains reliable patch knowledge;
2. add common transforms only when they generalize cleanly to exact and generated
   material; avoid turning YAML into an unrestricted programming language;
3. enrich harmonic/function notation only when real compositions demonstrate a
   concise authoring benefit over key context plus chord-symbol timelines;
4. improve generator musical behavior rather than expanding source syntax merely
   for theoretical completeness.

Completion condition: an agent can write a polished cue with normal form,
harmony, melody, accompaniment, drums, expressive dynamics and specialized
instrument techniques in v3 without expanding ordinary musical intent into a
large literal MIDI dump. Literal events remain the escape hatch for passages
where exact notes are clearer.

### Phase C — Generator capability registry and introspection

Status: second major pass implemented.

The checked-in generator catalog now defines public names, bridge targets,
parameter types/ranges/enums, timing/harmony capabilities, deterministic behavior,
and executable examples. The validator consumes those contracts. Opt-in musical
controls now let arpeggios vary velocity/register by step, bass vary dynamics by
step/bar, and drum patterns vary bar dynamics and schedule periodic fills.

Continue by improving musical intelligence from real composition evidence:

1. richer drum transitions, fills, cymbal logic and section-aware density;
2. more guitar phrasing/fretboard/articulation behavior;
3. stronger bass/drum locking and approach-note behavior;
4. harmony/voice-leading and melody-development generators;
5. moving established generators to exact score-clock output when that removes
   the current tempo/meter bridge restriction;
6. preserving one public registry throughout those changes.

Completion condition: a source-only agent can discover every supported v3
generator, know how to invoke it, validate its parameters, and understand its
important musical limitations without reading implementation code.

### Phase D — Validation + expansion/provenance diagnostics

Status: first major pass implemented.

Source validation now runs v3-specific authoring checks before canonical
compilation and reports structured diagnostics with stable codes, semantic YAML
paths, one-based line/column coordinates, and targeted repair hints. The compiler
remains the semantic authority: restrictions that only become knowable while
lowering are wrapped as a compile diagnostic rather than duplicated in a second
semantic implementation.

Primary validation surface:

```text
cue validate <score>
cue validate <score> --json
```

The first inspection surfaces are also implemented:

```text
cue graph <score>
cue expand <score> [--clip ID]
cue trace_event <score> <event-id>
```

`musicir.inspect` consumes `CompiledScore`, `NormalizedScoreGraph`, and the
canonical `InstrumentResolutionPlan`. It does not reconstruct event generation or
instrument selection. Expansion reports source clip/material/generator, common
transforms, exact harmony at compiled event ticks, expanded notes/controllers,
and current instrument realization. Event tracing walks one stable provenance id
back to its source event/material/generator and forward to the realized
instrument. Graph inspection keeps composition structure unexpanded.

Remaining improvements are incremental rather than blockers for v3 authoring:

- add source spans/end columns if an editor integration needs them;
- increase typed/ranged generator metadata as established implementations gain
  explicit contracts;
- add optional machine-readable graph formats (for example DOT) if they prove
  useful;
- carry source-file locations into DAW sidecars if round-trip UX benefits from
  opening the exact YAML location;
- keep new diagnostics generic and renderer-oriented rather than adding tests or
  rules for named songs.

See `docs/musicir_diagnostics.md` for the diagnostic/inspection contract.

### Phase E — Processing/effect authority

Status: first major pass implemented.

`data/processing_catalog.json` is now the public processing authority. It owns
processor/backend aliases, parameter metadata/defaults, automation capability,
and inspector templates. `ProcessingPlan` is the normalized stage contract and
`processing.pipeline` is the execution boundary. Legacy flat postprocess fields
compile through one compatibility translator; renderer/group workers, plugin
dispatch, validation, inspector templates, render dependency scanning, and stem
cache planning consume the shared vocabulary/plan architecture. Source-only
agents can inspect the catalog with `dev/read_processing_catalog.py`.

Remaining work is incremental: add DSP parameter automation only after a
deterministic cross-backend contract exists, enrich parameter enums/types where
plugins have stable contracts, and add new processors through the one catalog.

### Phase F — Mastering and signal-flow consolidation

Status: first major pass implemented.

The canonical full-mix path is now explicit:

```text
synthesis
 -> processed stem groups
 -> section/stem mix gain + foreground protection
 -> native composition sum
 -> optional canonical section-bus processing
 -> one composition master
 -> mastered timeline
 -> soundtrack/loops/adaptive slices
```

New v3 music defaults to `composition_master`; adaptive full-section assets are
literal slices of the one mastered timeline. Canonical `processing.sections` is
pre-master. V1/v2 without an explicit policy retain historical
`legacy_section_postprocess` behavior, preserving regeneration. Historical
`global_master_slices` / `section_postprocess` spellings remain accepted.

Render manifests record master/section processing plans, policy decisions, and
signal-flow regression metrics. Generic tests pin representative legacy PCM and
section-master behavior. See `docs/processing_architecture.md`.

Remaining work should be sonic improvement rather than authority cleanup: tune
master presets from listening evidence, add optional LUFS comparison reports,
and improve section-bus transition treatment if real compositions need effects
with tails across boundaries.

### Phase G — Instrument authoring knowledge and canonical auditions

Status: first major pass implemented.

`data/instrument_family_profiles.json` adds conservative family-level writing
knowledge and `data/instrument_authoring_index.json` is a derived plain-JSON view
combining that guidance with every stable catalog ref. `instrument_authoring.py`
can generate one canonical v3 comparison phrase for every catalog instrument;
the generic test suite compiles all 73 auditions. Source-only readers can join
normative catalog knowledge with the observational workstation snapshot without
merging their authorities.

Continue by adding patch-specific reliable ranges, articulation realization,
weak/silent zones, and family audition phrases only when supported by census,
smoke-test, or listening evidence.

### Phase H — Composition quality and audio-regression evidence

Status: first major pass implemented.

`cue quality` reports canonical note density, section/group dynamics, pitch
ranges, recommended-register excursions, register overlap, and repeated-bar
evidence. It deliberately does not produce a scalar taste score. Render manifests
carry the same deterministic composition evidence.

`audio compare` reports before/after peak, RMS, optional LUFS, crest factor,
spectral balance/centroid, stereo width/correlation, waveform correlation, and
aligned difference magnitude. Use this when a change intentionally improves the
sound and exact PCM equality is therefore the wrong gate.

`cue determinism` independently recompiles a score and verifies stable canonical
fingerprints/events. Extend these reports with measurements that provide useful
revision evidence; do not make heuristics an authority on musical taste.

### Phase I — V3 new-composition workflow

Status: usable now.

A packaged, dependency-light v3 starter is available through `cue new`, and
checked-in rock, orchestral, automation, adaptive, and hybrid authoring examples
serve as executable documentation. New composition agents should start in v3,
use `cue validate`, inspect source-only catalogs, render/audit/listen/revise, and
lower only passages that need exact literal events.

The next major feedback source should be **real new or reimagined cues**. When an
agent repeatedly works around the same limitation, improve the common v3 semantic
or generator/instrument capability rather than adding a cue-specific hack.

### Phase J — Legacy implementation isolation and module decomposition

Status: later, intentionally conservative.

The v1/v2 *frontends* are permanent supported regeneration inputs. Their internal
implementations can eventually be isolated behind `CompiledScore`, and historical
large modules can be split along the now-stable musicir/generator/instrument/
processing/render boundaries. Remove a compatibility transport only when all
consumers are migrated and the whole-corpus legacy regeneration gate stays green.

Do not prioritize module motion over authoring capability or real composition
feedback.

### Active — DAW round trip

Status: stages 1 and 2 established on 2026-09-07.

Established:

1. exact MIDI + provenance sidecar export, including instrument identities,
   source mappings, conductor baseline, and v3 clip source regions;
2. edited-MIDI ingestion against the saved baseline with PPQ normalization;
3. note classification for unchanged/moved/resized/repitched/velocity-changed,
   deleted, and added notes;
4. clip-owned CC/pitch-bend reconciliation, while renderer initialization CCs
   remain transport evidence rather than authored source;
5. source apply by lowering only affected v3 clips to literal events/automation;
6. stale-baseline refusal and post-apply recompilation verification before write.

Next large stages:

1. conductor reconciliation: tempo/meter/form-marker edits with an explicit
   policy for sampled SMF tempo ramps and sidecar-authoritative holds;
2. Ardour-first session/setup adapter around the neutral interchange core,
   including useful reference audio/stems and a deterministic edited-MIDI export
   handoff;
3. REAPER adapter after the Ardour workflow is exercised;
4. source-location-aware YAML patching to reduce textual diff without changing
   the structural reconciliation model.

Sparse generator-event override layers should be added only if real round-trip
experience shows they are easier to reason about than lowering an edited clip
to exact events.

### Later cleanup — Compatibility surfaces

Do this only after consumers and tests make each deletion mechanical. Possible
future removals include private PrettyMIDI metadata, redundant schema branches
in consumers, and tuple compatibility facades.

**Do not remove the ability to parse/compile v1 or v2 scores.** Compatibility
cleanup means isolating old implementation surfaces, not invalidating authored
music that is needed to regenerate assets.

## Explicit non-goals

The campaign does not currently need:

- automatic bulk v1/v2 -> v3 source conversion;
- rewriting old scores solely to use the newest schema;
- a built-in DAW competitive with Ardour or REAPER;
- arbitrary Python-like expressions/loops/conditionals embedded in YAML;
- checked-in copies of the full `/data/audio-tools` census/sample tree;
- machine-local absolute sample paths in ordinary MusicIR scores.

If an old track needs improvement, prefer asking an agent to compose a new,
polished v3 version while retaining the old score as a reproducible historical
asset source.

## Testing policy for this campaign

### Legacy preservation

For changes that can affect compilation:

- run the generic v1/v2 migration-contract tests;
- run the complete committed v1/v2 corpus when the change is broad;
- compare the synthesis/form contract, not YAML formatting;
- retain deterministic audio-equivalence tests for common backend paths.

A new v3 feature does not justify modifying old source files.

### V3 features

Tests should be generic renderer tests, never snapshots of named songs. Cover:

- exact and generated forms of shared transforms;
- pitch semantics and exact harmony boundaries;
- controller/pitch-bend points and deterministic automation curves;
- explicit technique gates and key-only/relative pitch semantics;
- sequence-material provenance and form energy/density behavior;
- generator registry typing/ranges/capabilities and opt-in variation controls;
- authoring-id independence from compiled/audio identity;
- DAW interchange source mapping;
- deterministic validation failures for malformed authoring constructs;
- YAML path/line diagnostics and typo suggestions for generic malformed v3 source;
- expansion/trace evidence without changing the compiled-score fingerprint.

### Environment registers

Tests should ensure:

- the instrument catalog parses and all stable refs remain unique;
- the checked-in workstation snapshot is valid plain JSON and contains portable
  resource paths;
- source-only stdlib readers work under `python -S`;
- every v3 generator bridge target exists in the implementation registry;
- the generator/processing/technique catalogs and instrument authoring index are packaged with the renderer;
- `python -S dev/check_source_only_authoring.py` and `python -S dev/music_authoring_reference.py summary` work without third-party dependencies;
- all stable catalog instruments produce a compilable canonical v3 audition score.

## Context recovery checklist

When a new agent inherits this repository with no conversation context:

1. Read `AGENTS.md`.
2. Read this document.
3. Read `docs/musicir_v3.md`, `docs/instrument_catalog.md`, and
   `docs/daw_interchange.md` for the subsystem being changed.
4. Inspect `data/instrument_catalog.yaml` for the expected instrument vocabulary.
5. Inspect `data/audio_environment_snapshot.json` when the question is what the
   user's standard workstation was actually observed to contain. Do not assume
   the agent's own filesystem represents that machine.
6. For a quick dependency-free overview run `python -S dev/music_authoring_reference.py summary` or `search <term>`. Inspect `data/generator_catalog.json`, `data/processing_catalog.json`, `data/technique_catalog.json`, and `data/instrument_authoring_index.json` for deeper source-only authoring knowledge.
7. For an unfamiliar v3 score, run `cue validate`, then `cue graph` / `cue expand`
   before reading generator implementation code. Use `cue trace_event` when an
   expanded event needs source/realization explanation.
8. Use `compile_score()` / `CompiledScore` for shared compiler/render work.
9. Before deleting a compatibility path, find the tests and consumers that make
   its removal safe. Do not infer that v3 adoption means old score regeneration
   can be dropped.

The desired end state is straightforward: old v1/v2 assets remain reproducible,
new agents can author concise and expressive v3 music from repository knowledge
alone, rendering has one semantic/dependency spine, and human DAW edits can
later return through a provenance-aware interchange boundary.

IMPORTANT: Never add tests for a specific song. Test the renderer, not the content. If a feature does not have a natural test, then don't add the test. Don't add a bullshit test for the sake of adding a test.

## Sampled-instrument authoring contract

- `ambition_music_renderer/data/instrument_catalog.yaml` is the checked-in authority for sampled instruments Ambition expects composers and agents to be able to use.
- The normal `download_ambition_audio_tools.sh` environment is expected to provide every catalog instrument. If a catalog ref does not resolve on the current machine, treat that as an environment/install problem rather than avoiding the instrument in authored music.
- Prefer stable MusicIR `instrument_backend: {kind: sfz, library_ref: ...}` identities from the catalog. Do not copy absolute `/data/audio-tools` paths or ordinary filename-selection `prefer` heuristics into scores when the catalog already owns them.
- A score-level `prefer` or explicit `sfz` is an intentional realization override, not normal boilerplate.
- `SFZ_USAGE_CENSUS.json` and other files under `AMBITION_AUDIO_TOOLS_ROOT` describe one machine's current installation. They provide exact paths, ranges, controllers, keyswitches, and health evidence; they do not define the supported authoring vocabulary.
- Use `python -m ambition_music_renderer instruments list` and `instruments describe <library_ref>` to discover the source-controlled vocabulary and known patch-level controls. Use `instruments doctor` on a machine with audio tools to compare expected downloaded sources and resolved roles against that contract.
- Instrument-backend compatibility spellings and resolution semantics belong in `instrument_resolution.py`. Renderers, audits, inspectors, caches, and validators should consume its canonical plan instead of interpreting `library_ref`, `sfz`, `prefer`, roots, or fallback fields independently.

## MusicIR compilation contract

- `ambition_music_renderer.musicir.compile.compile_score()` is the canonical boundary between authored MusicIR and renderer consumers. New renderer, audit, inspector, cache, timeline, or export code should consume `CompiledScore` instead of calling a schema-specific compiler or reading semantic data from private `PrettyMIDI` attributes.
- MusicIR v1 and v2 remain distinct authoring frontends. Both compile to `CompiledScore`; do not make shared consumers branch on source schema when the compiled object already carries the needed semantics.
- `musicir/normalize.py` owns source-schema compatibility and authoring aliases. Keep compatibility behavior there during migration; downstream code should see canonical schema/fields.
- `render.score_layers.build_score()` and `_ambition_note_events` / `_ambition_instrument_specs` / `_ambition_exact_score` are compatibility surfaces only. Do not add new dependencies on them.
- Preserve musical behavior while migrating. Generic migration-contract tests should compare expanded notes, velocities, timing, controllers, pitch bends, groups, section boundaries, MIDI resolution, and exact-score clock metadata. Audio-path changes should also have a deterministic generic render comparison when a dependency-free backend can exercise them.
- Do not add snapshots for named cues. Frozen migration fixtures must describe renderer capabilities generically so score edits remain free to evolve.
- `cue validate <cue>` compiles without synthesis and reports schema normalization plus the `CompiledScore` fingerprint. The fingerprint represents the synthesis/form contract, not a local sample-file realization; use instrument-resolution and render-cache diagnostics for machine-specific backend identity.
- During this migration, legacy compatibility paths stay in place until tests demonstrate their consumers have moved. Remove them in a later explicit cleanup rather than opportunistically while refactoring another subsystem.

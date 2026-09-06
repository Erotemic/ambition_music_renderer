# MusicIR compilation and migration safety

MusicIR now has three supported source frontends during migration:

- v1: the established procedural/layer language used by most cues;
- v2: the exact tick/form language; and
- v3: the unified authoring graph, where exact clips/materials and procedural
  generator clips can coexist before expansion.

All three meet at the same compiled semantic boundary:

```text
MusicIR YAML
   |
   +-- v1 procedural compiler --------+
   |                                  |
   +-- v2 exact compiler -------------+--> CompiledScore --> render / audit / inspect / export
   |                                  |
   +-- v3 authoring graph ------------+
         | exact clips                |
         + generator registry --------+
```

`ambition_music_renderer.musicir.compile.compile_score()` is the public
compilation entry point. Source compatibility remains in `musicir.normalize`;
v3 authoring structure is normalized by `musicir.graph` before exact material
and generator intent are expanded.

V3 does not replace the renderer contract and should not trigger a mechanical
conversion of the existing corpus. See `docs/musicir_v3.md` for the source model
and `docs/daw_interchange.md` for the DAW-facing provenance boundary.

## CompiledScore

`CompiledScore` carries the semantic state shared consumers need:

- the canonical normalized MusicIR document and source/canonical schema names;
- `PrettyMIDI` as the current synthesis representation;
- instrument-to-group assignments and canonical instrument specifications;
- expanded note/controller event metadata;
- compiled section/form timing;
- exact-score clock metadata when applicable; and
- compatibility-normalization warnings.

Private attributes historically attached to `PrettyMIDI` are still populated so
older callers keep working during migration. They are compatibility adapters,
not the authority for new code.

For v3, `CompiledScore` also carries the normalized authoring graph and its
source-structure fingerprint. Note events may carry stable `event_id` /
`source_ref` provenance. These source identities are deliberately excluded from
the compiled audio-semantic fingerprint; the same notes/controllers/form should
remain the same compiled music even if a clip is renamed.

## Compatibility firewall

Production compilation remains permissive for now. The deprecated
`ambition.music.v1` spelling, missing schemas, and historically unknown schema
fallbacks retain the old v1 behavior while reporting warnings. `cue validate
--strict-schema` rejects those cases. This lets the corpus and external score
producers migrate before the renderer changes its compatibility behavior.

Instrument backend aliases are also canonicalized at this boundary. Exact local
SFZ paths and installed-library facts remain the responsibility of the
instrument resolver and machine inventory; `CompiledScore` deliberately stays
machine-independent.

## Migration tests

The migration uses generic renderer contracts rather than named-song snapshots.
The frozen v1/v2 contract fixture was captured from the renderer before the
`CompiledScore` refactor and records the synthesis/form inputs that determine
music before backend realization:

- MIDI resolution;
- instrument program/drum identity;
- note starts, ends, pitches, and velocities;
- control changes and pitch bends;
- stem/group assignment;
- section boundaries; and
- exact-score timing metadata.

Both frontends must continue to match that pre-refactor contract. A separate
deterministic procedural-synthesis test renders the legacy facade and the new
explicit `CompiledScore` path and requires identical PCM. These tests provide a
non-destructive seam while consumers migrate.

The checked-in fixtures intentionally avoid real cue names. Music can continue
to change without rewriting architecture snapshots.

## Compiled semantic fingerprint

`compiled_score_fingerprint()` hashes a deterministic representation of the
compiled synthesis/form contract. A source-only compatibility change such as
the deprecated v1 schema spelling does not change it; a musical change such as
a changed note velocity does.

`cue validate` reports this fingerprint, and render manifests record it. It is
useful for answering "did the compiler feed different music to the renderer?"
without confusing that question with local SFZ/SoundFont changes.

This remains distinct from the complete render-cache fingerprint.
`render.dependencies` layers the compiled fingerprint together with resolved
instrument/sample/SoundFont identity, processing dependencies, renderer source,
and relevant runtime tools. See `docs/render_dependencies.md`. Keeping these
two fingerprints separate lets a migration answer whether the *music* changed
independently of whether its machine realization changed.

## Removal gates

The compatibility facade should be removed only after all in-repo consumers use
`CompiledScore` directly and migration tests stay green. In particular:

1. shared consumers must stop reading private `PrettyMIDI` semantic attributes;
2. schema compatibility must live only in the normalizer;
3. full corpus compilation must remain successful in compatibility mode;
4. strict validation should pass after deprecated/missing schemas are migrated;
5. synthesis-contract comparisons must show no unexplained drift; and
6. any intended audio change should be reviewed as an audio change rather than
   hidden inside an architecture cleanup.

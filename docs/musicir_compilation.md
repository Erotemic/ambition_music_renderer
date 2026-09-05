# MusicIR compilation and migration safety

MusicIR has two authoring frontends with different strengths. Version 1 is the
procedural composition language used by most cues; version 2 is the exact-score
language for explicit tick/form authoring. They are not being collapsed into a
single source syntax. They now meet at one compiled semantic boundary.

```text
MusicIR YAML
   |
   +-- v1 procedural compiler --+
   |                            |
   +-- v2 exact compiler -------+--> CompiledScore --> render / audit / inspect / export
```

`ambition_music_renderer.musicir.compile.compile_score()` is the public
compilation entry point. It first passes source data through
`musicir.normalize.normalize_musicir_spec()`, then dispatches to the appropriate
frontend compiler. The normalizer is the only place that should acquire new
source compatibility aliases.

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

This is not yet the final render-cache fingerprint. Machine realization still
needs the resolved instrument plan, sample/SoundFont identities, effects, and
renderer implementation identity. Those can be layered on later without
changing the compiled musical contract.

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

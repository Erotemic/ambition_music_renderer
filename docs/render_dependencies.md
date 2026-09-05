# Render dependency identity

`CompiledScore` answers a narrow migration question: did authored MusicIR compile
to the same notes, controllers, timing, instruments, groups, and form? It does
not by itself answer whether two renders used the same machine realization.

`ambition_music_renderer.render.dependencies` is the authority for that second
question. Every versioned render directory is keyed by a canonical render
dependency fingerprint. The full inspectable payload is also stored in the
adaptive manifest.

## What determines a render

The dependency payload currently includes:

- the canonical `CompiledScore` fingerprint;
- audio-affecting render, stem, group, section, playback, and master settings;
- the selected top-level render backend;
- the chosen SoundFont identity;
- the canonical instrument-resolution plan for every instrument;
- each resolved SFZ program and include file, plus the identities of sample
  files referenced by that program;
- the concrete sfizz executable or VST3 host/plugin realization when relevant;
- requested VST3, LV2, and external effect-chain processors and known model,
  preset, or impulse-response files;
- production renderer source plus checked-in renderer data; and
- relevant Python/DSP/tool versions and executable identities.

The identity is dependency-local. The renderer does **not** hash all of
`/data/audio-tools`. Installing or editing an unrelated sample library therefore
does not invalidate a cue. Replacing a sample referenced by the SFZ that the cue
actually resolves to does invalidate that cue and the affected stem cache entry.

SFZ program/include text is content-hashed. Large audio files use path, size,
and nanosecond mtime rather than re-reading gigabytes on every currentness
check. VST3 bundle directories similarly use a tree of contained file metadata.

## Currentness and generated paths

The short prefix of the full SHA-256 fingerprint is the generated-layout hash:

```text
generated/<cue>/.versioned/<render-hash>/...
```

The short hash is only a path key. The manifest records the full fingerprint and
payload, and currentness checks compare that record to the current dependency
identity.

The parent orchestration process computes the dependency identity before
selecting the versioned directory. It passes the expected render hash to the
renderer/worker path. The renderer rejects a launch if dependencies changed
between directory selection and render startup, rather than writing new audio
under an old hash.

`needs_render()` remains a compatibility mtime/output-presence hook during the
migration. Bulk and single-cue orchestration also run the canonical dependency
check, so an unchanged YAML file can still become stale because a referenced
sample, SoundFont, processor, renderer implementation, or relevant runtime tool
changed.

## Inspecting identity

Use:

```bash
python -m ambition_music_renderer cue fingerprint <cue>
python -m ambition_music_renderer cue fingerprint <cue> --json
```

The human form shows the short/full render fingerprint, compiled-score
fingerprint, renderer-source fingerprint, and selected instrument realizations.
The JSON form exposes the complete dependency payload and is the preferred
input for diagnostics.

The older `audit instrument_drift` report remains useful for explaining changes
between historical renders. It is not a second cache/currentness authority.

## Renderer version compatibility

`RENDERER_VERSION` remains in manifests and in the legacy hash helper so older
tools and historical renders remain interpretable. New currentness code must
not require a developer to bump it. Production renderer source/data are part of
the canonical dependency fingerprint, so an implementation edit changes render
identity automatically.

## Adding a new backend or processor

When a new synthesis or processing backend can affect output through a machine
resource that is not already represented by authored MusicIR, add that resource
to `render.dependencies` at the same time as the backend. Examples are a plugin
binary, model/preset file, external executable, or runtime package that selects
a different DSP implementation.

Prefer the narrowest concrete dependency. Do not fingerprint a whole plugin or
sample root when one resolved file/bundle is sufficient.

## Migration contract

This layer changes cache/currentness identity, not musical synthesis semantics.
The generic MusicIR migration contracts and deterministic procedural-FM audio
comparison remain the guard against accidental musical changes. Changes to
mastering or synthesis should be reviewed separately as intended audio changes.

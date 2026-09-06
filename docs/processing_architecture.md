# Processing and mastering architecture

This document describes the Phase 5/6 audio-processing authority. It is the
reference for new MusicIR v3 processing authoring and for compatibility work on
older `postprocess` fields.

## Authorities

`ambition_music_renderer/data/processing_catalog.json` is the checked-in public
processing vocabulary. It owns canonical processor names, compatibility
aliases, parameter metadata/defaults, backend family, automation capability,
and inspector templates. A source-only agent can inspect it directly or run:

```bash
python -S dev/read_processing_catalog.py list
python -S dev/read_processing_catalog.py describe compressor
python -S dev/read_processing_catalog.py templates
```

With the package installed, the same authority is exposed through:

```bash
python -m ambition_music_renderer processing list
python -m ambition_music_renderer processing describe compressor
python -m ambition_music_renderer processing schema compressor
python -m ambition_music_renderer processing plan <cue>
```

`processing.model.ProcessingPlan` is the normalized render-time contract.
Renderer stages consume plans rather than independently interpreting YAML
aliases/defaults.

`processing.pipeline.apply_processing_plan()` is the execution boundary.
Historical `render.effects.post_process()` remains a compatibility facade: it
translates the old flat mapping into an ordered `ProcessingPlan` and executes
that plan.

## Canonical v3 syntax

New v3 sources should prefer an explicit `processing:` block:

```yaml
processing:
  stems:
    chain:
      - {processor: highpass, cutoff_hz: 45}

  groups:
    guitars:
      chain:
        - {processor: gain, gain_db: -1.5}
        - processor: pedalboard
          effects:
            - {effect: distortion, drive_db: 7}

  sections:
    intro:
      chain:
        - {processor: gain, gain_db: -3}

  master:
    chain:
      - {processor: compressor, threshold_db: -20, ratio: 2.2}
      - {processor: reverb, wet: 0.06, decay_seconds: 1.1}
      - {processor: limiter, target_peak_db: -1.2, drive: 1.04, normalize: true}

  adaptive_sections:
    mode: composition_master
```

`stems` is the default post-synthesis chain for every rendered stem group.
`groups.<name>` appends group-specific operations. `sections.<id>` is an
explicit **pre-master composition-bus** section treatment. `master` is the one
composition-master chain.

The current processing vocabulary is static at render time. The catalog records
automation capability explicitly; processors currently report static-only
support. MusicIR note/controller automation remains separate from DSP parameter
automation until a deterministic cross-backend contract is designed.

## Legacy processing compatibility

Existing scores use flat mappings such as:

```yaml
stem_postprocess: {...}
group_postprocess: {...}
postprocess: {...}
sections:
  - id: intro
    postprocess: {...}
```

These fields remain supported. They are not migration backlog because v1/v2
scores must remain regenerable from source.

`processing.legacy.legacy_postprocess_chain()` is the single compatibility
translation. It preserves the historical operation order and defaults,
including defaults that were previously implicit:

1. gain
2. high-pass
3. transient tame
4. presence band
5. high shelf
6. parametric EQ
7. low-pass
8. compressor
9. built-in room
10. post-room high shelf
11. stereo width
12. optional external effect chain
13. LUFS normalization
14. limiter

Generic PCM migration tests freeze representative pre-Phase-5 outputs so a
change to this translation is visible before old assets are regenerated.

## Canonical signal flow

The intended full-mix path is:

```text
synthesis
  -> per-group stem processing
  -> section stem/mix gain + foreground protection
  -> native composition sum
  -> explicit canonical section-bus processing (optional)
  -> one composition master
  -> mastered timeline
  -> soundtrack / adaptive full-section slices / previews
```

For new v3 music, `composition_master` is the default adaptive mastering policy.
Full-section adaptive assets are literal slices of the one mastered timeline.
A section cannot independently peak-normalize itself after the master.

This keeps intro/loop/outro assets in one loudness system and makes DAW/export
reasoning much clearer.

## Historical section mastering

V1/v2 scores without an explicit policy retain the old
`legacy_section_postprocess` behavior. Historical spellings are still accepted:

- `section_postprocess` -> `legacy_section_postprocess`
- `global_master_slices` -> `composition_master`

The legacy mode only reprocesses a raw section slice when that old score actually
contains `sections[].postprocess`; otherwise it slices the composition master.
This keeps old regeneration behavior intact.

New v3 music should not use `sections[].postprocess`. Use
`processing.sections.<id>` when a section needs a special treatment; that stage
runs before the composition master.

## Regression evidence

`processing.metrics` provides deterministic peak/RMS/clipping/DC and section
boundary metrics. Render manifests also record:

- native post-stem composition sum;
- pre-master composition bus;
- mastered timeline;
- resolved master processing plan;
- section-bus plans;
- mastering policy;
- adaptive full-mix decision per section;
- mastered section-boundary discontinuity metrics.

This makes later sonic improvements reviewable as audio changes rather than
being hidden inside architecture changes.

## Plugin realization

The same processing catalog is consumed by:

- `backends/plugin_chain.py` for backend aliases;
- `backends/pedalboard_backend.py` for effect aliases and owned defaults;
- plugin validation;
- render dependency fingerprinting;
- the instrument inspector's effect templates.

The observational workstation plugin inventory remains in
`data/audio_environment_snapshot.json`. It says what was observed on the user's
machine; it does not redefine the public processing vocabulary.

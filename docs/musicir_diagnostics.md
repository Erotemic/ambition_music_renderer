# MusicIR validation and derivation diagnostics

MusicIR v3 keeps compositional intent above the fully expanded `CompiledScore`.
The diagnostic tools make that boundary inspectable without introducing another
compiler or instrument resolver.

## Validation contract

Run:

```bash
python -m ambition_music_renderer cue validate path/to/score.music.yaml
python -m ambition_music_renderer cue validate path/to/score.music.yaml --json
```

For v3, validation first checks mistakes that can be explained directly in the
authored source. Diagnostics carry:

- a stable code such as `V3_GENERATOR_FIELD`;
- a semantic source path such as
  `parts[0].voices[0].clips[2].generate.pattern`;
- one-based YAML line/column coordinates when validating a file;
- a focused message;
- a repair hint when there is a strong suggestion.

Example:

```text
ERROR V3_GENERATOR_FIELD: unknown harmony.arpeggio generator field `patern`
  at score.music.yaml:42:15 [parts[0].voices[0].clips[2].generate.patern]
  hint: did you mean `pattern`?
```

Current source checks cover the v3 structural vocabulary, stable/duplicate IDs,
material and instrument references, generator names/required parameters, common
parameter domains, pitch semantics, exact durations, clip transforms, and
controller/pitch-bend points. They intentionally do not duplicate the full
compiler. If a valid-looking graph violates a lowering restriction, validation
reports `V3_COMPILE` with the canonical compiler's explanation.

`--json` is intended for agents/editors. Invalid input returns a nonzero status
and a JSON object with `ok: false` and structured diagnostics. Valid input has
`ok: true` and the normal compilation summary/fingerprints.

MusicIR v1/v2 remain supported regeneration inputs. Their compilation path is
not made stricter by the v3 source validator.

## Inspect the authoring graph

```bash
python -m ambition_music_renderer cue graph <cue>
python -m ambition_music_renderer cue graph <cue> --json
```

The graph view keeps composition intent unexpanded. It shows score → part →
voice → clip structure and edges from clips to reusable materials and procedural
generators. V1/v2 scores report that no v3 authoring graph exists while remaining
fully compilable/renderable.

## Expand a score or clip

```bash
python -m ambition_music_renderer cue expand <cue>
python -m ambition_music_renderer cue expand <cue> --clip harmony_motion
python -m ambition_music_renderer cue expand <cue> --clip harmony_motion --json
```

Expansion is read-only. For each selected v3 clip it reports:

- authored clip path and stable ids;
- whether the source is literal events, a reusable material, or a generator;
- the material/generator payload;
- common clip transforms and repeats;
- expanded note/controller events and stable `event_id` / `source_ref`;
- exact harmony active at each compiled event tick;
- the canonical `InstrumentResolutionPlan` for instruments used by those events.

On a remote machine without `/data/audio-tools`, the resolution plan can show an
expected catalog identity without a concrete SFZ path. That is correct: the
checked-in instrument catalog remains the authoring contract and local paths are
runtime evidence.

## Trace one event

Take an `event_id` from `cue expand`, the timeline, or a DAW interchange sidecar:

```bash
python -m ambition_music_renderer cue trace_event <cue> \
  musicir_v3_authoring_example/keys_part/right_hand/opening_answer/r000/a1/p00
```

The trace returns the compiled event, exact harmony context, source reference,
source clip/material/event (when literal), generator output ordinal (when
procedural), transforms, and instrument realization. This is the preferred way
to answer "why did this note/controller exist?" before reading implementation
code.

## Authority boundaries

These tools deliberately reuse existing authorities:

- `validation/v3.py` explains authored-v3 shape/reference mistakes;
- `musicir.compile.compile_score()` remains the semantic compiler;
- `NormalizedScoreGraph` remains v3 composition intent;
- `CompiledScore` remains the exact renderer contract;
- `instrument_resolution.py` remains realization authority;
- `musicir.inspect` only joins those facts for inspection.

Do not add a second event expander, harmony resolver, or SFZ resolver to make a
diagnostic more convenient. If inspection cannot answer a question from the
canonical objects, improve the provenance those objects carry.

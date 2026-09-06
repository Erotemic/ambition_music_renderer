# MusicIR v3 authoring graph

MusicIR v3 is the migration target for new authoring work. It combines the two
capabilities that were previously split across source schemas:

- exact, tick-addressable score material from MusicIR v2; and
- compact musical generators from MusicIR v1.

V3 is an **authoring graph above `CompiledScore`**. It does not add another
renderer contract. Exact clips and generated clips both expand into the same
canonical notes/controllers/instruments/form consumed by rendering, audits,
caching, and interchange.

```text
MusicIR v3 YAML
      |
      v
NormalizedScoreGraph
  |            |
  | exact      | generate
  | clips      | clips
  v            v
exact lowerer  established v1 generator registry
       \       /
        \     /
         v   v
      CompiledScore
           |
           +--> audio/render pipeline
           +--> audits/timeline
           +--> DAW interchange MIDI + provenance sidecar
```

V1 and v2 remain supported. Do not mass-convert existing cues merely to change
the schema label. Migration should be driven by tests and by an authoring or
interchange benefit.

## Core shape

A v3 score has an exact score clock, stable instruments, optional first-class
key/harmony/materials, and parts containing voices containing clips:

```yaml
schema: ambition.musicir.v3
id: example_v3
seed: 7

timebase: {ppq: 960}
meter: 4/4
tempo: 132
key: E minor
end: {bar: 9, beat: 1}

form:
  - id: main
    from: {bar: 1, beat: 1}
    to: {bar: 9, beat: 1}
    loopable: true

harmony:
  progression: [Em, C, G, D]
  cycle: true

instruments:
  - name: piano
    group: harmony
    program: acoustic_grand_piano

materials:
  hook:
    events:
      - [0, 1/8, E5, 96]
      - [1/8, 1/8, G5, 90]
      - [1/4, 1/4, B5, 100]

parts:
  - id: piano_part
    instrument: piano
    voices:
      - id: lead
        clips:
          - id: opening_hook
            at: {bar: 1, beat: 1}
            use: hook
            repeat: {count: 4, every: {bars: 2}}

          - id: generated_arp
            at: {bar: 5, beat: 1}
            duration: {bars: 4}
            generate:
              kind: harmony.arpeggio
              pattern: [0, 2, 1, 2]
              step: 0.5
              octave: 4
              velocity: 72
```

The exact and generated clips belong to the same voice and score clock. There
is no global "procedural versus exact" mode.

## Stable ids and provenance

V3 requires ids for scores, parts, voices, and clips. Material ids are also
stable. These ids do **not** affect musical compilation. Renaming a clip changes
the authoring-graph fingerprint and DAW provenance ids, but does not change the
compiled-music fingerprint or default generator randomization.

Compiled v3 note events carry an `event_id` and `source_ref`. Exact material can
optionally give individual source events an `id`; if omitted, the source event
index is used. Generated events are mapped back to the generator clip and
expansion ordinal.

This separation gives two useful identities:

- `authoring_graph_fingerprint`: source structure, stable ids, material reuse,
  and generator intent; useful for source/DAW reconciliation.
- `compiled_score_fingerprint`: the actual synthesis/form contract; source-only
  renames and provenance do not change it.

## Exact clips and materials

An exact clip may contain `events` inline or `use` a reusable event material.
Compact events are:

```yaml
- [at, dur, pitch_or_pitches, velocity]
```

Local time values are deliberately exact and DAW-friendly:

- an integer is an exact tick offset;
- `1/4`, `1/8`, `3/16`, etc. are fractions of a whole note;
- `{ticks: 240}` is explicit tick addressing;
- `{beats: 1.5}` means quarter-note beats.

A clip can apply common transforms without modifying its source material:

```yaml
- id: high_hook
  at: {bar: 9, beat: 1}
  use: hook
  transpose: 12
  velocity_scale: 0.82
  gate: 0.9
```

Repeats can infer their spacing from event material or state it explicitly:

```yaml
repeat: 4
```

or:

```yaml
repeat: {count: 4, every: {bars: 2}}
```

Exact clips use the v2-derived exact clock and can span tempo and meter changes.

## Materials

V3 has three material kinds: literal event material, interval/rhythm motif
material, and composable sequence material.

Event material is reusable literal notation:

```yaml
materials:
  answer:
    kind: events
    events:
      - {id: a, at: 0, dur: 1/4, pitch: E5, velocity: 88}
      - {id: b, at: 1/4, dur: 1/4, pitch: D5, velocity: 82}
```

Motif material retains the useful interval/rhythm model from v1:

```yaml
materials:
  hero_motif:
    kind: motif
    root: E4
    intervals: [0, 3, 7, 10]
    rhythm: [0.5, 0.5, 1.0, 2.0]
    durations: [0.45, 0.45, 0.9, 1.8]
    velocities: [1.0, 0.94, 1.06, 1.0]
```

Use motif material through `melody.motif` rather than treating its interval data
as exact events.

Sequence material composes named event/sequence materials without flattening the
source structure:

```yaml
materials:
  answer:
    kind: events
    events:
      - [0, 1/4, E5, 88]
      - [1/4, 1/4, D5, 84]

  phrase:
    kind: sequence
    items:
      - {id: first, use: answer, at: 0}
      - {id: response, use: answer, at: 1/2, transpose: -5, velocity_scale: 0.9}
```

Sequence items support local placement, repetition, common transforms, and
explicit technique intent. Expansion preserves the material chain in event
provenance, so a phrase can grow from reusable building blocks without becoming
an opaque literal note dump.

## Harmony

Harmony is score-level musical intent rather than a property trapped inside a
legacy section. The concise form is:

```yaml
harmony: [Em, C, G, D]
```

The expanded form can cycle or start later:

```yaml
harmony:
  start_bar: 1
  every_bars: 1
  progression: [Em, C, G, D]
  cycle: true
```

Explicit changes are also accepted:

```yaml
harmony:
  events:
    - {bar: 1, chord: Em}
    - {bar: 5, chord: Cmaj7}
```

Harmony-following generators resolve this timeline when they expand.

A score can also declare key/mode context:

```yaml
key: E minor
```

or:

```yaml
key: {tonic: D, mode: dorian}
```

A `scale_degree` pitch expression uses score key context when its own tonic/mode
is omitted. It does not require a harmony timeline in that case. Chord-relative
pitches continue to resolve the chord active at the exact event tick.

## Generator registry

V3 uses namespaced musical generator names. They currently bridge to the
established v1 implementations, so the renderer does not acquire a second
arpeggiator/guitar/drum implementation during migration.

Current public generator names include:

- `harmony.pad`
- `harmony.arpeggio`
- `rhythm.ostinato`
- `harmony.bass`
- `melody.motif`
- `harmony.chord_hits`
- `drums.pattern`
- `texture.pattern`
- `harmony.pedal`
- `harmony.root_hits`
- `guitar.shape_pick`
- `guitar.strum`
- `guitar.chug`
- `harmony.sampled_chord`
- `guitar.lead`
- `midi.automation`

`ambition_music_renderer/data/generator_catalog.json` is the public v3 generator
registry and maps each public name to an established bridge implementation.
`render.score_layers.LAYER_RENDERERS` remains the v1 implementation registry.
`musicir.v3.GENERATOR_KINDS` is only a derived compatibility/readability view of
the checked-in catalog. Tests require every catalog bridge target to exist in
the implementation registry.

The catalog also carries machine-readable parameter types/ranges/enums and
capability metadata. Several established generators expose opt-in variation
controls intended to make long sections less mechanical without changing old
scores: `harmony.arpeggio` supports per-step `velocity_pattern` and
`octave_pattern`; `harmony.bass` supports per-step/per-bar velocity patterns;
and `drums.pattern` supports per-bar dynamics plus periodic `fill_events` in
overlay or replace mode. Form-region `energy`/`intensity` and `density` provide
a shared section-level intent signal to procedural clips.

### Temporary generator-bridge restrictions

The old procedural generators use a fixed meter and tempo while expanding.
Rather than approximate and introduce musical drift, the v3 bridge currently
requires each generated clip to:

- start on a bar boundary;
- have `duration: {bars: N}`;
- remain within one meter; and
- remain within a constant-tempo region with no score hold.

Split a generated passage into multiple clips at a clock change. Exact clips do
not have this restriction. A later generator refactor can emit clock-domain
events directly and remove the restriction without changing v3 source concepts.

## Why `CompiledScore` remains separate

V3 is not the renderer's event structure. It preserves reusable material,
generator intent, stable source ids, and transforms that disappear after
expansion. `CompiledScore` remains the canonical answer to "what notes,
controllers, instruments, timing, and form are being rendered?"

That separation is what lets an agent use compact composition intent while
still giving migration tests an exact synthesis contract.

## Migration rule

Do not remove v1/v2 compatibility as part of v3 feature work. A conversion is
ready to land when generic tests or an explicit corpus comparison demonstrate
that its compiled notes/controllers/timing/form are unchanged, or when an
audible difference is intentional and reviewed as such.

## Common clip transforms

Clip transforms run **after material expansion**, so the same authoring knobs
apply to literal events, reused materials, and generator output:

```yaml
- id: transformed_phrase
  at: {bar: 9, beat: 1}
  use: hook
  transpose: 2
  octave: 1
  velocity_scale: 0.85
  velocity_offset: -4
  time_scale: 0.5
  gate: 0.9
  repeat: {count: 2, every: {bars: 1}}
```

The current common transforms are `transpose`, `octave`, `velocity_scale`,
`velocity_offset`, `time_scale`, `gate`, and `repeat`. Generator-specific knobs
execute inside the generator first; common clip transforms then operate on the
expanded performance. Prefer adding a common transform when the behavior makes
sense for exact and generated material alike.

## Explicit pitch intent

An exact v3 event may continue to use a MIDI integer or note name:

```yaml
pitch: C#5
```

When musical intent is relative, use an explicit pitch expression rather than
forcing an agent to precompute a MIDI number:

```yaml
pitch: {kind: relative, root: E4, semitones: 7}
pitch: {kind: harmony_root, octave: 3}
pitch: {kind: chord_tone, degree: 3, octave: 4}
pitch: {kind: scale_degree, tonic: E, mode: minor, degree: 6, octave: 4}
pitch: {kind: drum, name: snare}
pitch: {kind: guitar_fret, string: A2, fret: 7}
```

`harmony_root` and `chord_tone` resolve against the harmony active at the exact
event tick, including a harmony event that changes mid-bar. `scale_degree`
supports the common diatonic modes plus natural/harmonic/melodic minor and major
or minor pentatonic scales. Degrees are one-based and can extend beyond one
octave.

These forms preserve compositional intent in `NormalizedScoreGraph`; they lower
to ordinary MIDI pitches in `CompiledScore`.

## Techniques and articulation intent

V3 has a checked-in backend-independent technique vocabulary in
`data/technique_catalog.json`, including sustain/tenuto/legato, staccato,
spiccato, marcato, pluck/pizzicato, palm mute, tremolo, pad, hit, and bell-like
intent. Techniques are explicit: an exact note with no authored technique keeps
its literal duration. An authored technique may apply its semantic gate, and a
part-level `technique_map` can route the intent to an alternate instrument or
backend realization when a library has a dedicated articulation.

```yaml
- id: muted_riff
  at: {bar: 1, beat: 1}
  technique: palm_mute
  use: riff
```

The source-only vocabulary is available with:

```bash
python -S dev/read_technique_catalog.py list
python -S dev/read_technique_catalog.py describe palm_mute
```

Do not encode a specific SFZ keyswitch into general MusicIR technique meaning;
patch-specific realization belongs in instrument knowledge/resolution.

## Clip automation

V3 clips can carry exact controller and pitch-bend points independent of the
source material type:

```yaml
- id: expressive_hook
  at: {bar: 1, beat: 1}
  use: hook
  automation:
    - {id: soft, at: 0, cc: expression, value: 64}
    - {id: swell, at: 1/2, cc: expression, value: 116}
    - {id: bend, at: 3/4, pitch_bend: 1024}
```

Automation participates in clip repeat and `time_scale`. It can also accompany
a `generate:` clip. Compiled controller events carry source provenance, and the
DAW interchange sidecar maps those authored points to exported MIDI CC/pitch
bend events.

Automation can also use deterministic curves. Curves are sampled on the exact
score clock and compile to ordinary CC/pitch-bend events with stable provenance:

```yaml
automation:
  - id: swell
    cc: expression
    points: [[0, 64], [1/2, 116]]
    interpolation: smooth
    resolution: 1/32
```

Supported interpolation modes are `step`, `linear`, and `smooth`. Resolution is
explicit so the expansion is bounded and reproducible rather than backend-
dependent.

## Form-level performance intent

Form regions may carry bounded `energy`/`intensity`, `density`, `variation`, and
role metadata. Procedural clips can consume the shared energy/density intent;
literal exact clips remain literal. This is a coordination signal for multiple
generators, not a hidden postprocessor that rewrites authored notes.

```yaml
form:
  - id: verse
    from: {bar: 1, beat: 1}
    to: {bar: 9, beat: 1}
    energy: 0.45
    density: 0.55
  - id: chorus
    from: {bar: 9, beat: 1}
    to: {bar: 17, beat: 1}
    energy: 0.9
    density: 0.85
```

## Generator catalog and source-only discovery

The public generator vocabulary and parameter surface live in
`ambition_music_renderer/data/generator_catalog.json`. The v3 compiler validates
`generate:` blocks against that checked-in catalog, and each entry identifies
the established v1 implementation used by the compatibility bridge. Generic
tests compile every catalog example, so examples shown to an agent must remain
valid through the real bridge.

With the package environment available:

```bash
python -m ambition_music_renderer generators list
python -m ambition_music_renderer generators describe harmony.arpeggio
python -m ambition_music_renderer generators schema guitar.strum
```

A remote agent with only source can read the JSON directly or use the stdlib
reader:

```bash
python -S dev/read_generator_catalog.py list
python -S dev/read_generator_catalog.py describe harmony.arpeggio
```

Do not infer extra public v3 parameters by reading a v1 implementation. If a
capability should be authorable in v3, add it to the generator catalog together
with validation/documentation evidence.

For a dependency-free overview of all public authoring vocabularies at once:

```bash
python -S dev/music_authoring_reference.py summary
python -S dev/music_authoring_reference.py search guitar
python -S dev/music_authoring_reference.py describe guitar.strum
```

## Starting a new score

V3 is the default for new compositions. With the package installed:

```bash
python -m ambition_music_renderer cue new "My New Cue"
```

A source-only checkout can create the same packaged starter with:

```bash
python -S dev/new_musicir_v3.py "My New Cue"
```

The repository also contains dependency-light rock, orchestral, automation, and
adaptive v3 examples. Treat them as executable documentation; do not port old
v1/v2 scores merely to obtain newer syntax.

## Compatibility direction

V3 is the normal schema for new compositions. Existing v1 and v2 scores are
not expected to be source-converted. They remain supported frontends so their
assets can be regenerated indefinitely. If an older cue needs a better mix,
arrangement, instrumentation, or composition, a new v3 score can replace it at
the game-content level while the original source remains intact and renderable.

See `docs/architecture_roadmap.md` for the complete campaign plan and authority
map.
## Validation and derivation inspection

V3 authoring errors and expansion provenance are inspectable without rendering:

```bash
python -m ambition_music_renderer cue validate <cue>
python -m ambition_music_renderer cue graph <cue>
python -m ambition_music_renderer cue expand <cue> --clip <clip-id>
python -m ambition_music_renderer cue trace_event <cue> <event-id>
```

Validation gives source paths/line coordinates and targeted hints. Expansion and
trace views connect an authored clip/material/generator through common transforms
and exact harmony context to the canonical compiled events and current instrument
resolution. See `docs/musicir_diagnostics.md` for the authority boundary and JSON
interfaces.


## Canonical render-time processing

New v3 scores can author explicit static DSP chains without falling back to the
historical flat `postprocess` mapping:

```yaml
processing:
  stems:
    chain:
      - {processor: highpass, cutoff_hz: 45}

  groups:
    guitars:
      chain:
        - {processor: gain, gain_db: -1.5}

  master:
    chain:
      - {processor: compressor, threshold_db: -20, ratio: 2.2}
      - {processor: reverb, wet: 0.06, decay_seconds: 1.1}
      - {processor: limiter, target_peak_db: -1.2, drive: 1.04, normalize: true}

  adaptive_sections:
    mode: composition_master
```

Processor names and parameters come from
`ambition_music_renderer/data/processing_catalog.json`, which is also consumed
by validation and rendering. Use `processing list`, `processing describe`, and
`processing plan <cue>` with the package available, or the stdlib-only
`dev/read_processing_catalog.py` from source.

`processing.sections.<id>` is an explicit pre-master section-bus treatment.
For new v3 music, adaptive full-section assets are slices of one mastered
timeline. Do not use legacy `sections[].postprocess` as a new v3 composition
technique. Existing v1/v2 scores continue to support it for exact regeneration.

See `docs/processing_architecture.md` for signal-flow and compatibility details.

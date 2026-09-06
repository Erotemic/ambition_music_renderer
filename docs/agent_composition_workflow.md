# Agent composition workflow

This is the default workflow for **new** Ambition music. New compositions use
MusicIR v3. Existing v1/v2 sources stay intact so their assets can always be
regenerated; a better version of an old tune should normally be a new v3 score.

## 1. Recover the authoring environment from source

An agent does not need access to `/data/audio-tools` to know what the normal
Ambition workstation is expected to provide.

Start with:

```bash
python -S dev/music_authoring_reference.py summary
python -S dev/music_authoring_reference.py search guitar
```

Then use the focused source-only readers when needed:

```bash
python -S dev/read_instrument_catalog.py describe guitar.emily
python -S dev/read_generator_catalog.py describe guitar.strum
python -S dev/read_processing_catalog.py describe compressor
python -S dev/read_technique_catalog.py describe palm_mute
```

The instrument authoring index/catalog are normative expectations. The checked-in
`audio_environment_snapshot.json` is observational evidence from the maintainer
workstation. Do not infer that a library is unsupported merely because the
current agent container lacks it.

## 2. Start from v3

With the package environment:

```bash
python -m ambition_music_renderer cue new "New Cue"
```

With only a source checkout:

```bash
python -S dev/new_musicir_v3.py "New Cue"
```

Use high-level intent where it is clearer: harmony, reusable/sequence materials,
generators, form energy/density, techniques, and automation curves. Use literal
exact events whenever a passage is easier to state precisely than to generate.

## 3. Validate before rendering

```bash
python -m ambition_music_renderer cue validate path/to/score.music.yaml
```

Fix structured source diagnostics first. If a generated passage is surprising,
inspect what the compiler actually produced:

```bash
python -m ambition_music_renderer cue graph path/to/score.music.yaml
python -m ambition_music_renderer cue expand path/to/score.music.yaml --clip CLIP_ID
python -m ambition_music_renderer cue trace_event path/to/score.music.yaml EVENT_ID
```

Do not debug by inventing another interpretation of MusicIR. These tools consume
the canonical graph, `CompiledScore`, and instrument-resolution authorities.

## 4. Render and review evidence

Render normally, then combine listening with measurements:

```bash
python -m ambition_music_renderer cue quality path/to/score.music.yaml
python -m ambition_music_renderer cue determinism path/to/score.music.yaml
```

`cue quality` reports density, section/group dynamics, pitch ranges,
recommended-register excursions, register overlap, and repeated-bar evidence.
It does not assign a taste score. Use these measurements to find places worth
listening to, not to replace musical judgment.

When changing instruments, generators, DSP, or mastering intentionally, compare
renders:

```bash
python -m ambition_music_renderer audio compare before.wav after.wav
```

The report includes loudness/peak/crest, stereo, spectral, waveform correlation,
and aligned-difference evidence. Exact PCM equality remains the right gate for
refactors that are supposed to be sonically neutral.

## 5. Revise the musical cause

Prefer fixing the highest-level source construct that explains a problem:

- weak section contrast -> form energy/density or arrangement;
- mechanical repetition -> generator variation/fill behavior or phrase material;
- register collision -> voicing/register/part choice;
- wrong articulation -> technique intent and instrument realization;
- weak sample realization -> stable instrument ref/catalog choice;
- one exact phrase that resists a generator -> lower only that phrase to exact events.

Avoid cue-specific renderer exceptions. If multiple compositions need the same
capability, improve a common v3 semantic, public generator, instrument knowledge,
or processing capability and add a generic test.

## 6. Preserve legacy regeneration

Any change to shared compilation or generation code must keep:

```bash
python dev/check_legacy_regeneration.py
```

green. It compiles every committed v1/v2/implicit-v1 score. For broad shared
compiler changes, generate ephemeral JSON reports from the pre-change and
post-change trees and compare them; do not add named-song fingerprint snapshots
to the test suite.

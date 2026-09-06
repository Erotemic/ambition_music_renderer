# Music quality and regression evidence

The renderer provides measurements to support listening and revision. These
reports intentionally do **not** define a single music-quality score.

## Composition evidence

`cue quality` operates on `CompiledScore`, so it sees the exact canonical notes
and form handed to synthesis:

```bash
python -m ambition_music_renderer cue quality <score>
python -m ambition_music_renderer cue quality <score> --json
```

It currently reports:

- total note count and density;
- velocity range/mean/diversity;
- per-group activity, pitch range, note duration, and dynamics;
- recommended-register excursions from checked-in instrument family guidance;
- per-section density/dynamics/register/group counts;
- register overlap between sufficiently populated groups;
- identical consecutive bar signatures of three or more bars when nominal bar
  metadata is available.

These are review leads. Register overlap can be intentional orchestration;
repetition can be a hook. The report should never turn those observations into
an automatic taste verdict.

Every render manifest also records this deterministic composition evidence.

## Compilation determinism

```bash
python -m ambition_music_renderer cue determinism <score>
```

recompiles the source independently and verifies the compiled fingerprint, note
events, and controller events are identical. Procedural/humanized features must
remain deterministic for a fixed score/seed.

## Before/after audio comparison

For an intentional sonic change:

```bash
python -m ambition_music_renderer audio compare before.wav after.wav
python -m ambition_music_renderer audio compare before.wav after.wav --json
```

The report includes peak/RMS, optional integrated LUFS, crest factor, spectral
centroid and broad bass/mid/high energy fractions, stereo correlation and
side-to-mid energy, aligned waveform correlation, and aligned difference RMS/max.

Use exact PCM comparison for changes expected to be neutral. Use the audio
comparison report plus listening for changes intended to sound better.

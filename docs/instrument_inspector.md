# Instrument Inspector

`./instrument_inspector.sh` is a standalone, score-independent patch browser and
probe auditioner. It deliberately does not own or save a MusicIR score.

It reuses the renderer's existing instrument infrastructure:

- named GM/SoundFont programs, grouped by General MIDI family;
- registered `instrument_libraries.py` aliases, grouped by namespace;
- an optional scan of every installed `.sfz`, grouped by its library/directory hierarchy;
- the same per-instrument backend fields used by MusicIR (`instrument_backend`,
  controls, `mix_gain_db`, note remaps, backend settings, etc.);
- the same built-in group processing and ordered `effect_chain` surface used by
  score `group_postprocess` blocks.

The two YAML editors are authoritative. Clicking a concrete browser entry
immediately applies it to the disposable instrument document and invalidates
any previous probe audio; there is no second load/apply step. Load From Score
copies one instrument definition and that group's processing into the
inspector. Export writes reusable YAML snippets only; it never modifies the
source score.

## Audition phrases

Play means **audition the exact configuration currently shown**. If that
instrument definition, processing YAML, and audition phrase are already
rendered, playback starts immediately. If they are valid but dirty/unrendered,
Play first renders that exact probe and then starts playback automatically.
Any subsequent library selection, YAML edit, root/key change, phrase-template
change, or backend change forgets the old media. An unresolved SFZ selection
cannot be rendered or played as if it were the requested patch. If the
selection changes while a render is running, the completed stale render is not
attached or played.

Pitched instruments default to a repeatable **major scale + arpeggio** phrase.
A natural-minor equivalent and a single-note probe are also available. Drum
kits default to a deliberately plain **two-bar rock backbeat** with MIDI crash
49 on the entrance, eighth-note closed hi-hat, kick, and snare. A kit-essentials
one-shot walk and a single-key probe are also available.

The renderer writes both dry and processed versions under
`agent/instrument_inspector/probes/`, so the transport can A/B the instrument
against its current processing chain.

Effect templates are only starters. Once inserted, edit their YAML directly.
The normal renderer remains the schema authority for Pedalboard, VST3, LV2,
Guitarix/NAM command adapters, built-in EQ/compression/reverb, and wet/dry
parameters.

## Terminal behavior

The Instrument Inspector and Stem Lab install the same Qt SIGINT bridge. Ctrl+C
in the launching terminal closes the window through its normal close handler so
media and child render processes are torn down instead of leaving the Qt event
loop running.

## SFZ diagnostics

For an SFZ selection, the inspector preflights the canonical probe against the
expanded SFZ region map before enabling Render/Play. The diagnostics panel
reports the parsed key span, region count, whether the probe pitches and
velocities can select regions, referenced-sample availability, SFZ `set_cc`
defaults, and controller gates such as `locc107` / `hicc107`.

If every otherwise-eligible region is blocked by a controller value, Render and
Play are disabled instead of producing a known-silent probe. When the allowed
controller range is unambiguous, **Apply suggested controls** adds an explicit
`controls:` entry to the disposable Instrument YAML. The inspector does not
apply inferred controller state to scores or to the renderer globally.

Instrument Inspector renders SFZ probes with strict backend selection. A broken
or silent selected SFZ is therefore reported as that SFZ's failure; it is never
accepted as a successful probe merely because the normal score renderer could
fall back to GM/SoundFont.

## Usage census and browsing cost

For large installed SFZ trees, generate the machine-local usage census with
`./instrument_usage_census.sh`. The Inspector loads it at startup and uses its
compact activation metadata for library browsing and controller suggestions.
This keeps selection changes off the expensive expanded-SFZ parse path. The
full parser remains authoritative when a probe is actually rendered.

## Measured tuning audit

**Audit tuning** is a separate dry-instrument measurement from the normal audition
phrase. For pitched instruments it renders a chromatic/range-covering sweep through
the selected backend, then compares each known MIDI pitch against equal temperament
with A4 = 440 Hz. Because the intended note is known in advance, the estimator only
searches a narrow frequency window around that target instead of asking a generic
pitch detector to guess the fundamental of a bright sample.

The GUI shows an indeterminate progress indicator while the offline sweep and
analysis run. Results are cached by the complete tuning-audit request under
`agent/instrument_inspector/tuning/<request-hash>/`, including the dry WAV, request
JSON, and report JSON. Every note is measured twice: normalized autocorrelation is
the primary period estimate and a harmonic spectral-peak estimator independently
checks the implied fundamental. The report records both estimates, their cents
agreement, a consensus value when they agree, the median offset, range slope, and a
classification such as `centered`, `global_offset`, `range_dependent`, or
`local_outliers_or_mixed`. Notes with at least six cents of measured error are
marked in the text view for quick inspection.

The measurement is deliberately **pre-processing**. EQ, reverb, amp chains, chorus,
and mastering are excluded so the report answers whether the instrument realization
itself is centered. Processing-only YAML edits therefore do not invalidate a tuning
report, while instrument/backend/velocity changes do. The audit never changes the
score or instrument catalog. A global correction value may be suggested when the
measurements support a nearly constant offset, but it is evidence for a later explicit
choice, not an automatic retune.

The same path is available without Qt:

```bash
python -m ambition_music_renderer instruments tuning-audit guitar.emily
python -m ambition_music_renderer instruments tuning-audit guitar.emily --json
```

For a real cue, prefer the score-level batch audit:

```bash
python -m ambition_music_renderer cue tuning-audit standing_on_shoulders_extended_boss
```

That command compiles the cue, finds every pitched instrument that actually emits
notes, skips drums, collapses identical dry realizations, and audits only the MIDI
pitches the score uses. Each audited pitch is rendered at the median velocity used
for that pitch in the cue, which keeps the sweep focused on the sampled layers the
composition is likely to hit. It always dumps `report.json`, `report.txt`, and a
`corrections.yaml` authoring snippet under `agent/tuning_audits/<cue>/<hash>/` unless
`--output-dir` is supplied. The correction snippet is generated only from notes whose
two estimators agree. It proposes a single global cents shift for a clean constant
offset, or a linearly interpolated per-note curve for validated range-dependent/local
drift. It is never applied to the score automatically. The individual realization
measurements continue to use the normal tuning cache, so re-running a batch after an
interrupted or already-completed audit reuses prior measurements. Use `--force` when
the local instrument assets changed and the dry measurements need to be regenerated.

When a proposal is accepted, copy its `tuning_correction` onto the corresponding
MusicIR instrument. Correction happens before audio processing and before sampled
instrument effects. The renderer uses MIDI pitch bend as the synthesis control and
partitions only conflicting simultaneous notes into independent tuning lanes, so
polyphonic curves remain correct without forcing one bend value across a chord.
A scale-aware VST3 effect remains available for intentionally creative pitch
processing, but measured instrument calibration does not require autotune.

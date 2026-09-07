# Ninja zone suite

Two new MusicIR v3 compositions. Existing cues are unchanged. The musical source
is the YAML: explicit note events, named phrases, voicings, bass parts, percussion,
and section-by-section orchestration. No generator or random seed chooses the
melody. Editing a phrase updates its deliberate returns through material references.

## Nine Lives at Midnight

`nine_lives_at_midnight` is the rooftop/action piece: D minor, 128 BPM, 4/4.
Its loop is 96 bars / 3:00; the full soundtrack is 104 bars / 3:15.

The opening idea is a short D, another D, a leap to A, and a descending answer.
The repeated-note rhythm returns in the higher skyline refrain. Shamisen attacks
and koto replies occupy different spaces; bass anticipations and taiko accents
supply motion without asking every instrument to play sixteenth notes. The
courtyard drops to a half-time feel and introduces E-flat before the shamisen
chase leads back to the hook. The last skyline return changes its answer rather
than simply increasing every instrument's volume.

| Full preview | Loop-relative bars | Passage |
| --- | --- | --- |
| 0:00 | Lead-in | Eight-bar threshold, with the hook already present |
| 0:15 | 1-8 | Rooftop hook |
| 0:30 | 9-16 | Hook lift and koto reply |
| 0:45 | 17-32 | Skyline refrain and varied answer |
| 1:15 | 33-40 | Half-time courtyard |
| 1:30 | 41-48 | Shamisen chase, sparse flute answers |
| 1:45 | 49-56 | Hook return |
| 2:00 | 57-64 | Lower shamisen statement, flute replies |
| 2:15 | 65-80 | Skyline return |
| 2:45 | 81-88 | Bass and koto footwork |
| 3:00 | 89-96 | Turn home, then return to loop bar 1 |

## The Last Lantern

`the_last_lantern` is the night/exploration piece: D minor, 96 BPM, 4/4.
Its loop is 64 bars / 2:40; the full soundtrack is 72 bars / 3:00.

It shares the D-D-A identity, but the revision treats 96 BPM as its native
time scale. Harmonic changes last two bars; the bass normally makes one long
footfall per bar; cello lines span bars; koto attacks are isolated lantern
flashes; and the flute phrases are long exhaled tones separated by actual rests.
The shamisen is punctuation instead of a low-density version of the action
groove. The empty bridge removes still more attacks before the garden and
refrain restore motion. This is deliberately different rhythmic architecture
from Nine Lives, not the same architecture with a smaller tempo number.

| Full preview | Loop-relative bars | Passage |
| --- | --- | --- |
| 0:00 | Lead-in | Homeward lantern threshold |
| 0:20 | 1-8 | One lantern in the rain; distant flute only |
| 0:40 | 9-16 | Breath enters over long cello motion |
| 1:00 | 17-24 | The long road |
| 1:20 | 25-32 | Empty bridge |
| 1:40 | 33-40 | Garden after midnight |
| 2:00 | 41-48 | Lantern refrain |
| 2:20 | 49-56 | Footsteps returning |
| 2:40 | 57-64 | Homeward lantern, then loop bar 1 |

## Instruments and mix

Both cues use GM shakuhachi, shamisen, koto, taiko, and a separate restrained drum
part. These are Japanese-inspired game arrangements, not claims of traditional
performance practice. The checked-in sampled-instrument catalog does not provide
those Japanese roles; the GM program choices are intentional.

Nine Lives now requests the required clean `bass.fashion` catalog role rather
than the broader `bass.electric` resolver; the latter resolved to Growlybass in
the first production review and its character was too colored for the part. The
night piece retains `bass.electric`. The action piece uses `strings.violins_1`;
the night piece uses `strings.cello`. Required SFZ roles still fail explicitly
when missing rather than changing instruments.

The first production report also exposed narrow koto energy around 4.1-4.4 kHz
in both cues and a 6.2-7.0 kHz ridge in the night-piece cello patch. The revised
group processing cuts those regions directly instead of globally darkening the
whole mix. Nine Lives also rounds its clean bass with less upper-mid boost and a
lower low-pass; Last Lantern makes the cello more audible after taming its high
ridge. The master requests -16 LUFS for the action piece and -17.5 LUFS for the
night piece. The existing `true_peak_db: -1.5` parameter uses
the renderer's sample-peak cap; it does not certify oversampled true peak or that
the requested integrated loudness is achieved after limiting. Measure the actual
export rather than treating the settings as results.

## Loop playback

The `threshold` section is an exact musical copy of the final eight bars of the
`zone_loop`, including instrumentation, note velocities, durations, and controller
state. Rendering it first supplies release/reverb history to the loop entrance.
The loop ending returns harmonically to the opening; no note extends beyond the
loop boundary. This is source-level preparation, not a guarantee of waveform
continuity for every sample engine or codec.

Render the entire composition with `composition_master`, then use the exported
`adaptive/zone_loop/*.full.ogg` as the repeating zone asset. It is sliced from the
mastered timeline. Do not render the cropped loop from a cold synth. Do not use
the whole `preview/*full_soundtrack.ogg` as the indefinitely repeating asset:
that file includes the threshold once.

For an entry sequence, play the exported threshold once and then the zone loop
on exact section boundaries. This overlay does not alter game zone assignments,
publish assets, or add a runtime transition system. It also does not claim that
arbitrary mid-phrase exits or equal-power crossfades preserve this arrangement.
The native bundle may contain other transition auditions; the new seam audition
specifically tests the untreated end-to-start wrap.

## Render and collect evidence

From the renderer checkout:

```bash
uv run python dev/review_ninja_suite.py --jobs 2
```

The command processes both cues in a new timestamped directory under
`generated/ninja_suite_reviews/`. It prints the two final archive paths:

- `ninja_suite_review.zip`: source, manifests, full previews, exported sections,
  native review/audition stems, numerical reports, and untreated loop-seam WAVs.
- `ninja_suite_report.zip`: compact diagnostics without audio, MIDI, or raw arrays.

The runner invokes the existing `cue bundle` command with `pretty-midi`,
`full-mix-only`, `audition_stems`, and `all_audits`. It adds no synthesis dependency,
does not publish, and does not select a fallback backend. Source validation,
three independent compilations, the loop-input comparison, and a compact pacing
summary (overall notes/second plus mean melody/bass note duration) happen first.
The render manifest must match the score just compiled. The runner measures the
actual decoded loop file and checks its duration and full-scale sample count.
Native audit command failures produce a nonzero result. Warnings are retained
without pretending they are automatic judgments of musical quality.

Completed native bundles are retained even when an audio or audit check fails.
Failure reports and render logs go into the review archives. A failed render
cannot pick up another run's old output, because the destination must be new.
Use a different `--output` directory for another run rather than deleting evidence.

For only the action cue:

```bash
uv run python dev/review_ninja_suite.py --cue nine_lives_at_midnight --jobs 2
```

For source checks without sample libraries:

```bash
uv run python dev/review_ninja_suite.py --score-only
```

Listen to the full preview first. Then listen to `zone_loop_seam.wav`: the actual
wrap is at eight seconds. It contains eight seconds from the exported loop's end
followed by eight from its beginning, with no crossfade, gain change, or repair.
Use `review_stem_*` to assess the relative native group balance; `audition_stem_*`
are individually normalized and should be used for timbre/articulation inspection,
not balance comparisons. The raw rendered stems and mastered mix do not necessarily
sum after nonlinear master processing; they are different inspection surfaces.

## Validation scope

The overlay's new tests use synthetic fixture music. They test generic note/CC
boundary comparisons, malformed audio handling, exact seam concatenation, separate
full/report archives, failure evidence retention, and rejection of reused output
directories. There are no named-song acceptance tests or frozen song fingerprints.

```bash
uv run pytest -q tests/test_loop_review.py tests/test_suite_review_packaging.py
```

The authoring environment verified schema diagnostics, canonical compilation,
three-round determinism, source loop preparation, and a selected existing compiler
and processing test suite. Local GM-only numerical renders used different bass
and strings at 24 kHz; they are structural checks, not production sound-library
validation. The normal SFZ/CLI render still needs the maintainer's audio environment.
Neither source metrics nor those substitutions establish a listening verdict.

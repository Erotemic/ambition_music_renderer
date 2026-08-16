# Piano score fidelity TODO

The public-domain piano reference corpus is now useful for more than demo material: it gives the renderer concrete acceptance pieces for timing, polyphony, voicing, pedal, ornamentation, and expressive interpretation. The renderer already has a strong literal-event core, but source-faithful notation and convincing piano performance are not the same problem.

## Current baseline we should preserve

- Literal `notes` events preserve fractional beat positions and independent note durations.
- Simultaneous polyphony is supported without collapsing voices onto a monophonic grid.
- Tempo maps support point changes and ramps; MIDI export preserves the authored event timeline.
- Dense piano scores can be represented as one instrument/stem, so left hand, inner voices, and melody do not require separate mix buses.
- The reference repertoire gives us real musical regression material instead of synthetic note-grid fixtures.

## Renderer fidelity work

### 1. Ornament semantics

Represent performance meaning rather than leaving engraving ornaments inert.

- Expand trills, turns, mordents, inverted mordents, and written tremolo into deterministic note events.
- Distinguish acciaccatura from appoggiatura and support multi-note grace groups.
- Give ornaments a tempo-aware duration budget and never silently move the following structural onset.
- Preserve the notated upper/lower auxiliary pitch spelling when it matters harmonically.
- Add source-to-event tests using the Chopin nocturne as the primary acceptance piece.

### 2. Arpeggiation semantics

The importer currently approximates written arpeggios with small offsets. Make this an explicit performance primitive.

- Support upward and downward arpeggio direction.
- Support a configurable spread measured in beats or milliseconds.
- Preserve the nominal chord onset separately from performed note offsets.
- Allow cross-staff arpeggios to act as one gesture.
- Ensure arpeggiation does not accidentally change chord duration or pedal release.

### 3. Tuplets and irrational-looking source timing

Literal fractional beats work, but the import path should retain the musical grouping that produced them.

- Preserve tuplet ratios and nested tuplets as authoring metadata.
- Validate exact onset/duration ratios after import and MIDI serialization.
- Add triplet, quintuplet, and mixed-subdivision fixtures.
- Keep notation grouping available for later phrase/performance logic instead of reducing everything immediately to anonymous floats.

### 4. Piano pedal as a first-class performance control

A convincing piano render needs real damper-pedal semantics, not just longer note durations.

- Represent CC64 sustain explicitly in MusicIR and carry it through every compatible backend.
- Model pedal-down, pedal-change, and pedal-up timing independently from note-off timing.
- Support half-pedal values when the backend can express them.
- Add sostenuto/soft-pedal representation only when it has a real backend path; keep unsupported controls explicit rather than pretending.
- Test detached pedal, legato pedal, overlapping harmony changes, and rapid pedal refresh.
- Use Gymnopédie No. 1 and Clair de Lune as primary acceptance pieces for pedal behavior.

### 5. Per-voice dynamics and piano voicing

A score can have correct notes while the melody disappears inside its accompaniment.

- Preserve independent source voices/staves through import rather than flattening them before performance shaping.
- Support per-voice velocity/expression curves.
- Add an optional piano voicing policy that can gently prioritize a designated melody voice without changing its timing or pitch.
- Support balance between outer voices and inner chord tones.
- Preserve explicit accents, sfz/fp/subito markings, and local dynamic resets.
- Use the Chopin nocturne for melody-over-arpeggio balance and Clair de Lune for inner-voice balance.

### 6. Articulation, slur, and phrase semantics

- Preserve staccato, staccatissimo, tenuto, marcato, accents, portato, and phrase/slur groups.
- Convert articulation into backend-independent note-length/attack policies before instrument-specific rendering.
- Allow legato overlap within a voice without creating accidental same-pitch stacking.
- Preserve phrase boundaries as metadata so humanization and rubato can be phrase-aware instead of random.

### 7. Rubato, fermata, and expressive tempo

A static metronome plus note velocities is not a convincing performance model for Chopin or Debussy.

- Support phrase-local tempo curves in addition to global bar ramps.
- Represent fermatas as explicit time expansion at an event/beat.
- Support accelerando/ritardando curves that can be imported from notation and edited in MusicIR.
- Add a deterministic rubato policy that moves a voice and its accompaniment coherently rather than jittering notes independently.
- Keep a strict mode that disables interpretation and proves exact score-time fidelity.

### 8. Repeat/navigation fidelity

- Preserve first/second endings, nested repeats, D.C., D.S., segno, coda, and fine.
- Detect unsupported or ambiguous navigation constructs during import instead of silently linearizing them incorrectly.
- Keep both written-measure coordinates and unfolded playback coordinates available for diagnostics.

### 9. Cross-staff and voice ownership

- Preserve staff/voice identity for notes that cross the grand staff.
- Treat hand assignment as performance metadata, not as pitch-range inference.
- Allow a voice to cross another voice without triggering a false mix/register warning.
- Add diagnostics for actual voice collision separately from intentional contrapuntal crossing.

### 10. Piano backend realism

Once notation semantics are correct, improve what the piano backend can actually express.

- Verify key-release samples and pedal resonance behavior in the selected SFZ library.
- Evaluate sympathetic resonance support and expose it only where the backend supports it.
- Avoid per-hand EQ as a substitute for correct voicing; prefer one coherent piano signal path.
- Keep normalization/mastering from turning an intentionally quiet piano performance into a hyper-compressed one.
- Report excessive makeup/normalization gain in the render bundle so low authored levels are visible.

## Acceptance repertoire

Use these pieces as targeted regression tests rather than only listening examples:

- **Ode to Joy** — exact nonuniform note timing, simple polyphony, MIDI round-trip.
- **Maple Leaf Rag** — syncopation against an independent left hand, jumps, repeated strains, articulation clarity.
- **The Entertainer** — long-form ragtime repeat/navigation behavior and dense syncopated independence.
- **Gymnopédie No. 1** — wide-register voicing, chord/melody balance, pedal changes, quiet dynamics.
- **Clair de Lune** — compound rhythmic texture, inner voices, arpeggiation, pedal, tempo shaping, large density changes.
- **Nocturne in E-flat Major, Op. 9 No. 2** — ornamentation, melody-over-accompaniment voicing, rubato, grace notes, phrase dynamics.

## Validation strategy

For each reference piece, keep two distinct correctness targets:

1. **Strict score-time mode**: deterministic expansion of the source notation into a canonical event timeline. This is where exact event fingerprints, source-to-MIDI round trips, and timing assertions belong.
2. **Performance mode**: deterministic but musical interpretation layered on top of the canonical events. This is where pedal, voicing, articulation, ornament realization, and rubato are evaluated.

Do not claim total score fidelity merely because the right pitches exist somewhere in the MIDI. Bundle reports should identify notation constructs that were approximated, ignored, or interpreted.

## Definition of done

The renderer does not need to imitate one famous recording. It should be able to reconstruct the *score* without losing musical information, then apply an explicit and controllable performance interpretation. A reference piece is ready when a knowledgeable listener can attribute remaining differences to interpretation choices rather than missing notation semantics, incorrect timing, accidental register collisions, or mix workarounds.

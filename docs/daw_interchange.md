# DAW interchange direction

The renderer now has a DAW-neutral interchange boundary intended for Ardour,
REAPER, and other mature MIDI editors. The design deliberately does not make a
DAW project file a second source of musical authority.

## Current export

```bash
python -m ambition_music_renderer cue daw_export <cue> --destination /tmp/daw
```

writes:

```text
<cue>.mid
<cue>.musicir-interchange.json
```

The MIDI file is the editable transport. The JSON file is the MusicIR provenance
sidecar.

For MusicIR v2/v3, the MIDI writer uses the exact score tick clock directly. It
writes:

- one conductor track;
- time-signature changes;
- tempo changes;
- sampled Standard-MIDI tempo events for MusicIR tempo ramps;
- form markers;
- one named track per compiled instrument;
- program changes, CCs, pitch bends, and notes.

This fixes an important interoperability limitation of writing exact scores back
through PrettyMIDI's seconds-domain clock.

V1 continues to use the historical marked-MIDI preview because its source clock
is not tick-authoritative.

## Why a sidecar is required

Standard MIDI can preserve musical events and track names well, but it has no
portable mechanism that Ardour and REAPER can both be expected to preserve for
MusicIR source identities on every note. MusicIR v3 therefore emits stable
`event_id` / `source_ref` information in the sidecar.

The sidecar records:

- source and canonical MusicIR schema;
- `CompiledScore` fingerprint;
- v3 authoring-graph fingerprint when available;
- track/instrument/group identity;
- exact baseline note ticks and velocities;
- stable v3 source mappings;
- compiled form metadata; and
- MIDI representability notes.

The sidecar is not generated music authority. It is a reconciliation baseline
for a future importer.

## Round trip status

The current direction is:

```text
MusicIR
  -> CompiledScore
  -> exact MIDI + provenance sidecar
  -> Ardour / REAPER editing
```

Automatic edited-MIDI-to-MusicIR reconciliation is intentionally not implemented
yet. The next stage can compare the returned MIDI against the sidecar baseline
and classify edits such as:

- unchanged source event;
- moved/resized note;
- velocity edit;
- pitch edit;
- deleted source event;
- newly added DAW event; and
- controller/automation changes.

V3's clip/material/event provenance gives that importer somewhere stable to
apply edits. If a DAW edit destroys the higher-level intent of a generated clip,
the importer can lower only that clip to explicit events rather than flattening
the whole composition.

That is the intended escape hatch: generated structure remains generated when
possible; edited passages can become literal notation when necessary.

## Holds and tempo ramps

MusicIR's exact clock can express timing that ordinary SMF cannot encode as one
native event. Tempo ramps are sampled into sufficiently dense `set_tempo`
events for DAW playback, while the exact MusicIR timing remains in the source
and interchange metadata. Score holds are marked in the MIDI conductor track;
the sidecar remains authoritative because SMF has no direct "pause score time
for N seconds" event.

A future DAW-specific adapter may use richer automation features, but that should
sit outside the DAW-neutral interchange model.

## Controller provenance

MusicIR v3 clip automation points are included in the interchange sidecar as
baseline `controls` and `pitch_bends` on their instrument track. Authored points
carry the same stable source coordinates used by notes, so a future importer can
distinguish a DAW edit to an authored expression/pitch-bend point from an
instrument's implicit t=0 controller initialization.

The sidecar reports `roundtrip.controller_source_mapping` independently from
note mapping because v1/v2 and backend initialization can legitimately contain
controller events with no v3 source id.

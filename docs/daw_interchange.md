# DAW interchange and round trip

MusicIR remains the source of musical authority. Standard MIDI is the editable
transport used by Ardour, REAPER, and other DAWs; the adjacent JSON sidecar is
the reconciliation baseline that preserves MusicIR identities MIDI cannot carry
portably.

Ardour is the primary DAW target. REAPER remains a secondary interoperability
target through the same DAW-neutral MIDI/sidecar boundary. DAW-specific project
adapters come after the generic reverse path is reliable.

## Current workflow

Export a v3 cue:

```bash
python -m ambition_music_renderer cue daw_export <cue> --destination /tmp/<cue>-daw
```

This writes:

```text
<cue>.mid
<cue>.musicir-interchange.json
```

Import `<cue>.mid` into Ardour, make MIDI performance edits, then export the
edited MIDI from Ardour. Keep the original interchange JSON; it describes the
baseline that the edited MIDI came from.

Inspect the edit without changing MusicIR:

```bash
python -m ambition_music_renderer cue daw_reconcile <cue> \
    --midi /tmp/<cue>-edited.mid \
    --manifest /tmp/<cue>-daw/<cue>.musicir-interchange.json \
    --output /tmp/<cue>-reconciliation.json
```

For a supported reconciliation, write a new MusicIR source:

```bash
python -m ambition_music_renderer cue daw_apply <cue> \
    --midi /tmp/<cue>-edited.mid \
    --manifest /tmp/<cue>-daw/<cue>.musicir-interchange.json \
    --output /tmp/<cue>.daw.music.yaml \
    --report /tmp/<cue>-apply.json
```

Use `--in-place` only after reviewing reconciliation evidence. `daw_apply`
recompiles the proposed MusicIR and verifies that the resulting note events
reproduce the edited MIDI before it writes the YAML.

If the MusicIR source changed after the DAW export, reconciliation refuses the
stale baseline and asks for a fresh export. The comparison checks both the
compiled-score fingerprint and v3 authoring-graph fingerprint.

## Landed reverse-path stages

### Stage 1: note reconciliation and clip lowering

`daw_reconcile` classifies note events as:

- unchanged;
- moved;
- resized;
- repitched;
- velocity changed;
- deleted; or
- added.

DAWs may rewrite the MIDI PPQ. Imported coordinates are therefore rescaled onto
the sidecar's original PPQ before matching. Non-integral rescaling is reported
as quantization evidence instead of being hidden.

The sidecar includes source regions for v3 clips. Existing notes retain stable
`event_id` / `source_ref` mappings. A newly drawn note can be assigned to a clip
when exactly one source region owns its coordinate, or when the track contains
only one source region. Ambiguous additions stop automatic apply.

When an edit is applied, the smallest currently supported mutation unit is one
v3 clip. An affected exact/material/generated clip is lowered to explicit exact
events containing the final DAW pitches, ticks, durations, and velocities.
Unedited clips and reusable materials remain unchanged. A repeated or generated
clip is expanded only when that clip has actually been hand-edited.

This is intentionally preferable to storing a permanent DAW override layer: the
MusicIR file remains sufficient to regenerate the result.

### Stage 2: clip-owned CC and pitch-bend reconciliation

Clip automation exported with stable v3 provenance can now be moved, changed,
deleted, or added through the same reconciliation path. When the owning clip is
lowered, its final automation is emitted as literal v3 automation points.

Renderer initialization CCs that have no MusicIR source identity are reported as
transport-level changes but are not mistaken for authored automation. A
controller edit with no unique v3 clip owner blocks source application rather
than being discarded.

### Stage 3: conductor reconciliation

`daw_reconcile` now emits event-level conductor diffs plus a semantic apply plan.
Supported conductor edits include:

- ordinary step-tempo insertions/deletions/moves/value changes;
- meter maps whose changes remain on exact bar boundaries at the score PPQ;
- form-marker moves and label edits without changing form topology;
- edits to an existing sampled MusicIR tempo ramp when the edited samples still
  fit a supported compact curve; and
- newly drawn dense monotone tempo ramps when the MIDI samples fit a linear or
  exponential curve tightly enough to infer intent.

Existing MusicIR ramp boundaries are baseline-guided. Moving a ramp boundary is
currently refused instead of guessing where a DAW's sampled run begins or ends.
Likewise, adding/deleting form markers is a form-topology edit and requires manual
resolution for now.

MusicIR holds remain source/sidecar-authoritative. If surrounding tempo changes,
the hold is re-anchored with the reconstructed BPM in force at its tick so the
hold does not accidentally restore the old tempo. `daw_apply` recompiles the
result and verifies note ticks, meter/markers, and the reconstructed tempo clock
before writing.

## Next large stages

### Stage 4: Ardour session adapter

Once conductor reconciliation is dependable, add an Ardour-first convenience
adapter around the neutral interchange core. The intended job is session setup,
not new musical authority. Likely outputs are an Ardour session scaffold,
reference full mix/stems, track naming/routing, and a scripted export location
that points back to `daw_reconcile` / `daw_apply`.

REAPER support should consume the same interchange/reconciliation objects and
receive a thinner adapter after the Ardour workflow has been exercised.

### Stage 5: source-preserving patch quality

The current apply writer emits clean YAML from the structural MusicIR mapping.
A later source-location-aware writer can minimize textual diffs and preserve
comments/formatting while retaining the same reconciliation semantics. It must
not become a second parser or change compilation behavior.

## Exact MIDI export

For MusicIR v2/v3, the writer uses the exact score tick clock directly. It
writes:

- one conductor track;
- time-signature changes;
- tempo changes;
- sampled Standard-MIDI tempo events for MusicIR tempo ramps;
- form markers;
- one named track per compiled instrument;
- program changes, CCs, pitch bends, and notes.

V1 continues to use the historical marked-MIDI preview because its source clock
is not tick-authoritative. V1/v2 can be reconciled for inspection, but automatic
source application currently requires v3 provenance.

## Why the sidecar is required

Standard MIDI can preserve musical events and track names, but it has no
portable mechanism that Ardour and REAPER can both be expected to preserve for
MusicIR source identities on every note. The sidecar records:

- source and canonical MusicIR schema;
- `CompiledScore` fingerprint;
- v3 authoring-graph fingerprint;
- MIDI PPQ and exact-clock status;
- conductor baseline;
- exact meter changes, compact tempo segments, holds, and score end tick;
- track/instrument/group identity and MIDI track index;
- exact baseline note ticks and velocities;
- stable v3 note/controller source mappings;
- v3 clip source regions used to classify additions;
- compiled form metadata; and
- representability notes for tempo ramps and holds.

The sidecar is reconciliation evidence, not generated-music authority.

## Holds and tempo ramps

MusicIR's exact clock can express timing that ordinary SMF cannot encode as one
native event. Tempo ramps are sampled into dense `set_tempo` events for DAW
playback, while the exact MusicIR timing remains in source and interchange
metadata. Score holds are marked in the MIDI conductor track; the sidecar remains
authoritative because SMF has no direct "pause score time for N seconds" event.

Stage 3 therefore treats the MIDI conductor as an editable transport surface
and reconstructs compact MusicIR timing semantics only when the mapping is
well-supported by the samples and sidecar baseline. Ambiguous ramp boundaries,
non-bar-aligned meter changes, and form-topology changes stop automatic apply.

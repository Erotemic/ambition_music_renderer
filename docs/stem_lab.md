# Stem Lab

Stem Lab is a standalone, read-only music-authoring frontend for comparing and recombining already-rendered stems across score variants. It is deliberately separate from the music review bank: it does not read or write ratings, pairwise judgments, review history, or review discovery state.

Launch it from the music renderer root:

```bash
./stem_lab.sh --cue standing_on_shoulders
```

## Working model

The version library discovers normal generated renders plus scratch variants under `agent/**/renders/*`. Use **Add render folder...** for another render tree. The on-disk library and the loaded working set are distinct: only loaded versions appear as stem sources. A reference is optional; labels containing `canonical_original`, `baseline`, `reference`, or `original` are offered as the initial reference when present. A new composition can leave the reference as `none`.

Each stem row has an enable toggle and a source-version selector. Changing a route rebuilds only a temporary playback mix from existing audio; score YAML is never modified. At cue load, the newest/current variant supplies every stem it has, while the reference fills groups that are absent from the current variant.

The transport is a reusable bottom transport rather than controls embedded in the routing tables. It provides a standard start / play-pause / stop cluster, a seek bar above it, volume, and the listening-source selector. Click anywhere on the seek bar to jump, drag it to scrub, or press Space to play/pause. Switching listening sources preserves the playhead. If playback is active, Stem Lab keeps the old source playing while a routed mix is rebuilt, then resumes the replacement source at the current position. The transport tracks user playback intent separately from Qt's temporary loading/stopped states, so its play/pause button stays coherent during source replacement.

## Read-only note view

The lower-right pane is a piano-roll view synchronized to the shared playhead. Notes are colored by stem group and retain their expanded renderer metadata: instrument, section, layer, pitch, velocity, and exact start/end time. The section/bar ruler is a separate widget above the note viewport, synchronized to its horizontal transform and scrollbar; ruler labels therefore never cover notes and update as the view scrolls or zooms. Clicking empty piano-roll space seeks playback; clicking a note only inspects it.

## Stem inspector and semantic diff

Stem routing and stem inspection are separate surfaces. Selecting a routing row focuses that stem in the inspector without changing its route. The inspector compares any two loaded versions that contain the stem and shows both the expanded instrument names and the authored instrument definitions from each render snapshot when available. Legacy variants fall back to their live score and are labeled accordingly.

The note diff compares expanded musical events rather than YAML text. Instrument identity is intentionally excluded from note equality, so a patch swap does not make every unchanged note look rewritten. Events are classified as unchanged, changed in the same musical slot, removed, or added. **Show note diff in piano roll** displays only that stem: unchanged events are dim, removed events use a dashed outline, added events use a strong solid outline, and changed events use a dash-dot outline. The diff remains read-only.

New renders persist two semantic authoring artifacts under the render directory:

- an immutable snapshot of the score file used for that render;
- a compact note-timeline JSON generated from the renderer's expanded note events.

The adaptive manifest points at both artifacts and records the snapshot SHA-256. This keeps the visualization tied to the audio that was actually rendered even if the live score later changes.

Older scratch renders remain inspectable when Stem Lab can locate their source score. That fallback is labeled **live source** and **not exact for render**, because the file may have changed since the audio was produced. Rerendering creates exact timeline provenance.

For a routed hybrid, Stem Lab combines only the notes belonging to the selected stem from each selected version. If those versions disagree on tempo/bar or section boundaries, the piano roll falls back to absolute time instead of drawing a misleading common musical grid.

## Audio fidelity and fast iteration

For the most faithful cross-version balance, render variants with `--audition-stems`. New renders emit compact `review_stem_<group>.ogg` files that preserve relative stem levels, plus normalized `audition_stem_<group>.ogg` files intended for solo listening. Retained `scratch_stems/*.npy` buffers are preferred when present. Older renders that only have normalized audition stems remain usable, but Stem Lab labels those assets as normalized fallbacks and warns against using that hybrid mix for balance judgments.

For repeated A/B score edits, `--stem-cache` can reuse content-identical rendered groups across sibling variants. The cache is renderer infrastructure and is independent of Stem Lab and the review bank.

## Editing boundary

Stem Lab is intentionally read-only for now. The render snapshot is provenance evidence, not an editor document, and the Qt widgets have no source-save operation.

If editing is added later, keep the boundary explicit:

1. Create a separate working document from a chosen snapshot or score.
2. Apply edits only to that working document and show the resulting diff/dirty state.
3. Export or **Save As** a new score variant; never overwrite the render snapshot.
4. Treat replacing/promoting a canonical score as a separate explicit publish operation.

That keeps direct manipulation useful without introducing a second authored truth or making exploratory audition capable of overwriting an accepted score.


## Stem selection and diff baseline

- **Select all** and **Select none** beside Stem routing enable or disable every routable stem in one action.
- The Stem inspector's **Main** side is always the source version currently routed for the selected stem. It is not an independent selector. **Compare with** chooses the alternate loaded version. This keeps the semantic diff anchored to the audio source that the routing table identifies as main for that stem.
- Checkable controls expose their state in their label. For example, the piano-roll comparison control reads **Note diff: OFF** or **Note diff: ON** in addition to the platform's checked-button styling.

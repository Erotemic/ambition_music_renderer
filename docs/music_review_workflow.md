# Music review bank

Ambition's music renderer includes a human review bank for answering a question
that raw render/audit metrics cannot: **which tracks are actually good, which
ones are merely acceptable, and which earlier versions were better?**

## Launch

From the music renderer project:

```bash
./review_music.sh
```

The wrapper supplies PySide6 ephemerally through `uv --with`, so the core music
renderer does not acquire Qt as a mandatory dependency.

Useful options:

```bash
./review_music.sh --cue many_names_one_hall
./review_music.sh --check
```

The GUI scans `generated/<cue>/.versioned/<hash>/` and the latest symlink. It
shows all locally playable historical versions, not only the newest one.

## Exact-version identity

A saved rating is keyed by the renderer hash **and** SHA-256 of the mastered
preview file. This means feedback never silently migrates to a different audio
render simply because both renders share a cue id.

The same exact identity is used for pairwise comparisons. A comparison is an
unordered pair, so choosing A over B and later editing the judgment while B is
selected updates the same comparison record.

## 1–10 decimal rating scale

The score is continuous from 1.0 through 10.0. Decimal values are accepted.
The broad labels are deliberately semantic rather than pretending that every
0.1 step has a different verbal meaning:

- 1.0–2.99: Replace
- 3.0–4.99: Major polish
- 5.0–6.99: Acceptable
- 7.0–8.99: Strong
- 9.0–10.0: Standout

The repository's original 1–5 ratings are migrated by multiplying them exactly
by two. Thus a previous 3 remains semantically Acceptable as 6, a 4 becomes 8,
and a 5 becomes 10. Legacy v1 review files are also interpreted this way if one
arrives from another branch before it has been migrated.

Saving a changed score, notes field, or issue selection on the same exact
render edits the existing review **in place**. It does not add another rating to
an opinion history. The review's creation timestamp is retained while its
update timestamp changes.

Selecting an unrated render resets the score to `Unrated` and clears notes and
issue checkboxes. Form state is never carried over from the previously selected
track.

## Pairwise ranking

The right-hand comparison panel lets the reviewer audition another exact
rendered version and record one of three outcomes:

- current version is better;
- approximately equal;
- comparison version is better.

These judgments are separate from 1–10 ratings. That permits later analysis to
say, for example, that two tracks are both 8-ish while still recording which
one is preferred.

The cue table displays the latest exact version's pairwise rank and W/L/T
record when comparisons exist. Headless tooling reports the whole version-level
ranking. The ranking is intentionally cycle-tolerant: one point per win, half a
point per tie, sorted by observed point rate and then net wins/comparison count.

## Review provenance

Issue checkboxes make notes searchable at a coarse level: composition,
arrangement, instrumentation, mix/master, loop/repetition, game-fit, and
technical/render. The freeform note records what a future pass should preserve
or change.

The player records the furthest position reached while actual playback was
running as lightweight provenance. Seeking by itself does not count as
listening. Pairwise playback of the comparison track does not alter the current
track's listening-progress provenance.

## Headless queries for agents

Future agents do not need Qt to consume the feedback:

```bash
python -m ambition_music_renderer.music_review_cli rubric
python -m ambition_music_renderer.music_review_cli summary --include-unrated
python -m ambition_music_renderer.music_review_cli summary --needs-polish
python -m ambition_music_renderer.music_review_cli summary --needs-polish --json
python -m ambition_music_renderer.music_review_cli pairwise
python -m ambition_music_renderer.music_review_cli pairwise --json
```

If a branch still contains legacy 1–5 review documents, rewrite them in place
without creating new opinions:

```bash
python -m ambition_music_renderer.music_review_cli migrate-legacy
```

Review and comparison YAML is intended to be committed. Generated previews
remain gitignored; the durable records keep the exact audio checksum and render
identity after those local files are cleaned.

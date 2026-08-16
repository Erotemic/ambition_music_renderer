# Music review bank

Ambition's music renderer includes a human review bank for answering a question
that raw render/audit metrics cannot: **which tracks are actually good?**

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

## Review model

A saved review is keyed by the renderer hash **and** SHA-256 of the mastered
preview file. This means a rating never silently migrates to a different audio
render simply because both renders share a cue id.

The five-point rubric is deliberately semantic rather than a vague star score:

1. Replace
2. Major polish
3. Acceptable
4. Strong
5. Standout

The main cue list shows the latest exact-version score and the best historical
score side-by-side. A future polish pass can therefore distinguish "this cue
has always been mediocre" from "the latest rewrite regressed from a version we
loved."

Issue checkboxes make notes searchable at a coarse level: composition,
arrangement, instrumentation, mix/master, loop/repetition, game-fit, and
technical/render. The freeform note is where the human records what to preserve
or change.

The player records the furthest position reached while actual playback was running as lightweight provenance. It is not a coverage meter or a gate: seeking does not by itself count as listening, and the user may deliberately rate a short sample.

## Headless queries for agents

Future agents do not need Qt to consume the feedback:

```bash
python -m ambition_music_renderer.music_review_cli rubric
python -m ambition_music_renderer.music_review_cli summary --include-unrated
python -m ambition_music_renderer.music_review_cli summary --needs-polish
python -m ambition_music_renderer.music_review_cli summary --needs-polish --json
```

Review YAML is intended to be committed. Generated previews remain gitignored;
the review document keeps the exact audio checksum and render identity after
those local files are cleaned.

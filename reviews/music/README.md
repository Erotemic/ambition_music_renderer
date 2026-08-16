# Human music reviews

This directory stores durable feedback about **exact rendered versions** of
Ambition music. The PySide6 review tool writes one YAML document per audible
version under:

```text
reviews/music/<cue>/<render-hash>--<preview-sha-prefix>.review.yaml
```

A cue name alone is intentionally not enough. Every review records both the
renderer hash and SHA-256 of the mastered preview bytes that the human actually
heard. Old reviews therefore remain valid historical evidence after a score is
rewritten or rerendered.

## Quality rubric

| Score | Label | Meaning |
|---|---|---|
| 1 | Replace | Placeholder or actively weak; prefer a rewrite. |
| 2 | Major polish | Works provisionally; prioritize substantial revision. |
| 3 | Acceptable | Good enough for now, but an obvious later polish candidate. |
| 4 | Strong | Ship-quality; change only for a concrete reason. |
| 5 | Standout | Benchmark/favorite; preserve its identity and use as a quality reference. |

The GUI also records freeform notes, structured issue tags, and the furthest playback position reached. Saving an updated opinion on the same
exact render preserves the previous value in the document's `history` array.

Agents should prefer the rating attached to the latest rendered version when
planning polish work, while also consulting `best_version_id` to avoid losing a
historically stronger arrangement.

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

## Quality scale

Ratings are continuous from **1.0 through 10.0**. Decimal values are allowed;
the GUI steps by 0.1 and accepts typed values with two decimal places.

| Score band | Label | Meaning |
|---|---|---|
| 1.0–2.99 | Replace | Placeholder or actively weak; prefer a rewrite. |
| 3.0–4.99 | Major polish | Works provisionally; prioritize substantial revision. |
| 5.0–6.99 | Acceptable | Good enough for now, but an obvious later polish candidate. |
| 7.0–8.99 | Strong | Ship-quality; change only for a concrete reason. |
| 9.0–10.0 | Standout | Benchmark/favorite; preserve its identity and use as a quality reference. |

The original review bank used a 1–5 scale. Legacy v1 review data is interpreted
as an exact `score * 2`, and the repository migration rewrites existing ratings
that way: 3 becomes 6, 4 becomes 8, and 5 becomes 10. Notes, issue tags,
playback provenance, timestamps, and exact render identities are preserved.

Saving again on the same exact rendered version **edits that rating in place**.
It does not append another opinion or create a new review-history entry. A new
audio SHA or renderer hash is a new subject and therefore gets its own review.

## Pairwise judgments

Pairwise comparisons are stored separately under:

```text
reviews/music/_comparisons/<pair-id>.comparison.yaml
```

Each comparison identifies both exact rendered versions by renderer hash and
full preview SHA-256. The pair is unordered for identity purposes, so comparing
A to B and later B to A edits the same record instead of creating duplicates.
The outcome is A better, B better, or approximately equal.

Ranking reports use observed pairwise points: one point for a win and half a
point for a tie. They sort by pairwise point rate, then net wins and comparison
count. Cycles are allowed and remain visible in each version's W/L/T record;
there is intentionally no requirement for a Condorcet-consistent global order.

Agents should use both signals when planning polish work: the numeric score is
the absolute quality judgment, while pairwise history captures relative
preferences that may be easier to make reliably between close alternatives.

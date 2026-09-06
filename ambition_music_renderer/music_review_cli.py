"""Headless queries over human music review and pairwise comparison data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .music_reviews import (
    POLISH_THRESHOLD,
    RUBRIC_BANDS,
    ReviewStore,
    cue_summary,
    discover_render_versions,
    discover_score_sources,
    format_score,
    pairwise_rankings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect version-exact human reviews of Ambition music")
    parser.add_argument("--project-root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="Print a cue-level score and pairwise-ranking summary")
    summary.add_argument("--json", action="store_true")
    summary.add_argument(
        "--needs-polish",
        action="store_true",
        help=f"Show reviewed latest versions scoring 1–{POLISH_THRESHOLD:g} first",
    )
    summary.add_argument("--include-unrated", action="store_true")

    pairwise = sub.add_parser("pairwise", help="Rank exact rendered versions from recorded pairwise comparisons")
    pairwise.add_argument("--json", action="store_true")

    sub.add_parser("rubric", help="Print the 1–10 review rubric")
    sub.add_parser("migrate-legacy", help="Rewrite legacy 1–5 review files as exact 2x scores on the 1–10 scale")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.project_root
    store = ReviewStore(root)

    if args.command == "rubric":
        for low, high, label, description in RUBRIC_BANDS:
            print(f"{low:g}–{high:g}  {label:<12} {description}")
        return 0

    if args.command == "migrate-legacy":
        changed = store.migrate_legacy_reviews()
        for path in changed:
            try:
                print(path.relative_to(store.project_root))
            except ValueError:
                print(path)
        print(f"migrated {len(changed)} review file(s)")
        return 0

    if args.command == "pairwise":
        rows = pairwise_rankings(store.load_comparisons())
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        print("rank  pair  W-L-T    comparisons  cue / exact version")
        print("----  ----  -------  -----------  ---------------------------------------------")
        for row in rows:
            pct = "-" if row["pairwise_score"] is None else f"{row['pairwise_score'] * 100:4.1f}%"
            record = f"{row['wins']}-{row['losses']}-{row['ties']}"
            print(
                f"{row['rank']:>4}  {pct:>5}  {record:<7}  {row['comparisons']:>11}  "
                f"{row['cue_id']} / {row['version_id']}"
            )
        return 0

    versions = discover_render_versions(root)
    sources = {cue: source for cue, source in discover_score_sources(root).items() if source.scope == "active"}
    rows = cue_summary(versions, store.load_all(), sources, store.load_comparisons())
    if args.needs_polish:
        rows.sort(key=lambda row: (row["latest_score"] is None, row["latest_score"] or 99, row["cue_id"]))
        if not args.include_unrated:
            rows = [
                row
                for row in rows
                if row["latest_score"] is not None and row["latest_score"] <= POLISH_THRESHOLD
            ]
    elif not args.include_unrated:
        rows = [row for row in rows if row["latest_score"] is not None]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print("score  best  pair-rank  W-L-T    reviews  cue                              verdict")
    print("-----  ----  ---------  -------  -------  -------------------------------  ------------")
    for row in rows:
        pair_rank = "-" if row["latest_pairwise_rank"] is None else str(row["latest_pairwise_rank"])
        pair_record = f"{row['latest_pairwise_wins']}-{row['latest_pairwise_losses']}-{row['latest_pairwise_ties']}"
        print(
            f"{format_score(row['latest_score']):>5}  {format_score(row['best_score']):>4}  "
            f"{pair_rank:>9}  {pair_record:<7}  {row['reviewed_versions']:>7}  "
            f"{row['cue_id'][:31]:<31}  {row['latest_label']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

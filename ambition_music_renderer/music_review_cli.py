"""Headless queries over human music review data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .music_reviews import RUBRIC, ReviewStore, cue_summary, discover_render_versions, discover_score_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect version-exact human reviews of Ambition music")
    parser.add_argument("--project-root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summary", help="Print a cue-level review/ranking summary")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--needs-polish", action="store_true", help="Show reviewed latest versions scoring 1-3 first")
    summary.add_argument("--include-unrated", action="store_true")
    sub.add_parser("rubric", help="Print the 1-5 review rubric")
    return parser


def _score_text(value: int | None) -> str:
    return "-" if value is None else str(value)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "rubric":
        for score, (label, description) in RUBRIC.items():
            print(f"{score}  {label:<12} {description}")
        return 0
    root = args.project_root
    versions = discover_render_versions(root)
    store = ReviewStore(root)
    sources = {cue: source for cue, source in discover_score_sources(root).items() if source.scope == "active"}
    rows = cue_summary(versions, store.load_all(), sources)
    if args.needs_polish:
        rows.sort(key=lambda row: (row["latest_score"] is None, row["latest_score"] or 99, row["cue_id"]))
        if not args.include_unrated:
            rows = [row for row in rows if row["latest_score"] is not None and row["latest_score"] <= 3]
    elif not args.include_unrated:
        rows = [row for row in rows if row["latest_score"] is not None]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print("score  best  reviews  cue                              verdict")
    print("-----  ----  -------  -------------------------------  ------------")
    for row in rows:
        print(
            f"{_score_text(row['latest_score']):>5}  {_score_text(row['best_score']):>4}  "
            f"{row['reviewed_versions']:>7}  {row['cue_id'][:31]:<31}  {row['latest_label']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

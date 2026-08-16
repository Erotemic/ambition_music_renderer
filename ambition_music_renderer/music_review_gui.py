"""Launcher for the optional PySide6 music review GUI.

Qt is imported only when the GUI actually starts.  The ``--check`` path and all
review data-model tooling remain usable in minimal/headless environments.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from ._paths import project_root as default_project_root
from .music_reviews import ReviewStore, discover_render_versions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview and rate exact rendered versions of Ambition music")
    parser.add_argument("--project-root", type=Path, help="music-renderer project root; normally auto-detected")
    parser.add_argument("--review-root", type=Path, help="override reviews/music storage directory")
    parser.add_argument("--cue", help="select this cue on startup")
    parser.add_argument("--check", action="store_true", help="scan versions/reviews without starting Qt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project_root or default_project_root()).resolve()
    versions = discover_render_versions(root)
    store = ReviewStore(root, args.review_root)
    if args.check:
        print(f"project: {root}")
        print(f"playable render versions: {len(versions)}")
        print(f"review records: {len(store.load_all())}")
        print(f"pairwise comparison records: {len(store.load_comparisons())}")
        print(f"review root: {store.review_root}")
        return 0
    try:
        from .music_review_gui_qt import run_gui
    except ImportError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise SystemExit(
                "PySide6 is required for the interactive review GUI.\n"
                "Run via ./review_music.sh, or install PySide6 into the music-renderer environment."
            ) from exc
        raise
    return run_gui(project_root=root, review_root=store.review_root, initial_cue=args.cue)


if __name__ == "__main__":
    raise SystemExit(main())

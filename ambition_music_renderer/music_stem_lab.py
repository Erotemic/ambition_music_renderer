"""Launcher for the optional standalone PySide6 Stem Lab."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from ._paths import project_root as default_project_root
from .music_audition import discover_versions, discover_versions_from_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audition hybrid mixes assembled from stems across rendered music variants"
    )
    parser.add_argument("--project-root", type=Path, help="music-renderer project root; normally auto-detected")
    parser.add_argument("--cue", help="select this cue on startup")
    parser.add_argument(
        "--library",
        type=Path,
        action="append",
        default=[],
        help="also discover render variants under this folder (repeatable)",
    )
    parser.add_argument("--check", action="store_true", help="scan available versions/stems without starting Qt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project_root or default_project_root()).resolve()
    versions = discover_versions(root)
    for library in args.library:
        versions.extend(discover_versions_from_path(library))
    # The Qt window performs the same deterministic de-duplication after manual
    # folder additions; for check mode a stable unique key is sufficient.
    unique = {version.key: version for version in versions}
    versions = sorted(unique.values(), key=lambda v: (v.cue_id, -v.generated_at, v.label.lower()))
    if args.check:
        cues = sorted({version.cue_id for version in versions})
        print(f"project: {root}")
        print(f"stem-lab render versions: {len(versions)}")
        print(f"cues: {len(cues)}")
        for cue_id in cues:
            count = sum(version.cue_id == cue_id for version in versions)
            print(f"  {cue_id}: {count}")
        return 0
    try:
        from .music_stem_lab_qt import run_gui
    except ImportError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise SystemExit(
                "PySide6 is required for Stem Lab.\n"
                "Run via ./stem_lab.sh, or install PySide6 into the music-renderer environment."
            ) from exc
        raise
    return run_gui(project_root=root, versions=versions, initial_cue=args.cue)


if __name__ == "__main__":
    raise SystemExit(main())

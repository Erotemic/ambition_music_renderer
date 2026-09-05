"""Standalone launcher for the music instrument inspector/auditioner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ._paths import project_root as default_project_root
from .music_instrument_inspector_model import render_probe_request_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Browse music instruments, edit YAML-backed patch/effect settings, and render disposable probes"
    )
    parser.add_argument("--project-root", type=Path, help="music-renderer project root; normally auto-detected")
    parser.add_argument("--render-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true", help="validate imports/catalog model without opening Qt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project_root or default_project_root()).resolve()
    if args.render_request:
        result = render_probe_request_file(args.render_request)
        print(json.dumps(result.report, sort_keys=True))
        return 0
    if args.check:
        from .music_instrument_inspector_model import alias_library_entries, gm_library_entries
        print(f"project: {root}")
        print(f"GM programs: {len(gm_library_entries())}")
        print(f"SFZ aliases: {len(alias_library_entries())}")
        return 0
    try:
        from .music_instrument_inspector_qt import run_gui
    except ImportError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            raise SystemExit(
                "PySide6 is required for Instrument Inspector.\n"
                "Run via ./instrument_inspector.sh, or install PySide6 into the music-renderer environment."
            ) from exc
        raise
    return run_gui(root)


if __name__ == "__main__":
    raise SystemExit(main())

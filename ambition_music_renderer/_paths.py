"""Path helpers for the source-tree based music renderer.

The renderer is normally executed from an editable checkout that lives at
``tools/ambition_music_renderer`` inside the parent game repository.  After the
package reorg, modules under subpackages cannot infer that renderer root with a
fixed number of ``.parent`` hops.  Keep the discovery rules centralized here so
score lookup, generated-output paths, and subprocess working directories all
agree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

SCORE_DIRS = ("active", "examples", "archive", "experiments")
SCORE_SUFFIXES = (".music.yaml", ".yaml", ".yml")


def package_root() -> Path:
    """Return the Python package directory."""
    return Path(__file__).resolve().parent


def project_root(start: Path | None = None) -> Path:
    """Return the renderer project root containing ``pyproject.toml`` and scores.

    This intentionally searches upward instead of relying on a fixed package
    depth.  Files in ``ambition_music_renderer/render`` and
    ``ambition_music_renderer/audit`` are one level deeper than the old flat
    layout, and hard-coded ``parent.parent`` calculations caused score discovery
    to look under ``ambition_music_renderer/scores`` instead of the project
    root's ``scores`` directory.
    """
    start_path = package_root() if start is None else Path(start).resolve()
    if start_path.is_file():
        start_path = start_path.parent
    for candidate in (start_path, *start_path.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "scores").is_dir():
            return candidate
    # Source-tree fallback: package_root() is <project>/ambition_music_renderer.
    return package_root().parent


def repo_root(start: Path | None = None) -> Path:
    """Return the parent game repository root when the renderer is a submodule."""
    renderer = project_root(start)
    for candidate in (renderer, *renderer.parents):
        if (candidate / "crates" / "ambition_gameplay_core").exists():
            return candidate
    if renderer.parent.name == "tools":
        return renderer.parent.parent
    return renderer.parent


def scores_root() -> Path:
    return project_root() / "scores"


def generated_root() -> Path:
    return project_root() / "generated"


def output_root() -> Path:
    return project_root() / "output"


def bundles_root() -> Path:
    return project_root() / "bundles"


def score_candidates(cue: str, *, subdirs: Iterable[str] = SCORE_DIRS) -> list[Path]:
    """Return candidate score paths for a cue id or path-like cue argument."""
    p = Path(cue)
    candidates: list[Path] = []
    if p.suffix in (".yaml", ".yml"):
        candidates.append(p if p.is_absolute() else (Path.cwd() / p))
    for subdir in subdirs:
        for suffix in SCORE_SUFFIXES:
            candidates.append(scores_root() / subdir / f"{cue}{suffix}")
    return candidates


def find_score(cue: str, *, subdirs: Iterable[str] = SCORE_DIRS) -> Path | None:
    """Locate a score YAML by cue id or path."""
    for candidate in score_candidates(cue, subdirs=subdirs):
        if candidate.exists():
            return candidate.resolve()
    return None

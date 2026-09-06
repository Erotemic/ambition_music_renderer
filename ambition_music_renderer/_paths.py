"""Path helpers for the source-tree based music renderer.

The renderer is normally executed from an editable checkout that lives at
``tools/ambition_music_renderer`` inside the parent game repository.  After the
package reorg, modules under subpackages cannot infer that renderer root with a
fixed number of ``.parent`` hops.  Keep the discovery rules centralized here so
score lookup, generated-output paths, and subprocess working directories all
agree.
"""

from __future__ import annotations

import os
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
    """Return the parent game repository root when the renderer is a submodule.

    ⛔ **This used to probe for ``crates/ambition_actors``, and that was a
    standing bug rather than a lookup.** The renderer is a submodule of a game
    repo whose crate names are that repo's business: ``ambition_actors`` became
    ``ambition_platformer2d_actor_monolith``, and the monolith is scheduled to be
    decomposed into names nobody has chosen yet. A probe keyed on one of them is
    wrong for every value it does not hold — and it failed SILENTLY, because a
    miss fell through to the ``tools/`` heuristic while
    :func:`publish_root` cheerfully CREATED the directory it expected.

    The renderer no longer knows what the consumer crate is called. It finds the
    repo structurally (this project lives at ``<repo>/tools/<name>``) and is
    TOLD where to publish; see :func:`publish_root`.
    """
    renderer = project_root(start)
    if renderer.parent.name == "tools":
        return renderer.parent.parent
    return renderer.parent


class PublishRootUndeclared(RuntimeError):
    """The caller did not say where rendered cues should be installed."""


def publish_root() -> Path:
    """Where rendered cues are installed in the consuming game.

    ⭐ **The consumer declares this; the renderer never guesses.** It is passed
    as ``--dest-root`` or through ``AMBITION_MUSIC_PUBLISH_ROOT``, both of which
    the game repo's own ``scripts/regen/music.sh`` sets from the one place that knows its
    asset layout.

    Raising is the point. The previous default was a hard-coded path into a crate
    the renderer cannot know the name of, so a wrong guess published 69 cues into
    a directory nothing reads and exited 0. A missing declaration is a question,
    not something to answer on the caller's behalf.
    """
    declared = os.environ.get("AMBITION_MUSIC_PUBLISH_ROOT")
    if declared:
        return Path(declared).expanduser().resolve()
    raise PublishRootUndeclared(
        "no publish destination was declared. Pass --dest-root, or set "
        "AMBITION_MUSIC_PUBLISH_ROOT to the game's "
        "<assets>/audio/music/generated directory. The renderer does not know "
        "what the consuming crate is called, and guessing is how 69 cues were "
        "once published into a directory nothing reads."
    )


def declared_publish_root() -> Path | None:
    """Where cues install, or ``None`` when nothing declared it.

    ⛔ **the variant an ARGUMENT DEFAULT needs**, and its absence was a real bug:
    `publish_root()` raises by design, and CLI configs used it as a
    ``default_factory`` — so merely PARSING ``render <cue>`` demanded a publish
    destination for a run that was never going to publish. Two tests failed on
    argument parsing alone.

    ⭐ the raise is not softened, it is MOVED to where the answer is used.
    `render.bundle` already resolves a `None` destination through
    :func:`publish_root` at publish time, so an undeclared destination still
    fails loudly — it just fails when somebody actually tries to install
    something. `audit.level_report` reached the same shape independently.
    """
    try:
        return publish_root()
    except PublishRootUndeclared:
        return None


def scores_root() -> Path:
    return project_root() / "scores"


def generated_root() -> Path:
    return project_root() / "generated"


def output_root() -> Path:
    return project_root() / "output"


def agent_root() -> Path:
    """Scratch drop-zone for agent-generated bundles/plots/reports.

    Bundles default here so that after a render (especially a blind fix) the
    audio, plots, and diagnostics for a cue land in one predictable place to
    audition and debug. Gitignored.
    """
    return project_root() / "agent"


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

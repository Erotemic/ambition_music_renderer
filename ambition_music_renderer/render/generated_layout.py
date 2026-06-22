"""Versioned generated-output directory helpers.

The renderer writes many hashed files while a cue is being built.  Keeping all
hashes directly under ``generated/<cue>/`` makes it hard to distinguish the
current render from old experiments.  These helpers keep default generated
outputs in content-versioned run directories while exposing stable symlinks for
humans and tools:

``generated/<cue>/.versioned/<hash>/``
    Actual render contents for one renderer/spec hash.
``generated/<cue>/building``
    Symlink to the hash currently being constructed.
``generated/<cue>/latest``
    Symlink to the newest successfully completed hash.

Explicit ``--outdir`` paths are intentionally left alone; this layout is for the
standard generated tree only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from ..profiler import profile


@dataclass(frozen=True)
class GeneratedRunLayout:
    """Resolved paths for one generated cue render."""

    cue_dir: Path
    hash_id: str

    @property
    def versioned_dir(self) -> Path:
        return self.cue_dir / ".versioned"

    @property
    def run_dir(self) -> Path:
        return self.versioned_dir / self.hash_id

    @property
    def latest_link(self) -> Path:
        return self.cue_dir / "latest"

    @property
    def building_link(self) -> Path:
        return self.cue_dir / "building"


def _relative_link_target(link: Path, target: Path) -> Path:
    try:
        return Path(os.path.relpath(target, start=link.parent))
    except ValueError:
        return target


@profile
def replace_directory_symlink(link: Path, target: Path) -> bool:
    """Atomically-ish replace ``link`` with a relative directory symlink.

    Returns ``True`` when a symlink was written.  If the platform or filesystem
    cannot create symlinks, write a small ``<link>.path`` pointer file instead
    and return ``False``.  Existing real directories/files are left untouched so
    a user does not lose hand-curated output by running the renderer.
    """

    link.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or not link.exists():
        if link.is_symlink() or link.exists():
            link.unlink()
        tmp = link.with_name(f".{link.name}.tmp")
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        try:
            tmp.symlink_to(_relative_link_target(tmp, target), target_is_directory=True)
            tmp.replace(link)
            return True
        except OSError:
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            link.with_name(f"{link.name}.path").write_text(str(target), encoding="utf8")
            return False
    if link.is_dir():
        # Existing real directory: do not destroy it.  Leave a sidecar pointer so
        # humans can still discover the intended run.
        link.with_name(f"{link.name}.path").write_text(str(target), encoding="utf8")
        return False
    link.with_name(f"{link.name}.path").write_text(str(target), encoding="utf8")
    return False


@profile
def compute_score_render_hash(score_path: Path, backend: str, spec: dict | None = None) -> str:
    """Return the same render hash that ``render.isolated`` will use."""

    from . import musicir_renderer as r

    if spec is None:
        spec = yaml.safe_load(Path(score_path).read_text(encoding="utf8")) or {}
    render_cfg = spec.get("render", {}) or {}
    soundfont = r.choose_soundfont(render_cfg.get("soundfont"))
    return str(r.spec_hash(Path(score_path), soundfont, backend))


@profile
def generated_run_layout(cue_dir: Path, score_path: Path, backend: str, spec: dict | None = None) -> GeneratedRunLayout:
    """Build a versioned generated-layout object for a cue."""

    hash_id = compute_score_render_hash(score_path, backend, spec=spec)
    return GeneratedRunLayout(cue_dir=Path(cue_dir), hash_id=hash_id)


@profile
def begin_generated_run(layout: GeneratedRunLayout) -> Path:
    """Prepare the versioned run dir and point ``building`` at it."""

    layout.run_dir.mkdir(parents=True, exist_ok=True)
    replace_directory_symlink(layout.building_link, layout.run_dir)
    return layout.run_dir


@profile
def mark_generated_run_latest(layout: GeneratedRunLayout) -> Path:
    """Point ``latest`` at a successfully completed versioned run."""

    layout.run_dir.mkdir(parents=True, exist_ok=True)
    replace_directory_symlink(layout.latest_link, layout.run_dir)
    return layout.latest_link


@profile
def resolve_latest_generated_dir(cue_dir: Path) -> Path:
    """Return ``generated/<cue>/latest`` target when present, else ``cue_dir``."""

    cue_dir = Path(cue_dir)
    latest = cue_dir / "latest"
    if latest.exists():
        return latest.resolve()
    pointer = cue_dir / "latest.path"
    if pointer.exists():
        target = Path(pointer.read_text(encoding="utf8").strip())
        if target.exists():
            return target
    return cue_dir


@profile
def generated_manifest_search_roots(cue_dir: Path) -> list[Path]:
    """Return candidate roots to inspect for the newest manifest."""

    cue_dir = Path(cue_dir)
    roots: list[Path] = []
    latest = resolve_latest_generated_dir(cue_dir)
    if latest not in roots:
        roots.append(latest)
    if cue_dir not in roots:
        roots.append(cue_dir)
    versioned = cue_dir / ".versioned"
    if versioned.is_dir():
        candidates = sorted(
            [p for p in versioned.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        roots.extend(p for p in candidates if p not in roots)
    return roots


@profile
def latest_manifest_in_roots(roots: Iterable[Path], cue_id: str) -> Path | None:
    """Find the newest cue manifest, respecting search-root priority.

    ``generated_manifest_search_roots`` yields ``latest`` first when it exists.
    Treat that link as the source of truth even if a stale versioned directory
    was touched later by a shell command.
    """

    for root in roots:
        candidates = sorted(
            Path(root).glob(f"{cue_id}_*.adaptive_manifest.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None

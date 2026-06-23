#!/usr/bin/env python3
"""Install ``first_goblin_tune_v2`` adaptive OGG assets into the sandbox crate.

Reads a renderer output directory (default: ``target/generated-audio/first_goblin_tune_v2``),
finds the adaptive manifest, and copies each section/stem OGG to a stable,
hash-free filename under
``crates/ambition_gameplay_core/assets/audio/music/generated/first_goblin_tune_v2/``.

The Rust loader (``crates/ambition_gameplay_core/src/generated_music.rs``) targets
those stable filenames, so re-rendering the cue does not require Rust changes.
"""

from __future__ import annotations

from ..profiler import profile

import kwconf
import json
import shutil
import sys
from pathlib import Path

from .._paths import repo_root as _repo_root

CUE_ID = "first_goblin_tune_v2"
SECTIONS = ("intro", "wave1", "wave2", "wave3", "recap_loop", "outro")
STEMS = ("strings", "brass", "winds", "choir_pad", "mallets", "percussion")
# Per-section full mixes get installed for every section because the
# in-game cue spec plays them directly: only intro / outro have ever
# played as a single mastered file, but wave1/2/3 / recap_loop now do
# the same to dodge the silent-stem problem (the renderer's mastering
# chain only runs on the full mix, not individual stems).
FULL_SECTIONS = SECTIONS


@profile
def repo_root() -> Path:
    return _repo_root()


@profile
def find_manifest(src: Path) -> Path:
    matches = sorted(
        src.glob(f"{CUE_ID}_*.adaptive_manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        raise SystemExit(
            f"no adaptive manifest matching {CUE_ID}_*.adaptive_manifest.json in {src}"
        )
    return matches[0]


@profile
def install_stable(
    src: Path,
    dest: Path,
    file_base: str,
    *,
    install_stems: bool,
) -> list[Path]:
    written: list[Path] = []
    missing: list[str] = []
    for section in SECTIONS:
        section_src = src / "adaptive" / section
        section_dest = dest / "adaptive" / section
        section_dest.mkdir(parents=True, exist_ok=True)
        if install_stems:
            for stem in STEMS:
                src_file = section_src / f"{file_base}.{section}.{stem}.ogg"
                dst_file = section_dest / f"{section}.{stem}.ogg"
                if not src_file.exists():
                    missing.append(str(src_file.relative_to(src)))
                    continue
                shutil.copy2(src_file, dst_file)
                written.append(dst_file)
        if section in FULL_SECTIONS:
            src_full = section_src / f"{file_base}.{section}.full.ogg"
            dst_full = section_dest / f"{section}.full.ogg"
            if not src_full.exists():
                missing.append(str(src_full.relative_to(src)))
            else:
                shutil.copy2(src_full, dst_full)
                written.append(dst_full)
    if missing:
        raise SystemExit(
            "missing expected renderer outputs:\n  " + "\n  ".join(missing)
        )
    return written


@profile
def _autodetect_src() -> Path:
    """Pick the renderer output dir with the newest manifest.

    The renderer writes to two known locations:
    1. ``target/generated-audio/<cue>`` (CI / build-time output)
    2. ``tools/ambition_music_renderer/generated/<cue>`` (interactive
       author runs through the modal CLI)

    When both exist, picking whichever has the newer
    ``adaptive_manifest.json`` gets re-runs of this script the
    *latest* stems without the user having to remember which
    ``--src`` to point at.
    """
    candidates = [
        repo_root() / "target/generated-audio" / CUE_ID,
        repo_root() / "tools/ambition_music_renderer/generated" / CUE_ID,
        repo_root() / "tools/ambition_music_renderer/output" / CUE_ID,
    ]
    scored: list[tuple[float, Path]] = []
    for c in candidates:
        if not c.exists():
            continue
        manifests = list(c.glob(f"{CUE_ID}_*.adaptive_manifest.json"))
        if not manifests:
            continue
        newest = max(manifests, key=lambda p: p.stat().st_mtime)
        scored.append((newest.stat().st_mtime, c))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    return candidates[0]


class InstallFirstGoblinTuneConfig(kwconf.Config):
    """Install first_goblin_tune_v2 renderer outputs into stable asset paths."""

    src: Path = kwconf.Value(default_factory=_autodetect_src, parser=Path, help="Renderer output directory")
    clean: bool = kwconf.Flag(False, help="Wipe destination directory first")
    with_stems: bool = kwconf.Flag(False, help="Also require/install per-stem OGGs")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


@profile
def run(args: InstallFirstGoblinTuneConfig) -> int:
    src = Path(args.src).resolve()
    if not (src / "adaptive").exists():
        print(f"error: no adaptive directory at {src}", file=sys.stderr)
        print("       run ./scripts/regen_first_goblin_tune_v2.sh first.", file=sys.stderr)
        return 2

    manifest_path = find_manifest(src)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("id") != CUE_ID:
        raise SystemExit(f"manifest id must be {CUE_ID}, got {manifest.get('id')!r}")
    file_base = f"{CUE_ID}_{manifest['hash']}"

    asset_root = repo_root() / "crates/ambition_gameplay_core/assets/audio/music/generated"
    dest = asset_root / CUE_ID

    if args.clean:
        shutil.rmtree(dest, ignore_errors=True)
        shutil.rmtree(asset_root / "first_goblin_encounter", ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    written = install_stable(src, dest, file_base, install_stems=args.with_stems)
    shutil.copy2(manifest_path, dest / "adaptive_manifest.json")

    print(f"installed {len(written)} OGG assets")
    print(f"  src:  {src}")
    print(f"  dest: {dest}")
    print(f"  cue:  {CUE_ID}  hash={manifest['hash']}")
    print(f"  stems_installed: {args.with_stems}")
    return 0


if __name__ == "__main__":
    raise SystemExit(InstallFirstGoblinTuneConfig.main())

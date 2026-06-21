"""Modal CLI for ambition_music_renderer.

Subcommands:

    render <cue>            Render a single cue YAML to local generated/<cue>/.
    publish <cue>           Publish newest preview into the sandbox asset tree.
    render-publish <cue>    Render then publish.
    sandbox render-publish  Render+publish the sandbox single-track cues
                            (lofi_study_loop, long_lofi_drift, pulse_drift_voyage).
    sandbox render          Render-only for sandbox cues.
    sandbox publish         Publish-only for sandbox cues (--skip-render alias).
    radio render-publish    Render+publish every cue exposed on the in-game
                            radio: SANDBOX_CUES plus auto-discovered
                            scores/active/* plus EXTRA_RADIO_CUES.
    radio render            Render-only for radio cues.
    radio publish           Publish-only for radio cues.

Pinning a specific render: drop a file named ``published.ogg`` (or a symlink)
into ``output/<cue>/preview/`` (or ``generated/<cue>/preview/``) and publish
will copy that exact file instead of the auto-named full mix. Used when a
cue's mastered preview lives under a manual filename.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Soft import: ubelt.ProgIter gives the bulk loop a count + ETA. If it's not
# installed in the active venv (older setup), fall back to a plain iterator
# so the renderer still works.
try:
    import ubelt as _ub  # type: ignore[import-not-found]

    def _progress(iterable, *, total, desc):
        return _ub.ProgIter(
            iterable,
            total=total,
            desc=desc,
            verbose=3,
            freq=1,
            adjust=False,
        )
except ImportError:  # pragma: no cover — graceful fallback

    def _progress(iterable, *, total, desc):  # noqa: ARG001
        return iterable


# Single-track cues authored under scores/active that ship via the radio.
# These render with --simple-mix and publish the mastered preview.
SANDBOX_CUES = ("lofi_study_loop", "long_lofi_drift", "pulse_drift_voyage")

# Adaptive cues handled by the dedicated pipeline
# (scripts/regen_first_goblin_tune_v2.sh).
# This module deliberately skips them in the bulk `radio` pass; their
# multi-stem layout is owned elsewhere.
ADAPTIVE_CUES = ("first_goblin_tune_v2",)


def is_adaptive_cue(cue: str) -> bool:
    return cue in ADAPTIVE_CUES


# Curated extras drawn from scores/examples that we expose on the radio.
# We keep this explicit (rather than scanning examples wholesale) because
# the examples tree also holds debug / fixture / archive scores that should
# not auto-publish. Add new entries here as content lands in examples/.
EXTRA_RADIO_CUES = (
    "crooked_ascent_boss",
    "dinosaur_liberators",
    "dinosaur_liberators_long",
    "env_advocacy_solace",
    "fast_paced_violin_boss",
    "glasswood",
    "military_iron_resolve",
    "moonlit_canal",
    "solo_soar",
    "solo_soar_9m08_loud",
    "tech_bros_disruption",
    "violin_boss_relentless",
)

SCORE_DIRS = ("active", "examples", "archive")

# Filename treated as a manual override inside any preview/ directory. When
# present, this is the file that gets copied to assets/.../<cue>/full.ogg
# instead of the renderer's auto-named full_soundtrack_preview.ogg.
PINNED_FILENAME = "published.ogg"


def package_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # tools/ambition_music_renderer/ambition_music_renderer/cli.py -> repo
    return Path(__file__).resolve().parents[3]


def generated_root() -> Path:
    return package_dir() / "generated"


def output_root() -> Path:
    """Legacy hashed output root used by the underlying renderer."""
    return package_dir() / "output"


def find_score(cue: str) -> Path | None:
    """Locate a cue YAML by name. Searches scores/{active,examples,archive}/.

    Accepts a bare cue id (e.g. ``lofi_study_loop``) or a relative/absolute
    path to a YAML.
    """
    p = Path(cue)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return p.resolve()
    candidates = [
        package_dir() / "scores" / sub / f"{cue}.music.yaml" for sub in SCORE_DIRS
    ]
    candidates += [package_dir() / "scores" / sub / f"{cue}.yaml" for sub in SCORE_DIRS]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_full_mix(preview_dir: Path, cue: str) -> Path | None:
    """Locate the OGG to publish for ``cue``.

    Order of preference:
      1. ``preview/published.ogg`` — manual pin (file or symlink). Lets a
         human elect a specific render (e.g. a renamed favorite) without
         renaming it back to the auto pattern.
      2. The most-recent ``{cue}_*.full_soundtrack_preview.ogg`` — the
         renderer's standard mastered preview output.
    Returns ``None`` if neither is present.
    """
    pinned = preview_dir / PINNED_FILENAME
    if pinned.exists():
        return pinned
    candidates = sorted(
        preview_dir.glob(f"{cue}_*.full_soundtrack_preview.ogg"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def discover_active_radio_cues() -> tuple[str, ...]:
    """List cues from scores/active/ that should appear on the radio.

    Excludes:
      - Cues already in ``SANDBOX_CUES`` (handled by that path).
      - Cues in ``ADAPTIVE_CUES`` (handled by
        ``scripts/regen_first_goblin_tune_v2.sh``).
    Returns a sorted, deduped tuple so the order is stable across runs.
    """
    active = package_dir() / "scores" / "active"
    if not active.is_dir():
        return ()
    cues: set[str] = set()
    for path in active.iterdir():
        name = path.name
        for suffix in (".music.yaml", ".yaml"):
            if name.endswith(suffix):
                cue = name[: -len(suffix)]
                if cue and cue not in SANDBOX_CUES and cue not in ADAPTIVE_CUES:
                    cues.add(cue)
                break
    return tuple(sorted(cues))


def radio_cues() -> tuple[str, ...]:
    """All cues we expect to publish into the in-game radio asset tree."""
    seen: set[str] = set()
    ordered: list[str] = []
    for cue in (*SANDBOX_CUES, *discover_active_radio_cues(), *EXTRA_RADIO_CUES):
        if cue not in seen:
            seen.add(cue)
            ordered.append(cue)
    return tuple(ordered)


def manifest_has_adaptive_full_sections(manifest_path: Path) -> bool:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    except Exception:
        return False
    adaptive = ((manifest.get("files") or {}).get("adaptive") or {})
    if not isinstance(adaptive, dict):
        return False
    return any(
        isinstance(section_files, dict) and bool(section_files.get("full"))
        for section_files in adaptive.values()
    )


def needs_render(cue: str, yaml_path: Path, outdir: Path) -> bool:
    preview_dir = outdir / "preview"
    latest = find_full_mix(preview_dir, cue)
    if latest is None:
        return True
    if is_adaptive_cue(cue):
        manifest = find_latest_manifest(outdir, cue)
        if manifest is None or not manifest_has_adaptive_full_sections(manifest):
            return True
    return yaml_path.stat().st_mtime > latest.stat().st_mtime


def python_exe() -> str:
    """Prefer the package venv if it exists, else current interpreter."""
    venv_python = package_dir() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def render_cue(
    cue: str,
    yaml_path: Path,
    outdir: Path,
    *,
    backend: str = "pretty-midi",
    simple_mix: bool = True,
    full_mix_only: bool = False,
    extra_args: list[str] | None = None,
) -> bool:
    cmd = [
        python_exe(),
        "-m",
        "ambition_music_renderer.render_isolated",
        str(yaml_path),
        "--outdir",
        str(outdir),
        "--backend",
        backend,
    ]
    if full_mix_only:
        cmd.append("--full-mix-only")
    elif simple_mix:
        cmd.append("--simple-mix")
    if extra_args:
        cmd.extend(extra_args)
    print(f"render {cue}: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=package_dir())
    return result.returncode == 0


def render_mode_for_cue(cue: str, args: argparse.Namespace) -> tuple[bool, bool]:
    """Return (simple_mix, full_mix_only) for top-level render commands.

    Goblin-style adaptive encounter cues ship as per-section full mixes. The
    historical top-level CLI defaulted every cue to --simple-mix, which renders
    only preview/full.ogg and leaves stale adaptive section files in the game
    asset tree. Treat known adaptive cues as full-mix-only unless the caller
    explicitly disables simple mixing with --no-simple-mix, in which case they
    get the full per-stem adaptive export.
    """
    simple_mix = bool(getattr(args, "simple_mix", True))
    full_mix_only = bool(getattr(args, "full_mix_only", False))
    if full_mix_only:
        return False, True
    if is_adaptive_cue(cue) and simple_mix:
        print(
            f"render {cue}: adaptive cue detected; using --full-mix-only so section assets are regenerated"
        )
        return False, True
    return simple_mix, False


def default_publish_dest_root() -> Path:
    return (
        repo_root()
        / "crates"
        / "ambition_gameplay_core"
        / "assets"
        / "audio"
        / "music"
        / "generated"
    )


def _display_path(path: Path) -> Path:
    try:
        return path.relative_to(repo_root())
    except ValueError:
        return path


def find_latest_manifest(outdir: Path, cue: str) -> Path | None:
    candidates = sorted(
        outdir.glob(f"{cue}_*.adaptive_manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def publish_adaptive_full_sections(cue: str, outdir: Path, dest_dir: Path) -> list[Path]:
    """Publish hashed adaptive full-section renders to stable runtime paths.

    The renderer keeps content-addressed filenames like
    ``adaptive/wave1/<cue>_<hash>.wave1.full.ogg`` so bundles are
    manifest-scoped and stale renders are easy to identify. The Rust music
    catalog intentionally uses stable asset paths:
    ``adaptive/<section>/<section>.full.ogg``. Publishing is the seam that
    converts the manifest-scoped render into those stable game assets.
    """
    manifest_path = find_latest_manifest(outdir, cue)
    if manifest_path is None:
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    except Exception as ex:
        print(f"skip adaptive publish {cue}: failed to read {manifest_path}: {ex}", file=sys.stderr)
        return []

    copied: list[Path] = []
    adaptive = ((manifest.get("files") or {}).get("adaptive") or {})
    if not isinstance(adaptive, dict):
        return copied

    to_copy: list[tuple[Path, Path]] = []
    missing: list[str] = []
    for section_id, section_files in sorted(adaptive.items()):
        if not isinstance(section_files, dict):
            continue
        rel = section_files.get("full")
        if not rel:
            continue
        src = outdir / str(rel)
        dest = dest_dir / "adaptive" / str(section_id) / f"{section_id}.full.ogg"
        if src.exists():
            to_copy.append((src, dest))
        else:
            missing.append(f"{section_id}: {src}")

    if missing:
        for item in missing:
            print(f"skip adaptive section publish {cue}: missing {item}", file=sys.stderr)
        return []

    for src, dest in to_copy:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest)

    # Keep the manifest next to the runtime files as a debugging breadcrumb.
    # The game does not load it today, but it makes it obvious which render hash
    # produced the shipped adaptive sections.
    if copied:
        shutil.copy2(manifest_path, dest_dir / f"{cue}.adaptive_manifest.json")
    return copied


def publish_cue(cue: str, outdir: Path, dest_root: Path) -> bool:
    preview_dir = outdir / "preview"
    src = find_full_mix(preview_dir, cue)
    if src is None:
        print(
            f"skip publish {cue}: no full_soundtrack_preview.ogg in {preview_dir}",
            file=sys.stderr,
        )
        return False
    dest_dir = dest_root / cue
    dest_dir.mkdir(parents=True, exist_ok=True)

    adaptive_copied = publish_adaptive_full_sections(cue, outdir, dest_dir)
    if is_adaptive_cue(cue) and not adaptive_copied:
        print(
            f"error: publish {cue}: no adaptive full-section assets were copied from {outdir}. "
            "The encounter runtime loads adaptive/<section>/<section>.full.ogg, not full.ogg. "
            "Render with `cue bundle --publish` or render_isolated --full-mix-only before publishing.",
            file=sys.stderr,
        )
        return False

    dest = dest_dir / "full.ogg"
    shutil.copy2(src, dest)
    print(f"publish {cue}: {_display_path(src)} -> {_display_path(dest)}")
    for adaptive_dest in adaptive_copied:
        print(f"publish {cue}: adaptive section -> {_display_path(adaptive_dest)}")
    if adaptive_copied:
        print(f"publish {cue}: {len(adaptive_copied)} adaptive full-section assets")
    return True


def cmd_render(args: argparse.Namespace) -> int:
    yaml_path = find_score(args.cue)
    if yaml_path is None:
        print(f"error: cue not found: {args.cue}", file=sys.stderr)
        return 2
    outdir = generated_root() / args.cue
    if not args.simple_mix and outdir == generated_root() / args.cue:
        # nothing special; just leaving the simple-mix off
        pass
    simple_mix, full_mix_only = render_mode_for_cue(args.cue, args)
    ok = render_cue(
        args.cue,
        yaml_path,
        outdir,
        backend=args.backend,
        simple_mix=simple_mix,
        full_mix_only=full_mix_only,
    )
    return 0 if ok else 1


def cmd_publish(args: argparse.Namespace) -> int:
    outdir = generated_root() / args.cue
    # Fallback to legacy output/ tree if generated/ is empty.
    if not (outdir / "preview").exists():
        legacy = output_root() / args.cue
        if (legacy / "preview").exists():
            outdir = legacy
    ok = publish_cue(args.cue, outdir, args.dest_root)
    return 0 if ok else 1


def cmd_render_publish(args: argparse.Namespace) -> int:
    yaml_path = find_score(args.cue)
    if yaml_path is None:
        print(f"error: cue not found: {args.cue}", file=sys.stderr)
        return 2
    outdir = generated_root() / args.cue
    if args.force_render or needs_render(args.cue, yaml_path, outdir):
        simple_mix, full_mix_only = render_mode_for_cue(args.cue, args)
        if not render_cue(
            args.cue,
            yaml_path,
            outdir,
            backend=args.backend,
            simple_mix=simple_mix,
            full_mix_only=full_mix_only,
        ):
            return 1
    else:
        print(f"skip render {args.cue}: YAML unchanged since last render")
    return 0 if publish_cue(args.cue, outdir, args.dest_root) else 1


def _process_simple_mix_cue(
    cue: str,
    *,
    action: str,
    backend: str,
    force_render: bool,
    dest_root: Path,
) -> str | None:
    """Run render/publish/render-publish for one simple-mix cue.

    Returns ``None`` on success, otherwise a short failure-stage label
    (``"resolve"`` / ``"render"`` / ``"publish"``) for the caller to
    aggregate. ``action`` is one of ``"render"``, ``"publish"``,
    ``"render-publish"``.
    """
    yaml_path = find_score(cue)
    if yaml_path is None:
        # Some cues only exist as legacy renders under output/ with no
        # active YAML (e.g. archived examples). Permit publish-only in
        # that case so existing previews still ship.
        if action == "publish":
            outdir = output_root() / cue
            if (outdir / "preview").exists():
                return None if publish_cue(cue, outdir, dest_root) else "publish"
        print(f"skip {cue}: missing YAML", file=sys.stderr)
        return "resolve"
    outdir = generated_root() / cue
    if action in ("render", "render-publish"):
        if force_render or needs_render(cue, yaml_path, outdir):
            if not render_cue(
                cue,
                yaml_path,
                outdir,
                backend=backend,
                simple_mix=True,
            ):
                return "render"
        else:
            print(f"skip render {cue}: YAML unchanged since last render")
    if action in ("publish", "render-publish"):
        if not publish_cue(cue, outdir, dest_root):
            # Fall back to the legacy output/ tree (older renders or
            # adaptive cues whose mastered preview lives there).
            legacy = output_root() / cue
            if (legacy / "preview").exists():
                if not publish_cue(cue, legacy, dest_root):
                    return "publish"
            else:
                return "publish"
    return None


def _run_bulk(args: argparse.Namespace, cues: tuple[str, ...]) -> int:
    failed: list[str] = []
    desc = f"music {args.action}"
    for cue in _progress(cues, total=len(cues), desc=desc):
        stage = _process_simple_mix_cue(
            cue,
            action=args.action,
            backend=args.backend,
            force_render=args.force_render,
            dest_root=args.dest_root,
        )
        if stage is not None:
            failed.append(f"{stage} {cue}")
    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"OK: {len(cues)} cue(s) ready")
    return 0


def cmd_sandbox(args: argparse.Namespace) -> int:
    """Render+publish the sandbox single-track cues.

    Mirrors the legacy ``tools/audio/render_sandbox_music.py`` behavior:
    skip the renderer when the YAML mtime is older than the latest preview,
    use --simple-mix for these single-track cues, publish the newest
    full_soundtrack_preview.ogg into the bevy asset tree.
    """
    cues = tuple(args.cue) if args.cue else SANDBOX_CUES
    return _run_bulk(args, cues)


def cmd_radio(args: argparse.Namespace) -> int:
    """Render+publish every cue we expose on the in-game radio.

    Covers ``SANDBOX_CUES`` plus auto-discovered ``scores/active/*`` cues
    plus the curated ``EXTRA_RADIO_CUES`` list. Skips ``ADAPTIVE_CUES``
    (those go through ``scripts/regen_first_goblin_tune_v2.sh``). Honors
    ``preview/published.ogg`` pins for cues whose mastered file lives
    under a manual filename.
    """
    cues = tuple(args.cue) if args.cue else radio_cues()
    return _run_bulk(args, cues)


def cmd_bundle(args: argparse.Namespace) -> int:
    from .cue_bundle import create_bundle, print_bundle_summary

    report = create_bundle(
        args.cue,
        backend=args.backend,
        runtime_stem_gain_mode=args.runtime_stem_gain_mode,
        runtime_stem_max_gain_db=args.runtime_stem_max_gain_db,
        outdir=args.outdir,
        bundle_root=args.bundle_root,
        force=args.force,
        publish=args.publish,
        dest_root=args.dest_root,
        zip_bundle=args.zip_bundle,
        zip_report_bundle=args.zip_report_bundle,
        jobs=args.jobs,
        include_scratch_stems=args.include_scratch_stems,
        skip_render=args.skip_render,
        skip_spectrograms=args.skip_spectrograms,
        plot_format=args.plot_format,
        jpeg_quality=args.jpeg_quality,
        render_audio_mode=args.render_audio_mode,
        profile_render=args.profile_render,
    )
    import json as _json

    print_bundle_summary(report)
    print(_json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok", True) else 1




def cmd_plugins_doctor(args: argparse.Namespace) -> int:
    from .audio_plugins import collect_plugin_diagnostics

    report = collect_plugin_diagnostics(probe_counts=not args.fast)
    print(json.dumps(report, indent=2))
    return 0


def cmd_plugins_list_vst3(args: argparse.Namespace) -> int:
    from .audio_plugins import discover_vst3_plugins

    roots = [Path(p) for p in args.path] if args.path else None
    plugins = discover_vst3_plugins(roots)
    if args.json:
        print(json.dumps(plugins, indent=2))
    else:
        for plugin in plugins:
            print(plugin["path"])
    return 0


def cmd_plugins_list_lv2(args: argparse.Namespace) -> int:
    from .audio_plugins import discover_lv2_plugins

    uris = discover_lv2_plugins(limit=args.limit)
    if args.json:
        print(json.dumps(uris, indent=2))
    else:
        for uri in uris:
            print(uri)
    return 0


def cmd_plugins_lv2_info(args: argparse.Namespace) -> int:
    from .audio_plugins import lv2_info

    report = lv2_info(args.uri)
    if args.raw:
        print(report.get("stdout", ""), end="")
        if report.get("stderr"):
            print(report["stderr"], file=sys.stderr, end="")
    else:
        print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def cmd_plugins_validate_score(args: argparse.Namespace) -> int:
    from .audio_plugins import load_score, validate_score_plugins

    score = find_score(args.score)
    if score is None:
        p = Path(args.score)
        if p.exists():
            score = p.resolve()
        else:
            print(f"error: score not found: {args.score}", file=sys.stderr)
            return 2
    report = validate_score_plugins(load_score(score), base_dir=score.parent)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") or args.warn_only else 1


def add_bundle_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("cue", help="cue id or .music.yaml path")
    p.add_argument(
        "--backend",
        default="pretty-midi",
        choices=["pretty-midi", "fluidsynth-cli", "fallback", "auto"],
        help="renderer backend (default: pretty-midi; fallback is explicit opt-in)",
    )
    p.add_argument(
        "--runtime-stem-gain-mode",
        choices=["native", "shared"],
        default="native",
        help=(
            "runtime adaptive stem export mode: native preserves current raw levels; "
            "shared applies one shared reference gain across all stems"
        ),
    )
    p.add_argument(
        "--runtime-stem-max-gain-db",
        type=float,
        default=None,
        help="cap shared runtime stem gain; default is renderer policy or YAML render.runtime_stems.max_gain_db",
    )
    p.add_argument("--outdir", type=Path, default=None)
    p.add_argument("--bundle-root", type=Path, default=None)
    p.add_argument("--force", action="store_true", help="force render regeneration")
    p.add_argument("--publish", action="store_true", help="publish full.ogg to game assets")
    p.add_argument("--dest-root", type=Path, default=None, help="game music generated asset root")
    p.add_argument("--zip", dest="zip_bundle", action="store_true", help="write a complete uploadable bundle zip including manifest-referenced audio")
    p.add_argument("--zip-report", dest="zip_report_bundle", action="store_true", help="write a compact report zip excluding OGG/WAV/NPY/MIDI binaries")
    p.add_argument(
        "--plot-format",
        choices=["jpg", "png"],
        default="jpg",
        help="spectrogram image format for bundles; jpg is smaller and numeric reports preserve detail",
    )
    p.add_argument("--jpeg-quality", type=int, default=84, help="JPEG quality for spectrogram plots")
    p.add_argument("--jobs", "-j", type=int, default=1, help="render worker count")
    p.add_argument(
        "--include-scratch-stems",
        action="store_true",
        help="include raw scratch_stems/*.npy in the bundle zip; useful but large",
    )
    p.add_argument("--skip-render", action="store_true", help="bundle/analyze existing outdir")
    p.add_argument("--skip-spectrograms", action="store_true", help="skip PNG spectrogram generation")
    p.add_argument(
        "--render-audio-mode",
        choices=["full", "full-mix-only", "simple-mix"],
        default="full",
        help=(
            "audio export scope for render_isolated. full preserves all adaptive stem/state preview OGGs; "
            "full-mix-only keeps scratch stems plus mastered preview and section full mixes; "
            "simple-mix writes only the mastered preview."
        ),
    )
    p.add_argument("--profile-render", action="store_true", help="cProfile render_isolated and per-group workers into reports/")


def add_render_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--backend",
        default="pretty-midi",
        help="renderer backend (pretty-midi / fluidsynth-cli / fallback / auto)",
    )
    p.add_argument(
        "--simple-mix",
        dest="simple_mix",
        action="store_true",
        default=True,
        help="emit only the mastered preview (default for sandbox cues)",
    )
    p.add_argument(
        "--no-simple-mix",
        dest="simple_mix",
        action="store_false",
        help="emit the full adaptive stem set (per-section per-group OGGs)",
    )
    p.add_argument(
        "--full-mix-only",
        action="store_true",
        help="emit mastered preview plus per-section full mixes, but skip per-section per-stem OGGs",
    )


def add_publish_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--dest-root",
        type=Path,
        default=default_publish_dest_root(),
        help="install destination root (default: bevy asset tree)",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ambition_music_renderer",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="Render a single cue YAML")
    p_render.add_argument("cue", help="cue id (e.g. lofi_study_loop) or YAML path")
    add_render_args(p_render)
    p_render.set_defaults(func=cmd_render)

    p_publish = sub.add_parser(
        "publish", help="Publish newest preview to sandbox assets"
    )
    p_publish.add_argument("cue")
    add_publish_args(p_publish)
    p_publish.set_defaults(func=cmd_publish)

    p_rp = sub.add_parser("render-publish", help="Render then publish a single cue")
    p_rp.add_argument("cue")
    add_render_args(p_rp)
    add_publish_args(p_rp)
    p_rp.add_argument("--force-render", action="store_true")
    p_rp.set_defaults(func=cmd_render_publish)

    p_bundle = sub.add_parser("bundle", help="Render, debug, and package a cue bundle")
    add_bundle_args(p_bundle)
    p_bundle.set_defaults(func=cmd_bundle)

    def _cmd_bundle_many(batch_args: argparse.Namespace) -> int:
        from .batch_bundle import main as batch_main

        argv: list[str] = []
        if batch_args.workers is not None:
            argv.extend(["--workers", str(batch_args.workers)])
        if batch_args.render_jobs is not None:
            argv.extend(["--render-jobs", str(batch_args.render_jobs)])
        argv.extend(["--scope", batch_args.scope])
        if batch_args.include_examples:
            argv.append("--include-examples")
        argv.extend(["--backend", batch_args.backend])
        argv.extend(["--runtime-stem-gain-mode", batch_args.runtime_stem_gain_mode])
        if batch_args.runtime_stem_max_gain_db is not None:
            argv.extend(["--runtime-stem-max-gain-db", str(batch_args.runtime_stem_max_gain_db)])
        if batch_args.force:
            argv.append("--force")
        if batch_args.publish:
            argv.append("--publish")
        if batch_args.zip:
            argv.append("--zip")
        if batch_args.zip_report:
            argv.append("--zip-report")
        else:
            argv.append("--no-zip-report")
        if batch_args.skip_spectrograms:
            argv.append("--skip-spectrograms")
        if batch_args.include_scratch_stems:
            argv.append("--include-scratch-stems")
        argv.extend(["--render-audio-mode", batch_args.render_audio_mode])
        if batch_args.profile_render:
            argv.append("--profile-render")
        argv.extend(["--plot-format", batch_args.plot_format])
        argv.extend(["--jpeg-quality", str(batch_args.jpeg_quality)])
        if batch_args.bundle_root is not None:
            argv.extend(["--bundle-root", str(batch_args.bundle_root)])
        if batch_args.log_root is not None:
            argv.extend(["--log-root", str(batch_args.log_root)])
        argv.extend(batch_args.cues)
        return batch_main(argv)

    p_bundle_many = sub.add_parser("bundle-many", help="Render/debug many cue bundles in parallel")
    p_bundle_many.add_argument("cues", nargs="*", help="cue ids or YAML paths; omit to discover by --scope")
    p_bundle_many.add_argument("-j", "--workers", type=int, default=None, help="parallel cue bundle jobs")
    p_bundle_many.add_argument("--render-jobs", type=int, default=1, help="per-cue render worker count")
    p_bundle_many.add_argument("--scope", choices=["active", "examples", "all"], default="active")
    p_bundle_many.add_argument("--include-examples", action="store_true")
    p_bundle_many.add_argument("--backend", default="pretty-midi")
    p_bundle_many.add_argument("--runtime-stem-gain-mode", choices=["native", "shared"], default="shared")
    p_bundle_many.add_argument("--runtime-stem-max-gain-db", type=float, default=None)
    p_bundle_many.add_argument("--force", action="store_true")
    p_bundle_many.add_argument("--publish", action="store_true")
    p_bundle_many.add_argument("--zip", action="store_true")
    p_bundle_many.add_argument("--zip-report", action="store_true", default=True)
    p_bundle_many.add_argument("--no-zip-report", dest="zip_report", action="store_false")
    p_bundle_many.add_argument("--skip-spectrograms", action="store_true")
    p_bundle_many.add_argument("--include-scratch-stems", action="store_true")
    p_bundle_many.add_argument("--render-audio-mode", choices=["full", "full-mix-only", "simple-mix"], default="full")
    p_bundle_many.add_argument("--profile-render", action="store_true")
    p_bundle_many.add_argument("--plot-format", choices=["jpg", "png"], default="jpg")
    p_bundle_many.add_argument("--jpeg-quality", type=int, default=84)
    p_bundle_many.add_argument("--bundle-root", type=Path, default=None)
    p_bundle_many.add_argument("--log-root", type=Path, default=None)
    p_bundle_many.set_defaults(func=_cmd_bundle_many)

    p_cue = sub.add_parser("cue", help="Cue-oriented workflows")
    cue_sub = p_cue.add_subparsers(dest="cue_action", required=True)
    p_cue_bundle = cue_sub.add_parser("bundle", help="Render, debug, and package one cue")
    add_bundle_args(p_cue_bundle)
    p_cue_bundle.set_defaults(func=cmd_bundle)

    p_sb = sub.add_parser(
        "sandbox",
        help="Sandbox-cue presets (lofi_study_loop, long_lofi_drift, pulse_drift_voyage)",
    )
    sb_sub = p_sb.add_subparsers(dest="action", required=True)
    for action in ("render", "publish", "render-publish"):
        sp = sb_sub.add_parser(action)
        sp.add_argument(
            "--cue",
            action="append",
            choices=SANDBOX_CUES,
            help="restrict to the named sandbox cue(s); repeat to select multiple",
        )
        sp.add_argument("--backend", default="pretty-midi")
        sp.add_argument("--force-render", action="store_true")
        # publish-only convenience: the user typing `publish` already implies skip-render.
        sp.add_argument(
            "--skip-render",
            action="store_true",
            help="alias: ignored when action is publish; treats render-publish as publish",
        )
        add_publish_args(sp)
        sp.set_defaults(func=cmd_sandbox)
    p_sb.set_defaults(func=cmd_sandbox)

    p_radio = sub.add_parser(
        "radio",
        help="All radio cues: SANDBOX_CUES + scores/active/* + EXTRA_RADIO_CUES",
    )
    radio_choices = radio_cues()
    radio_sub = p_radio.add_subparsers(dest="action", required=True)
    for action in ("render", "publish", "render-publish"):
        sp = radio_sub.add_parser(action)
        sp.add_argument(
            "--cue",
            action="append",
            choices=radio_choices,
            help="restrict to the named radio cue(s); repeat to select multiple",
        )
        sp.add_argument("--backend", default="pretty-midi")
        sp.add_argument("--force-render", action="store_true")
        sp.add_argument(
            "--skip-render",
            action="store_true",
            help="alias: ignored when action is publish; treats render-publish as publish",
        )
        add_publish_args(sp)
        sp.set_defaults(func=cmd_radio)
    p_radio.set_defaults(func=cmd_radio)


    p_plugins = sub.add_parser("plugins", help="Inspect optional LV2/VST3/SFZ rendering infrastructure")
    plugin_sub = p_plugins.add_subparsers(dest="plugin_action", required=True)

    p_pd = plugin_sub.add_parser("doctor", help="print optional backend diagnostics as JSON")
    p_pd.add_argument("--fast", action="store_true", help="skip plugin-count probes")
    p_pd.set_defaults(func=cmd_plugins_doctor)

    p_pv = plugin_sub.add_parser("list-vst3", help="list discovered VST3 bundle paths")
    p_pv.add_argument("--path", action="append", default=[], help="additional/override search root; repeatable")
    p_pv.add_argument("--json", action="store_true", help="emit JSON instead of one path per line")
    p_pv.set_defaults(func=cmd_plugins_list_vst3)

    p_pl = plugin_sub.add_parser("list-lv2", help="list installed LV2 plugin URIs via lv2ls")
    p_pl.add_argument("--limit", type=int, default=None)
    p_pl.add_argument("--json", action="store_true", help="emit JSON instead of one URI per line")
    p_pl.set_defaults(func=cmd_plugins_list_lv2)

    p_pi = plugin_sub.add_parser("lv2-info", help="inspect one LV2 plugin URI via lv2info")
    p_pi.add_argument("uri")
    p_pi.add_argument("--raw", action="store_true", help="print raw lv2info text instead of JSON")
    p_pi.set_defaults(func=cmd_plugins_lv2_info)

    p_ps = plugin_sub.add_parser("validate-score", help="preflight optional plugin/effect references in a score")
    p_ps.add_argument("score", help="cue id or score YAML path")
    p_ps.add_argument("--warn-only", action="store_true", help="return success even if missing optional tools are reported")
    p_ps.set_defaults(func=cmd_plugins_validate_score)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command in ("sandbox", "radio"):
        # Map --skip-render onto action.
        if getattr(args, "skip_render", False) and args.action == "render-publish":
            args.action = "publish"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

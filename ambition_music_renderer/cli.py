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

import json
import shutil
import subprocess
import sys
from pathlib import Path

from ._paths import find_score as _find_score
from ._paths import generated_root as _generated_root
from ._paths import output_root as _output_root
from ._paths import project_root as _project_root
from ._paths import repo_root as _repo_root

import kwconf

from .profiler import profile
from .render.generated_layout import begin_generated_run
from .render.generated_layout import generated_manifest_search_roots
from .render.generated_layout import generated_run_layout
from .render.generated_layout import latest_manifest_in_roots
from .render.generated_layout import mark_generated_run_latest
from .render.generated_layout import resolve_latest_generated_dir


def _progress(iterable, *, total, desc):
    import ubelt as ub

    return ub.ProgIter(
        iterable,
        total=total,
        desc=desc,
        verbose=3,
        freq=1,
        adjust=False,
    )


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
    return _project_root()


def repo_root() -> Path:
    return _repo_root()


def generated_root() -> Path:
    return _generated_root()


def output_root() -> Path:
    """Legacy hashed output root used by the underlying renderer."""
    return _output_root()


def find_score(cue: str) -> Path | None:
    """Locate a cue YAML by name. Searches scores/{active,examples,archive}/.

    Accepts a bare cue id (e.g. ``lofi_study_loop``) or a relative/absolute
    path to a YAML.
    """
    return _find_score(cue, subdirs=SCORE_DIRS)


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


@profile
def needs_render(cue: str, yaml_path: Path, outdir: Path) -> bool:
    latest_outdir = resolve_latest_generated_dir(outdir)
    preview_dir = latest_outdir / "preview"
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
        "ambition_music_renderer.render.isolated",
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


def render_mode_for_cue(cue: str, args) -> tuple[bool, bool]:
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


@profile
def find_latest_manifest(outdir: Path, cue: str) -> Path | None:
    return latest_manifest_in_roots(generated_manifest_search_roots(outdir), cue)


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
    manifest_root = manifest_path.parent

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
        src = manifest_root / str(rel)
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
    outdir = resolve_latest_generated_dir(outdir)
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
            "Render with `cue_bundle --publish` or render_isolated --full-mix-only before publishing.",
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


@profile
def render_cue_to_versioned_generated(
    cue: str,
    yaml_path: Path,
    *,
    backend: str = "pretty-midi",
    simple_mix: bool = True,
    full_mix_only: bool = False,
    extra_args: list[str] | None = None,
) -> bool:
    cue_dir = generated_root() / cue
    layout = generated_run_layout(cue_dir, yaml_path, backend)
    outdir = begin_generated_run(layout)
    ok = render_cue(
        cue,
        yaml_path,
        outdir,
        backend=backend,
        simple_mix=simple_mix,
        full_mix_only=full_mix_only,
        extra_args=extra_args,
    )
    if ok:
        mark_generated_run_latest(layout)
    return ok


@profile
def cmd_render(args) -> int:
    yaml_path = find_score(args.cue)
    if yaml_path is None:
        print(f"error: cue not found: {args.cue}", file=sys.stderr)
        return 2
    simple_mix, full_mix_only = render_mode_for_cue(args.cue, args)
    ok = render_cue_to_versioned_generated(
        args.cue,
        yaml_path,
        backend=args.backend,
        simple_mix=simple_mix,
        full_mix_only=full_mix_only,
    )
    return 0 if ok else 1


@profile
def cmd_publish(args) -> int:
    outdir = generated_root() / args.cue
    resolved_outdir = resolve_latest_generated_dir(outdir)
    # Fallback to legacy output/ tree if generated/ is empty.
    if not (resolved_outdir / "preview").exists():
        legacy = output_root() / args.cue
        if (legacy / "preview").exists():
            outdir = legacy
        else:
            outdir = resolved_outdir
    ok = publish_cue(args.cue, outdir, args.dest_root)
    return 0 if ok else 1


@profile
def cmd_render_publish(args) -> int:
    yaml_path = find_score(args.cue)
    if yaml_path is None:
        print(f"error: cue not found: {args.cue}", file=sys.stderr)
        return 2
    outdir = generated_root() / args.cue
    if args.force_render or needs_render(args.cue, yaml_path, outdir):
        simple_mix, full_mix_only = render_mode_for_cue(args.cue, args)
        if not render_cue_to_versioned_generated(
            args.cue,
            yaml_path,
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
            if not render_cue_to_versioned_generated(
                cue,
                yaml_path,
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


def _run_bulk(args, cues: tuple[str, ...]) -> int:
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


@profile
def cmd_sandbox(args) -> int:
    """Render+publish the sandbox single-track cues.

    Mirrors the legacy ``tools/audio/render_sandbox_music.py`` behavior:
    skip the renderer when the YAML mtime is older than the latest preview,
    use --simple-mix for these single-track cues, publish the newest
    full_soundtrack_preview.ogg into the bevy asset tree.
    """
    cues = tuple(args.cue) if args.cue else SANDBOX_CUES
    return _run_bulk(args, cues)


@profile
def cmd_radio(args) -> int:
    """Render+publish every cue we expose on the in-game radio.

    Covers ``SANDBOX_CUES`` plus auto-discovered ``scores/active/*`` cues
    plus the curated ``EXTRA_RADIO_CUES`` list. Skips ``ADAPTIVE_CUES``
    (those go through ``scripts/regen_first_goblin_tune_v2.sh``). Honors
    ``preview/published.ogg`` pins for cues whose mastered file lives
    under a manual filename.
    """
    cues = tuple(args.cue) if args.cue else radio_cues()
    return _run_bulk(args, cues)


@profile
def cmd_bundle(args) -> int:
    from .render.bundle import CueBundleConfig, create_bundle_from_config, print_bundle_summary

    config = args if isinstance(args, CueBundleConfig) else CueBundleConfig.cli(argv=False, data=dict(args))
    report = create_bundle_from_config(config)
    print_bundle_summary(report)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok", True) else 1




def cmd_plugins_doctor(args) -> int:
    from .audio_plugins import collect_plugin_diagnostics

    report = collect_plugin_diagnostics(probe_counts=not args.fast)
    print(json.dumps(report, indent=2))
    return 0


def cmd_plugins_list_vst3(args) -> int:
    from .audio_plugins import discover_vst3_plugins

    roots = [Path(p) for p in args.path] if args.path else None
    plugins = discover_vst3_plugins(roots)
    if args.json:
        print(json.dumps(plugins, indent=2))
    else:
        for plugin in plugins:
            print(plugin["path"])
    return 0


def cmd_plugins_list_lv2(args) -> int:
    from .audio_plugins import discover_lv2_plugins

    uris = discover_lv2_plugins(limit=args.limit)
    if args.json:
        print(json.dumps(uris, indent=2))
    else:
        for uri in uris:
            print(uri)
    return 0


def cmd_plugins_lv2_info(args) -> int:
    from .audio_plugins import lv2_info

    report = lv2_info(args.uri)
    if args.raw:
        print(report.get("stdout", ""), end="")
        if report.get("stderr"):
            print(report["stderr"], file=sys.stderr, end="")
    else:
        print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


def cmd_plugins_validate_score(args) -> int:
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


class RenderCommand(kwconf.Config):
    """Render a single cue YAML."""


    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path")
    backend: str = kwconf.Value("pretty-midi", help="renderer backend")
    simple_mix: bool = kwconf.Flag(True, help="emit only the mastered preview")
    full_mix_only: bool = kwconf.Flag(False, help="emit mastered preview plus per-section full mixes")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return cmd_render(config)


class PublishCommand(kwconf.Config):
    """Publish newest preview to sandbox assets."""

    cue: str = kwconf.Value(None, position=1)
    dest_root: Path = kwconf.Value(default_factory=default_publish_dest_root, parser=Path, help="install destination root")

    def __post_init__(self) -> None:
        if not isinstance(self.dest_root, Path):
            self.dest_root = Path(self.dest_root)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return cmd_publish(config)


class RenderPublishCommand(kwconf.Config):
    """Render then publish a single cue."""

    cue: str = kwconf.Value(None, position=1)
    backend: str = kwconf.Value("pretty-midi")
    simple_mix: bool = kwconf.Flag(True)
    full_mix_only: bool = kwconf.Flag(False)
    dest_root: Path = kwconf.Value(default_factory=default_publish_dest_root, parser=Path)
    force_render: bool = kwconf.Flag(False)

    def __post_init__(self) -> None:
        if not isinstance(self.dest_root, Path):
            self.dest_root = Path(self.dest_root)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return cmd_render_publish(config)


class BundleCommand(kwconf.Config):
    """Render, debug, and package a cue bundle."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    backend: str = kwconf.Value("pretty-midi", choices=["pretty-midi", "fluidsynth-cli", "fallback", "auto"])
    runtime_stem_gain_mode: str = kwconf.Value(
        "native",
        choices=["native", "shared"],
        help=(
            "runtime adaptive stem export mode: native preserves current raw "
            "levels; shared applies one shared reference gain across all stems"
        ),
    )
    runtime_stem_max_gain_db: float | None = kwconf.Value(
        None,
        help="cap shared runtime stem gain; default is renderer policy or YAML render.runtime_stems.max_gain_db",
    )
    outdir: Path | None = kwconf.Value(None, parser=Path)
    bundle_root: Path | None = kwconf.Value(None, parser=Path)
    force: bool = kwconf.Flag(False, help="force render regeneration")
    publish: bool = kwconf.Flag(False, help="publish full.ogg to game assets after rendering")
    dest_root: Path | None = kwconf.Value(None, parser=Path, help="game music generated asset root")
    zip_bundle: bool = kwconf.Flag(
        False,
        alias=["zip"],
        help="write a complete uploadable bundle zip including manifest-referenced audio",
    )
    zip_report_bundle: bool = kwconf.Flag(
        False,
        alias=["zip_report"],
        help="write a compact report zip excluding OGG/WAV/NPY/MIDI binaries",
    )
    plot_format: str = kwconf.Value(
        "jpg",
        choices=["jpg", "png"],
        help="spectrogram image format for bundles; jpg is much smaller and reports keep numeric values",
    )
    jpeg_quality: int = kwconf.Value(84, help="JPEG quality for spectrogram plots")
    jobs: int = kwconf.Value(1, short_alias=["j"], help="render worker count")
    include_scratch_stems: bool = kwconf.Flag(
        False,
        help="include raw scratch_stems/*.npy in the bundle zip; useful but can be large",
    )
    skip_render: bool = kwconf.Flag(False, help="bundle/analyze existing outdir")
    skip_spectrograms: bool = kwconf.Flag(False, help="skip spectrogram generation")
    render_audio_mode: str = kwconf.Value(
        "full",
        choices=["full", "full-mix-only", "simple-mix"],
        help=(
            "audio export scope for render_isolated. full preserves all adaptive "
            "stem/state preview OGGs; full-mix-only keeps scratch stems plus "
            "mastered preview and section full mixes; simple-mix writes only the "
            "mastered preview."
        ),
    )
    profile_render: bool = kwconf.Flag(
        False,
        help="enable LINE_PROFILE=1 and run render_isolated plus serial workers in-process for line_profiler",
    )
    render_in_process: bool = kwconf.Flag(
        False,
        help="debug/profiling mode: import and run render_isolated instead of launching it as a subprocess",
    )

    def __post_init__(self) -> None:
        self.jobs = int(self.jobs)
        self.jpeg_quality = int(self.jpeg_quality)
        for key in ("outdir", "bundle_root", "dest_root"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return cmd_bundle(config)



class CueModal(kwconf.ModalCLI):
    """Cue-oriented workflows."""

    bundle = BundleCommand


class BundleManyCommand(kwconf.Config):
    """Render/debug many cue bundles in parallel with per-cue logs."""


    cues: list[str] = kwconf.Value(default_factory=list, position=1, nargs="*", help="cue ids or YAML paths; omit to discover by --scope")
    workers: int | None = kwconf.Value(None, short_alias=["j"], help="parallel cue_bundle jobs")
    render_jobs: int = kwconf.Value(1, help="per-cue render worker count")
    scope: str = kwconf.Value("active", choices=["active", "examples", "all"])
    include_examples: bool = kwconf.Flag(False)
    backend: str = kwconf.Value("pretty-midi")
    runtime_stem_gain_mode: str = kwconf.Value("shared", choices=["native", "shared"])
    runtime_stem_max_gain_db: float | None = kwconf.Value(None)
    force: bool = kwconf.Flag(False)
    publish: bool = kwconf.Flag(False)
    zip: bool = kwconf.Flag(False)
    zip_report: bool = kwconf.Flag(True)
    skip_spectrograms: bool = kwconf.Flag(False)
    include_scratch_stems: bool = kwconf.Flag(False)
    render_audio_mode: str = kwconf.Value("full", choices=["full", "full-mix-only", "simple-mix"])
    profile_render: bool = kwconf.Flag(False)
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])
    jpeg_quality: int = kwconf.Value(84)
    bundle_root: Path | None = kwconf.Value(None, parser=Path)
    log_root: Path | None = kwconf.Value(None, parser=Path)

    def __post_init__(self) -> None:
        if self.log_root is None:
            self.log_root = package_dir() / "batch_logs"
        self.render_jobs = int(self.render_jobs)
        self.jpeg_quality = int(self.jpeg_quality)
        if self.workers is not None:
            self.workers = int(self.workers)
        for key in ("bundle_root", "log_root"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        from .render.batch_bundle import run_batch_bundle

        return run_batch_bundle(config)


class BulkActionConfig(kwconf.Config):
    """Shared options for sandbox/radio bulk cue actions."""

    cue: list[str] | None = kwconf.Value(None, help="restrict to named cue(s); may be comma/list parsed")
    backend: str = kwconf.Value("pretty-midi")
    force_render: bool = kwconf.Flag(False)
    skip_render: bool = kwconf.Flag(False, help="treat render_publish as publish")
    dest_root: Path = kwconf.Value(default_factory=default_publish_dest_root, parser=Path)

    def __post_init__(self) -> None:
        if not isinstance(self.dest_root, Path):
            self.dest_root = Path(self.dest_root)


class SandboxRender(BulkActionConfig):

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        config.action = "render"
        return cmd_sandbox(config)


class SandboxPublish(BulkActionConfig):

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        config.action = "publish"
        return cmd_sandbox(config)


class SandboxRenderPublish(BulkActionConfig):

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        config.action = "publish" if config.skip_render else "render-publish"
        return cmd_sandbox(config)


class SandboxModal(kwconf.ModalCLI):
    """Sandbox-cue presets."""

    render = SandboxRender
    publish = SandboxPublish
    render_publish = SandboxRenderPublish


class RadioRender(BulkActionConfig):

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        config.action = "render"
        return cmd_radio(config)


class RadioPublish(BulkActionConfig):

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        config.action = "publish"
        return cmd_radio(config)


class RadioRenderPublish(BulkActionConfig):

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        config.action = "publish" if config.skip_render else "render-publish"
        return cmd_radio(config)


class RadioModal(kwconf.ModalCLI):
    """All radio cues."""

    render = RadioRender
    publish = RadioPublish
    render_publish = RadioRenderPublish


class PluginDoctor(kwconf.Config):
    fast: bool = kwconf.Flag(False, help="skip plugin-count probes")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_doctor(cls.cli(argv=argv, data=kwargs))


class PluginListVST3(kwconf.Config):
    path: list[str] = kwconf.Value(default_factory=list, help="additional/override search root")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_list_vst3(cls.cli(argv=argv, data=kwargs))


class PluginListLV2(kwconf.Config):
    limit: int | None = kwconf.Value(None)
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_list_lv2(cls.cli(argv=argv, data=kwargs))


class PluginLV2Info(kwconf.Config):
    uri: str = kwconf.Value(None, position=1)
    raw: bool = kwconf.Flag(False, help="print raw lv2info text")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_lv2_info(cls.cli(argv=argv, data=kwargs))


class PluginValidateScore(kwconf.Config):
    score: str = kwconf.Value(None, position=1, help="cue id or score YAML path")
    warn_only: bool = kwconf.Flag(False, help="return success even if missing optional tools are reported")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_validate_score(cls.cli(argv=argv, data=kwargs))


class PluginsModal(kwconf.ModalCLI):
    """Inspect optional LV2/VST3/SFZ rendering infrastructure."""

    doctor = PluginDoctor
    list_vst3 = PluginListVST3
    list_lv2 = PluginListLV2
    lv2_info = PluginLV2Info
    validate_score = PluginValidateScore

class _LazyToolCommand(kwconf.Config):
    """Local proxy for package tool modules with optional/heavy imports."""

    _module_name = ""
    _config_name = ""

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        import importlib

        from .kwconf_runner import config_to_argv

        module = importlib.import_module(f".{cls._module_name}", __package__)
        target_config_cls = getattr(module, cls._config_name)
        return int(module.main(argv=config_to_argv(target_config_cls, config.asdict())))


class ArrangementAuditTool(_LazyToolCommand):
    """Audit MusicIR arrangement density and event overlap."""

    _module_name = "audit.arrangement_audit"
    _config_name = "ArrangementAuditConfig"

    score: Path = kwconf.Value(None, position=1, parser=Path)
    outdir: Path | None = kwconf.Value(None, parser=Path)
    bucket_beats: float = kwconf.Value(0.25)
    max_rows: int = kwconf.Value(40)
    json: bool = kwconf.Flag(False)


class DissonanceAuditTool(_LazyToolCommand):
    """Audit MusicIR harmonic dissonance hotspots."""

    _module_name = "audit.dissonance_audit"
    _config_name = "DissonanceAuditConfig"

    score: Path = kwconf.Value(None, position=1, parser=Path, help="MusicIR YAML score to analyze")
    outdir: Path | None = kwconf.Value(None, parser=Path, help="directory for reports; defaults next to score")
    bucket_beats: float = kwconf.Value(0.25, help="analysis bucket size in beats")
    max_hotspots: int = kwconf.Value(40)
    json: bool = kwconf.Flag(False, help="also print JSON payload to stdout")
    plots: Path | None = kwconf.Value(None, parser=Path, help="optional directory for plot images")
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"], help="format for generated plots")


class ReferenceAudioAuditTool(_LazyToolCommand):
    """Analyze reference audio and write comparison reports."""

    _module_name = "audit.reference_audio_audit"
    _config_name = "ReferenceAudioAuditConfig"

    audio: Path = kwconf.Value(None, position=1, parser=Path, help="reference audio file")
    outdir: Path = kwconf.Value(None, parser=Path, required=True)
    frame_seconds: float = kwconf.Value(0.5)
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])


class ShrillNoteAuditTool(_LazyToolCommand):
    """Audit notes that may be shrill or whistle-like."""

    _module_name = "audit.shrill_note_audit"
    _config_name = "ShrillNoteAuditConfig"

    score: Path = kwconf.Value(None, position=1, parser=Path)
    outdir: Path | None = kwconf.Value(None, parser=Path)
    plots: Path | None = kwconf.Value(None, parser=Path)
    min_frequency_hz: float = kwconf.Value(4186.01)
    max_candidates: int = kwconf.Value(120)
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])
    json: bool = kwconf.Flag(False)


class SourNoteAuditTool(_LazyToolCommand):
    """Audit likely sour-note candidates."""

    _module_name = "audit.sour_note_audit"
    _config_name = "SourNoteAuditConfig"

    score: Path = kwconf.Value(None, position=1, parser=Path)
    outdir: Path | None = kwconf.Value(None, parser=Path)
    plots: Path | None = kwconf.Value(None, parser=Path)
    bucket_beats: float = kwconf.Value(0.25)
    max_candidates: int = kwconf.Value(80)
    min_score: float = kwconf.Value(0.28)
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])
    json: bool = kwconf.Flag(False)


class AuditCueBalanceTool(_LazyToolCommand):
    """Print peak/RMS balance for generated cue OGG files."""

    _module_name = "audit.audit_cue_balance"
    _config_name = "AuditCueBalanceConfig"

    root: Path | None = kwconf.Value(None, position=1, parser=Path, nargs="?")


class InstallFirstGoblinTuneTool(_LazyToolCommand):
    """Install first_goblin_tune_v2 renderer outputs into stable asset paths."""

    _module_name = "legacy.install_first_goblin_tune_v2"
    _config_name = "InstallFirstGoblinTuneConfig"

    src: Path | None = kwconf.Value(None, parser=Path, help="Renderer output directory")
    clean: bool = kwconf.Flag(False, help="Wipe destination directory first")
    with_stems: bool = kwconf.Flag(False, help="Also require/install per-stem OGGs")


class LevelReportTool(_LazyToolCommand):
    """Report rendered cue loudness / peak levels."""

    _module_name = "audit.level_report"
    _config_name = "LevelReportConfig"

    root: Path | None = kwconf.Value(None, parser=Path, help="music root to scan")
    glob: str = kwconf.Value("*/full.ogg", help="glob under --root for files to analyze")
    target_rms_db: float = kwconf.Value(-20.0)
    rms_tol: float = kwconf.Value(3.0)
    format: str = kwconf.Value("table", choices=["table", "tsv"])
    check: bool = kwconf.Flag(False)


class FirstGoblinTransitionLabTool(_LazyToolCommand):
    """Create the first-goblin transition lab experiment score."""

    _module_name = "legacy.make_first_goblin_transition_lab"
    _config_name = "FirstGoblinTransitionLabConfig"

    source: Path | None = kwconf.Value(None, parser=Path)
    output: Path | None = kwconf.Value(None, parser=Path)
    force: bool = kwconf.Flag(False, help="overwrite an existing experiment score")


class SpectralCompareTool(_LazyToolCommand):
    """Compare spectral energy in rendered scratch stems."""

    _module_name = "audit.spectral_compare"
    _config_name = "SpectralCompareConfig"

    cue_outdir: Path = kwconf.Value(None, position=1, parser=Path)
    window: list[float] = kwconf.Value(default_factory=lambda: [38.0, 43.0], nargs=2)
    sr: int = kwconf.Value(48000)
    label: str = kwconf.Value("")


class SpectralLocalizeTool(_LazyToolCommand):
    """Localize spectral content in rendered scratch stems."""

    _module_name = "audit.spectral_localize"
    _config_name = "SpectralLocalizeConfig"

    cue_outdir: Path = kwconf.Value(None, position=1, parser=Path)
    window: list[float] = kwconf.Value(default_factory=lambda: [0.0, -1.0], nargs=2, help="Time window in seconds")
    bucket: float = kwconf.Value(0.25, help="Bucket size in seconds")
    sr: int = kwconf.Value(48000, help="Sample rate of stems")
    bands: str = kwconf.Value("default", choices=["default", "vhigh-only"])


class TransitionAuditTool(_LazyToolCommand):
    """Audit adaptive section transition metrics and previews."""

    _module_name = "audit.transition_audit"
    _config_name = "TransitionAuditConfig"

    root: Path = kwconf.Value(None, position=1, parser=Path, help="generated cue root containing adaptive/<section>/")
    sections: list[str] = kwconf.Value(default_factory=lambda: ["intro", "wave1"], nargs=2)
    window: float = kwconf.Value(1.0, help="head/tail analysis window in seconds")
    tail_window: float = kwconf.Value(1.5, help="tail hiss/noise window in seconds")
    crossfade: float = kwconf.Value(0.35, help="runtime-style crossfade seconds")
    crossfade_shape: str = kwconf.Value("ambition_runtime", choices=["linear", "equal_power", "ambition_runtime"])
    incoming_start: str = kwconf.Value("smooth", choices=["smooth", "target"])
    context: float = kwconf.Value(4.0, help="seconds of each side to include in previews")
    outdir: Path | None = kwconf.Value(None, parser=Path)
    no_preview: bool = kwconf.Flag(False, help="only print metrics; do not write WAV previews")
    no_plots: bool = kwconf.Flag(False, help="skip plots and Markdown visual report")
    envelope_window_ms: float = kwconf.Value(80.0)
    envelope_hop_ms: float = kwconf.Value(20.0)


class AuditModal(kwconf.ModalCLI):
    """Analysis and audit helpers for rendered scores and generated audio."""

    arrangement = ArrangementAuditTool
    arrangement_audit = ArrangementAuditTool
    dissonance = DissonanceAuditTool
    dissonance_audit = DissonanceAuditTool
    reference_audio = ReferenceAudioAuditTool
    reference_audio_audit = ReferenceAudioAuditTool
    shrill_notes = ShrillNoteAuditTool
    shrill_note_audit = ShrillNoteAuditTool
    sour_notes = SourNoteAuditTool
    sour_note_audit = SourNoteAuditTool
    cue_balance = AuditCueBalanceTool
    audit_cue_balance = AuditCueBalanceTool
    levels = LevelReportTool
    level_report = LevelReportTool
    spectral_compare = SpectralCompareTool
    spectral_localize = SpectralLocalizeTool
    transition = TransitionAuditTool
    transition_audit = TransitionAuditTool


class LegacyModal(kwconf.ModalCLI):
    """Quarantined legacy helpers kept importable until we verify deletion safety."""

    install_first_goblin_tune_v2 = InstallFirstGoblinTuneTool
    make_first_goblin_transition_lab = FirstGoblinTransitionLabTool


class ToolsModal(kwconf.ModalCLI):
    """Compatibility alias for older `tools ...` invocations.

    Prefer `audit ...` for active diagnostics and `legacy ...` for quarantined
    one-off helpers.
    """

    arrangement_audit = ArrangementAuditTool
    dissonance_audit = DissonanceAuditTool
    reference_audio_audit = ReferenceAudioAuditTool
    shrill_note_audit = ShrillNoteAuditTool
    sour_note_audit = SourNoteAuditTool
    audit_cue_balance = AuditCueBalanceTool
    level_report = LevelReportTool
    spectral_compare = SpectralCompareTool
    spectral_localize = SpectralLocalizeTool
    transition_audit = TransitionAuditTool
    install_first_goblin_tune_v2 = InstallFirstGoblinTuneTool
    make_first_goblin_transition_lab = FirstGoblinTransitionLabTool


class AmbitionMusicRendererCLI(kwconf.ModalCLI):
    """Modal CLI for ambition_music_renderer."""

    render = RenderCommand
    publish = PublishCommand
    render_publish = RenderPublishCommand
    cue_bundle = BundleCommand
    bundle = BundleCommand
    bundle_many = BundleManyCommand
    cue = CueModal
    sandbox = SandboxModal
    radio = RadioModal
    plugins = PluginsModal
    audit = AuditModal
    legacy = LegacyModal
    tools = ToolsModal



@profile
def main(argv: list[str] | None = None) -> int:
    import time as _time

    total_start = _time.perf_counter()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    command_name = next((item for item in raw_argv if not str(item).startswith("-")), "<parse-error>")
    try:
        return int(AmbitionMusicRendererCLI.main(argv=argv))
    finally:
        elapsed = _time.perf_counter() - total_start
        print(f"[ambition_music_renderer] command={command_name} total_elapsed_s={elapsed:.3f}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

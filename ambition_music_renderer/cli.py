"""Modal CLI for ambition_music_renderer.

Subcommands:

    cue list                List every cue id discovered under scores/.
    cue render <cue>        Render a single cue YAML to local generated/<cue>/.
                            Add --publish to also install full.ogg into the
                            game asset tree.
    cue publish <cue>       Publish newest preview into the sandbox asset tree.
    cue bundle <cue>...     Render+debug+package one or more cues. Pass several
                            cue ids and -j/--jobs N to run them in parallel
                            (one render subprocess per cue).
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
from ._paths import scores_root as _scores_root
from ._paths import SCORE_DIRS as _SCORE_DIRS
from ._paths import SCORE_SUFFIXES as _SCORE_SUFFIXES

import kwconf

from .profiler import profile
from .render.bundle_options import BundleOptions
from .render.bundle_options import PASSTHROUGH_FIELDS
from .render.generated_layout import begin_generated_run
from .render.generated_layout import generated_manifest_search_roots
from .render.generated_layout import generated_run_layout
from .render.generated_layout import latest_manifest_in_roots
from .render.generated_layout import mark_generated_run_latest
from .render.generated_layout import resolve_latest_generated_dir


_FINAL_BUNDLE_REPORT: dict[str, object] | None = None


def _schedule_final_bundle_summary(report: dict[str, object]) -> None:
    """Defer bundle path printing until after top-level timing output."""
    global _FINAL_BUNDLE_REPORT
    _FINAL_BUNDLE_REPORT = report


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
    if not ok:
        return 1
    if getattr(args, "publish", False):
        outdir = generated_root() / args.cue
        return 0 if publish_cue(args.cue, outdir, args.dest_root) else 1
    return 0


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


def _run_bulk(args, cues: tuple[str, ...], action: str) -> int:
    failed: list[str] = []
    desc = f"music {action}"
    for cue in _progress(cues, total=len(cues), desc=desc):
        stage = _process_simple_mix_cue(
            cue,
            action=action,
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
def run_bulk_cues(config, *, cues_factory, action: str) -> int:
    """Run a render/publish/render-publish pass over a preset cue set.

    ``cues_factory`` resolves the default cue set when ``--cue`` is not given
    (``SANDBOX_CUES`` for sandbox, ``radio_cues()`` for radio). For the
    ``render-publish`` action, ``--skip_render`` degrades it to publish-only.
    """
    cues = tuple(config.cue) if config.cue else tuple(cues_factory())
    if action == "render-publish" and config.skip_render:
        action = "publish"
    return _run_bulk(config, cues, action)


def _single_bundle_config(args, cue: str):
    """Build a per-cue ``CueBundleConfig`` from the orchestrator ``args``.

    The shared ``BundleOptions`` fields copy across by name; the only divergence
    is the positional (``cues`` -> ``cue``) and the meaning of ``jobs`` (the
    orchestrator's ``render_jobs`` becomes the renderer's ``jobs`` worker count).
    """
    from .render.bundle import CueBundleConfig

    data = {field: getattr(args, field) for field in PASSTHROUGH_FIELDS}
    data["cue"] = cue
    data["jobs"] = args.render_jobs
    return CueBundleConfig.cli(argv=False, data=data)


@profile
def cmd_bundle(args) -> int:
    cues = list(args.cues)
    # Multiple cues, or an explicit cross-cue parallelism request, go through
    # the batch runner (one render subprocess per cue). A lone serial cue stays
    # in-process so profiling / --render_in_process / --json keep working.
    if len(cues) > 1 or args.jobs > 1:
        from .render.batch_bundle import run_batch_bundle

        return run_batch_bundle(args)

    from .render.bundle import create_bundle_from_config

    config = _single_bundle_config(args, cues[0])
    report = create_bundle_from_config(config)
    if config.json:
        print(json.dumps(report, indent=2, default=str))
    _schedule_final_bundle_summary(report)
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


def cmd_plugins_list_clap(args) -> int:
    from .audio_plugins import discover_clap_plugins

    roots = [Path(p) for p in args.path] if args.path else None
    plugins = discover_clap_plugins(roots)
    if args.json:
        print(json.dumps(plugins, indent=2))
    else:
        for plugin in plugins:
            print(plugin["path"])
    return 0


def cmd_plugins_list_sfz_libraries(args) -> int:
    from .instrument_libraries import collect_sfz_library_diagnostics

    report = collect_sfz_library_diagnostics(limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("SFZ roots:")
        for root in report["sfz_roots"]:
            print(f"  {root}")
        print(f"SFZ files: {report['sfz_count']}")
        print("Resolved aliases:")
        for name, resolved in sorted(report["alias_hits"].items()):
            if resolved:
                print(f"  {name}: {resolved}")
        missing = [name for name, resolved in sorted(report["alias_hits"].items()) if not resolved]
        if missing:
            print("Missing aliases:")
            for name in missing:
                print(f"  {name}")
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
    """Render a single cue YAML; optionally publish it to the game assets."""


    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path")
    backend: str = kwconf.Value("pretty-midi", help="renderer backend")
    simple_mix: bool = kwconf.Flag(True, help="emit only the mastered preview")
    full_mix_only: bool = kwconf.Flag(False, help="emit mastered preview plus per-section full mixes")
    publish: bool = kwconf.Flag(False, help="after rendering, install full.ogg into the game asset tree")
    dest_root: Path = kwconf.Value(
        default_factory=default_publish_dest_root,
        parser=Path,
        help="publish destination root (with --publish)",
    )

    def __post_init__(self) -> None:
        if not isinstance(self.dest_root, Path):
            self.dest_root = Path(self.dest_root)

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


class BundleCommand(BundleOptions):
    """Render, debug, and package one or more cue bundles.

    Shared per-cue knobs come from :class:`BundleOptions`. This orchestrator adds
    the multi-cue positional and the cross-cue parallelism: pass a single cue id
    to render it in-process (profiling and ``--json`` available), or several cue
    ids and/or ``-j/--jobs N`` to fan out across cues, one render subprocess each,
    with per-cue logs.
    """

    cues: list[str] = kwconf.Value(
        default_factory=list,
        position=1,
        nargs="+",
        help="one or more cue ids or .music.yaml paths",
    )
    jobs: int = kwconf.Value(1, short_alias=["j"], help="parallel cue count; >1 fans out across cues")
    render_jobs: int = kwconf.Value(1, help="per-cue render worker count")
    log_root: Path | None = kwconf.Value(None, parser=Path, help="batch per-cue log root (multi-cue runs)")

    def __post_init__(self) -> None:
        super().__post_init__()
        self.jobs = int(self.jobs)
        self.render_jobs = int(self.render_jobs)
        if self.log_root is None:
            self.log_root = package_dir() / "batch_logs"
        elif not isinstance(self.log_root, Path):
            self.log_root = Path(self.log_root)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return cmd_bundle(config)



def cue_id_from_path(path: Path) -> str:
    """Return the cue id for a score file (filename minus its score suffix)."""
    name = path.name
    for suffix in (".music.yaml", ".music.yml", *_SCORE_SUFFIXES):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def discover_cues() -> dict[str, list[str]]:
    """Map each scores/ subdir to the sorted cue ids it defines."""
    root = _scores_root()
    found: dict[str, list[str]] = {}
    for subdir in _SCORE_DIRS:
        directory = root / subdir
        if not directory.is_dir():
            continue
        ids = {
            cue_id_from_path(path)
            for path in directory.iterdir()
            if path.is_file() and any(path.name.endswith(s) for s in _SCORE_SUFFIXES)
        }
        if ids:
            found[subdir] = sorted(ids)
    return found


def cmd_cue_list(args) -> int:
    cues = discover_cues()
    if getattr(args, "json", False):
        print(json.dumps(cues, indent=2))
        return 0
    total = 0
    for subdir in _SCORE_DIRS:
        ids = cues.get(subdir, [])
        if not ids:
            continue
        print(f"{subdir} ({len(ids)}):")
        for cue_id in ids:
            print(f"  {cue_id}")
        total += len(ids)
    print(f"total cues: {total}")
    return 0


class ListCommand(kwconf.Config):
    """List all cue ids discovered under scores/."""

    json: bool = kwconf.Flag(False, help="emit JSON mapping of scores subdir -> cue ids")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_cue_list(cls.cli(argv=argv, data=kwargs))


class CueModal(kwconf.ModalCLI):
    """Cue-oriented workflows."""

    list = ListCommand
    render = RenderCommand
    publish = PublishCommand
    bundle = BundleCommand


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


def _bulk_command(name: str, doc: str, *, cues_factory, action: str):
    """Build a ``BulkActionConfig`` leaf command bound to a cue set + action.

    Replaces six near-identical subclasses (and their post-hoc ``config.action``
    attribute injection) with one factory: the action and default cue set are
    captured in the closure instead of mutated onto the parsed config.
    """

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return run_bulk_cues(config, cues_factory=cues_factory, action=action)

    return type(
        name,
        (BulkActionConfig,),
        {"__doc__": doc, "__module__": __name__, "main": main},
    )


class SandboxModal(kwconf.ModalCLI):
    """Sandbox-cue presets (single-track cues that ship via the radio)."""

    render = _bulk_command(
        "SandboxRender", "Render the sandbox cues.", cues_factory=lambda: SANDBOX_CUES, action="render"
    )
    publish = _bulk_command(
        "SandboxPublish", "Publish the sandbox cues.", cues_factory=lambda: SANDBOX_CUES, action="publish"
    )
    render_publish = _bulk_command(
        "SandboxRenderPublish",
        "Render+publish the sandbox cues (--skip_render = publish-only).",
        cues_factory=lambda: SANDBOX_CUES,
        action="render-publish",
    )


class RadioModal(kwconf.ModalCLI):
    """All in-game radio cues (SANDBOX_CUES + scores/active/* + EXTRA_RADIO_CUES)."""

    render = _bulk_command(
        "RadioRender", "Render every radio cue.", cues_factory=radio_cues, action="render"
    )
    publish = _bulk_command(
        "RadioPublish", "Publish every radio cue.", cues_factory=radio_cues, action="publish"
    )
    render_publish = _bulk_command(
        "RadioRenderPublish",
        "Render+publish every radio cue (--skip_render = publish-only).",
        cues_factory=radio_cues,
        action="render-publish",
    )


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


class PluginListCLAP(kwconf.Config):
    path: list[str] = kwconf.Value(default_factory=list, help="additional/override search root")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_list_clap(cls.cli(argv=argv, data=kwargs))


class PluginListSFZLibraries(kwconf.Config):
    limit: int = kwconf.Value(200)
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_list_sfz_libraries(cls.cli(argv=argv, data=kwargs))


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
    list_clap = PluginListCLAP
    list_sfz_libraries = PluginListSFZLibraries
    lv2_info = PluginLV2Info
    validate_score = PluginValidateScore

# Audit/legacy commands register their own Config classes directly. Each module
# defers its heavy imports (numpy/scipy/pretty_midi/matplotlib/render.score_*)
# via lazy_loader, so importing them here keeps CLI startup cheap while letting
# each Config own its argument schema as the single source of truth.
from .audit.arrangement_audit import ArrangementAuditConfig
from .audit.audit_cue_balance import AuditCueBalanceConfig
from .audit.dissonance_audit import DissonanceAuditConfig
from .audit.level_report import LevelReportConfig
from .audit.mix_balance_audit import MixBalanceAuditConfig
from .audit.reference_audio_audit import ReferenceAudioAuditConfig
from .audit.shrill_note_audit import ShrillNoteAuditConfig
from .audit.sour_note_audit import SourNoteAuditConfig
from .audit.spectral_compare import SpectralCompareConfig
from .audit.spectral_localize import SpectralLocalizeConfig
from .audit.transition_audit import TransitionAuditConfig
from .legacy.install_first_goblin_tune_v2 import InstallFirstGoblinTuneConfig
from .legacy.make_first_goblin_transition_lab import FirstGoblinTransitionLabConfig


class AuditModal(kwconf.ModalCLI):
    """Analysis and audit helpers for rendered scores and generated audio."""

    arrangement = ArrangementAuditConfig
    dissonance = DissonanceAuditConfig
    mix_balance = MixBalanceAuditConfig
    reference_audio = ReferenceAudioAuditConfig
    shrill_notes = ShrillNoteAuditConfig
    sour_notes = SourNoteAuditConfig
    cue_balance = AuditCueBalanceConfig
    levels = LevelReportConfig
    spectral_compare = SpectralCompareConfig
    spectral_localize = SpectralLocalizeConfig
    transition = TransitionAuditConfig


class LegacyModal(kwconf.ModalCLI):
    """Quarantined legacy helpers kept importable until we verify deletion safety."""

    install_first_goblin_tune_v2 = InstallFirstGoblinTuneConfig
    make_first_goblin_transition_lab = FirstGoblinTransitionLabConfig


class AmbitionMusicRendererCLI(kwconf.ModalCLI):
    """Modal CLI for ambition_music_renderer."""

    cue = CueModal
    sandbox = SandboxModal
    radio = RadioModal
    plugins = PluginsModal
    audit = AuditModal
    legacy = LegacyModal



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
        if _FINAL_BUNDLE_REPORT is not None:
            from .render.bundle_archive import print_bundle_summary

            print_bundle_summary(_FINAL_BUNDLE_REPORT)


if __name__ == "__main__":
    raise SystemExit(main())

"""Modal CLI for ambition_music_renderer.

Subcommands:

    cue list                List every cue id discovered under scores/.
    cue new <name>          Create a new MusicIR v3 score from the starter.
    cue render <cue>        Render a single cue YAML to local generated/<cue>/.
                            Add --publish to also install full.ogg into the
                            game asset tree.
    cue midi <cue>          Export a marked MIDI preview for score/form review.
    cue daw_export <cue>    Export DAW MIDI plus MusicIR provenance sidecar.
    cue daw_reconcile <cue> Compare edited DAW MIDI with its saved baseline.
    cue daw_apply <cue>     Apply supported DAW note edits back into MusicIR v3.
    cue validate <cue>      Compile/validate MusicIR without synthesizing audio.
    cue expand <cue>        Explain v3 source clips and their compiled events.
    cue graph <cue>         Show the v3 authoring graph and dependencies.
    cue trace_event <cue>   Trace one stable compiled event id to its source.
    cue quality <cue>       Report composition-level review evidence.
    cue determinism <cue>   Verify repeated compilation is identical.
    cue publish <cue>       Publish newest preview into the sandbox asset tree.
    cue bundle <cue>...     Render+debug+package one or more cues. For one cue,
                            -j/--jobs N parallelizes stem groups. For several,
                            it parallelizes cue subprocesses.
    sandbox render-publish  Render+publish the sandbox single-track cues
                            (lofi_study_loop, long_lofi_drift, pulse_drift_voyage).
    sandbox render          Render-only for sandbox cues.
    sandbox publish         Publish-only for sandbox cues (--skip-render alias).
    radio render-publish    Render+publish every cue exposed on the in-game
                            radio: SANDBOX_CUES plus auto-discovered
                            scores/active/* plus EXTRA_RADIO_CUES.
    radio render            Render-only for radio cues.
    radio publish           Publish-only for radio cues.
    instruments list        List the checked-in sampled-instrument vocabulary.
    instruments describe    Show canonical MusicIR usage and library nuances.
    instruments doctor      Check the local audio-tools install against expectations.
    instruments audition    Write a canonical v3 audition score for one instrument.
    techniques list         List backend-independent v3 performance techniques.
    techniques describe     Describe one performance technique.
    generators list         List MusicIR v3 procedural generator capabilities.
    generators describe     Describe one generator and its public parameters.
    generators schema       Emit JSON Schema for one generator block.
    processing list         List canonical render-time processors.
    processing describe     Describe one processor and its parameters.
    processing schema       Emit JSON Schema for one processor step.
    processing plan         Show canonical processing/mastering plans for a cue.
    audio compare           Compare before/after audio metrics and deltas.

Pinning a specific render: drop a file named ``published.ogg`` (or a symlink)
into ``output/<cue>/preview/`` (or ``generated/<cue>/preview/``) and publish
will copy that exact file instead of the auto-named full mix. Used when a
cue's mastered preview lives under a manual filename.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .publish_safely import publish_copy
from ._paths import find_score as _find_score
from ._paths import generated_root as _generated_root
from ._paths import output_root as _output_root
from ._paths import project_root as _project_root
from ._paths import declared_publish_root as _declared_publish_root
from ._paths import publish_root as _publish_root
from ._paths import repo_root as _repo_root
from ._paths import scores_root as _scores_root
from ._paths import SCORE_DIRS as _SCORE_DIRS
from ._paths import SCORE_SUFFIXES as _SCORE_SUFFIXES

import kwconf

from .profiler import profile
from .render.bundle_options import BACKEND_CHOICES
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

# Adaptive (multi-section) cues. Marked so the general render/publish path
# renders them full-mix-only and publishes each adaptive/<section>/<section>.full.ogg
# (see `render_mode_for_cue` / `publish_adaptive_full_sections`). They ride the
# normal bulk `radio` pass now — there is no dedicated per-cue installer.
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
    """Locate a cue YAML by id or path using the shared score-directory policy."""
    return _find_score(cue)


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

    Excludes cues already in ``SANDBOX_CUES`` (handled by that path). Adaptive
    cues (``ADAPTIVE_CUES``) ARE included — the render/publish path detects them
    and publishes their per-section adaptive full mixes.
    Returns a sorted, deduped tuple so the order is stable across runs.
    """
    active = package_dir() / "scores" / "active"
    if not active.is_dir():
        return ()
    cues: set[str] = set()
    for path in active.iterdir():
        name = path.name
        for suffix in (".music.yaml", *_SCORE_SUFFIXES):
            if name.endswith(suffix):
                cue = name[: -len(suffix)]
                if cue and cue not in SANDBOX_CUES:
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


def render_dependencies_need_refresh(
    yaml_path: Path, outdir: Path, backend: str
) -> tuple[bool, str]:
    """Cheaply decide whether the current machine/code needs a new render.

    ``needs_render`` remains the historical mtime/output-presence facade.  This
    companion check closes the migration gap it cannot see: renderer source,
    runtime/DSP versions, SoundFont contents, or the concrete SFZ/sample files
    selected by an unchanged score.
    """
    from .render.dependencies import dependency_change_summary
    from .render.generated_layout import (
        GeneratedRunLayout,
        compute_score_render_dependencies,
    )
    from .render.score_core import load_yaml

    try:
        spec = load_yaml(yaml_path)
        current = compute_score_render_dependencies(yaml_path, backend, spec=spec)
    except Exception as ex:  # Let preflight/render report the actionable error.
        return True, f"could not compute render dependencies: {ex}"
    layout = GeneratedRunLayout(cue_dir=Path(outdir), hash_id=current.short_hash)
    manifest_name = (
        f"{spec.get('id', Path(yaml_path).stem)}_{current.short_hash}"
        ".adaptive_manifest.json"
    )
    manifest_path = layout.run_dir / manifest_name
    if not manifest_path.is_file():
        return True, "no render for current dependency fingerprint"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    except Exception as ex:
        return True, f"could not read current dependency manifest: {ex}"
    reasons = dependency_change_summary(manifest.get("render_dependencies"), current)
    if reasons:
        return True, reasons[0]
    return False, "render dependencies current"


def python_exe() -> str:
    """Prefer the package venv if it exists, else current interpreter."""
    venv_python = package_dir() / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


#: Thread-pool knobs every numeric library reads at import time. A cue's own
#: parallelism is `--jobs`; these decide how many threads each of ITS libraries
#: opens underneath that, and they default to "one per core" regardless of how
#: many sibling cues are already running.
_THREAD_LIMIT_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def _child_env_with_thread_limit(threads: int) -> dict[str, str]:
    """The child's environment with its numeric libraries pinned to `threads`.

    ⛔ FANNING OUT CUES WITHOUT THIS OVERSUBSCRIBES THE BOX BY THE BLAS POOL.
    Measured 2026-09-02 on 14 cores: 14 concurrent cues, each nominally one
    worker, drove load average to 36 because every cue's numpy opened its own
    core-count-sized OpenBLAS pool. The cue budget in `_bulk_job_plan` is only
    honest if the libraries under each cue honour it too.

    ⚠ An explicit setting from the caller WINS. Someone who exported
    `OMP_NUM_THREADS` meant it.
    """
    env = dict(os.environ)
    for name in _THREAD_LIMIT_VARS:
        env.setdefault(name, str(max(1, int(threads))))
    return env


def render_cue(
    cue: str,
    yaml_path: Path,
    outdir: Path,
    *,
    backend: str = "pretty-midi",
    simple_mix: bool = True,
    full_mix_only: bool = False,
    extra_args: list[str] | None = None,
    thread_limit: int | None = None,
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
    env = _child_env_with_thread_limit(thread_limit) if thread_limit else None
    result = subprocess.run(cmd, cwd=package_dir(), env=env)
    return result.returncode == 0


def render_mode_for_cue(cue: str, args=None) -> tuple[bool, bool]:
    """Return ``(simple_mix, full_mix_only)`` for top-level rendering.

    Adaptive encounter cues default to per-section full mixes. Explicit
    ``--no-simple-mix`` requests the full per-stem adaptive export.
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
    """Return the consumer-declared publish root, raising if none is configured.

    Use ``declared_publish_dest_root`` for parse-time defaults that must permit
    commands which never publish.
    """
    return _publish_root()


def declared_publish_dest_root() -> Path | None:
    """The same answer, or `None` when nothing declared one — for an argument
    default. The raise moves to publish time; see `_paths.declared_publish_root`.
    """
    return _declared_publish_root()


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
        publish_copy(src, dest)
        copied.append(dest)

    # Keep the manifest next to the runtime files as a debugging breadcrumb.
    # The game does not load it today, but it makes it obvious which render hash
    # produced the shipped adaptive sections.
    if copied:
        publish_copy(manifest_path, dest_dir / f"{cue}.adaptive_manifest.json")
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
    publish_copy(src, dest)
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
    thread_limit: int | None = None,
) -> bool:
    cue_dir = generated_root() / cue
    layout = generated_run_layout(cue_dir, yaml_path, backend)
    outdir = begin_generated_run(layout)
    render_args = list(extra_args or [])
    render_args.append(f"--expected_render_hash={layout.hash_id}")
    ok = render_cue(
        cue,
        yaml_path,
        outdir,
        backend=backend,
        simple_mix=simple_mix,
        full_mix_only=full_mix_only,
        # main's `render_args` (which appends `--expected_render_hash`) AND the
        # branch's `thread_limit`: the two edits are independent and both wanted.
        extra_args=render_args,
        thread_limit=thread_limit,
    )
    if ok:
        mark_generated_run_latest(layout)
        # Keep the narrow historical instrument-resolution report as a human
        # diagnostic. Currentness itself is now owned by render_dependencies:
        # it fingerprints only the SFZ/sample files this cue resolves to rather
        # than hashing the complete audio-tools tree.
        # Bookkeeping must never fail a good render.
        try:
            from .audit.instrument_drift import write_fingerprint
            from .render.score_core import load_yaml as _load_yaml

            write_fingerprint(outdir, _load_yaml(yaml_path))
        except Exception as ex:  # noqa: BLE001 - never escalate bookkeeping
            print(f"warning: could not record instrument fingerprint for {cue}: {ex}", file=sys.stderr)
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
    render_jobs: int = 1,
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
        coarse_refresh = needs_render(cue, yaml_path, outdir)
        dependency_refresh = False
        dependency_reason = ""
        if not force_render and not coarse_refresh:
            dependency_refresh, dependency_reason = render_dependencies_need_refresh(
                yaml_path, outdir, backend
            )
        if force_render or coarse_refresh or dependency_refresh:
            if dependency_refresh and not coarse_refresh and not force_render:
                print(f"refresh render {cue}: {dependency_reason}")
            # Batch and single-cue rendering share adaptive-cue mode selection.
            simple_mix, full_mix_only = render_mode_for_cue(cue)
            # ⛔ `--force_render` must reach the ISOLATED renderer, not just
            # this branch. The versioned run directory is keyed by (YAML,
            # backend), so a forced run resolves to the SAME directory as the
            # previous render and `render.isolated` then no-ops on the finished
            # output already sitting there. Without this the flag only decides
            # whether to invoke a renderer that declines to do anything, and
            # `--force` is silently a no-op for any cue already rendered once.
            #
            # That is not hypothetical: the run key does not include which
            # instrument libraries are installed, so every cue rendered BEFORE
            # the SFZ libraries existed kept its General-MIDI audio through a
            # full forced re-render, and only cues whose YAML had changed since
            # picked up the sampled instruments.
            # ⚠ `--jobs` is the CUE'S share of the machine, decided by
            # `_bulk_job_plan`, not this renderer's own default. Its default is
            # `cpu_count // 2`, which is correct for one cue alone and
            # oversubscribes the box by that factor once cues run concurrently.
            extra_args = ["--force"] if force_render else []
            extra_args.append(f"--jobs={max(1, int(render_jobs))}")
            if not render_cue_to_versioned_generated(
                cue,
                yaml_path,
                backend=backend,
                simple_mix=simple_mix,
                full_mix_only=full_mix_only,
                extra_args=extra_args,
                thread_limit=render_jobs,
            ):
                return "render"
        else:
            print(f"skip render {cue}: score and render dependencies unchanged")
    if action in ("publish", "render-publish"):
        if not publish_cue(cue, outdir, dest_root):
            # Compatibility output may still hold publishable mastered previews.
            legacy = output_root() / cue
            if (legacy / "preview").exists():
                if not publish_cue(cue, legacy, dest_root):
                    return "publish"
            else:
                return "publish"
    return None


def _sampled_libraries_installed() -> bool:
    """Is ANY sampled instrument library present on this machine?

    Not "did this instrument resolve" — that is the renderer's job. This is the
    coarser question: the `.sfz` tree either exists here or it does not.
    """
    try:
        from .instrument_libraries import discover_sfz_files

        return bool(discover_sfz_files())
    except Exception:
        return False


def _walk_instrument_backends(node: Any) -> "Iterator[dict[str, Any]]":
    """Every `instrument_backend` mapping anywhere in a score, at any depth."""
    if isinstance(node, dict):
        backend = node.get("instrument_backend")
        if isinstance(backend, dict):
            yield backend
        for value in node.values():
            yield from _walk_instrument_backends(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_instrument_backends(value)


@functools.lru_cache(maxsize=None)
def _sfz_reference_resolves(
    reference: str, library_ref: bool, base_dir: str, prefer: tuple[str, ...]
) -> bool:
    """Memoised, because resolution GLOBS the library roots.

    Measured 2026-09-03 against an installed `/data/audio-tools`: 0.36 s to
    5.54 s for ONE reference, and a repeat call cost 0.84 s because nothing
    below here caches. The active catalogue names 68 distinct references across
    247 instrument backends, so resolving per backend without this would add
    minutes to a preflight whose whole purpose is to be cheap.
    """
    from .instrument_libraries import resolve_sfz_reference

    if library_ref:
        return resolve_sfz_reference(
            None, library_ref=reference, prefer=list(prefer),
            base_dir=Path(base_dir) if base_dir else None,
        ) is not None
    return resolve_sfz_reference(
        reference, prefer=list(prefer),
        base_dir=Path(base_dir) if base_dir else None,
    ) is not None


def _unresolvable_sfz_references(spec: Any, *, base_dir: "Path | None") -> list[str]:
    """The sampled libraries this score NAMES and this machine cannot find.

    ⛔⛔ THIS IGNORES `optional:` ON PURPOSE, AND THAT IS THE ENTIRE POINT.
    A missing library is not a per-instrument style choice — it is the machine
    rendering somebody's cue in the wrong instrument and reporting success,
    which is the failure Jon named: *"I don't want new machines to get bad
    fallbacks of songs."*

    ⚠ AND THE CATALOGUE CANNOT DEFEND ITSELF HERE. Measured 2026-09-03 across
    `scores/active`: **all 247 sfz instrument backends are `optional: True`** —
    231 say so explicitly, 16 inherit it from
    `_is_optional_instrument_backend`'s default — and only 2 of 75 scores set
    `render.strict_backends`. So `group.py`'s guard
    `(wants_sfizz and not optional) or strict_backends` is FALSE for every
    instrument in the shipped catalogue: each one warns once to stderr, falls
    back to General MIDI, and the command exits 0.

    ⭐ AND MAKING IT FATAL COSTS A CORRECTLY-INSTALLED MACHINE NOTHING, which is
    why this is a gate rather than a warning: on a box with the libraries
    installed all 247 resolve, this one included.
    """
    references: list[str] = []
    seen: set[str] = set()
    base = str(base_dir) if base_dir is not None else ""
    for backend in _walk_instrument_backends(spec):
        library = backend.get("library_ref") or backend.get("library")
        explicit = (
            backend.get("sfz")
            or backend.get("path")
            or backend.get("sfz_path")
            or backend.get("sfz_glob")
        )
        if library:
            reference, is_library = str(library), True
        elif explicit:
            reference, is_library = str(explicit), False
        else:
            continue
        if reference in seen:
            continue
        seen.add(reference)
        prefer = tuple(
            str(item)
            for item in (backend.get("prefer") or backend.get("prefer_keywords") or [])
        )
        if not _sfz_reference_resolves(reference, is_library, base, prefer):
            references.append(reference)
    return references


def _preflight_bulk_render(
    cues: tuple[str, ...], *, backend: str, force_render: bool
) -> bool:
    """Resolve every render that this bulk invocation will actually need.

    Hash/layout resolution is cheap and is also where score-level render inputs
    such as an explicit soundfont are resolved. Do it for the whole batch before
    starting cue 1 so a bad path on cue 40 cannot waste minutes of successful
    renders before aborting the command. Cues whose current render will be reused
    are deliberately skipped: publish-only reuse does not need local synthesis
    dependencies.
    """
    from .render.score_core import load_yaml
    # Keep bulk preflight on the historical public score-build facade during
    # the CompiledScore migration.  build_score() delegates to compile_score()
    # in normal operation, but retaining this boundary keeps downstream hooks,
    # tests, and callers that intercept score construction observable until the
    # compatibility facade is intentionally retired.
    from .render.score_layers import build_score

    failures: list[str] = []
    missing_libraries: dict[str, list[str]] = {}
    for cue in cues:
        yaml_path = find_score(cue)
        if yaml_path is None:
            failures.append(f"{cue}: missing YAML")
            continue
        outdir = generated_root() / cue
        coarse_refresh = needs_render(cue, yaml_path, outdir)
        dependency_refresh = False
        if not force_render and not coarse_refresh:
            dependency_refresh, _reason = render_dependencies_need_refresh(
                yaml_path, outdir, backend
            )
        if not force_render and not coarse_refresh and not dependency_refresh:
            continue
        try:
            spec = load_yaml(yaml_path)
            generated_run_layout(outdir, yaml_path, backend, spec=spec)
            build_score(spec)
        except Exception as ex:
            failures.append(f"{cue}: {ex}")
            continue
        for reference in _unresolvable_sfz_references(spec, base_dir=yaml_path.parent):
            missing_libraries.setdefault(reference, []).append(cue)

    if missing_libraries:
        print(
            "music render preflight failed: this machine is missing sampled "
            "instrument libraries that the selected cues NAME.",
            file=sys.stderr,
        )
        for reference, affected in sorted(missing_libraries.items()):
            shown = ", ".join(affected[:4])
            more = f" (+{len(affected) - 4} more)" if len(affected) > 4 else ""
            print(f"  - {reference} — wanted by {shown}{more}", file=sys.stderr)
        print(
            "\nEvery one of these would have rendered through General MIDI and "
            "reported SUCCESS.\nInstall the libraries:\n"
            "  ./run_developer_setup.sh                     (from the game repo)\n"
            "  ./download_ambition_audio_tools.sh           (this tool, MODE=pro)\n"
            "Set AMBITION_MUSIC_ALLOW_GM_FALLBACK=1 to render stand-ins anyway.",
            file=sys.stderr,
        )
        return False

    if not failures:
        return True

    print("music render preflight failed before rendering any cue:", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return False


def _bulk_job_plan(n_cues: int, requested: int) -> tuple[int, int]:
    """Split the CPU budget between cue fan-out and per-cue stem groups.

    ⛔⛔ CUES WERE RENDERED STRICTLY ONE AT A TIME AND THE MACHINE SAT IDLE.
    Every cue is already an independent subprocess writing its own versioned
    output directory, so nothing forced the serial loop that drove them — and a
    75-cue radio pass is the FRESH-CLONE path, where no cue is cached and all 75
    render. Measured 2026-09-02 on 14 cores: mean 15% busy, median 0%, under two
    cores busy for 78% of the run, with a repeating one-second burst and a
    two-second trough.

    ⭐ THE PER-CUE `--jobs` COULD NOT FIX THIS. It parallelises stem GROUPS,
    which is the burst; the trough is the serial remainder of a cue — mix,
    master, encode, and the interpreter start of each worker. Only overlapping
    whole cues fills those troughs.

    The budget is SPLIT, not nested: N cues each fanning out to N groups
    oversubscribes the box by N². Cue fan-out is the outer, wider dimension
    because cues are many and independent; groups get what is left over, which
    matters only when few cues were selected.
    """
    budget = requested if requested > 0 else (os.cpu_count() or 1)
    cue_jobs = max(1, min(n_cues, budget))
    group_jobs = max(1, budget // cue_jobs)
    return cue_jobs, group_jobs


def _run_bulk(args, cues: tuple[str, ...], action: str) -> int:
    failed: list[str] = []
    desc = f"music {action}"
    cue_jobs, group_jobs = _bulk_job_plan(len(cues), int(getattr(args, "jobs", 0) or 0))

    def run_one(cue: str) -> str | None:
        return _process_simple_mix_cue(
            cue,
            action=action,
            backend=args.backend,
            force_render=args.force_render,
            dest_root=args.dest_root,
            render_jobs=group_jobs,
        )

    if cue_jobs <= 1:
        # Serial stays reachable with `--jobs 1`: interleaved child output is
        # unreadable when profiling or chasing one cue's failure.
        for cue in _progress(cues, total=len(cues), desc=desc):
            stage = run_one(cue)
            if stage is not None:
                failed.append(f"{stage} {cue}")
    else:
        from concurrent.futures import as_completed

        import ubelt as ub

        print(f"{desc}: {len(cues)} cue(s), {cue_jobs} at a time, {group_jobs} stem worker(s) each")
        # Threads supervising independent child PROCESSES — the same shape
        # `render.batch_bundle` already uses, and the reason the GIL is not in
        # the way: no cue's CPU work happens in this interpreter.
        with ub.Executor(mode="thread", max_workers=cue_jobs) as pool:
            futures = {pool.submit(run_one, cue): cue for cue in cues}
            for future in _progress(as_completed(futures), total=len(futures), desc=desc):
                cue = futures[future]
                stage = future.result()
                if stage is not None:
                    failed.append(f"{stage} {cue}")

    if failed:
        # Completion order is nondeterministic under fan-out; the report is not.
        failed.sort()
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
    # ⛔ `tuple()` OF A STRING IS ITS CHARACTERS. `cue` is annotated
    # `list[str] | None`, but the CLI hands back a bare `str` for
    # `--cue=some_id` (kwconf warns about the annotation mismatch and keeps the
    # string), so this produced one "cue" per LETTER and the run died in
    # preflight with `- b: missing YAML`, `- r: missing YAML`, ... — a failure
    # that names every character of the argument and never the argument.
    #
    # The help has always promised "may be comma/list parsed"; nothing parsed
    # it. Honour that here, for both the string and already-list forms.
    if config.cue:
        selected = config.cue.split(",") if isinstance(config.cue, str) else list(config.cue)
        cues = tuple(part.strip() for part in selected if part.strip())
    else:
        cues = tuple(cues_factory())
    if action == "render-publish" and config.skip_render:
        action = "publish"
    # ⛔⛔ REFUSE RATHER THAN RENDER THE FALLBACK. Without the sampled libraries
    # every cue that names one still "succeeds" — through General MIDI, which is
    # not the music. Nothing downstream can tell the difference: the .ogg is
    # there, the registry lists it, the game plays it. A machine that renders
    # the whole catalogue in the wrong instruments and reports success is worse
    # than one that stops and says what is missing.
    #
    # ⭐ THE LIBRARIES ARE NOT OPTIONAL ANY MORE. `run_developer_setup.sh`
    # installs them by default; `download_ambition_audio_tools.sh` fetches every
    # one of them from a public URL. This is the check that a machine which
    # skipped that step cannot silently ship the wrong audio.
    if action in ("render", "render-publish") and not _sampled_libraries_installed():
        print(
            "no sampled instrument libraries found; refusing to render every cue "
            "through the General-MIDI fallback.",
            file=sys.stderr,
        )
        print(
            "  install them with: ./run_developer_setup.sh\n"
            "  or directly:       tools/ambition_music_renderer/download_ambition_audio_tools.sh /data/audio-tools\n"
            "  to render the fallback anyway (previews, no sound design): "
            "AMBITION_MUSIC_ALLOW_GM_FALLBACK=1",
            file=sys.stderr,
        )
        if not os.environ.get("AMBITION_MUSIC_ALLOW_GM_FALLBACK"):
            return 1
        print("  AMBITION_MUSIC_ALLOW_GM_FALLBACK set; continuing with fallback audio", file=sys.stderr)
    if action in ("render", "render-publish") and not _preflight_bulk_render(
        cues, backend=config.backend, force_render=config.force_render
    ):
        return 1
    return _run_bulk(config, cues, action)


def _single_bundle_render_jobs(args) -> int:
    """Resolve group-render workers for a one-cue bundle invocation.

    ``--jobs`` is the natural spelling for a one-cue command, while multi-cue
    runs reserve it for cue-level fan-out and use ``--render_jobs`` per cue.
    An explicit ``--render_jobs`` remains a supported override in either mode.
    """
    if args.render_jobs is not None:
        return max(1, int(args.render_jobs))
    return max(1, int(args.jobs))


def _single_bundle_config(args, cue: str):
    """Build a per-cue ``CueBundleConfig`` from the orchestrator ``args``."""
    from .render.bundle import CueBundleConfig

    data = {field: getattr(args, field) for field in PASSTHROUGH_FIELDS}
    data["cue"] = cue
    data["jobs"] = _single_bundle_render_jobs(args)
    return CueBundleConfig.cli(argv=False, data=data)


@profile
def cmd_bundle(args) -> int:
    cues = list(args.cues)
    # Only a true multi-cue invocation uses the batch runner. For one cue,
    # --jobs controls the renderer's independent stem-group workers directly.
    if len(cues) > 1:
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


def cmd_plugins_smoke_sfz(args) -> int:
    from .audit.sfz_smoke import run_sfz_smoke, write_sfz_smoke_report

    roots = [Path(args.root)] if args.root else None
    report = run_sfz_smoke(
        roots=roots,
        sample_rate=int(args.sample_rate),
        render_timeout_s=float(args.timeout),
    )
    if args.output:
        path = write_sfz_smoke_report(report, Path(args.output))
        report["output"] = str(path)
    if args.json or args.output:
        print(json.dumps(report, indent=2))
    else:
        print(f"SFZ smoke probes: {report['ok_count']}/{report['candidate_count']} passed")
        for row in report["rows"]:
            print(f"  {row['name']:<22} {row['status']:<18} {row.get('resolved') or 'UNRESOLVED'}")
    return 0 if report["ok_count"] == report["candidate_count"] else 1


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


def cmd_instruments_list(args) -> int:
    """List the checked-in authoring vocabulary without consulting local samples."""

    from .instrument_catalog import instrument_catalog_report

    report = instrument_catalog_report(
        family=str(args.family) if args.family else None,
        expected_only=bool(args.expected_only),
    )
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for row in report["instruments"]:
        source = row.get("source") or "-"
        role = row.get("role") or "-"
        profile = row.get("install_profile") or "-"
        print(f"{row['ref']:<34} {row['family']:<12} {role:<24} {profile:<8} {source}")
    print(f"catalog instruments: {report['instrument_count']}")
    return 0


def cmd_instruments_describe(args) -> int:
    """Describe one stable MusicIR instrument identity and how to author it."""

    from .instrument_catalog import describe_instrument

    try:
        report = describe_instrument(str(args.ref))
    except KeyError:
        print(f"error: unknown instrument catalog ref: {args.ref}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        import yaml

        print(yaml.safe_dump(report, sort_keys=False, allow_unicode=True, width=110), end="")
    return 0


def cmd_instruments_doctor(args) -> int:
    """Compare expected repo-side instruments with the current machine inventory."""

    from .instrument_catalog import instrument_catalog, instrument_catalog_policy, instrument_source_catalog
    from .instrument_libraries import collect_sfz_library_diagnostics

    catalog = instrument_catalog()
    diagnostics = collect_sfz_library_diagnostics(limit=int(args.limit))
    rows = []
    for ref, entry in sorted(catalog.items()):
        if not entry.expected:
            continue
        resolved = diagnostics["alias_hits"].get(ref)
        rows.append({
            "ref": ref,
            "family": entry.family,
            "source": entry.source,
            "install_profile": entry.install_profile,
            "resolved": resolved,
            "ok": bool(resolved),
        })
    missing = [row for row in rows if not row["ok"]]
    source_hits = diagnostics.get("source_hits") or {}
    expected_sources_missing = list(diagnostics.get("expected_sources_missing") or [])
    expected_source_count = sum(
        1 for info in instrument_source_catalog().values() if bool(info.get("expected", False))
    )
    report = {
        "schema": "ambition.instrument_environment_report.v1",
        "policy": instrument_catalog_policy(),
        "sfz_roots": diagnostics["sfz_roots"],
        "sfz_count": diagnostics["sfz_count"],
        "expected_source_count": expected_source_count,
        "resolved_expected_source_count": expected_source_count - len(expected_sources_missing),
        "missing_expected_source_count": len(expected_sources_missing),
        "missing_expected_sources": expected_sources_missing,
        "source_hits": source_hits,
        "expected_count": len(rows),
        "resolved_expected_count": len(rows) - len(missing),
        "missing_expected_count": len(missing),
        "missing_expected": [row["ref"] for row in missing],
        "instruments": rows,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Expected Ambition instrument environment:")
        print(f"  sample sources: {report['resolved_expected_source_count']}/{report['expected_source_count']} present")
        print(f"  catalog refs:   {report['resolved_expected_count']}/{report['expected_count']} resolved")
        print("  roots:")
        for root in report["sfz_roots"]:
            print(f"    {root}")
        if expected_sources_missing:
            print("Missing expected sample sources:")
            for source in expected_sources_missing:
                print(f"  {source}")
        if missing:
            print("Missing expected instrument refs:")
            for row in missing:
                print(f"  {row['ref']:<34} source={row.get('source') or '-'}")
        if expected_sources_missing or missing:
            print("Run or repair download_ambition_audio_tools.sh; these are catalog expectations, not optional discoveries.")
    failed = bool(expected_sources_missing or missing)
    return 0 if not failed or args.warn_only else 1


class NewCommand(kwconf.Config):
    """Create a new MusicIR v3 score from the checked-in starter template."""

    name: str = kwconf.Value(None, position=1, help="stable cue id or human-readable cue name")
    output: Path | None = kwconf.Value(None, parser=Path, help="output .music.yaml path")
    force: bool = kwconf.Flag(False, help="overwrite an existing output path")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        from .musicir.template import write_v3_starter
        try:
            path = write_v3_starter(config.name, config.output, force=bool(config.force))
        except (ValueError, FileExistsError) as ex:
            print(str(ex), file=sys.stderr)
            return 1
        print(path)
        return 0


class RenderCommand(kwconf.Config):
    """Render a single cue YAML; optionally publish it to the game assets."""


    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path")
    backend: str = kwconf.Value(
        "pretty-midi",
        choices=list(BACKEND_CHOICES),
        help="renderer backend",
    )
    simple_mix: bool = kwconf.Flag(True, help="emit only the mastered preview")
    full_mix_only: bool = kwconf.Flag(False, help="emit mastered preview plus per-section full mixes")
    publish: bool = kwconf.Flag(False, help="after rendering, install full.ogg into the game asset tree")
    dest_root: Path = kwconf.Value(
        default_factory=declared_publish_dest_root,
        parser=Path,
        help="publish destination root (with --publish)",
    )

    def __post_init__(self) -> None:
        # ⚠ `None` is legal and means UNDECLARED — see
        # `_paths.declared_publish_root`. Coercing it to a `Path` here is what
        # turned "nobody said where to publish" into a `TypeError` from
        # `pathlib` during argument parsing. The publish path resolves it (and
        # raises with the real message) when it is actually needed.
        if self.dest_root is not None and not isinstance(self.dest_root, Path):
            self.dest_root = Path(self.dest_root)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return cmd_render(config)


class MidiCommand(kwconf.Config):
    """Export a MIDI preview with authored MusicIR form markers."""

    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path")
    output: Path | None = kwconf.Value(
        None,
        parser=Path,
        help="output .mid path; defaults to <cue>.mid in the current directory",
    )

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        score = find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2

        from .render.score_core import load_yaml
        from .musicir.compile import compile_score
        from .musicir.interchange import write_compiled_midi

        spec = load_yaml(score)
        compiled = compile_score(spec)
        cue_id = str(spec.get("id", cue_id_from_path(score)))
        output = Path(config.output) if config.output is not None else Path.cwd() / f"{cue_id}.mid"
        write_compiled_midi(compiled, output)
        print(output)
        return 0


class DawExportCommand(kwconf.Config):
    """Export DAW-neutral MIDI plus a MusicIR provenance sidecar."""

    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path")
    destination: Path = kwconf.Value(
        Path("."), parser=Path, help="directory for <cue>.mid and interchange JSON"
    )

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        score = find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2

        from .render.score_core import load_yaml
        from .musicir.compile import compile_score
        from .musicir.interchange import export_interchange_bundle

        spec = load_yaml(score)
        compiled = compile_score(spec)
        cue_id = str(spec.get("id", cue_id_from_path(score)))
        paths = export_interchange_bundle(compiled, config.destination, stem=cue_id)
        print(paths["midi"])
        print(paths["manifest"])
        return 0


class DawReconcileCommand(kwconf.Config):
    """Compare edited DAW MIDI against a saved MusicIR interchange baseline."""

    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path used for the original export")
    midi: Path = kwconf.Value(None, parser=Path, help="MIDI exported from the DAW after editing")
    manifest: Path = kwconf.Value(None, parser=Path, help=".musicir-interchange.json from cue daw_export")
    output: Path | None = kwconf.Value(None, parser=Path, help="optional reconciliation JSON path")
    json: bool = kwconf.Flag(False, help="print the complete reconciliation report")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        score = find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2
        from .render.score_core import load_yaml
        from .musicir.compile import compile_score
        from .musicir.interchange import read_midi_snapshot
        from .musicir.interchange_reconcile import (
            DawRoundtripError,
            load_interchange_manifest,
            reconcile_edited_midi,
        )

        try:
            spec = load_yaml(score)
            compiled = compile_score(spec)
            manifest = load_interchange_manifest(config.manifest)
            snapshot = read_midi_snapshot(config.midi)
            report = reconcile_edited_midi(compiled, manifest, snapshot)
        except (OSError, ValueError, DawRoundtripError) as ex:
            print(str(ex), file=sys.stderr)
            return 1
        if config.output is not None:
            config.output.parent.mkdir(parents=True, exist_ok=True)
            config.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf8")
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            print(
                f"DAW reconciliation: {summary['note_changes']} note change(s), "
                f"{summary['controller_changes']} controller/bend change(s), "
                f"conductor={summary['tempo_event_changes']} tempo/"
                f"{summary['meter_event_changes']} meter/"
                f"{summary['form_marker_changes']} marker change(s), "
                f"apply={'yes' if report['apply']['supported'] else 'no'}"
            )
            if report["apply"]["blocked_by"]:
                print("blocked by: " + ", ".join(report["apply"]["blocked_by"]))
            if config.output is not None:
                print(config.output)
        return 0


class DawApplyCommand(kwconf.Config):
    """Apply supported DAW note/automation/conductor edits back to MusicIR v3."""

    cue: str = kwconf.Value(None, position=1, help="cue id or YAML path used for the original export")
    midi: Path = kwconf.Value(None, parser=Path, help="MIDI exported from the DAW after editing")
    manifest: Path = kwconf.Value(None, parser=Path, help=".musicir-interchange.json from cue daw_export")
    output: Path | None = kwconf.Value(None, parser=Path, help="destination MusicIR YAML; defaults beside source")
    report: Path | None = kwconf.Value(None, parser=Path, help="optional reconciliation/apply report JSON")
    in_place: bool = kwconf.Flag(False, help="replace the source YAML after recompilation verification")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        score = find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2
        score = Path(score)
        if config.in_place and config.output is not None:
            print("--in-place and --output are mutually exclusive", file=sys.stderr)
            return 2

        from .render.score_core import load_yaml
        from .musicir.compile import compile_score
        from .musicir.interchange import read_midi_snapshot
        from .musicir.interchange_reconcile import (
            DawRoundtripError,
            load_interchange_manifest,
            lower_reconciled_clips,
            reconcile_edited_midi,
            verify_compiled_matches_edited_midi,
            write_musicir_yaml,
        )

        try:
            source_spec = load_yaml(score)
            baseline_compiled = compile_score(source_spec)
            manifest = load_interchange_manifest(config.manifest)
            snapshot = read_midi_snapshot(config.midi)
            reconciliation = reconcile_edited_midi(baseline_compiled, manifest, snapshot)
            if not reconciliation["apply"]["supported"]:
                blocked = ", ".join(reconciliation["apply"]["blocked_by"])
                raise DawRoundtripError(f"DAW changes cannot be applied safely: {blocked}")
            updated_spec, apply_report = lower_reconciled_clips(source_spec, manifest, reconciliation)
            compiled_after = compile_score(updated_spec)
            verification = verify_compiled_matches_edited_midi(compiled_after, manifest, snapshot)
            if not verification["ok"]:
                raise DawRoundtripError(
                    "refusing to write MusicIR because recompilation did not reproduce the edited MIDI; "
                    + json.dumps(verification["mismatches"][:3], sort_keys=True)
                )
        except (OSError, ValueError, DawRoundtripError) as ex:
            print(str(ex), file=sys.stderr)
            return 1

        if config.in_place:
            output = score
        elif config.output is not None:
            output = config.output
        else:
            suffix = ".music.yaml"
            name = score.name
            base = name[:-len(suffix)] if name.endswith(suffix) else score.stem
            output = score.with_name(f"{base}.daw.music.yaml")
        write_musicir_yaml(updated_spec, output)
        combined_report = {
            "reconciliation": reconciliation,
            "apply": apply_report,
            "verification": verification,
            "source": str(score),
            "output": str(output),
        }
        if config.report is not None:
            config.report.parent.mkdir(parents=True, exist_ok=True)
            config.report.write_text(json.dumps(combined_report, indent=2, sort_keys=True), encoding="utf8")
        print(output)
        for row in apply_report["clips_lowered"]:
            print(
                f"lowered {row['part_id']}/{row['voice_id']}/{row['clip_id']}: "
                f"{row['from']} -> events ({row['notes']} notes)"
            )
        conductor_apply = apply_report.get("conductor") or {}
        if conductor_apply.get("changed"):
            changed = [
                name
                for name in ("tempo", "meter", "form_markers")
                if conductor_apply.get(name)
            ]
            print("reconciled conductor: " + ", ".join(changed))
        if config.report is not None:
            print(config.report)
        return 0


class ValidateCommand(kwconf.Config):
    """Compile and validate one cue without synthesizing audio."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    strict_schema: bool = kwconf.Flag(
        False,
        help="reject missing, deprecated, or unknown MusicIR schema spellings",
    )
    allow_external_score: bool = kwconf.Flag(
        False,
        help="allow MusicIR v2 to depend on external symbolic score files",
    )
    json: bool = kwconf.Flag(False, help="emit the complete validation report as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        candidate = Path(config.cue).expanduser()
        score = candidate.resolve() if candidate.is_file() else find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2
        from .validation.musicir import validate_musicir_file
        from .validation.diagnostics import MusicIRValidationError

        try:
            report = validate_musicir_file(
                score,
                strict_schema=bool(config.strict_schema),
                require_self_contained=not bool(config.allow_external_score),
            )
        except MusicIRValidationError as ex:
            if config.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "score": str(score),
                            "diagnostics": [item.as_dict() for item in ex.diagnostics],
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(ex.format(), file=sys.stderr)
            return 1
        if config.json:
            payload = dict(report)
            payload["ok"] = True
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                f"OK {report['score_id']}: {report['canonical_schema']} "
                f"instruments={report['instruments']} notes={report['note_events']} "
                f"sections={report['sections']} duration={report['duration_seconds']:.3f}s"
            )
            for warning in report.get("normalization_warnings", []):
                print(f"WARNING: {warning}", file=sys.stderr)
        return 0


def _load_compiled_for_inspection(cue: str):
    candidate = Path(cue).expanduser()
    score = candidate.resolve() if candidate.is_file() else find_score(cue)
    if score is None:
        raise FileNotFoundError(f"cue not found: {cue}")
    from .render.score_core import load_yaml
    from .musicir.compile import compile_score

    return score, compile_score(load_yaml(score))


class ExpandCommand(kwconf.Config):
    """Explain authored v3 clips and the exact events they compile into."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    clip: str | None = kwconf.Value(None, help="restrict expansion to one stable clip id")
    part: str | None = kwconf.Value(None, help="optional part-id disambiguation")
    voice: str | None = kwconf.Value(None, help="optional voice-id disambiguation")
    limit: int = kwconf.Value(80, help="maximum note/control rows shown in human output")
    json: bool = kwconf.Flag(False, help="emit the complete expansion report as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        try:
            score, compiled = _load_compiled_for_inspection(str(config.cue))
        except FileNotFoundError as ex:
            print(str(ex), file=sys.stderr)
            return 2
        from .musicir.inspect import expand_compiled_score

        try:
            report = expand_compiled_score(
                compiled,
                clip_id=str(config.clip) if config.clip else None,
                part_id=str(config.part) if config.part else None,
                voice_id=str(config.voice) if config.voice else None,
                base_dir=score.parent,
            )
        except (KeyError, ValueError) as ex:
            print(str(ex), file=sys.stderr)
            return 1
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 0
        print(f"{report['score_id']}  schema={report['canonical_schema']}")
        print(
            f"selection: clips={report['counts']['clips']} notes={report['counts']['notes']} "
            f"controls={report['counts']['controls']}"
        )
        for clip in report.get("source_clips", []):
            detail = clip.get("generator_kind") or clip.get("material_id") or clip.get("source_kind")
            print(f"\nclip {clip['clip_id']}  {clip['part_id']}/{clip['voice_id']}  source={detail}")
            print(f"  path:       {clip['path']}")
            print(f"  instrument: {clip['instrument']}")
            transforms = {k: v for k, v in clip.get("transforms", {}).items() if v not in (0, 0.0, 1, 1.0)}
            if transforms:
                print(f"  transforms: {transforms}")
        rows = [*(report.get("expanded_notes") or []), *(report.get("expanded_controls") or [])]
        for row in rows[: max(0, int(config.limit))]:
            event_id = row.get("event_id", "-")
            if row.get("event_type", "note") == "note":
                print(
                    f"  {event_id}  tick={row.get('start_tick')} {row.get('note', row.get('pitch'))} "
                    f"vel={row.get('velocity')} harmony={row.get('harmony', '-')} inst={row.get('instrument')}"
                )
            else:
                value = row.get("value", row.get("pitch_bend"))
                print(
                    f"  {event_id}  tick={row.get('tick')} {row.get('event_type')} "
                    f"value={value} harmony={row.get('harmony', '-')} inst={row.get('instrument')}"
                )
        if len(rows) > int(config.limit):
            print(f"  ... {len(rows) - int(config.limit)} more events; use --json or raise --limit")
        for name, plan in report.get("instrument_resolution", {}).items():
            selected = plan.get("resolved_sfz") or plan.get("fallback_backend") or plan.get("kind") or "default backend"
            print(f"instrument {name}: {selected}")
        return 0


class GraphCommand(kwconf.Config):
    """Show the MusicIR v3 authoring graph without flattening composition intent."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    json: bool = kwconf.Flag(False, help="emit nodes/edges as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        try:
            _score, compiled = _load_compiled_for_inspection(str(config.cue))
        except FileNotFoundError as ex:
            print(str(ex), file=sys.stderr)
            return 2
        from .musicir.inspect import authoring_graph_report

        report = authoring_graph_report(compiled)
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 0
        if report.get("authoring_graph") is None and report.get("message"):
            print(f"{report['score_id']}: {report['message']}")
            return 0
        print(f"score {report['score_id']}")
        for node in report.get("nodes", []):
            if node.get("kind") == "clip":
                print(
                    f"  clip {node['label']}: source={node.get('source_kind')} "
                    f"instrument={node.get('instrument')} path={node.get('path')}"
                )
        for edge in report.get("edges", []):
            if edge.get("kind") in {"uses", "generates"}:
                print(f"    {edge['from']} --{edge['kind']}--> {edge['to']}")
        return 0


class TraceEventCommand(kwconf.Config):
    """Trace one stable compiled event id through source and instrument realization."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    event_id: str = kwconf.Value(None, position=2, help="stable event id from cue expand/DAW sidecar")
    json: bool = kwconf.Flag(False, help="emit the complete trace as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        try:
            score, compiled = _load_compiled_for_inspection(str(config.cue))
        except FileNotFoundError as ex:
            print(str(ex), file=sys.stderr)
            return 2
        from .musicir.inspect import trace_compiled_event

        try:
            report = trace_compiled_event(compiled, str(config.event_id), base_dir=score.parent)
        except (KeyError, ValueError) as ex:
            print(str(ex), file=sys.stderr)
            return 1
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 0
        event = report["compiled_event"]
        print(f"event {report['event_id']} ({report['event_kind']})")
        print(f"  source: {report.get('source_ref')}")
        if event.get("event_type", "note") == "note":
            print(
                f"  compiled: tick={event.get('start_tick')} note={event.get('note', event.get('pitch'))} "
                f"velocity={event.get('velocity')} instrument={event.get('instrument')}"
            )
        else:
            print(f"  compiled: {event}")
        clip = report.get("source_clip")
        if clip:
            print(f"  clip: {clip['path']} source={clip.get('generator_kind') or clip.get('material_id') or clip.get('source_kind')}")
        plan = report.get("instrument_resolution") or {}
        if plan:
            print(f"  realization: {plan.get('resolved_sfz') or plan.get('fallback_backend') or plan.get('kind')}")
        return 0


class QualityCommand(kwconf.Config):
    """Report composition-review evidence from the canonical CompiledScore."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    json: bool = kwconf.Flag(False, help="emit the full report as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        try:
            _score, compiled = _load_compiled_for_inspection(str(config.cue))
        except FileNotFoundError as ex:
            print(str(ex), file=sys.stderr)
            return 2
        from .audit.composition_quality import composition_quality_report
        report = composition_quality_report(compiled)
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 0
        print(f"notes={report['note_count']} duration={report['duration_s']:.3f}s density={report['notes_per_second']:.2f}/s")
        for row in report["groups"]:
            pitch = row.get("pitch_range") or [None, None]
            print(
                f"  {row['group']:<16} notes={row['note_count']:<5} "
                f"pitch={pitch[0]}..{pitch[1]} mean_vel={row.get('mean_velocity')}"
            )
            for issue in row.get("recommended_range_observations", []):
                print(
                    f"    range: {issue['instrument']} observed={issue['observed_midi_range']} "
                    f"recommended={issue['recommended_midi_range']}"
                )
        if report["register_overlap"]:
            print(f"register-overlap observations: {len(report['register_overlap'])}")
        if report["identical_bar_runs"]:
            print(f"identical-bar runs (>=3 bars): {len(report['identical_bar_runs'])}")
        return 0


class DeterminismCommand(kwconf.Config):
    """Compile a cue repeatedly and verify identical canonical/provenance events."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    rounds: int = kwconf.Value(3, help="number of independent compilation rounds")
    json: bool = kwconf.Flag(False, help="emit the complete report as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        candidate = Path(config.cue).expanduser()
        score = candidate.resolve() if candidate.is_file() else find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2
        from .render.score_core import load_yaml
        from .audit.determinism import compilation_determinism_report
        report = compilation_determinism_report(load_yaml(score), rounds=int(config.rounds))
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
        else:
            status = "OK" if report["deterministic"] else "FAIL"
            print(f"{status}: {config.cue} compiled identically across {report['rounds']} rounds")
            print(f"compiled fingerprint: {report['compiled_fingerprints'][0]}")
        return 0 if report["deterministic"] else 1


class FingerprintCommand(kwconf.Config):
    """Explain the exact static dependencies that determine a cue render."""

    cue: str = kwconf.Value(None, position=1, help="cue id or .music.yaml path")
    backend: str = kwconf.Value("pretty-midi", choices=list(BACKEND_CHOICES))
    json: bool = kwconf.Flag(False, help="emit the complete dependency payload")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        candidate = Path(config.cue).expanduser()
        score = candidate.resolve() if candidate.is_file() else find_score(config.cue)
        if score is None:
            print(f"cue not found: {config.cue}", file=sys.stderr)
            return 2
        from .render.dependencies import render_dependency_fingerprint_for_score
        from .render.score_core import load_yaml

        spec = load_yaml(score)
        result = render_dependency_fingerprint_for_score(
            score, str(config.backend), spec=spec
        )
        report = result.manifest_payload()
        report["score"] = str(score)
        report["id"] = spec.get("id")
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        print(f"{spec.get('id', score.stem)}  {result.short_hash}")
        print(f"  full fingerprint: {result.fingerprint}")
        deps = result.payload
        print(f"  compiled score:   {deps.get('compiled_score_fingerprint')}")
        impl = (deps.get("renderer_implementation") or {}).get("fingerprint")
        print(f"  renderer source:  {impl}")
        instruments = ((deps.get("instrument_resolution") or {}).get("instruments") or {})
        for name, row in instruments.items():
            sfz = row.get("resolved_sfz")
            program = ((sfz or {}).get("program") or {}).get("path") if isinstance(sfz, dict) else None
            selected = program or row.get("fallback_backend") or row.get("kind") or config.backend
            print(f"  {name}: {selected}")
        return 0


class PublishCommand(kwconf.Config):
    """Publish newest preview to sandbox assets."""

    cue: str = kwconf.Value(None, position=1)
    dest_root: Path = kwconf.Value(default_factory=declared_publish_dest_root, parser=Path, help="install destination root")

    def __post_init__(self) -> None:
        # ⚠ `None` is legal and means UNDECLARED — see
        # `_paths.declared_publish_root`. Coercing it to a `Path` here is what
        # turned "nobody said where to publish" into a `TypeError` from
        # `pathlib` during argument parsing. The publish path resolves it (and
        # raises with the real message) when it is actually needed.
        if self.dest_root is not None and not isinstance(self.dest_root, Path):
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
    ids to fan out across cues, one render subprocess each, with per-cue logs.
    For one cue, ``-j/--jobs N`` controls parallel stem-group rendering. For
    several cues it controls cue-level fan-out and ``--render_jobs N`` controls
    the workers inside each cue subprocess.
    """

    cues: list[str] = kwconf.Value(
        default_factory=list,
        position=1,
        nargs="+",
        help="one or more cue ids or .music.yaml paths",
    )
    jobs: int = kwconf.Value(
        1,
        short_alias=["j"],
        help=(
            "worker count: parallel stem groups for one cue; parallel cue "
            "subprocesses when several cues are supplied"
        ),
    )
    render_jobs: int | None = kwconf.Value(
        None,
        help="per-cue stem-group workers for multi-cue runs; defaults to 1",
    )
    log_root: Path | None = kwconf.Value(None, parser=Path, help="batch per-cue log root (multi-cue runs)")

    def __post_init__(self) -> None:
        super().__post_init__()
        self.jobs = max(1, int(self.jobs))
        if self.render_jobs is not None:
            self.render_jobs = max(1, int(self.render_jobs))
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
    new = NewCommand
    render = RenderCommand
    midi = MidiCommand
    daw_export = DawExportCommand
    daw_reconcile = DawReconcileCommand
    daw_apply = DawApplyCommand
    validate = ValidateCommand
    expand = ExpandCommand
    graph = GraphCommand
    trace_event = TraceEventCommand
    quality = QualityCommand
    determinism = DeterminismCommand
    fingerprint = FingerprintCommand
    publish = PublishCommand
    bundle = BundleCommand


class BulkActionConfig(kwconf.Config):
    """Shared options for sandbox/radio bulk cue actions."""

    cue: list[str] | None = kwconf.Value(None, help="restrict to named cue(s); may be comma/list parsed")
    backend: str = kwconf.Value("pretty-midi")
    force_render: bool = kwconf.Flag(False)
    skip_render: bool = kwconf.Flag(False, help="treat render_publish as publish")
    dest_root: Path = kwconf.Value(default_factory=declared_publish_dest_root, parser=Path)
    jobs: int = kwconf.Value(
        0,
        short_alias=["j"],
        help=(
            "cue-level fan-out; 0 (the default) uses the machine's CPU count, "
            "1 renders cues strictly one at a time"
        ),
    )

    def __post_init__(self) -> None:
        # ⚠ `None` is legal and means UNDECLARED — see
        # `_paths.declared_publish_root`. Coercing it to a `Path` here is what
        # turned "nobody said where to publish" into a `TypeError` from
        # `pathlib` during argument parsing. The publish path resolves it (and
        # raises with the real message) when it is actually needed.
        if self.dest_root is not None and not isinstance(self.dest_root, Path):
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


class InstrumentList(kwconf.Config):
    """List stable sampled-instrument identities agents can author against."""

    family: str | None = kwconf.Value(None, help="restrict to one catalog family")
    expected_only: bool = kwconf.Flag(False, help="show only instruments expected in the normal environment")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_instruments_list(cls.cli(argv=argv, data=kwargs))


class InstrumentDescribe(kwconf.Config):
    """Describe one catalog ref, including MusicIR usage and sample-library nuances."""

    ref: str = kwconf.Value(None, position=1, help="catalog library_ref, e.g. guitar.emily")
    json: bool = kwconf.Flag(False, help="emit JSON instead of YAML")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_instruments_describe(cls.cli(argv=argv, data=kwargs))


class InstrumentDoctor(kwconf.Config):
    """Check that the current machine satisfies the checked-in instrument catalog."""

    limit: int = kwconf.Value(50, help="maximum discovered SFZ paths retained in diagnostics")
    warn_only: bool = kwconf.Flag(False, help="return success even when expected catalog instruments are missing")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_instruments_doctor(cls.cli(argv=argv, data=kwargs))


class InstrumentAuditionScore(kwconf.Config):
    """Write a canonical v3 comparison phrase for one catalog instrument."""

    ref: str = kwconf.Value(None, position=1, help="catalog library_ref")
    output: Path | None = kwconf.Value(None, parser=Path, help="output .music.yaml path")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        from .instrument_authoring import canonical_audition_score
        import yaml
        try:
            spec = canonical_audition_score(str(config.ref))
        except (KeyError, ValueError) as ex:
            print(str(ex), file=sys.stderr)
            return 1
        output = Path(config.output) if config.output is not None else Path(f"audition_{str(config.ref).replace('.', '_')}.music.yaml")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf8")
        print(output)
        return 0


class InstrumentsModal(kwconf.ModalCLI):
    """Discover the checked-in instrument vocabulary and verify local installation."""

    list = InstrumentList
    describe = InstrumentDescribe
    doctor = InstrumentDoctor
    audition = InstrumentAuditionScore


def cmd_techniques_list(args) -> int:
    from .technique_catalog import technique_specs
    rows = technique_specs()
    if getattr(args, "json", False):
        print(json.dumps({name: spec.as_dict() for name, spec in rows.items()}, indent=2, sort_keys=True))
        return 0
    for name, spec in sorted(rows.items()):
        aliases = f" aliases={','.join(spec.aliases)}" if spec.aliases else ""
        print(f"{name:18s} gate={spec.default_gate:.3f}{aliases}  {spec.summary}")
    print(f"techniques: {len(rows)}")
    return 0


def cmd_techniques_describe(args) -> int:
    from .technique_catalog import canonical_technique_name, technique_specs
    try:
        name = canonical_technique_name(str(args.name))
    except ValueError as ex:
        print(str(ex), file=sys.stderr)
        return 2
    payload = technique_specs()[name].as_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


class TechniqueList(kwconf.Config):
    """List backend-independent v3 performance techniques."""
    json: bool = kwconf.Flag(False)
    @classmethod
    def main(cls, argv=True, **kwargs):
        return cmd_techniques_list(cls.cli(argv=argv, data=kwargs))


class TechniqueDescribe(kwconf.Config):
    """Describe one v3 performance technique."""
    name: str = kwconf.Value(None, position=1)
    json: bool = kwconf.Flag(False)
    @classmethod
    def main(cls, argv=True, **kwargs):
        return cmd_techniques_describe(cls.cli(argv=argv, data=kwargs))


class TechniquesModal(kwconf.ModalCLI):
    """Inspect the checked-in performance-technique vocabulary."""
    list = TechniqueList
    describe = TechniqueDescribe


def cmd_generators_list(args) -> int:
    from .musicir.generators import generator_specs

    specs = generator_specs()
    if getattr(args, "json", False):
        print(json.dumps({name: spec.as_dict() for name, spec in specs.items()}, indent=2, sort_keys=True))
        return 0
    for name in sorted(specs):
        spec = specs[name]
        print(f"{name:26s} harmony={spec.harmony:8s} {spec.summary}")
    print(f"generators: {len(specs)}")
    return 0


def cmd_generators_describe(args) -> int:
    from .musicir.generators import get_generator_spec

    spec = get_generator_spec(str(args.name))
    payload = spec.as_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"{spec.name}: {spec.summary}")
    print(f"  bridge:   {spec.bridge_kind}")
    print(f"  harmony:  {spec.harmony}")
    print("  parameters:")
    for key in spec.parameter_names:
        meta = spec.parameters[key]
        bits = []
        if meta.get("required"):
            bits.append("required")
        elif "default" in meta:
            bits.append(f"default={meta['default']!r}")
        desc = str(meta.get("description", ""))
        suffix = ("; " + ", ".join(bits)) if bits else ""
        print(f"    {key}{suffix}")
        if desc:
            print(f"      {desc}")
    if spec.notes:
        print("  notes:")
        for note in spec.notes:
            print(f"    - {note}")
    print("  example:")
    print(json.dumps(spec.example, indent=2, sort_keys=True))
    return 0


def cmd_generators_schema(args) -> int:
    from .musicir.generators import generator_json_schema

    print(json.dumps(generator_json_schema(str(args.name)), indent=2, sort_keys=True))
    return 0


class GeneratorList(kwconf.Config):
    """List the checked-in MusicIR v3 generator vocabulary."""

    json: bool = kwconf.Flag(False, help="emit complete generator metadata as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_generators_list(cls.cli(argv=argv, data=kwargs))


class GeneratorDescribe(kwconf.Config):
    """Describe one MusicIR v3 generator."""

    name: str = kwconf.Value(None, position=1, help="generator name, e.g. guitar.strum")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_generators_describe(cls.cli(argv=argv, data=kwargs))


class GeneratorSchema(kwconf.Config):
    """Emit JSON Schema for one MusicIR v3 generate block."""

    name: str = kwconf.Value(None, position=1, help="generator name, e.g. harmony.arpeggio")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_generators_schema(cls.cli(argv=argv, data=kwargs))


class GeneratorsModal(kwconf.ModalCLI):
    """Inspect the checked-in MusicIR v3 procedural capability registry."""

    list = GeneratorList
    describe = GeneratorDescribe
    schema = GeneratorSchema



def cmd_processing_list(args) -> int:
    from .processing.catalog import get_processor_spec, processor_names

    names = processor_names()
    if getattr(args, "json", False):
        print(json.dumps({name: get_processor_spec(name).as_dict() for name in names}, indent=2, sort_keys=True))
        return 0
    for name in names:
        spec = get_processor_spec(name)
        print(f"{name:18s} backend={spec.backend:11s} {spec.summary}")
    print(f"processors: {len(names)}")
    return 0


def cmd_processing_describe(args) -> int:
    from .processing.catalog import get_processor_spec

    spec = get_processor_spec(str(args.name))
    payload = spec.as_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"{spec.name}: {spec.summary}")
    print(f"  backend: {spec.backend}")
    print(f"  aliases: {', '.join(spec.aliases) if spec.aliases else '-'}")
    print(f"  automation: {'yes' if spec.automation.get('supported') else 'no'}")
    print("  parameters:")
    for key, meta in spec.parameters.items():
        bits = []
        if "default" in meta:
            bits.append(f"default={meta['default']!r}")
        if meta.get("minimum") is not None:
            bits.append(f"min={meta['minimum']}")
        if meta.get("maximum") is not None:
            bits.append(f"max={meta['maximum']}")
        print(f"    {key}" + (f" ({', '.join(bits)})" if bits else ""))
    return 0


def cmd_processing_schema(args) -> int:
    from .processing.catalog import processor_json_schema

    print(json.dumps(processor_json_schema(str(args.name)), indent=2, sort_keys=True))
    return 0


def cmd_processing_plan(args) -> int:
    from .processing.mastering import mastering_policy
    from .processing.plans import processing_plan_summary
    from .render.score_core import load_yaml

    path = find_score(str(args.cue))
    if path is None:
        raise FileNotFoundError(f"could not find score {args.cue!r}")
    spec = load_yaml(path)
    groups = sorted({str(row.get("group")) for row in spec.get("instruments", []) if isinstance(row, dict) and row.get("group")})
    sections = [str(row.get("id")) for row in spec.get("sections", []) if isinstance(row, dict) and row.get("id")]
    payload = processing_plan_summary(spec, groups=groups, sections=sections)
    payload["mastering_policy"] = mastering_policy(spec).as_dict()
    payload["score"] = str(path)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


class ProcessingList(kwconf.Config):
    json: bool = kwconf.Flag(False, help="emit complete processor metadata as JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_processing_list(cls.cli(argv=argv, data=kwargs))


class ProcessingDescribe(kwconf.Config):
    name: str = kwconf.Value(None, position=1, help="processor name, e.g. compressor")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_processing_describe(cls.cli(argv=argv, data=kwargs))


class ProcessingSchema(kwconf.Config):
    name: str = kwconf.Value(None, position=1, help="processor name")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_processing_schema(cls.cli(argv=argv, data=kwargs))


class ProcessingPlanCommand(kwconf.Config):
    cue: str = kwconf.Value(None, position=1, help="cue id or score path")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_processing_plan(cls.cli(argv=argv, data=kwargs))


class ProcessingModal(kwconf.ModalCLI):
    """Inspect the checked-in processing registry and resolved score plans."""

    list = ProcessingList
    describe = ProcessingDescribe
    schema = ProcessingSchema
    plan = ProcessingPlanCommand


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


class PluginSmokeSFZ(kwconf.Config):
    root: str | None = kwconf.Value(None, help="SFZ root override")
    sample_rate: int = kwconf.Value(24000)
    timeout: float = kwconf.Value(30.0, help="per-patch sfizz timeout in seconds")
    output: Path | None = kwconf.Value(None, parser=Path, help="write JSON report to this path")
    json: bool = kwconf.Flag(False, help="emit JSON")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return cmd_plugins_smoke_sfz(cls.cli(argv=argv, data=kwargs))


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
    smoke_sfz = PluginSmokeSFZ
    lv2_info = PluginLV2Info
    validate_score = PluginValidateScore

# Audit/legacy commands register their own Config classes directly. Each module
# defers its heavy imports (numpy/scipy/pretty_midi/matplotlib/render.score_*)
# via lazy_loader, so importing them here keeps CLI startup cheap while letting
# each Config own its argument schema as the single source of truth.
from .audit.arrangement_audit import ArrangementAuditConfig
from .audit.audit_cue_balance import AuditCueBalanceConfig
from .audit.dissonance_audit import DissonanceAuditConfig
from .audit.lead_collision import LeadCollisionConfig
from .audit.level_report import LevelReportConfig
from .audit.instrument_drift import InstrumentDriftConfig
from .audit.mix_balance_audit import MixBalanceAuditConfig
from .audit.pitch_stability import PitchStabilityConfig
from .audit.reference_audio_audit import ReferenceAudioAuditConfig
from .audit.shrill_note_audit import ShrillNoteAuditConfig
from .audit.sour_note_audit import SourNoteAuditConfig
from .audit.spectral_compare import SpectralCompareConfig
from .audit.spectral_localize import SpectralLocalizeConfig
from .audit.transition_audit import TransitionAuditConfig
from .legacy.make_first_goblin_transition_lab import FirstGoblinTransitionLabConfig


class AuditModal(kwconf.ModalCLI):
    """Analysis and audit helpers for rendered scores and generated audio."""

    arrangement = ArrangementAuditConfig
    dissonance = DissonanceAuditConfig
    lead_collision = LeadCollisionConfig
    mix_balance = MixBalanceAuditConfig
    pitch_stability = PitchStabilityConfig
    reference_audio = ReferenceAudioAuditConfig
    shrill_notes = ShrillNoteAuditConfig
    sour_notes = SourNoteAuditConfig
    cue_balance = AuditCueBalanceConfig
    levels = LevelReportConfig
    spectral_compare = SpectralCompareConfig
    spectral_localize = SpectralLocalizeConfig
    transition = TransitionAuditConfig
    instrument_drift = InstrumentDriftConfig


class AudioCompareCommand(kwconf.Config):
    """Compare two rendered audio files using objective review metrics."""

    before: Path = kwconf.Value(None, position=1, parser=Path)
    after: Path = kwconf.Value(None, position=2, parser=Path)
    json: bool = kwconf.Flag(False, help="emit the complete comparison report")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        from .audit.render_compare import compare_audio_files
        try:
            report = compare_audio_files(config.before, config.after)
        except (OSError, ValueError) as ex:
            print(str(ex), file=sys.stderr)
            return 1
        if config.json:
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
        else:
            delta = report["delta"]
            print(f"RMS: {delta.get('rms_db'):+.3f} dB")
            print(f"peak: {delta.get('peak_db'):+.3f} dB")
            if delta.get("integrated_lufs") is not None:
                print(f"LUFS: {delta['integrated_lufs']:+.3f}")
            print(f"spectral centroid: {delta.get('spectral_centroid_hz'):+.1f} Hz")
            print(f"waveform correlation: {delta.get('aligned_waveform_correlation'):.6f}")
            print(f"aligned difference RMS: {delta.get('aligned_rms'):.8f}")
        return 0


class AudioModal(kwconf.ModalCLI):
    """Audio-level before/after review tools."""

    compare = AudioCompareCommand


class LegacyModal(kwconf.ModalCLI):
    """Quarantined legacy helpers kept importable until we verify deletion safety."""

    make_first_goblin_transition_lab = FirstGoblinTransitionLabConfig


class AmbitionMusicRendererCLI(kwconf.ModalCLI):
    """Modal CLI for ambition_music_renderer."""

    cue = CueModal
    sandbox = SandboxModal
    radio = RadioModal
    instruments = InstrumentsModal
    techniques = TechniquesModal
    generators = GeneratorsModal
    processing = ProcessingModal
    audio = AudioModal
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

"""Parallel cue bundle runner for overnight MusicIR diagnostics.

This wrapper deliberately launches one normal ``cue_bundle`` subprocess per cue.
That is safer than importing the renderer into many in-process workers because
pretty-midi, fluidsynth/ffmpeg, matplotlib, and SoundFont handles all have their
own process-level state.  The Python coordinator is mostly waiting on child process I/O.  We use
``ubelt.Executor`` so ``--workers 0`` / ``--workers 1`` have an explicit serial
fallback, while larger values use a thread coordinator around separate render
processes.
"""

from __future__ import annotations

import csv
import os
import queue
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import kwconf


from ..cli import find_score, package_dir
from .bundle import default_bundle_root, terminal_link
from ..profiler import profile
from ..kwconf_runner import KwconfCommand


@dataclass(frozen=True)
class BundleJob:
    cue: str
    log_path: Path
    command: list[str]


@dataclass(frozen=True)
class BundleResult:
    cue: str
    returncode: int
    elapsed_s: float
    log_path: Path
    latest_stage: str
    bundle_dir: Path | None = None
    report_zip: Path | None = None
    full_zip: Path | None = None


def _score_dirs() -> Path:
    return package_dir() / "scores"


def _cue_id_from_path(path: Path) -> str:
    name = path.name
    for suffix in (".music.yaml", ".yaml", ".yml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def discover_cues(*, scope: str, include_examples: bool = False) -> list[str]:
    roots: list[Path]
    scores = _score_dirs()
    if scope == "active":
        roots = [scores / "active"]
    elif scope == "examples":
        roots = [scores / "examples"]
    elif scope == "all":
        roots = [scores / "active", scores / "examples", scores / "experiments"]
    else:
        raise ValueError(f"unknown scope: {scope}")
    if include_examples and scores / "examples" not in roots:
        roots.append(scores / "examples")
    cues: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.music.yaml")):
            cues.add(_cue_id_from_path(path))
        for path in sorted(root.glob("*.yaml")):
            cues.add(_cue_id_from_path(path))
    return sorted(cues)


def resolve_cues(raw_cues: Iterable[str], *, scope: str, include_examples: bool) -> list[str]:
    cues = list(raw_cues)
    if not cues:
        cues = discover_cues(scope=scope, include_examples=include_examples)
    resolved: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for cue in cues:
        cue_id = _cue_id_from_path(Path(cue)) if Path(cue).suffix else cue
        if cue_id in seen:
            continue
        if find_score(cue) is None and find_score(cue_id) is None:
            missing.append(cue)
            continue
        seen.add(cue_id)
        resolved.append(cue_id)
    if missing:
        raise SystemExit("missing cue score(s): " + ", ".join(missing))
    return resolved



def _newer_than(paths: Iterable[Path], start_mtime: float) -> Path | None:
    existing = [p for p in paths if p.exists() and p.stat().st_mtime >= start_mtime - 1.0]
    if not existing:
        return None
    return max(existing, key=lambda p: p.stat().st_mtime)


def _find_job_artifacts(cue: str, bundle_root: Path, start_time: float) -> tuple[Path | None, Path | None, Path | None]:
    """Find bundle outputs created by a just-finished cue_bundle subprocess."""
    root = bundle_root.resolve()
    bundle_dir = _newer_than(root.glob(f"{cue}_*_bundle"), start_time)
    report_zip = _newer_than(root.glob(f"{cue}_*_bundle_report.zip"), start_time)
    full_zip = _newer_than((p for p in root.glob(f"{cue}_*_bundle.zip") if not p.name.endswith("_report.zip")), start_time)
    return bundle_dir, report_zip, full_zip


def _fmt_link(path: Path | None) -> str:
    return terminal_link(path) if path else ""

def _build_command(args, cue: str) -> list[str]:
    from .bundle import CueBundleConfig

    data = {
        "cue": cue,
        "backend": args.backend,
        "runtime_stem_gain_mode": args.runtime_stem_gain_mode,
        "jobs": args.render_jobs,
        "plot_format": args.plot_format,
        "jpeg_quality": args.jpeg_quality,
        "runtime_stem_max_gain_db": args.runtime_stem_max_gain_db,
        "force": args.force,
        "publish": args.publish,
        "zip_bundle": args.zip,
        "zip_report_bundle": args.zip_report,
        "skip_spectrograms": args.skip_spectrograms,
        "render_audio_mode": args.render_audio_mode,
        "profile_render": args.profile_render,
        "include_scratch_stems": args.include_scratch_stems,
        "bundle_root": args.bundle_root,
    }
    return KwconfCommand(
        CueBundleConfig,
        module="ambition_music_renderer.render.bundle",
        cwd=package_dir(),
    ).python_command(data)


@profile
def _worker(job: BundleJob, events: "queue.Queue[tuple[str, str, object]]") -> BundleResult:
    start_wall_time = time.time()
    start = time.monotonic()
    latest_stage = "starting"
    job.log_path.parent.mkdir(parents=True, exist_ok=True)
    events.put(("stage", job.cue, latest_stage))
    with job.log_path.open("w", encoding="utf8") as log:
        log.write("$ " + shlex.join(job.command) + "\n\n")
        log.flush()
        proc = subprocess.Popen(
            job.command,
            cwd=package_dir(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
            if line.startswith("[music bundle] "):
                latest_stage = line.strip().removeprefix("[music bundle] ")
                events.put(("stage", job.cue, latest_stage))
        returncode = proc.wait()
    elapsed = time.monotonic() - start
    bundle_root = default_bundle_root()
    for idx, item in enumerate(job.command):
        if item == "--bundle_root" and idx + 1 < len(job.command):
            bundle_root = Path(job.command[idx + 1])
            break
        if item.startswith("--bundle_root="):
            bundle_root = Path(item.split("=", 1)[1])
            break
    start_wall = start_wall_time
    bundle_dir, report_zip, full_zip = _find_job_artifacts(job.cue, bundle_root, start_wall)
    result = BundleResult(job.cue, returncode, elapsed, job.log_path, latest_stage, bundle_dir, report_zip, full_zip)
    events.put(("done", job.cue, result))
    return result


def _executor_mode(workers: int) -> tuple[str, int]:
    """Return an ubelt executor mode for cue-level bundle jobs.

    ``workers <= 1`` deliberately means serial execution.  That avoids thread
    coordinator overhead and makes single-cue profiling easier to interpret.
    ``workers > 1`` uses threads only to supervise independent child processes;
    the CPU-heavy work still happens in those subprocesses.
    """
    if workers <= 1:
        return "serial", 0
    return "thread", int(workers)


@profile
def _run_plain(jobs: list[BundleJob], *, workers: int) -> list[BundleResult]:
    events: "queue.Queue[tuple[str, str, object]]" = queue.Queue()
    results: list[BundleResult] = []
    mode, max_workers = _executor_mode(workers)
    import ubelt as ub

    with ub.Executor(mode=mode, max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, job, events) for job in jobs]
        remaining = len(futures)
        stages: dict[str, str] = {job.cue: "queued" for job in jobs}
        while remaining:
            kind, cue, payload = events.get()
            if kind == "stage":
                stages[cue] = str(payload)
                print(f"[{cue}] {payload}", flush=True)
            elif kind == "done":
                result = payload
                assert isinstance(result, BundleResult)
                results.append(result)
                remaining -= 1
                status = "OK" if result.returncode == 0 else f"FAIL {result.returncode}"
                links = []
                if result.report_zip:
                    links.append(f"report={terminal_link(result.report_zip)}")
                if result.bundle_dir:
                    links.append(f"bundle={terminal_link(result.bundle_dir)}")
                print(f"[{cue}] {status} in {result.elapsed_s:.1f}s; log={terminal_link(result.log_path)}" + ("; " + "; ".join(links) if links else ""), flush=True)
        for fut in futures:
            fut.result()
    return results


@profile
def _run_rich(jobs: list[BundleJob], *, workers: int) -> list[BundleResult]:
    try:
        from rich.console import Console
        from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
        from rich.table import Table
    except Exception:
        return _run_plain(jobs, workers=workers)

    console = Console(stderr=True)
    events: "queue.Queue[tuple[str, str, object]]" = queue.Queue()
    results: list[BundleResult] = []
    task_for_cue: dict[str, int] = {}
    mode, max_workers = _executor_mode(workers)
    import ubelt as ub

    with ub.Executor(mode=mode, max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, job, events) for job in jobs]
        columns = [
            SpinnerColumn(),
            TextColumn("{task.fields[cue]}", justify="right"),
            BarColumn(),
            TaskProgressColumn(),
            # Keep TextColumn arguments compatible with older Rich versions.
            # Some distro/venv Rich releases do not accept overflow= here.
            TextColumn("{task.fields[stage]}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]
        with Progress(*columns, console=console, refresh_per_second=4) as progress:
            overall = progress.add_task("overall", cue="all", stage="queued", total=len(jobs))
            for job in jobs:
                task_for_cue[job.cue] = progress.add_task(job.cue, cue=job.cue, stage="queued", total=1)
            remaining = len(futures)
            while remaining:
                try:
                    kind, cue, payload = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                task = task_for_cue.get(cue)
                if kind == "stage" and task is not None:
                    progress.update(task, stage=str(payload))
                elif kind == "done":
                    result = payload
                    assert isinstance(result, BundleResult)
                    results.append(result)
                    remaining -= 1
                    if task is not None:
                        status = "done" if result.returncode == 0 else f"failed {result.returncode}"
                        progress.update(task, completed=1, stage=status)
                    progress.advance(overall, 1)
            for fut in futures:
                fut.result()

    table = Table(title="Bundle results")
    table.add_column("cue")
    table.add_column("status")
    table.add_column("elapsed")
    table.add_column("last stage")
    table.add_column("log")
    table.add_column("bundle dir")
    table.add_column("report zip")
    for result in sorted(results, key=lambda r: r.cue):
        status = "OK" if result.returncode == 0 else f"FAIL {result.returncode}"
        table.add_row(
            result.cue,
            status,
            f"{result.elapsed_s:.1f}s",
            result.latest_stage,
            _fmt_link(result.log_path),
            _fmt_link(result.bundle_dir),
            _fmt_link(result.report_zip),
        )
    console.print(table)
    return results


def write_status(results: list[BundleResult], status_path: Path) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with status_path.open("w", encoding="utf8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["cue", "returncode", "elapsed_s", "latest_stage", "log", "bundle_dir", "report_zip", "full_zip"], delimiter="\t")
        writer.writeheader()
        for result in sorted(results, key=lambda r: r.cue):
            writer.writerow(
                {
                    "cue": result.cue,
                    "returncode": result.returncode,
                    "elapsed_s": f"{result.elapsed_s:.3f}",
                    "latest_stage": result.latest_stage,
                    "log": str(result.log_path),
                    "bundle_dir": str(result.bundle_dir or ""),
                    "report_zip": str(result.report_zip or ""),
                    "full_zip": str(result.full_zip or ""),
                }
            )


class BatchBundleConfig(kwconf.Config):
    """Render/debug many cue bundles in parallel with per-cue logs."""


    cues: list[str] = kwconf.Value(default_factory=list, position=1, nargs="*", help="cue ids or YAML paths; omit to discover by --scope")
    workers: int | None = kwconf.Value(max(1, min(4, (os.cpu_count() or 4) // 2)), short_alias=["j"], help="parallel cue jobs; 0 or 1 runs serially")
    render_jobs: int = kwconf.Value(1, help="per-cue render worker count passed to cue_bundle")
    scope: str = kwconf.Value("active", choices=["active", "examples", "all"])
    include_examples: bool = kwconf.Flag(False, help="include scores/examples in discovery")
    backend: str = kwconf.Value("pretty-midi")
    runtime_stem_gain_mode: str = kwconf.Value("shared", choices=["native", "shared"])
    runtime_stem_max_gain_db: float | None = kwconf.Value(None)
    force: bool = kwconf.Flag(False)
    publish: bool = kwconf.Flag(False)
    zip: bool = kwconf.Flag(False, help="write full bundle zips including audio")
    zip_report: bool = kwconf.Flag(True, help="write compact report zips; enabled by default")
    skip_spectrograms: bool = kwconf.Flag(False)
    include_scratch_stems: bool = kwconf.Flag(False)
    render_audio_mode: str = kwconf.Value("full", choices=["full", "full-mix-only", "simple-mix"])
    profile_render: bool = kwconf.Flag(False, help="enable line_profiler in render subprocesses via LINE_PROFILE=1")
    plot_format: str = kwconf.Value("jpg", choices=["jpg", "png"])
    jpeg_quality: int = kwconf.Value(84)
    bundle_root: Path | None = kwconf.Value(None, parser=Path)
    log_root: Path = kwconf.Value(default_factory=lambda: package_dir() / "batch_logs", parser=Path)

    def __post_init__(self) -> None:
        self.workers = int(self.workers if self.workers is not None else 1)
        self.render_jobs = int(self.render_jobs)
        self.jpeg_quality = int(self.jpeg_quality)
        for key in ("bundle_root", "log_root"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        return run_batch_bundle(config)




@profile
def run_batch_bundle(args) -> int:
    total_start = time.perf_counter()
    rc = 1
    try:
        cues = resolve_cues(args.cues, scope=args.scope, include_examples=args.include_examples)
        if not cues:
            print("no cues selected", file=sys.stderr)
            rc = 2
            return rc
        stamp = time.strftime("%Y%m%dT%H%M%S")
        log_root = args.log_root / f"bundle_many_{stamp}"
        jobs = [BundleJob(cue, log_root / f"{cue}.log", _build_command(args, cue)) for cue in cues]
        bundle_root = args.bundle_root or default_bundle_root()
        print(f"bundle-many: {len(jobs)} cue(s), {args.workers} parallel job(s)", file=sys.stderr)
        print(f"logs: {terminal_link(log_root)}", file=sys.stderr)
        print(f"bundle root: {terminal_link(bundle_root)}", file=sys.stderr)
        print("queued bundle logs:", file=sys.stderr)
        for job in jobs:
            print(f"  {job.cue}: {terminal_link(job.log_path)}", file=sys.stderr)
        results = _run_rich(jobs, workers=args.workers)
        status_path = log_root / "status.tsv"
        write_status(results, status_path)
        print(f"status: {terminal_link(status_path)}", file=sys.stderr)
        print("bundle-many output links:", file=sys.stderr)
        for result in sorted(results, key=lambda r: r.cue):
            status = "OK" if result.returncode == 0 else f"FAIL {result.returncode}"
            print(f"  {result.cue} [{status}]", file=sys.stderr)
            print(f"    log:    {terminal_link(result.log_path)}", file=sys.stderr)
            if result.bundle_dir:
                print(f"    bundle: {terminal_link(result.bundle_dir)}", file=sys.stderr)
            if result.report_zip:
                print(f"    report: {terminal_link(result.report_zip)}", file=sys.stderr)
            if result.full_zip:
                print(f"    zip:    {terminal_link(result.full_zip)}", file=sys.stderr)
        failures = [r for r in results if r.returncode != 0]
        rc = 1 if failures else 0
        return rc
    finally:
        elapsed = time.perf_counter() - total_start
        print(f"[ambition_music_renderer.bundle_many] total_elapsed_s={elapsed:.3f}", flush=True)


def main(argv: list[str] | None = None) -> int:
    config = BatchBundleConfig.cli(argv=argv)
    return run_batch_bundle(config)


if __name__ == "__main__":
    raise SystemExit(main())

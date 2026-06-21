"""Parallel cue bundle runner for overnight MusicIR diagnostics.

This wrapper deliberately launches one normal ``cue bundle`` subprocess per cue.
That is safer than importing the renderer into many in-process workers because
pretty-midi, fluidsynth/ffmpeg, matplotlib, and SoundFont handles all have their
own process-level state.  The Python coordinator is mostly waiting on child
process I/O, so a ThreadPoolExecutor is the right fit: it lets several fully
separate render processes consume CPU while the parent keeps a live progress UI
and per-cue logs.
"""

from __future__ import annotations

import argparse
import csv
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .cli import find_score, package_dir, python_exe
from .cue_bundle import default_bundle_root, terminal_link


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
    """Find bundle outputs created by a just-finished cue bundle subprocess."""
    root = bundle_root.resolve()
    bundle_dir = _newer_than(root.glob(f"{cue}_*_bundle"), start_time)
    report_zip = _newer_than(root.glob(f"{cue}_*_bundle_report.zip"), start_time)
    full_zip = _newer_than((p for p in root.glob(f"{cue}_*_bundle.zip") if not p.name.endswith("_report.zip")), start_time)
    return bundle_dir, report_zip, full_zip


def _fmt_link(path: Path | None) -> str:
    return terminal_link(path) if path else ""

def _build_command(args: argparse.Namespace, cue: str) -> list[str]:
    cmd = [
        python_exe(),
        "-m",
        "ambition_music_renderer",
        "cue",
        "bundle",
        cue,
        "--backend",
        args.backend,
        "--runtime-stem-gain-mode",
        args.runtime_stem_gain_mode,
        "--jobs",
        str(args.render_jobs),
        "--plot-format",
        args.plot_format,
        "--jpeg-quality",
        str(args.jpeg_quality),
    ]
    if args.runtime_stem_max_gain_db is not None:
        cmd.extend(["--runtime-stem-max-gain-db", str(args.runtime_stem_max_gain_db)])
    if args.force:
        cmd.append("--force")
    if args.publish:
        cmd.append("--publish")
    if args.zip:
        cmd.append("--zip")
    if args.zip_report:
        cmd.append("--zip-report")
    if args.skip_spectrograms:
        cmd.append("--skip-spectrograms")
    cmd.extend(["--render-audio-mode", args.render_audio_mode])
    if args.profile_render:
        cmd.append("--profile-render")
    if args.include_scratch_stems:
        cmd.append("--include-scratch-stems")
    if args.bundle_root is not None:
        cmd.extend(["--bundle-root", str(args.bundle_root)])
    return cmd


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
        if item == "--bundle-root" and idx + 1 < len(job.command):
            bundle_root = Path(job.command[idx + 1])
            break
    start_wall = start_wall_time
    bundle_dir, report_zip, full_zip = _find_job_artifacts(job.cue, bundle_root, start_wall)
    result = BundleResult(job.cue, returncode, elapsed, job.log_path, latest_stage, bundle_dir, report_zip, full_zip)
    events.put(("done", job.cue, result))
    return result


def _run_plain(jobs: list[BundleJob], *, workers: int) -> list[BundleResult]:
    events: "queue.Queue[tuple[str, str, object]]" = queue.Queue()
    results: list[BundleResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
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
    with ThreadPoolExecutor(max_workers=workers) as pool:
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ambition_music_renderer.batch_bundle",
        description="Render/debug many cue bundles in parallel with per-cue logs.",
    )
    ap.add_argument("cues", nargs="*", help="cue ids or YAML paths; omit to discover by --scope")
    ap.add_argument("-j", "--workers", type=int, default=max(1, min(4, (os.cpu_count() or 4) // 2)), help="parallel cue jobs")
    ap.add_argument("--render-jobs", type=int, default=1, help="per-cue render worker count passed to cue bundle")
    ap.add_argument("--scope", choices=["active", "examples", "all"], default="active")
    ap.add_argument("--include-examples", action="store_true", help="include scores/examples in discovery")
    ap.add_argument("--backend", default="pretty-midi")
    ap.add_argument("--runtime-stem-gain-mode", choices=["native", "shared"], default="shared")
    ap.add_argument("--runtime-stem-max-gain-db", type=float, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--zip", action="store_true", help="write full bundle zips including audio")
    ap.add_argument("--zip-report", action="store_true", default=True, help="write compact report zips; enabled by default")
    ap.add_argument("--no-zip-report", dest="zip_report", action="store_false")
    ap.add_argument("--skip-spectrograms", action="store_true")
    ap.add_argument("--include-scratch-stems", action="store_true")
    ap.add_argument("--render-audio-mode", choices=["full", "full-mix-only", "simple-mix"], default="full")
    ap.add_argument("--profile-render", action="store_true")
    ap.add_argument("--plot-format", choices=["jpg", "png"], default="jpg")
    ap.add_argument("--jpeg-quality", type=int, default=84)
    ap.add_argument("--bundle-root", type=Path, default=None)
    ap.add_argument("--log-root", type=Path, default=package_dir() / "batch_logs")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cues = resolve_cues(args.cues, scope=args.scope, include_examples=args.include_examples)
    if not cues:
        print("no cues selected", file=sys.stderr)
        return 2
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
    results = _run_rich(jobs, workers=max(1, args.workers))
    status_path = log_root / "status.tsv"
    write_status(results, status_path)
    print(f"status: {terminal_link(status_path)}", file=sys.stderr)
    print("bundle-many output links:", file=sys.stderr)
    for result in sorted(results, key=lambda r: r.cue):
        status = "OK" if result.returncode == 0 else f"FAIL {result.returncode}"
        print(f"  {result.cue} [{status}]", file=sys.stderr)
        print(f"    log: {terminal_link(result.log_path)}", file=sys.stderr)
        if result.bundle_dir:
            print(f"    bundle dir: {terminal_link(result.bundle_dir)}", file=sys.stderr)
        if result.report_zip:
            print(f"    report zip: {terminal_link(result.report_zip)}", file=sys.stderr)
        if result.full_zip:
            print(f"    full zip: {terminal_link(result.full_zip)}", file=sys.stderr)
    failed = [r for r in results if r.returncode != 0]
    if failed:
        print("FAILED: " + ", ".join(f"{r.cue}({r.returncode})" for r in failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

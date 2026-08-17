"""Heartbeat helpers for long-running renderer subprocesses."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable

StatusFn = Callable[[], str | None]
EmitFn = Callable[[str], None]


def heartbeat_seconds(value: float | None = None) -> float:
    """Resolve the subprocess heartbeat interval.

    ``AMBITION_SUBPROCESS_HEARTBEAT_S=0`` disables heartbeat messages while
    preserving the same wait/timeout semantics.
    """
    if value is None:
        value = float(os.environ.get("AMBITION_SUBPROCESS_HEARTBEAT_S", "15"))
    return max(0.0, float(value))


def _status_text(status_fn: StatusFn | None) -> str:
    if status_fn is None:
        return ""
    try:
        value = status_fn()
    except Exception as ex:  # diagnostics must never break a render
        return f" status_error={type(ex).__name__}: {ex}"
    return f" {value.strip()}" if value else ""


def _heartbeat_message(proc: subprocess.Popen, label: str, elapsed_s: float, status_fn: StatusFn | None) -> str:
    return f"{label} still running: elapsed={elapsed_s:.1f}s pid={proc.pid}{_status_text(status_fn)}"


def _wait_slice(*, started: float, heartbeat_s: float, timeout_s: float | None) -> float | None:
    if heartbeat_s <= 0 and timeout_s is None:
        return None
    waits: list[float] = []
    if heartbeat_s > 0:
        waits.append(heartbeat_s)
    if timeout_s is not None:
        remaining = float(timeout_s) - (time.monotonic() - started)
        if remaining <= 0:
            return 0.0
        waits.append(remaining)
    return max(0.001, min(waits)) if waits else None


def _timed_out(*, started: float, timeout_s: float | None) -> bool:
    return timeout_s is not None and (time.monotonic() - started) >= float(timeout_s)


def wait_with_heartbeat(
    proc: subprocess.Popen,
    *,
    label: str,
    heartbeat_s: float | None = None,
    timeout_s: float | None = None,
    status_fn: StatusFn | None = None,
    emit: EmitFn = print,
) -> int:
    """Wait for ``proc`` while periodically emitting a liveness heartbeat."""
    interval = heartbeat_seconds(heartbeat_s)
    started = time.monotonic()
    while True:
        wait_s = _wait_slice(started=started, heartbeat_s=interval, timeout_s=timeout_s)
        try:
            return int(proc.wait(timeout=wait_s))
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            if _timed_out(started=started, timeout_s=timeout_s):
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(proc.args, float(timeout_s))
            if interval > 0:
                emit(_heartbeat_message(proc, label, elapsed, status_fn))


def communicate_with_heartbeat(
    proc: subprocess.Popen,
    *,
    label: str,
    heartbeat_s: float | None = None,
    timeout_s: float | None = None,
    status_fn: StatusFn | None = None,
    emit: EmitFn = print,
) -> tuple[str | bytes | None, str | bytes | None]:
    """Like ``Popen.communicate`` with periodic progress and a total timeout."""
    interval = heartbeat_seconds(heartbeat_s)
    started = time.monotonic()
    while True:
        wait_s = _wait_slice(started=started, heartbeat_s=interval, timeout_s=timeout_s)
        try:
            return proc.communicate(timeout=wait_s)
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            if _timed_out(started=started, timeout_s=timeout_s):
                proc.kill()
                stdout, stderr = proc.communicate()
                raise subprocess.TimeoutExpired(
                    proc.args,
                    float(timeout_s),
                    output=stdout,
                    stderr=stderr,
                )
            if interval > 0:
                emit(_heartbeat_message(proc, label, elapsed, status_fn))


def tail_status(*paths: tuple[str, Path]) -> str:
    """Compact status for report files: byte counts plus latest nonempty line."""
    sizes: list[str] = []
    latest: tuple[float, str] | None = None
    for name, path in paths:
        p = Path(path)
        try:
            stat = p.stat()
        except OSError:
            sizes.append(f"{name}=missing")
            continue
        sizes.append(f"{name}={stat.st_size}B")
        try:
            text = p.read_text(encoding="utf8", errors="replace")
        except OSError:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            candidate = (stat.st_mtime, lines[-1][-240:])
            if latest is None or candidate[0] >= latest[0]:
                latest = candidate
    if latest is not None:
        sizes.append(f"last={latest[1]!r}")
    return " ".join(sizes)


def wav_growth_status(path: Path, *, sample_rate: int | None = None) -> str:
    """Report live WAV growth without opening a file still being written."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return "wav=not-created-yet"
    parts = [f"wav={size}B"]
    # The byte count is authoritative. This duration is intentionally labeled
    # an estimate because a custom sfizz_render build could choose another WAV
    # encoding than the usual stereo PCM16 output.
    if sample_rate and size > 44:
        estimated_s = max(0, size - 44) / (int(sample_rate) * 2 * 2)
        parts.append(f"pcm16_stereo_est={estimated_s:.1f}s")
    return " ".join(parts)

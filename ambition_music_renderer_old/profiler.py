"""Small optional profiling helpers for the MusicIR renderer.

Use ``from ambition_music_renderer.profiler import profile`` throughout the
codebase. When ``line_profiler`` is installed this is its modern decorator; when
it is not installed it is a no-op identity decorator. The environment variable
``LINE_PROFILE=1`` is handled by line_profiler itself.
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def _identity_profile(func: F) -> F:
    """Identity replacement for ``line_profiler.profile``."""
    return func


try:  # pragma: no cover - optional developer dependency.
    from line_profiler import profile as profile  # type: ignore
except Exception:  # noqa: BLE001
    profile = _identity_profile  # type: ignore[assignment]


class PhaseTimer:
    """Collect coarse wall-clock timings for renderer phases."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    @contextlib.contextmanager
    def phase(self, name: str, **meta: Any) -> Iterator[None]:
        start_wall = time.time()
        start = time.perf_counter()
        ok = False
        try:
            yield
            ok = True
        finally:
            end = time.perf_counter()
            self.rows.append(
                {
                    "phase": name,
                    "elapsed_s": end - start,
                    "start_wall_time": start_wall,
                    "ok": ok,
                    **meta,
                }
            )

    def add(self, name: str, elapsed_s: float, **meta: Any) -> None:
        self.rows.append({"phase": name, "elapsed_s": float(elapsed_s), "ok": True, **meta})

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        total = sum(float(row.get("elapsed_s", 0.0)) for row in self.rows)
        payload = {"total_recorded_s": total, "phases": self.rows}
        path.write_text(json.dumps(payload, indent=2), encoding="utf8")
        return path

    def write_tsv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        keys: list[str] = ["phase", "elapsed_s", "ok"]
        for row in self.rows:
            for key in row.keys():
                if key not in keys:
                    keys.append(key)
        with path.open("w", encoding="utf8") as file:
            file.write("\t".join(keys) + "\n")
            for row in self.rows:
                file.write("\t".join(_format_tsv(row.get(key, "")) for key in keys) + "\n")
        return path

    def write_summary(self, path: Path, *, limit: int = 30) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self.rows, key=lambda row: float(row.get("elapsed_s", 0.0)), reverse=True)
        total = sum(float(row.get("elapsed_s", 0.0)) for row in self.rows)
        lines = [f"total_recorded_s: {total:.3f}", "", "slowest phases:"]
        for row in rows[:limit]:
            elapsed = float(row.get("elapsed_s", 0.0))
            pct = 100.0 * elapsed / total if total > 0 else 0.0
            meta = ", ".join(f"{k}={v}" for k, v in row.items() if k not in {"phase", "elapsed_s", "ok", "start_wall_time"})
            suffix = f" ({meta})" if meta else ""
            lines.append(f"  {elapsed:8.3f}s {pct:5.1f}%  {row.get('phase')}{suffix}")
        path.write_text("\n".join(lines) + "\n", encoding="utf8")
        return path


def _format_tsv(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value).replace("\t", " ").replace("\n", " ")

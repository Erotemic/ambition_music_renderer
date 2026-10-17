"""Stable per-stem error reports for isolated concurrent rendering."""

from __future__ import annotations

import re
from pathlib import Path


def worker_failure_path(outdir: str | Path, group: str) -> Path:
    # A group name comes from authored score data. Do not allow it to form
    # directories outside the report root.
    safe_group = re.sub(r"[^A-Za-z0-9_.-]", "_", str(group)).strip("._") or "unnamed"
    return Path(outdir) / "reports" / "group_workers" / f"{safe_group}.failure.txt"


def read_worker_failure(outdir: str | Path, group: str) -> tuple[str | None, Path]:
    """Return the recorded root exception and where its full traceback lives."""
    path = worker_failure_path(outdir, group)
    try:
        lines = path.read_text(encoding="utf8").splitlines()
    except OSError:
        return None, path
    for index, line in enumerate(lines):
        if line.startswith("exception: "):
            # SFZ failures are deliberately multi-line. Keep the whole
            # explanation, not just the first line, in the bundle summary.
            details = [line.removeprefix("exception: ")]
            for extra in lines[index + 1:]:
                if not extra.strip():
                    break
                details.append(extra)
            return "\n".join(details), path
    return None, path

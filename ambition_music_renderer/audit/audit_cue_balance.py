#!/usr/bin/env python3
"""Print peak/RMS balance for generated cue OGG files."""

from __future__ import annotations

from ..profiler import profile

import lazy_loader as lazy

import kwconf
from pathlib import Path

from .._paths import output_root

sf = lazy.load("soundfile")

from ._common import db, peak, rms


@profile
def stats(path: Path) -> tuple[float, float, float]:
    data, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    if data.size == 0:
        return 0.0, 0.0, 0.0
    duration = data.shape[0] / float(sample_rate)
    return peak(data), rms(data), duration


@profile
def discover_files(root: Path) -> list[tuple[str, str, Path]]:
    out = []
    adaptive = root / "adaptive"
    for path in sorted(adaptive.rglob("*.ogg")):
        rel = path.relative_to(adaptive)
        if len(rel.parts) < 2:
            continue
        section = rel.parts[0]
        name = rel.name
        if name.endswith(".full.ogg"):
            stem = "full"
        else:
            stem = name[:-4].split(".")[-1]
        out.append((section, stem, path))
    return out


# The renderer was moved from tools/audio/music_renderer to
# tools/ambition_music_renderer; resolve the default relative to this script
# so it works regardless of the caller's cwd.
DEFAULT_ROOT = output_root() / "first_goblin_tune_v2"


class AuditCueBalanceConfig(kwconf.Config):
    """Audit rendered cue balance."""

    root: Path = kwconf.Value(DEFAULT_ROOT, position=1, parser=Path, nargs="?")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


@profile
def run(args: AuditCueBalanceConfig) -> int:
    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"missing root: {root}")
    files = discover_files(root)
    if not files:
        raise SystemExit(f"no adaptive ogg files under {root}")

    print(f"audio balance audit: {root}")
    print(
        f"{'section':<12} {'stem':<12} {'peak':>9} {'peak_db':>9} {'rms':>9} {'rms_db':>9} {'dur':>7}"
    )
    for section, stem, path in files:
        peak_value, rms_value, duration = stats(path)
        print(
            f"{section:<12} {stem:<12} {peak_value:9.4f} {db(peak_value):9.1f} {rms_value:9.4f} {db(rms_value):9.1f} {duration:7.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(AuditCueBalanceConfig.main())

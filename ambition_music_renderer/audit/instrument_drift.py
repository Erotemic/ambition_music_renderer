"""Explain instrument-resolution changes between a recorded render and today.

Canonical render currentness now lives in ``render.dependencies`` and includes
the concrete SFZ/sample dependencies selected by a cue.  This audit remains a
narrow human-facing explanation layer: it compares the latest completed run's
recorded instrument choices with current resolution and names changes such as
``solo_violin: GM fallback -> Violin Solo 1 Marcato.sfz``.

Older runs that predate instrument records remain ``unrecorded``.  The audit is
therefore useful for history and diagnosis, but it is no longer a second cache
authority.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import kwconf

from .instrument_resolution import audit_spec

FINGERPRINT_NAME = "instrument_fingerprint.json"
SCHEMA = "ambition.music_instrument_fingerprint.v1"


def _row_key(row: dict[str, Any]) -> str:
    return str(row.get("instrument"))


def _row_value(row: dict[str, Any]) -> dict[str, Any]:
    """The part of a resolution row that decides how the audio SOUNDS.

    Deliberately narrow. ``status`` carries note-range commentary
    ("29 notes octave-folded") that shifts with unrelated score edits, and
    including it would report drift for cues whose instruments never moved.
    """
    return {
        "backend": row.get("backend"),
        "requested": row.get("requested"),
        "resolved": row.get("resolved"),
    }


def fingerprint_for_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``spec``'s instruments against the CURRENTLY installed roots."""
    payload = audit_spec(spec)
    return {
        "schema": SCHEMA,
        "id": payload.get("id"),
        "default_soundfont": payload.get("default_soundfont"),
        "sfizz_library_roots": payload.get("sfizz_library_roots"),
        "instruments": {
            _row_key(row): _row_value(row) for row in payload.get("instruments", [])
        },
    }


def write_fingerprint(run_dir: Path, spec: dict[str, Any]) -> Path:
    """Record what this render resolved. Never fatal: a render that succeeded
    must not be reported as failed because its bookkeeping could not be written.
    """
    reports = Path(run_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / FINGERPRINT_NAME
    path.write_text(json.dumps(fingerprint_for_spec(spec), indent=2, sort_keys=True))
    return path


def read_fingerprint(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / "reports" / FINGERPRINT_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if data.get("schema") == SCHEMA else None


@dataclass
class InstrumentChange:
    instrument: str
    before: dict[str, Any]
    after: dict[str, Any]

    def describe(self) -> str:
        def side(value: dict[str, Any]) -> str:
            resolved = value.get("resolved")
            if value.get("backend") == "sfz" and resolved:
                return Path(str(resolved)).name
            if value.get("backend") == "sfz":
                # No "->" here: this string is itself placed either side of an
                # arrow, and a nested one reads as a three-stage change.
                return "SFZ unresolved (GM fallback)"
            return f"GM {value.get('requested') or 'soundfont'}"

        return f"{self.instrument}: {side(self.before)} -> {side(self.after)}"


@dataclass
class CueDrift:
    cue: str
    state: str  # "current" | "drifted" | "unrecorded" | "missing-score"
    changes: list[InstrumentChange] = field(default_factory=list)
    note: str = ""

    @property
    def needs_render(self) -> bool:
        return self.state in ("drifted", "unrecorded")


def diff_fingerprints(before: dict[str, Any], after: dict[str, Any]) -> list[InstrumentChange]:
    old = before.get("instruments", {}) or {}
    new = after.get("instruments", {}) or {}
    changes: list[InstrumentChange] = []
    for name in sorted(set(old) | set(new)):
        lhs, rhs = old.get(name, {}), new.get(name, {})
        if lhs != rhs:
            changes.append(InstrumentChange(instrument=name, before=lhs, after=rhs))
    return changes


def drift_for_cue(cue: str) -> CueDrift:
    # Imported here: cli imports this module for the render-time hook, so a
    # module-level import back into cli would be circular.
    from ..cli import find_score, generated_root
    from ..render.generated_layout import resolve_latest_generated_dir
    from ..render.score_core import load_yaml

    score = find_score(cue)
    if score is None:
        return CueDrift(cue=cue, state="missing-score", note="no YAML under scores/")

    spec = load_yaml(score)
    run_dir = resolve_latest_generated_dir(generated_root() / cue)
    if not run_dir.is_dir():
        return CueDrift(cue=cue, state="unrecorded", note="no completed generated render")

    recorded = read_fingerprint(run_dir)
    if recorded is None:
        return CueDrift(cue=cue, state="unrecorded", note="render predates instrument fingerprints")

    changes = diff_fingerprints(recorded, fingerprint_for_spec(spec))
    if not changes:
        return CueDrift(cue=cue, state="current")
    return CueDrift(cue=cue, state="drifted", changes=changes)


def scan(cues: Iterable[str]) -> list[CueDrift]:
    return [drift_for_cue(cue) for cue in cues]


def newest_library_mtime() -> float | None:
    """When the installed sample libraries last changed.

    Used only as EVIDENCE for backfilling a baseline, never as a cache key: a
    render finished after the library tree stopped changing necessarily saw the
    tree as it stands, so its resolution can be recorded honestly without
    re-rendering.

    Bounded to the top few directory levels on purpose. Installing or extracting
    a library creates its family directory, so the signal is always near the
    root; walking the whole tree instead means stat-ing a 24GB, ~1800-file
    install and taking minutes to answer a question that should cost a moment.
    """
    from ..instrument_libraries import configured_sfz_roots

    max_depth = 3
    newest: float | None = None

    def consider(path: Path) -> None:
        nonlocal newest
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if newest is None or mtime > newest:
            newest = mtime

    def walk(path: Path, depth: int) -> None:
        consider(path)
        if depth >= max_depth:
            return
        try:
            children = [child for child in path.iterdir() if child.is_dir()]
        except OSError:
            return
        for child in children:
            walk(child, depth + 1)

    for root in configured_sfz_roots():
        if root.exists():
            walk(root, 0)
    return newest


def backfill_fingerprint(cue: str, *, library_mtime: float) -> str:
    """Record a baseline for one cue, but ONLY on evidence.

    Returns a short status word. A render older than the library tree gets
    nothing written: we cannot tell what it used, and inventing a record would
    make a stale cue permanently claim to be current — the precise failure this
    module exists to catch.
    """
    from ..cli import find_score, generated_root
    from ..render.generated_layout import resolve_latest_generated_dir
    from ..render.score_core import load_yaml

    score = find_score(cue)
    if score is None:
        return "no-score"
    spec = load_yaml(score)
    run_dir = resolve_latest_generated_dir(generated_root() / cue)
    if not run_dir.is_dir():
        return "no-render"
    if read_fingerprint(run_dir) is not None:
        return "already-recorded"
    try:
        rendered = run_dir.stat().st_mtime
    except OSError:
        return "unreadable"
    if rendered < library_mtime:
        return "predates-libraries"
    write_fingerprint(run_dir, spec)
    return "recorded"


class InstrumentDriftConfig(kwconf.Config):
    """Report cues whose instruments would resolve differently than when rendered."""

    cue: str | None = kwconf.Value(None, help="restrict to named cue(s); comma separated")
    regen: bool = kwconf.Flag(False, help="re-render the cues that would change, then publish")
    include_unrecorded: bool = kwconf.Flag(
        False, help="with --regen, also re-render cues that have no recorded fingerprint"
    )
    json: bool = kwconf.Flag(False, help="emit the report as JSON")
    backfill: bool = kwconf.Flag(
        False,
        help="record a baseline fingerprint for renders that provably postdate the "
             "installed libraries (renders older than the library tree are left alone)",
    )

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


def run(args: InstrumentDriftConfig) -> int:
    from ..cli import radio_cues

    if args.cue:
        cues = tuple(part.strip() for part in str(args.cue).split(",") if part.strip())
    else:
        cues = radio_cues()

    if args.backfill:
        library_mtime = newest_library_mtime()
        if library_mtime is None:
            print("no sample libraries installed; nothing to baseline", file=sys.stderr)
            return 1
        from datetime import datetime

        stamp = datetime.fromtimestamp(library_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"libraries last changed {stamp}; recording renders newer than that")
        tally: dict[str, int] = {}
        for cue in cues:
            status = backfill_fingerprint(cue, library_mtime=library_mtime)
            tally[status] = tally.get(status, 0) + 1
        for status, count in sorted(tally.items()):
            print(f"  {status:20s} {count}")
        print()

    reports = scan(cues)
    drifted = [r for r in reports if r.state == "drifted"]
    unrecorded = [r for r in reports if r.state == "unrecorded"]
    missing = [r for r in reports if r.state == "missing-score"]

    if args.json:
        print(json.dumps(
            [
                {
                    "cue": r.cue,
                    "state": r.state,
                    "note": r.note,
                    "changes": [
                        {"instrument": c.instrument, "before": c.before, "after": c.after}
                        for c in r.changes
                    ],
                }
                for r in reports
            ],
            indent=2,
        ))
    else:
        for r in drifted:
            print(f"DRIFTED  {r.cue}")
            for change in r.changes:
                print(f"           {change.describe()}")
        for r in unrecorded:
            print(f"UNKNOWN  {r.cue}  ({r.note})")
        for r in missing:
            print(f"NO SCORE {r.cue}  ({r.note})")
        print(
            f"\n{len(reports)} cue(s): {len(reports) - len(drifted) - len(unrecorded) - len(missing)} current, "
            f"{len(drifted)} drifted, {len(unrecorded)} unrecorded, {len(missing)} without a score"
        )

    if not args.regen:
        # Exit non-zero on drift so this is usable as a check in a pipeline.
        return 1 if drifted else 0

    targets = [r.cue for r in drifted]
    if args.include_unrecorded:
        targets += [r.cue for r in unrecorded]
    if not targets:
        print("nothing to re-render")
        return 0

    print(f"\nre-rendering {len(targets)} cue(s): {', '.join(targets)}")
    # `render_publish` is built by `_bulk_command`, so it has no importable
    # module-level name; reach it through the modal that owns it.
    from ..cli import RadioModal

    return int(RadioModal.render_publish.main(
        argv=False, cue=",".join(targets), force_render=True
    ))

#!/usr/bin/env python3
"""Build the checked-in Ambition audio-workstation snapshot using stdlib only.

This script intentionally has no renderer/package imports.  It turns the large,
machine-generated /data/audio-tools reports into a compact source-control record
that remote agents can inspect without access to the workstation or its Python
environment.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "ambition.audio_environment_snapshot.v1"
_KEEP_PROGRAM_FIELDS = (
    "relative_path",
    "role",
    "aliases",
    "region_count",
    "key_span",
    "playable_key_ranges",
    "velocity_ranges",
    "startup_cc",
    "suggested_default_controls",
    "recommended_backend",
    "recommended_probe",
    "keyswitches",
    "round_robin_opcodes",
    "triggers",
)


def _relative(value: str, root: Path) -> str:
    path = Path(value)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _portable_value(value: Any, root: Path) -> Any:
    """Rewrite paths under the workstation root as source-portable relative paths."""

    if isinstance(value, dict):
        return {str(key): _portable_value(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_value(item, root) for item in value]
    if isinstance(value, tuple):
        return [_portable_value(item, root) for item in value]
    if isinstance(value, str):
        root_text = root.as_posix().rstrip("/")
        if value == root_text or value.startswith(root_text + "/"):
            return _relative(value, root)
    return value


def _parse_plugin_summary(path: Path, root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"clap": [], "lv2": [], "vst3": []}
    if not path.is_file():
        return result
    current: str | None = None
    for raw in path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        low = line.lower()
        if low == "clap bundles:":
            current = "clap"
            continue
        if low == "lv2 bundles:":
            current = "lv2"
            continue
        if low == "vst3 bundles:":
            current = "vst3"
            continue
        if current and line.startswith("/"):
            result[current].append(_relative(line, root))
    for values in result.values():
        values.sort()
    return result


def _parse_soundfont_summary(path: Path, root: Path) -> list[str]:
    if not path.is_file():
        return []
    values = []
    in_files = False
    for raw in path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if line == "SoundFont files:":
            in_files = True
            continue
        if in_files and line.startswith("/"):
            values.append(_relative(line, root))
        elif in_files and values and not line:
            break
    return sorted(set(values))


def build_snapshot(
    census_path: Path,
    *,
    root: Path,
    plugin_summary: Path,
    soundfont_summary: Path,
) -> dict[str, Any]:
    census = json.loads(census_path.read_text(encoding="utf8"))
    programs = []
    for source in census.get("instruments", []):
        row = {key: source[key] for key in _KEEP_PROGRAM_FIELDS if key in source}
        row = _portable_value(row, root)
        if "relative_path" not in row and source.get("path"):
            row["relative_path"] = _relative(str(source["path"]), root / "sfz")
        missing = source.get("missing_sample_references") or []
        row["missing_sample_reference_count"] = len(missing)
        row["samples_found"] = int(source.get("samples_found", 0) or 0)
        programs.append(row)
    programs.sort(key=lambda row: str(row.get("relative_path", "")))

    alias_hits = {
        str(alias): _relative(str(path), root / "sfz")
        for alias, path in (census.get("alias_hits") or {}).items()
    }

    roots = [_relative(str(path), root) for path in census.get("sfz_roots", [])]
    return {
        "schema": SCHEMA,
        "captured_at": census.get("generated_at"),
        "workstation_root": root.as_posix(),
        "purpose": (
            "Checked-in observation of the maintainer workstation. It records what was "
            "actually present when captured. instrument_catalog.yaml remains the stable "
            "authoring/expected-environment authority."
        ),
        "source_reports": {
            "sfz_usage_census_schema": census.get("schema"),
            "sfz_roots": roots,
            "discovered_sfz_count": int(census.get("discovered_sfz_count", 0) or 0),
            "analyzed_sfz_count": int(census.get("analyzed_sfz_count", 0) or 0),
            "skipped_likely_helpers": int(census.get("skipped_likely_helpers", 0) or 0),
            "errors": list(census.get("errors") or []),
        },
        "stable_alias_resolutions": dict(sorted(alias_hits.items())),
        "soundfonts": _parse_soundfont_summary(soundfont_summary, root),
        "plugins": _parse_plugin_summary(plugin_summary, root),
        "sfz_programs": programs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("AMBITION_AUDIO_TOOLS_ROOT", "/data/audio-tools")))
    parser.add_argument("--census", type=Path)
    parser.add_argument("--plugin-summary", type=Path)
    parser.add_argument("--soundfont-summary", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "ambition_music_renderer/data/audio_environment_snapshot.json")
    args = parser.parse_args()
    root = args.root
    census = args.census or root / "SFZ_USAGE_CENSUS.json"
    plugin_summary = args.plugin_summary or root / "PLUGIN_LIBRARY_SUMMARY.txt"
    soundfont_summary = args.soundfont_summary or root / "SOUNDFONT_SUMMARY.txt"
    snapshot = build_snapshot(census, root=root, plugin_summary=plugin_summary, soundfont_summary=soundfont_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf8")
    print(f"wrote {args.output}")
    print(f"sfz programs: {len(snapshot['sfz_programs'])}")
    print(f"stable aliases: {len(snapshot['stable_alias_resolutions'])}")
    print(f"soundfonts: {len(snapshot['soundfonts'])}")
    print("plugins: " + ", ".join(f"{key}={len(value)}" for key, value in snapshot["plugins"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

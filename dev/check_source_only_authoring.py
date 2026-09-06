#!/usr/bin/env python3
"""Stdlib-only integrity check for the repository-visible authoring registers."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ambition_music_renderer" / "data"

EXPECTED_SCHEMAS = {
    "generator_catalog.json": "ambition.musicir.generator_catalog.v1",
    "processing_catalog.json": "ambition.processing_catalog.v1",
    "technique_catalog.json": "ambition.musicir.technique_catalog.v1",
    "instrument_authoring_index.json": "ambition.instrument_authoring_index.v1",
    "audio_environment_snapshot.json": "ambition.audio_environment_snapshot.v1",
}


def load(name: str) -> dict:
    data = json.loads((DATA / name).read_text(encoding="utf8"))
    expected = EXPECTED_SCHEMAS[name]
    if data.get("schema") != expected:
        raise RuntimeError(f"{name}: expected schema {expected!r}, got {data.get('schema')!r}")
    return data


def main() -> int:
    try:
        generator = load("generator_catalog.json")
        processing = load("processing_catalog.json")
        technique = load("technique_catalog.json")
        instruments = load("instrument_authoring_index.json")
        snapshot = load("audio_environment_snapshot.json")

        generators = generator.get("generators") or {}
        processors = processing.get("processors") or {}
        techniques = technique.get("techniques") or {}
        instrument_rows = instruments.get("instruments") or {}
        families = instruments.get("family_profiles") or {}
        if int(instruments.get("instrument_count", -1)) != len(instrument_rows):
            raise RuntimeError("instrument_authoring_index instrument_count does not match instruments")
        for ref, row in instrument_rows.items():
            family = row.get("family")
            if family and family not in families:
                raise RuntimeError(f"{ref}: family {family!r} lacks a family profile")
        for name, row in generators.items():
            if not row.get("summary") or not row.get("example"):
                raise RuntimeError(f"generator {name!r} lacks source-only summary/example")
            if not row.get("bridge_kind"):
                raise RuntimeError(f"generator {name!r} lacks bridge implementation identity")
            if (row.get("capabilities") or {}).get("implementation") != "established_v1_bridge":
                raise RuntimeError(f"generator {name!r} lacks established bridge capability metadata")
        for name, row in processors.items():
            if not row.get("summary"):
                raise RuntimeError(f"processor {name!r} lacks source-only summary")
        for name, row in techniques.items():
            if row.get("default_gate") is None:
                raise RuntimeError(f"technique {name!r} lacks default_gate")

        aliases = snapshot.get("stable_alias_resolutions") or {}
        unresolved_expected = [
            ref for ref, row in instrument_rows.items()
            if row.get("expected") and ref not in aliases
        ]
        # An observed workstation snapshot may legitimately miss a normative
        # expected instrument. Report it rather than making the source-only
        # knowledge layer impossible to inspect on a partially installed host.
        print(
            "source-only authoring registers OK: "
            f"{len(instrument_rows)} instruments, {len(generators)} generators, "
            f"{len(processors)} processors, {len(techniques)} techniques, "
            f"{len(snapshot.get('sfz_programs') or [])} observed SFZ programs"
        )
        if unresolved_expected:
            print(
                "observational snapshot lacks normative expected aliases: "
                + ", ".join(sorted(unresolved_expected)),
                file=sys.stderr,
            )
        return 0
    except Exception as ex:
        print(f"source-only authoring register check failed: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

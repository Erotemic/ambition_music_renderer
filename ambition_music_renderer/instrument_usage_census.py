"""Static census of how installed SFZ programs are meant to be triggered.

The existing library inventory answers *what files exist*.  This module answers
*how a program can produce sound*: playable key/velocity zones, controller gates,
startup controllers, keyswitches, crossfade/modulation controllers, samples, and
compact known-working controller presets.

The census is intentionally static.  It never renders audio and therefore can be
run once after installing/updating sample libraries, checked into no repository,
and attached to a remote-agent handoff as machine-local ground truth.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

from .audit.sfz_measurement import sfz_regions, sfz_startup_cc
from .instrument_catalog import instrument_catalog
from .instrument_libraries import configured_sfz_roots, discover_sfz_files, resolve_sfz_reference


SCHEMA = "ambition.sfz_usage_census.v1"
DEFAULT_JSON_NAME = "SFZ_USAGE_CENSUS.json"
DEFAULT_MARKDOWN_NAME = "SFZ_USAGE_CENSUS.md"

_GATE_RE = re.compile(r"^(lo|hi)cc(\d+)$")
_XFADE_RE = re.compile(r"^(xfin|xfout)_(lo|hi)cc(\d+)$")
_ONCC_RE = re.compile(r"^(.+)_oncc(\d+)$")
_CC_SUFFIX_RE = re.compile(r"^(.+)_cc(\d+)$")
_HELPER_PART_RE = re.compile(r"^(?:_?modules?|_?includes?|maps?(?:[_-].*)?|libs?|src|scripts?)$", re.I)


def _bound(region: Mapping[str, Any], low: str, high: str, default_low: int, default_high: int) -> tuple[int, int]:
    key = region.get("key") if low == "lokey" else None
    lo = region.get(low, key if key is not None else default_low)
    hi = region.get(high, key if key is not None else default_high)
    try:
        return max(0, int(lo)), min(127, int(hi))
    except (TypeError, ValueError):
        return default_low, default_high


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[list[int]]:
    pairs = sorted((max(0, int(lo)), min(127, int(hi))) for lo, hi in ranges if int(lo) <= int(hi))
    merged: list[list[int]] = []
    for lo, hi in pairs:
        if not merged or lo > merged[-1][1] + 1:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return merged


def _gate_ranges(region: Mapping[str, Any]) -> dict[int, tuple[int, int]]:
    out: dict[int, list[int]] = {}
    for key, value in region.items():
        match = _GATE_RE.fullmatch(str(key))
        if match is None or not isinstance(value, (int, float)):
            continue
        cc = int(match.group(2))
        pair = out.setdefault(cc, [0, 127])
        pair[0 if match.group(1) == "lo" else 1] = int(value)
    return {cc: (max(0, lo), min(127, hi)) for cc, (lo, hi) in out.items()}


def _midpoint(lo: int, hi: int) -> int:
    return max(0, min(127, int(round((int(lo) + int(hi)) / 2.0))))


def _relative_path(path: Path, roots: Sequence[Path]) -> str:
    path = path.resolve()
    candidates: list[Path] = []
    for root in roots:
        try:
            candidates.append(path.relative_to(root.resolve()))
        except (OSError, ValueError):
            pass
    if candidates:
        return str(min(candidates, key=lambda p: len(p.parts)))
    return str(path)


def _role_for_path(path: Path, roots: Sequence[Path], aliases: Sequence[str]) -> tuple[str, list[str]]:
    rel = Path(_relative_path(path, roots))
    reasons: list[str] = []
    if aliases:
        reasons.append("target of registered alias")
        return "alias_target", reasons
    parts = list(rel.parts)
    lower_parts = [part.lower() for part in parts[:-1]]
    helper_parts = [part for part in parts[:-1] if _HELPER_PART_RE.match(part)]
    name = path.stem.lower()
    if helper_parts or any(token in name for token in ("include", "module", "mapping", "map_", "_map", "defs")):
        if helper_parts:
            reasons.append("helper-like directory: " + "/".join(helper_parts))
        else:
            reasons.append("helper-like filename")
        return "likely_helper", reasons
    if any(part in {"programs", "program", "instruments", "instrument", "user", "patches", "presets"} for part in lower_parts):
        reasons.append("human-facing program/preset directory")
        return "likely_entrypoint", reasons
    if len(parts) <= 5:
        reasons.append("shallow library path")
        return "likely_entrypoint", reasons
    return "unknown", reasons


def _controller_usage(regions: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    gate_ranges: dict[int, list[tuple[int, int]]] = defaultdict(list)
    gate_region_count: Counter[int] = Counter()
    modulation_values: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    crossfade_values: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    total = max(1, len(regions))

    for region in regions:
        gates = _gate_ranges(region)
        for cc, rng in gates.items():
            gate_ranges[cc].append(rng)
            gate_region_count[cc] += 1
        for key, value in region.items():
            key_s = str(key)
            match = _XFADE_RE.fullmatch(key_s)
            if match:
                if isinstance(value, (int, float)):
                    crossfade_values[int(match.group(3))][key_s].append(int(value))
                continue
            match = _ONCC_RE.fullmatch(key_s)
            if match:
                if isinstance(value, (int, float)):
                    modulation_values[int(match.group(2))][match.group(1)].append(float(value))
                else:
                    modulation_values[int(match.group(2))].setdefault(match.group(1), [])
                continue
            match = _CC_SUFFIX_RE.fullmatch(key_s)
            if match and not key_s.startswith(("locc", "hicc", "xfin_", "xfout_")):
                if isinstance(value, (int, float)):
                    modulation_values[int(match.group(2))][match.group(1)].append(float(value))
                else:
                    modulation_values[int(match.group(2))].setdefault(match.group(1), [])

    gates = []
    for cc in sorted(gate_ranges):
        merged = _merge_ranges(gate_ranges[cc])
        gates.append({
            "cc": cc,
            "allowed_ranges": merged,
            "constrained_regions": int(gate_region_count[cc]),
            "all_regions_constrained": int(gate_region_count[cc]) == len(regions),
            "coverage_fraction": round(float(gate_region_count[cc]) / total, 6),
        })
    mod_rows = []
    for cc, opcodes in sorted(modulation_values.items()):
        details = {}
        for opcode, values in sorted(opcodes.items()):
            details[opcode] = {
                "amount_min": min(values) if values else None,
                "amount_max": max(values) if values else None,
            }
        mod_rows.append({"cc": cc, "opcodes": sorted(opcodes), "details": details})
    xfade_rows = []
    for cc, opcodes in sorted(crossfade_values.items()):
        xfade_rows.append({
            "cc": cc,
            "opcodes": sorted(opcodes),
            "breakpoints": {opcode: sorted(set(values)) for opcode, values in sorted(opcodes.items())},
        })
    return gates, mod_rows, xfade_rows


def _activation_zones(regions: Sequence[Mapping[str, Any]], *, limit: int = 256) -> list[dict[str, Any]]:
    counts: Counter[tuple[Any, ...]] = Counter()
    for region in regions:
        klo, khi = _bound(region, "lokey", "hikey", 0, 127)
        vlo, vhi = _bound(region, "lovel", "hivel", 1, 127)
        gates = tuple(sorted((cc, lo, hi) for cc, (lo, hi) in _gate_ranges(region).items()))
        counts[(klo, khi, vlo, vhi, gates)] += 1
    rows = []
    for (klo, khi, vlo, vhi, gates), count in counts.most_common(limit):
        rows.append({
            "key_range": [klo, khi],
            "velocity_range": [vlo, vhi],
            "controllers": {str(cc): [lo, hi] for cc, lo, hi in gates},
            "region_count": int(count),
        })
    return rows


def _control_presets(regions: Sequence[Mapping[str, Any]], *, limit: int = 24) -> list[dict[str, Any]]:
    signatures: Counter[tuple[tuple[int, int, int], ...]] = Counter()
    for region in regions:
        sig = tuple(sorted((cc, lo, hi) for cc, (lo, hi) in _gate_ranges(region).items()))
        if sig:
            signatures[sig] += 1
    rows = []
    for sig, count in signatures.most_common(limit):
        rows.append({
            "controls": {str(cc): _midpoint(lo, hi) for cc, lo, hi in sig},
            "ranges": {str(cc): [lo, hi] for cc, lo, hi in sig},
            "region_count": int(count),
        })
    return rows


def _suggested_default_controls(regions: Sequence[Mapping[str, Any]], startup_cc: Mapping[int, int]) -> dict[str, int]:
    if not regions:
        return {}
    by_cc: dict[int, Counter[tuple[int, int]]] = defaultdict(Counter)
    constrained_count: Counter[int] = Counter()
    for region in regions:
        for cc, rng in _gate_ranges(region).items():
            by_cc[cc][rng] += 1
            constrained_count[cc] += 1
    out: dict[str, int] = {}
    for cc, zones in sorted(by_cc.items()):
        if constrained_count[cc] != len(regions):
            continue
        current = int(startup_cc.get(cc, 0))
        if any(lo <= current <= hi for lo, hi in zones):
            continue
        (lo, hi), _count = zones.most_common(1)[0]
        out[str(cc)] = _midpoint(lo, hi)
    return out


def _keyswitch_info(regions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, set[int]] = defaultdict(set)
    ranges: set[tuple[int, int]] = set()
    for region in regions:
        for opcode in ("sw_last", "sw_default", "sw_up", "sw_down", "sw_previous"):
            value = region.get(opcode)
            if isinstance(value, (int, float)):
                values[opcode].add(int(value))
        lo = region.get("sw_lokey")
        hi = region.get("sw_hikey")
        if isinstance(lo, (int, float)) or isinstance(hi, (int, float)):
            lo_i = int(lo if isinstance(lo, (int, float)) else hi)
            hi_i = int(hi if isinstance(hi, (int, float)) else lo)
            ranges.add((lo_i, hi_i))
    return {
        "ranges": [list(pair) for pair in sorted(ranges)],
        "states": {key: sorted(vals) for key, vals in sorted(values.items()) if vals},
    }


def analyze_sfz_usage(
    path: str | Path,
    *,
    roots: Sequence[Path] | None = None,
    aliases: Sequence[str] = (),
    activation_zone_limit: int = 256,
) -> dict[str, Any]:
    """Return static trigger/parameter metadata for one SFZ program."""
    path = Path(path).resolve()
    roots = tuple(roots or configured_sfz_roots())
    regions = sfz_regions(path)
    startup = sfz_startup_cc(path)
    key_ranges = [_bound(region, "lokey", "hikey", 0, 127) for region in regions]
    vel_ranges = sorted(set(_bound(region, "lovel", "hivel", 1, 127) for region in regions))
    gate_rows, modulation_rows, crossfade_rows = _controller_usage(regions)
    samples = {str(region.get("sample")) for region in regions if region.get("sample")}
    sample_paths = {str(region.get("sample_path")) for region in regions if region.get("sample_path")}
    missing_samples = sorted({
        str(region.get("sample")) for region in regions
        if region.get("sample") and not region.get("sample_path")
    })
    role, role_reasons = _role_for_path(path, roots, aliases)
    rr_modes = sorted({
        key
        for region in regions
        for key in ("lorand", "hirand", "seq_length", "seq_position")
        if key in region
    })
    triggers = sorted({str(region.get("trigger")) for region in regions if region.get("trigger")})
    suggested = _suggested_default_controls(regions, startup)
    presets = _control_presets(regions)
    stat = path.stat()
    rel = _relative_path(path, roots)
    merged_keys = _merge_ranges(key_ranges)
    if merged_keys:
        widest_key = max(merged_keys, key=lambda pair: pair[1] - pair[0])
        probe_midi = _midpoint(widest_key[0], widest_key[1])
    else:
        probe_midi = 60
    if vel_ranges:
        widest_vel = max(vel_ranges, key=lambda pair: pair[1] - pair[0])
        probe_velocity = _midpoint(widest_vel[0], widest_vel[1])
    else:
        probe_velocity = 100
    effective_probe_controls = {str(cc): int(value) for cc, value in sorted(startup.items())}
    effective_probe_controls.update(suggested)
    recommended_backend = ({"kind": "sfz", "library_ref": aliases[0]} if aliases else {"kind": "sfz", "sfz": str(path)})
    return {
        "path": str(path),
        "relative_path": rel,
        "mtime_ns": int(stat.st_mtime_ns),
        "size_bytes": int(stat.st_size),
        "role": role,
        "role_reasons": role_reasons,
        "aliases": sorted(set(str(a) for a in aliases)),
        "region_count": len(regions),
        "key_span": [min(lo for lo, _ in key_ranges), max(hi for _, hi in key_ranges)] if key_ranges else None,
        "playable_key_ranges": merged_keys,
        "velocity_ranges": [list(pair) for pair in vel_ranges],
        "startup_cc": {str(cc): int(value) for cc, value in sorted(startup.items())},
        "suggested_default_controls": suggested,
        "recommended_backend": recommended_backend,
        "recommended_probe": {
            "midi": probe_midi,
            "velocity": probe_velocity,
            "controls": effective_probe_controls,
        },
        "controller_gates": gate_rows,
        "control_presets": presets,
        "modulation_controllers": modulation_rows,
        "crossfade_controllers": crossfade_rows,
        "keyswitches": _keyswitch_info(regions),
        "round_robin_opcodes": rr_modes,
        "triggers": triggers,
        "sample_references": len(samples),
        "samples_found": len(sample_paths),
        "missing_sample_references": missing_samples[:100],
        "activation_zones": _activation_zones(regions, limit=activation_zone_limit),
    }


def _alias_reverse_map(roots: Sequence[Path]) -> dict[Path, list[str]]:
    reverse: dict[Path, list[str]] = defaultdict(list)
    for alias in sorted(instrument_catalog()):
        resolved = resolve_sfz_reference(library_ref=alias, roots=roots)
        if resolved is not None:
            reverse[resolved.resolve()].append(alias)
    return reverse


def build_usage_census(
    *,
    roots: Sequence[str | Path] | None = None,
    include_helpers: bool = False,
    jobs: int = 0,
    progress: bool = False,
) -> dict[str, Any]:
    resolved_roots = tuple(Path(root).expanduser().resolve() for root in configured_sfz_roots(roots))
    paths = [path.resolve() for path in discover_sfz_files(resolved_roots)]
    aliases = _alias_reverse_map(resolved_roots)

    selected: list[Path] = []
    skipped_helpers = 0
    for path in paths:
        role, _reasons = _role_for_path(path, resolved_roots, aliases.get(path, ()))
        if not include_helpers and role == "likely_helper":
            skipped_helpers += 1
            continue
        selected.append(path)

    max_workers = int(jobs or min(8, max(1, (os.cpu_count() or 2))))
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    def analyze(path: Path) -> dict[str, Any]:
        return analyze_sfz_usage(path, roots=resolved_roots, aliases=aliases.get(path, ()))

    if max_workers <= 1:
        for index, path in enumerate(selected, 1):
            try:
                rows.append(analyze(path))
            except Exception as exc:  # census should continue past one malformed third-party patch
                errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            if progress and (index == 1 or index % 25 == 0 or index == len(selected)):
                print(f"[instrument-census] {index}/{len(selected)} {path.name}", file=sys.stderr)
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sfz-census") as executor:
            pending = {executor.submit(analyze, path): path for path in selected}
            for index, future in enumerate(as_completed(pending), 1):
                path = pending[future]
                try:
                    rows.append(future.result())
                except Exception as exc:
                    errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
                if progress and (index == 1 or index % 25 == 0 or index == len(selected)):
                    print(f"[instrument-census] {index}/{len(selected)} {path.name}", file=sys.stderr)

    rows.sort(key=lambda row: str(row.get("relative_path", "")).lower())
    alias_hits = {
        name: str(path)
        for path, names in sorted(aliases.items(), key=lambda item: str(item[0]).lower())
        for name in names
    }
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sfz_roots": [str(root) for root in resolved_roots],
        "discovered_sfz_count": len(paths),
        "analyzed_sfz_count": len(rows),
        "skipped_likely_helpers": skipped_helpers,
        "include_helpers": bool(include_helpers),
        "alias_hits": dict(sorted(alias_hits.items())),
        "errors": errors,
        "instruments": rows,
    }


def write_usage_census(report: Mapping[str, Any], output: Path, markdown: Path | None = None) -> tuple[Path, Path | None]:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf8")
    md_path = None
    if markdown is not None:
        md_path = Path(markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(format_usage_census_markdown(report), encoding="utf8")
    return output, md_path


def _fmt_ranges(ranges: Sequence[Sequence[int]]) -> str:
    return ", ".join(f"{lo}-{hi}" if lo != hi else str(lo) for lo, hi in ranges) or "-"


def format_usage_census_markdown(report: Mapping[str, Any]) -> str:
    rows = list(report.get("instruments") or [])
    lines = [
        "# SFZ usage census",
        "",
        f"Generated: {report.get('generated_at', 'unknown')}",
        "",
        f"Analyzed {len(rows)} SFZ programs from {report.get('discovered_sfz_count', len(rows))} discovered files.",
        "This report is static machine-local metadata: it describes how installed SFZ programs can be triggered; it does not prove audio quality.",
        "",
        "## Registered aliases",
        "",
    ]
    alias_hits = report.get("alias_hits") or {}
    if alias_hits:
        for name, path in sorted(alias_hits.items()):
            row = next((r for r in rows if r.get("path") == path), None)
            controls = (row or {}).get("suggested_default_controls") or {}
            control_text = ", ".join(f"CC{k}={v}" for k, v in controls.items()) or "none"
            key_span = (row or {}).get("key_span")
            lines.append(f"- `{name}` -> `{path}`; key span `{key_span}`; suggested controls `{control_text}`")
    else:
        lines.append("- No registered aliases resolved.")

    lines.extend(["", "## Programs", ""])
    for row in rows:
        if row.get("role") == "likely_helper":
            continue
        lines.append(f"### {row.get('relative_path')}")
        lines.append("")
        lines.append(f"- Path: `{row.get('path')}`")
        lines.append(f"- Role: `{row.get('role')}`")
        if row.get("aliases"):
            lines.append("- Aliases: " + ", ".join(f"`{a}`" for a in row["aliases"]))
        lines.append(f"- Regions: {row.get('region_count', 0)}; playable keys: `{_fmt_ranges(row.get('playable_key_ranges') or [])}`")
        lines.append(f"- Velocity zones: `{_fmt_ranges(row.get('velocity_ranges') or [])}`")
        startup = row.get("startup_cc") or {}
        suggested = row.get("suggested_default_controls") or {}
        if startup:
            lines.append("- SFZ startup controls: " + ", ".join(f"`CC{k}={v}`" for k, v in startup.items()))
        if suggested:
            lines.append("- Suggested controls needed to reach a globally gated region: " + ", ".join(f"`CC{k}={v}`" for k, v in suggested.items()))
        gates = row.get("controller_gates") or []
        if gates:
            text = []
            for gate in gates:
                ranges = _fmt_ranges(gate.get("allowed_ranges") or [])
                scope = "all regions" if gate.get("all_regions_constrained") else f"{gate.get('constrained_regions')} regions"
                text.append(f"CC{gate.get('cc')} {ranges} ({scope})")
            lines.append("- Controller gates: " + "; ".join(text))
        switches = row.get("keyswitches") or {}
        if switches.get("ranges") or switches.get("states"):
            lines.append(f"- Keyswitches: `{json.dumps(switches, sort_keys=True)}`")
        mod = row.get("modulation_controllers") or []
        xfade = row.get("crossfade_controllers") or []
        if mod:
            lines.append("- Modulation CCs: " + "; ".join(f"CC{x['cc']} -> {', '.join(x['opcodes'])}" for x in mod))
        if xfade:
            lines.append("- Crossfade CCs: " + "; ".join(f"CC{x['cc']} -> {', '.join(x['opcodes'])}" for x in xfade))
        if row.get("missing_sample_references"):
            lines.append(f"- WARNING: {len(row['missing_sample_references'])} missing sample references (report is capped at 100 paths).")
        lines.append("")
    if report.get("errors"):
        lines.extend(["## Parse errors", ""])
        for error in report["errors"]:
            lines.append(f"- `{error.get('path')}`: {error.get('error')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def default_census_paths() -> tuple[Path, Path]:
    root = Path(os.environ.get("AMBITION_AUDIO_TOOLS_ROOT", "/data/audio-tools")).expanduser()
    return root / DEFAULT_JSON_NAME, root / DEFAULT_MARKDOWN_NAME


def load_usage_census(path: str | Path | None = None) -> dict[str, Any] | None:
    json_path = Path(path) if path is not None else default_census_paths()[0]
    if not json_path.is_file():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    return data


def census_by_resolved_path(report: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not report:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in report.get("instruments") or []:
        if isinstance(row, dict) and row.get("path"):
            try:
                key = str(Path(row["path"]).resolve())
            except OSError:
                key = str(row["path"])
            out[key] = row
    return out


def census_row_is_fresh(row: Mapping[str, Any], path: str | Path) -> bool:
    try:
        stat = Path(path).stat()
    except OSError:
        return False
    try:
        return int(row.get("mtime_ns", -1)) == int(stat.st_mtime_ns) and int(row.get("size_bytes", -1)) == int(stat.st_size)
    except (TypeError, ValueError):
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate machine-local SFZ usage/parameter census for remote agents and Instrument Inspector")
    parser.add_argument("--root", action="append", default=[], help="override SFZ search root (repeatable)")
    parser.add_argument("--output", type=Path, help=f"JSON output (default: $AMBITION_AUDIO_TOOLS_ROOT/{DEFAULT_JSON_NAME})")
    parser.add_argument("--markdown", type=Path, help=f"Markdown output (default: sibling {DEFAULT_MARKDOWN_NAME}; use --no-markdown to disable)")
    parser.add_argument("--no-markdown", action="store_true", help="do not write the human-readable Markdown companion")
    parser.add_argument("--all", action="store_true", help="deep-analyze helper/module SFZ files too; default skips obvious implementation helpers")
    parser.add_argument("--jobs", type=int, default=0, help="parallel parser workers; 0 chooses a small machine-dependent default")
    parser.add_argument("--quiet", action="store_true", help="suppress progress")
    parser.add_argument("--strict", action="store_true", help="return nonzero if any third-party SFZ could not be analyzed")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    default_json, default_md = default_census_paths()
    output = Path(args.output or default_json)
    markdown = None if args.no_markdown else Path(args.markdown or (output.with_suffix(".md") if args.output else default_md))
    roots = [Path(item) for item in args.root] or None
    report = build_usage_census(
        roots=roots,
        include_helpers=bool(args.all),
        jobs=int(args.jobs),
        progress=not bool(args.quiet),
    )
    json_path, md_path = write_usage_census(report, output, markdown)
    print(f"usage census: {json_path}")
    if md_path is not None:
        print(f"human summary: {md_path}")
    print(
        f"analyzed {report['analyzed_sfz_count']}/{report['discovered_sfz_count']} SFZ files; "
        f"skipped helpers={report['skipped_likely_helpers']}; errors={len(report['errors'])}"
    )
    return 1 if args.strict and report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

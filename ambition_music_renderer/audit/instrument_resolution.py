"""Instrument resolution provenance — exactly what each instrument resolved to.

Authoring asks for an instrument by a *role* (``library_ref: bass.growly``, a GM
``program``, a ``prefer`` list).  The renderer then does a lot of implicit work:
fuzzy-matches the alias to a concrete ``.sfz`` file, picks a program, octave-folds
notes that fall outside the sampled range, or falls back to GM when an SFZ is
silent.  That "we asked for X but got Y" magic was invisible.

This audit records it, statically (no audio render): for every instrument it
reports what was requested, what it resolved to on disk, the playable key range,
how many of the part's notes fall outside that range (and would be octave-folded),
and whether it is at risk of silence.  Runs by default in every bundle.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def audit_spec(spec: dict[str, Any]) -> dict[str, Any]:
    from ..instrument_libraries import resolve_sfz_reference
    from ..backends.sfizz_backend import sfz_key_span
    from ..render.score_layers import build_score

    render_cfg = spec.get("render") or {}
    sfizz_cfg = render_cfg.get("sfizz") or {}
    roots = list(sfizz_cfg.get("library_roots") or [])
    default_soundfont = render_cfg.get("soundfont")

    # per-instrument note pitches (to predict folding / silence)
    pitches: dict[str, list[int]] = {}
    try:
        pm, _groups, _meta = build_score(spec)
        for ev in getattr(pm, "_ambition_note_events", []) or []:
            pitches.setdefault(str(ev.get("instrument")), []).append(int(ev["pitch"]))
    except Exception:
        pass
    note_lo = {k: min(v) for k, v in pitches.items() if v}
    note_hi = {k: max(v) for k, v in pitches.items() if v}
    note_n = {k: len(v) for k, v in pitches.items()}

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for inst in spec.get("instruments", []):
        name = str(inst.get("name"))
        is_drum = bool(inst.get("is_drum"))
        be = inst.get("instrument_backend") if isinstance(inst.get("instrument_backend"), dict) else {}
        kind = str(be.get("kind", "")).lower()
        row: dict[str, Any] = {
            "instrument": name,
            "group": inst.get("group", name),
            "program": inst.get("program"),
            "note_count": note_n.get(name, 0),
            "part_low": note_lo.get(name),
            "part_high": note_hi.get(name),
        }
        if kind in ("sfz", "sfizz", "sample", "sampled"):
            requested = be.get("library_ref") or be.get("sfz") or be.get("library")
            prefer = [str(x) for x in (be.get("prefer") or [])]
            resolved = resolve_sfz_reference(
                be.get("sfz") or be.get("path"),
                library_ref=be.get("library_ref") or be.get("library"),
                prefer=prefer, roots=roots,
            )
            span = sfz_key_span(str(resolved)) if resolved else None
            oob = 0
            if span and pitches.get(name):
                lo, hi = span
                oob = sum(1 for p in pitches[name] if p < lo or p > hi)
            row.update({
                "backend": "sfz",
                "requested": requested,
                "prefer": prefer or None,
                "resolved": str(resolved) if resolved else None,
                "resolved_name": Path(resolved).name if resolved else None,
                "fallback_backend": be.get("fallback_backend", sfizz_cfg.get("fallback_backend")),
                "key_span": list(span) if span else None,
                "notes_out_of_range": oob,
            })
            if resolved is None:
                row["status"] = "UNRESOLVED → will fall back to GM"
                warnings.append(f"{name!r}: SFZ {requested!r} did not resolve to any file; "
                                f"will fall back to GM.")
            elif oob and is_drum:
                # drum maps key→sound; out-of-range keys are NOT folded — they are
                # simply unmapped (that drum piece is silent).
                row["status"] = f"resolved; {oob}/{note_n.get(name,0)} drum hits UNMAPPED (silent)"
                warnings.append(
                    f"{name!r} (drum kit): requested {requested!r} → {Path(str(resolved)).name} maps "
                    f"keys {span[0]}..{span[1]}, but {oob}/{note_n.get(name,0)} hits use keys outside "
                    f"that ({note_lo[name]}..{note_hi[name]}) — those pieces are SILENT (no remap).")
            elif oob:
                row["status"] = f"resolved; {oob}/{note_n.get(name,0)} notes octave-folded into range"
                warnings.append(
                    f"{name!r}: requested {requested!r} → {Path(str(resolved)).name}; "
                    f"{oob}/{note_n.get(name,0)} notes ({note_lo[name]}..{note_hi[name]}) fall outside "
                    f"the sampled range {span[0]}..{span[1]} and are octave-folded.")
            else:
                row["status"] = "resolved"
        else:
            row.update({
                "backend": "soundfont",
                "requested": f"GM program {inst.get('program')}",
                "resolved": default_soundfont,
                "resolved_name": Path(default_soundfont).name if default_soundfont else "renderer default GM",
                "status": "GM soundfont" if default_soundfont else "GM (renderer default soundfont)",
            })
        rows.append(row)

    return {
        "schema": "ambition.music_instrument_resolution.v1",
        "id": spec.get("id"),
        "default_soundfont": default_soundfont,
        "sfizz_library_roots": roots,
        "instruments": rows,
        "warnings": warnings,
    }


def audit_file(path: Path) -> dict[str, Any]:
    from ..render.score_core import load_yaml
    return audit_spec(load_yaml(path))


def _summary(payload: dict[str, Any]) -> str:
    lines = [f"cue: {payload.get('id')}",
             f"default soundfont: {payload.get('default_soundfont')}",
             "what each instrument actually resolved to:", ""]
    for r in payload["instruments"]:
        if r["backend"] == "sfz":
            lines.append(
                f"  {r['instrument']:<20} [{r['group']}]  requested {r.get('requested')!r}"
                f" → {r.get('resolved_name') or 'UNRESOLVED'}"
                f"  span {r.get('key_span')}  part {r.get('part_low')}..{r.get('part_high')}"
                f"  · {r['status']}")
        else:
            lines.append(
                f"  {r['instrument']:<20} [{r['group']}]  GM program {r.get('program')}"
                f" → {r.get('resolved_name')}  · {r['status']}")
    lines.append("")
    lines.append(f"warnings ({len(payload['warnings'])}):")
    lines.extend(f"  - {w}" for w in payload["warnings"])
    return "\n".join(lines) + "\n"


def write_reports(payload: dict[str, Any], reports_dir: Path) -> dict[str, str]:
    import json
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    (reports_dir / "instrument_resolution.json").write_text(json.dumps(payload, indent=2))
    paths["json"] = str(reports_dir / "instrument_resolution.json")
    (reports_dir / "instrument_resolution_summary.txt").write_text(_summary(payload))
    paths["summary"] = str(reports_dir / "instrument_resolution_summary.txt")
    md = [f"# Instrument resolution — {payload.get('id')}", "",
          f"Default soundfont: `{payload.get('default_soundfont')}`", "",
          "| instrument | group | requested | resolved | range | part | status |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in payload["instruments"]:
        req = r.get("requested")
        md.append(f"| {r['instrument']} | {r['group']} | `{req}` | "
                  f"`{r.get('resolved_name') or '—'}` | {r.get('key_span') or '—'} | "
                  f"{r.get('part_low')}..{r.get('part_high')} | {r['status']} |")
    (reports_dir / "instrument_resolution.md").write_text("\n".join(md))
    paths["markdown"] = str(reports_dir / "instrument_resolution.md")
    return paths

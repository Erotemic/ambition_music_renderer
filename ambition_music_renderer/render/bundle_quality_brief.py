"""Concise DAW-style quality brief for rendered music bundles.

The full audit suite produces many focused reports.  This module condenses the
most actionable signals into one small text/JSON pair that is easy to paste into
an LLM follow-up or read in a terminal after a fast render.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _tail_lines(path: Path, *, max_lines: int = 80) -> list[str]:
    try:
        lines = path.read_text(encoding="utf8", errors="replace").splitlines()
    except Exception:
        return []
    return lines[-max_lines:]


def _stem_rows(diag: dict[str, Any]) -> list[dict[str, Any]]:
    stems = ((diag.get("diagnostics") or {}).get("native_stems") or {})
    rows: list[dict[str, Any]] = []
    if not isinstance(stems, dict):
        return rows
    for name, item in stems.items():
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                {
                    "stem": str(name),
                    "rms_dbfs": float(item.get("rms_dbfs", -120.0)),
                    "peak_dbfs": float(item.get("peak_dbfs", -120.0)),
                }
            )
        except Exception:
            continue
    rows.sort(key=lambda r: r["rms_dbfs"], reverse=True)
    return rows


def _collect_fallback_lines(reports_dir: Path) -> list[str]:
    lines: list[str] = []
    for name in ("render_isolated.stderr.txt", "render_group_worker.stderr.txt"):
        for line in _tail_lines(reports_dir / name, max_lines=160):
            lower = line.lower()
            if any(token in lower for token in ("fallback", "skipped optional", "requested sfz", "rendering failed")):
                lines.append(line.strip())
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out[:20]



def _top_sources(rows: list[dict[str, Any]], *, limit: int = 6) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or row.get("stem") or "unknown")
        try:
            score = float(row.get("score", 0.0))
        except Exception:
            score = 0.0
        scores[source] = max(scores.get(source, 0.0), score)
        counts[source] = counts.get(source, 0) + 1
    return [
        {"source": source, "candidate_count": counts[source], "max_score": scores[source]}
        for source in sorted(scores, key=lambda k: (scores[k], counts[k]), reverse=True)[:limit]
    ]


def _lead_vs_backing_actions(stem_rows: list[dict[str, Any]]) -> list[str]:
    by_name = {row["stem"]: row for row in stem_rows}
    out: list[str] = []
    lead = by_name.get("lead_guitars")
    rhythm = by_name.get("rhythm_guitars")
    rhythm_bed = by_name.get("rhythm_bed_guitars")
    if lead and rhythm:
        diff = float(lead["rms_dbfs"]) - float(rhythm["rms_dbfs"])
        if diff < -5.0:
            out.append(f"lead_guitars sit {abs(diff):.1f} dB below rhythm_guitars; lift lead or carve backing during solos")
        elif diff > 5.0:
            out.append(f"lead_guitars sit {diff:.1f} dB above rhythm_guitars; verify solo does not detach from band")
    if lead and rhythm_bed:
        diff = float(lead["rms_dbfs"]) - float(rhythm_bed["rms_dbfs"])
        if diff < -3.0:
            out.append(f"lead_guitars sit {abs(diff):.1f} dB below rhythm_bed_guitars; check solo focus")
    return out

def write_quality_brief(
    reports_dir: Path,
    *,
    cue_id: str,
    render_hash: str,
    all_audits: bool,
    spectrograms: bool,
) -> tuple[Path, list[str]]:
    """Write a concise production-quality brief and return warnings.

    The brief is intentionally heuristic.  It avoids failing a render while
    surfacing the issues that usually guide the next score/effects pass: stem
    imbalance, obvious fallback paths, section energy cliffs, and high-band
    dominance when full audits are available.
    """

    reports_dir.mkdir(parents=True, exist_ok=True)
    mix = _read_json(reports_dir / "mix_diagnostics.json")
    spectral = _read_json(reports_dir / "spectral_fingerprint.json")
    adaptive = _read_json(reports_dir / "adaptive_composition_mastering.json")
    shrill = _read_json(reports_dir / "audio_shrillness_candidates.json")

    stem_rows = _stem_rows(mix)
    action_items: list[str] = []
    warnings: list[str] = []

    if stem_rows:
        action_items.extend(_lead_vs_backing_actions(stem_rows))
        loudest = stem_rows[0]
        quiet = [r for r in stem_rows if loudest["rms_dbfs"] - r["rms_dbfs"] > 24.0]
        if quiet:
            stems = ", ".join(r["stem"] for r in quiet[:6])
            msg = f"stems more than 24 dB below {loudest['stem']}: {stems}"
            action_items.append(msg)
            warnings.append(msg)
        for r in stem_rows[:2]:
            if r["peak_dbfs"] > -8.0 and r["rms_dbfs"] - loudest["rms_dbfs"] > -4.0:
                action_items.append(f"{r['stem']} is a dominant stem; verify it still leaves room for arrangement support")

    fallback_lines = _collect_fallback_lines(reports_dir)
    if fallback_lines:
        msg = f"{len(fallback_lines)} backend fallback/optional-skip messages found"
        action_items.append(msg)
        warnings.append(msg)

    # Full-audit cues may include section RMS rows and high-band dominance.
    rows = adaptive.get("rows") or adaptive.get("sections") or []
    if isinstance(rows, list) and rows:
        prev: dict[str, Any] | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if prev is not None:
                try:
                    diff = float(row.get("rms_dbfs")) - float(prev.get("rms_dbfs"))
                except Exception:
                    diff = 0.0
                if abs(diff) >= 6.0:
                    msg = f"section energy jump {prev.get('section') or prev.get('id')} -> {row.get('section') or row.get('id')}: {diff:+.1f} dB"
                    action_items.append(msg)
                    warnings.append(msg)
            prev = row

    if spectral:
        # The existing spectral report has a concise TSV and JSON shape that may
        # evolve, so this looks for obvious high/vhigh dominance in any rows.
        spectral_text = json.dumps(spectral).lower()
        if "lead_guitars" in spectral_text and "high" in spectral_text:
            action_items.append("review high-band ownership; lead guitars can mask other instruments around 4-6 kHz")

    shrill_sources: list[dict[str, Any]] = []
    candidate_count = shrill.get("candidate_count")
    if isinstance(candidate_count, int) and candidate_count > 0:
        msg = f"audio shrillness candidates: {candidate_count}"
        action_items.append(msg)
        warnings.append(msg)
        candidates = shrill.get("candidates") or []
        if isinstance(candidates, list):
            shrill_sources = _top_sources([row for row in candidates if isinstance(row, dict)])
            for item in shrill_sources[:4]:
                action_items.append(
                    f"shrillness source {item['source']}: {item['candidate_count']} candidates, max score {item['max_score']:.2f}"
                )

    payload = {
        "schema": "ambition.music_quality_brief.v1",
        "cue": cue_id,
        "hash": render_hash,
        "all_audits": bool(all_audits),
        "spectrograms": bool(spectrograms),
        "stem_ranking": stem_rows,
        "fallback_messages": fallback_lines,
        "shrillness_sources": shrill_sources,
        "action_items": action_items,
        "warnings": warnings,
    }
    json_path = reports_dir / "quality_brief.json"
    txt_path = reports_dir / "quality_brief.txt"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    lines = [
        f"cue: {cue_id}",
        f"hash: {render_hash}",
        f"all_audits: {bool(all_audits)}",
        f"spectrograms: {bool(spectrograms)}",
        "",
        "stem ranking by RMS:",
    ]
    if stem_rows:
        for row in stem_rows:
            lines.append(f"  {row['stem']}: rms {row['rms_dbfs']:.1f} dBFS, peak {row['peak_dbfs']:.1f} dBFS")
    else:
        lines.append("  no stem diagnostics available")
    lines.extend(["", "fallback / optional-skip messages:"])
    if fallback_lines:
        lines.extend(f"  - {line}" for line in fallback_lines)
    else:
        lines.append("  none seen in render stderr tails")
    lines.extend(["", "shrillness sources:"])
    if shrill_sources:
        for item in shrill_sources:
            lines.append(f"  {item['source']}: {item['candidate_count']} candidates, max score {item['max_score']:.2f}")
    else:
        lines.append("  none from available audits")
    lines.extend(["", "action items:"])
    if action_items:
        lines.extend(f"  - {item}" for item in action_items)
    else:
        lines.append("  none from fast heuristics")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf8")
    return txt_path, warnings

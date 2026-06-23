"""Static mix-balance / lead-audibility audit.

Why this exists
---------------
An instrument's loudness in the *final adaptive mix* is the product of three
things authored in three different places:

    instrument ``volume``/``expression``   (the ``instruments:`` block)
  x group ``gain_db``                        (``group_postprocess:``)
  x per-section stem weight                  (``state_map`` ``stems:``)

It is easy to "make the piano the lead" by cranking its ``volume:`` and never
notice that its *group* (e.g. ``mallets``) is weighted down to 0.1 in every
section's ``state_map`` entry, so the lead is inaudible.  That mistake produced a
piano-led variant where you could barely hear the piano.

This audit reconstructs that product per (section, group) **without rendering
audio** (it reuses the score builder, like the dissonance/sour audits), expresses
each group in dB relative to the loudest group in its section, and flags any group
that carries a *melodic lead* yet sits far below the loudest comp.  It is meant to
run by default in every bundle so a buried lead is caught at author time.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

try:  # optional, only needed for the plot
    import kwconf  # type: ignore
except Exception:  # pragma: no cover
    kwconf = None

# Layer kinds whose notes are a foreground melodic line (a "lead").
LEAD_LAYER_KINDS = {"guitar_lead", "motif"}


def _lead_for_layer(layer_kind: str, layer_name: str) -> bool:
    if layer_kind in LEAD_LAYER_KINDS:
        return True
    name = (layer_name or "").lower()
    return "lead" in name or "answer" in name or "_run_" in name


def _channel_gain(inst_cfg: dict[str, Any]) -> float:
    """Linear channel gain from the instrument's volume + expression CCs."""
    vol = float(inst_cfg.get("volume", 100)) / 127.0
    expr = float(inst_cfg.get("expression", 127)) / 127.0
    return max(1e-6, vol * expr)


def _section_state_weights(spec: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Map each section id to the stem weights of the state that previews it."""
    out: dict[str, dict[str, float]] = {}
    for cfg in (spec.get("state_map") or {}).values():
        if not isinstance(cfg, dict):
            continue
        section = cfg.get("preferred_section") or cfg.get("section")
        stems = cfg.get("stems")
        if section and isinstance(stems, dict):
            # keep the most specific (preferred_section over generic section)
            if section not in out or cfg.get("preferred_section"):
                out[str(section)] = {str(g): float(w) for g, w in stems.items()}
    return out


def audit_spec(spec: dict[str, Any], *, buried_db: float = 10.0,
               lead_velocity_floor: float = 30.0) -> dict[str, Any]:
    """Return per-section group balance and buried-lead warnings.

    ``buried_db`` is how far below the best-budgeted group (in dB) a foreground
    lead may sit before it is flagged.  ``lead_velocity_floor`` is the rendered
    velocity a lead's loudest note must reach to count as a *foreground* lead
    (rather than a quiet background "memory"/answer echo that is meant to sit low).
    """
    from ..render.score_layers import build_score

    pm, _groups, _section_meta = build_score(spec)
    events = list(getattr(pm, "_ambition_note_events", []) or [])
    if not events:
        return {
            "schema": "ambition.music_mix_balance_audit.v1",
            "id": spec.get("id"),
            "sections": [],
            "warnings": ["score generated no note events"],
        }

    inst_cfg = {str(i["name"]): i for i in spec.get("instruments", [])}
    gpp = spec.get("group_postprocess") or {}

    def group_gain_lin(group: str) -> float:
        return 10.0 ** (float((gpp.get(group) or {}).get("gain_db", 0.0)) / 20.0)

    sec_weights = _section_state_weights(spec)

    # section order as it appears in the score
    section_order: list[str] = []
    # energy[section][group] -> summed weighted note energy
    energy: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # which (section, group) carries a lead, the lead layer names, and the
    # loudest lead-note velocity there (so a low-velocity background "memory"
    # garnish is not mistaken for a foreground lead that must be heard)
    leads: dict[tuple[str, str], set[str]] = defaultdict(set)
    lead_vel: dict[tuple[str, str], float] = defaultdict(float)

    bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
    for ev in events:
        sec = str(ev.get("section"))
        grp = str(ev.get("group"))
        if sec not in section_order:
            section_order.append(sec)
        dur_s = max(0.0, float(ev["end_time"]) - float(ev["start_time"]))
        chan = _channel_gain(inst_cfg.get(str(ev.get("instrument")), {}))
        energy[sec][grp] += (float(ev["velocity"]) / 127.0) * chan * dur_s
        if _lead_for_layer(str(ev.get("layer_kind")), str(ev.get("layer"))):
            leads[(sec, grp)].add(str(ev.get("layer")))
            lead_vel[(sec, grp)] = max(lead_vel[(sec, grp)], float(ev["velocity"]))

    sections_out: list[dict[str, Any]] = []
    warnings: list[str] = []
    for sec in section_order:
        weights = sec_weights.get(sec, {})
        # The "buried lead" judgement is based on the MIX BUDGET the arrangement
        # assigns a group (state weight x group gain), NOT on summed note energy.
        # A monophonic lead legitimately plays fewer/sparser notes than a dense
        # chug bed, so energy-share would falsely flag it; the budget reflects
        # whether the mix is even *trying* to let the group be heard.
        budget: dict[str, float] = {}
        for grp in energy[sec]:  # only groups that actually sound in this section
            w = weights.get(grp, 1.0)  # sections without explicit weights play native
            budget[grp] = max(1e-9, w * group_gain_lin(grp))
        peak_budget = max(budget.values(), default=1e-9)
        total_energy = sum(energy[sec].values()) or 1.0
        rows = []
        for grp, b in sorted(budget.items(), key=lambda kv: kv[1], reverse=True):
            rel_db = 20.0 * math.log10(b / peak_budget)
            # secondary, informational: this group's share of note activity
            share_db = 20.0 * math.log10(max(1e-9, energy[sec][grp]) / total_energy)
            is_lead = bool(leads.get((sec, grp)))
            # Flag a lead that is authored to be HEARD (its loudest lead note has
            # real velocity, i.e. not a low-velocity background "memory" echo) yet
            # is allocated far less mix budget than the best-served group: the "I
            # made it the lead but mixed it like a garnish" mistake.  A tasteful
            # sparse solo over a dense bed keeps a healthy budget, so it is not hit.
            foreground_lead = is_lead and lead_vel.get((sec, grp), 0.0) >= lead_velocity_floor
            buried = foreground_lead and rel_db < -abs(buried_db)
            rows.append(
                {
                    "group": grp,
                    "budget_db": round(rel_db, 1),
                    "note_share_db": round(share_db, 1),
                    "state_weight": round(weights.get(grp, 1.0), 3),
                    "group_gain_db": round(float((gpp.get(grp) or {}).get("gain_db", 0.0)), 1),
                    "is_lead": is_lead,
                    "lead_layers": sorted(leads.get((sec, grp), set())),
                    "buried_lead": buried,
                }
            )
            if buried:
                warnings.append(
                    f"buried lead: section '{sec}' group '{grp}' carries "
                    f"{', '.join(sorted(leads[(sec, grp)]))} but its mix budget is "
                    f"{rel_db:.1f} dB below the loudest group "
                    f"(state_weight={weights.get(grp, 1.0):g}, "
                    f"group_gain={float((gpp.get(grp) or {}).get('gain_db', 0.0)):+g}dB). "
                    f"Raise its state_map stem weight or move the lead to a foreground group."
                )
        sections_out.append({"section": sec, "groups": rows})

    return {
        "schema": "ambition.music_mix_balance_audit.v1",
        "id": spec.get("id"),
        "title": spec.get("title"),
        "bpm": bpm,
        "buried_db": buried_db,
        "sections": sections_out,
        "warnings": warnings,
    }


def audit_file(path: Path, *, buried_db: float = 12.0) -> dict[str, Any]:
    from ..render.score_core import load_yaml

    return audit_spec(load_yaml(path), buried_db=buried_db)


def _format_summary(payload: dict[str, Any]) -> str:
    lines = [
        f"cue: {payload.get('id')}",
        "per-section MIX BUDGET per group (state_weight x group_gain), dB below the",
        "best-budgeted group in that section. note_share = that group's share of note",
        "activity (informational). leads marked [LEAD]; a starved lead <<BURIED LEAD>>.",
        "",
    ]
    for sec in payload.get("sections", []):
        lines.append(f"  {sec['section']}:")
        for row in sec["groups"]:
            tag = ""
            if row["buried_lead"]:
                tag = "  <<BURIED LEAD>>"
            elif row["is_lead"]:
                tag = "  [LEAD]"
            lines.append(
                f"    budget {row['budget_db']:>6.1f} dB  (notes {row['note_share_db']:>6.1f} dB)  "
                f"{row['group']:<16}(w={row['state_weight']:<5g} gain={row['group_gain_db']:+.1f}dB){tag}"
            )
        lines.append("")
    warnings = payload.get("warnings", [])
    lines.append(f"warnings ({len(warnings)}):")
    lines.extend(f"  - {w}" for w in warnings)
    return "\n".join(lines) + "\n"


def render_plot(payload: dict[str, Any], path: Path, *, plot_format: str = "jpg", jpeg_quality: int = 90) -> bool:
    from .dissonance_audit import _ensure_matplotlib, _save_figure

    if not _ensure_matplotlib():
        return False
    import matplotlib.pyplot as plt  # noqa
    import numpy as np

    sections = payload.get("sections", [])
    if not sections:
        return False
    groups = sorted({r["group"] for s in sections for r in s["groups"]})
    grid = np.full((len(sections), len(groups)), -60.0)
    lead_mask = np.zeros_like(grid, dtype=bool)
    buried_mask = np.zeros_like(grid, dtype=bool)
    for i, sec in enumerate(sections):
        for r in sec["groups"]:
            j = groups.index(r["group"])
            grid[i, j] = max(-60.0, r["budget_db"])
            lead_mask[i, j] = r["is_lead"]
            buried_mask[i, j] = r["buried_lead"]

    fig, ax = plt.subplots(figsize=(max(7, len(groups) * 1.1), max(3, len(sections) * 0.6)))
    im = ax.imshow(grid, aspect="auto", cmap="magma", vmin=-40, vmax=0)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels(groups, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(len(sections)))
    ax.set_yticklabels([s["section"] for s in sections], fontsize=8)
    for i in range(len(sections)):
        for j in range(len(groups)):
            txt = f"{grid[i, j]:.0f}"
            if buried_mask[i, j]:
                txt += "\nBURIED"
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="cyan", lw=2.5))
            elif lead_mask[i, j]:
                txt += "\nlead"
            ax.text(j, i, txt, ha="center", va="center", fontsize=6,
                    color="white" if grid[i, j] < -18 else "black")
    ax.set_title(f"Mix budget (state_weight x group_gain, dB below best group/section) — {payload.get('id')}")
    fig.colorbar(im, ax=ax, label="dB below section's best-budgeted group")
    _save_figure(fig, path, plot_format=plot_format, jpeg_quality=jpeg_quality)
    return True


def write_reports(payload: dict[str, Any], reports_dir: Path, *, plots_dir: Path | None = None,
                  plot_format: str = "jpg", jpeg_quality: int = 90) -> dict[str, str]:
    import json

    reports_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    (reports_dir / "mix_balance.json").write_text(json.dumps(payload, indent=2), encoding="utf8")
    paths["json"] = str(reports_dir / "mix_balance.json")
    (reports_dir / "mix_balance_summary.txt").write_text(_format_summary(payload), encoding="utf8")
    paths["summary"] = str(reports_dir / "mix_balance_summary.txt")

    md = [f"# Mix Balance — {payload.get('id')}", "",
          "Per-section group level in dB relative to the loudest group in that section.",
          "Combines instrument volume/expression x group gain x state_map stem weight.", ""]
    warnings = payload.get("warnings", [])
    if warnings:
        md += ["## ⚠ Buried-lead warnings", ""] + [f"- {w}" for w in warnings] + [""]
    for sec in payload.get("sections", []):
        md += [f"## {sec['section']}", "",
               "| group | budget dB | note-share dB | state weight | group gain | role |",
               "| --- | ---: | ---: | ---: | ---: | --- |"]
        for row in sec["groups"]:
            role = "**BURIED LEAD**" if row["buried_lead"] else ("lead" if row["is_lead"] else "")
            md.append(f"| {row['group']} | {row['budget_db']} | {row['note_share_db']} | "
                      f"{row['state_weight']} | {row['group_gain_db']:+.1f} dB | {role} |")
        md.append("")
    (reports_dir / "mix_balance.md").write_text("\n".join(md), encoding="utf8")
    paths["markdown"] = str(reports_dir / "mix_balance.md")

    if plots_dir is not None:
        plots_dir.mkdir(parents=True, exist_ok=True)
        suffix = "jpg" if plot_format in {"jpg", "jpeg"} else "png"
        plot_path = plots_dir / f"mix_balance.{suffix}"
        if render_plot(payload, plot_path, plot_format=plot_format, jpeg_quality=jpeg_quality):
            paths["plot"] = str(plot_path)
    return paths


if kwconf is not None:

    class MixBalanceAuditConfig(kwconf.Config):
        __command__ = "mix_balance"
        __default__ = {
            "spec": kwconf.Value(None, position=1, help="path to a .music.yaml"),
            "buried_db": kwconf.Value(12.0, help="dB below section peak that flags a buried lead"),
            "reports_dir": kwconf.Value(".", help="output directory"),
            "plot_format": kwconf.Value("jpg"),
        }

        @classmethod
        def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
            return run(cls.cli(argv=argv, **kwargs))

    def run(args: "MixBalanceAuditConfig") -> int:
        payload = audit_file(Path(args["spec"]), buried_db=float(args["buried_db"]))
        out = Path(args["reports_dir"])
        write_reports(payload, out, plots_dir=out, plot_format=str(args["plot_format"]))
        print(_format_summary(payload))
        return 0

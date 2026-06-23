"""Shared piano-roll renderer for the harmony audits.

Both the dissonance audit (notes colored by clash score) and the sour-note audit
(notes colored by out-of-key severity) want the same picture: a time x pitch
grid with a value-colored note per event, an optional marker overlay, and an
optional time-ordered strip beneath. Keep that one renderer here so the two
audits theme it rather than each carrying their own copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import lazy_loader as lazy

np = lazy.load("numpy")


def render_note_pianoroll(
    path: Path,
    *,
    notes: Sequence[dict[str, Any]],
    end_beat: float,
    beats_per_bar: float,
    sections: Sequence[dict[str, Any]],
    title: str,
    value_label: str,
    cmap: str = "turbo",
    strip: Sequence[float] | None = None,
    strip_label: str = "",
    bucket_beats: float = 0.25,
    markers: Sequence[dict[str, Any]] | None = None,
    marker_label: str = "",
    marker_color: str = "magenta",
    plot_format: str = "jpg",
    jpeg_quality: int = 90,
) -> bool:
    """Render a value-colored piano-roll. Returns False if matplotlib is absent.

    ``notes`` items need ``pitch``/``x0``/``x1``/``value``; ``markers`` items need
    ``pitch``/``x``/``severity``; ``strip`` is one value per ``bucket_beats``.
    """
    if not notes:
        return False
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
        from matplotlib.gridspec import GridSpec
    except Exception:  # pragma: no cover - plotting is best-effort
        return False

    pitches = [int(n["pitch"]) for n in notes]
    vmax = max((float(n["value"]) for n in notes), default=0.0) or 1.0
    colormap = plt.get_cmap(cmap)

    fig = plt.figure(figsize=(15, 7.5))
    if strip is not None:
        gs = GridSpec(2, 1, height_ratios=[4, 1], hspace=0.06, figure=fig)
        ax = fig.add_subplot(gs[0])
        axd: Any = fig.add_subplot(gs[1], sharex=ax)
    else:
        ax = fig.add_subplot(1, 1, 1)
        axd = None
    ax.set_facecolor("0.11")

    segs, cols = [], []
    for n in sorted(notes, key=lambda r: float(r["value"])):  # hot notes on top
        segs.append([(float(n["x0"]), int(n["pitch"])), (float(n["x1"]), int(n["pitch"]))])
        cols.append(colormap(min(1.0, float(n["value"]) / vmax)))
    ax.add_collection(LineCollection(segs, colors=cols, linewidths=2.2))

    if markers:
        smax = max(float(m["severity"]) for m in markers) or 1.0
        ax.scatter(
            [float(m["x"]) for m in markers],
            [int(m["pitch"]) for m in markers],
            marker="v",
            s=[18 + 70 * (float(m["severity"]) / smax) for m in markers],
            facecolors="none",
            edgecolors=marker_color,
            linewidths=1.1,
            alpha=0.9,
            label=marker_label or None,
            zorder=5,
        )

    top_pitch = max(pitches)
    for sec in sections:
        ax.axvline(float(sec["start_beat"]), color="white", lw=0.7, alpha=0.22)
        ax.text(float(sec["start_beat"]) + 0.4, top_pitch + 2.0, str(sec["id"]), fontsize=8, color="0.45")
    ax.set_xlim(0, end_beat)
    ax.set_ylim(min(pitches) - 2, top_pitch + 5)
    ax.set_ylabel("MIDI pitch")
    ax.set_title(title)
    if markers and marker_label:
        ax.legend(loc="upper right", fontsize=8)
    sm = plt.cm.ScalarMappable(cmap=colormap, norm=plt.Normalize(0, vmax))
    sm.set_array([])
    fig.colorbar(sm, ax=ax, label=value_label, pad=0.01, fraction=0.025)

    if axd is not None and strip is not None:
        ax.tick_params(labelbottom=False)
        xs = [i * bucket_beats for i in range(len(strip))]
        axd.fill_between(xs, list(strip), step="mid", color="orangered", alpha=0.65)
        for b in range(0, int(end_beat) + 1, max(1, int(beats_per_bar))):
            axd.axvline(b, color="0.85", lw=0.3)
        axd.set_ylabel(strip_label)
        axd.set_xlabel("beat")
        axd.set_xlim(0, end_beat)
    else:
        ax.set_xlabel("beat")

    fmt = plot_format.lower()
    save_kwargs: dict[str, Any] = {"dpi": 150, "bbox_inches": "tight"}
    if fmt in {"jpg", "jpeg"}:
        save_kwargs["format"] = "jpeg"
        save_kwargs["pil_kwargs"] = {"quality": int(jpeg_quality)}
    else:
        save_kwargs["format"] = fmt
    fig.savefig(path, **save_kwargs)
    plt.close(fig)
    return True

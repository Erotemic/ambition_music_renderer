#!/usr/bin/env python3
"""Create an isolated first-goblin transition-lab score.

This script deliberately does not edit the active score. It reads
``scores/active/first_goblin_tune_v2.music.yaml`` and writes a separate
experiment score under ``scores/experiments/`` so runtime / asset-install work
from other agents can continue independently.
"""

from __future__ import annotations

from ..profiler import profile

import kwconf
import copy
from pathlib import Path

from .._paths import project_root
from typing import Any

import yaml

try:
    from rich import print as rich_print
except Exception:  # pragma: no cover - fallback for fresh environments
    rich_print = print


RENDERER_ROOT = project_root()
REPO_ROOT = RENDERER_ROOT.parents[1]
DEFAULT_SOURCE = RENDERER_ROOT / "scores" / "active" / "first_goblin_tune_v2.music.yaml"
DEFAULT_OUTPUT = (
    RENDERER_ROOT / "scores" / "experiments" / "first_goblin_transition_lab.music.yaml"
)


@profile
def path_link(path: Path) -> str:
    resolved = path.resolve()
    return f"[link=file://{resolved}]{resolved}[/link]"


@profile
def deep_merge(dst: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            deep_merge(dst[key], value)
        else:
            dst[key] = value
    return dst


@profile
def section_by_id(score: dict[str, Any], section_id: str) -> dict[str, Any]:
    for section in score.get("sections", []) or []:
        if section.get("id") == section_id:
            return section
    raise KeyError(f"missing section {section_id!r}")


@profile
def template_by_id(score: dict[str, Any], template_id: str) -> dict[str, Any]:
    templates = score.setdefault("layer_templates", {})
    item = templates.get(template_id)
    if not isinstance(item, dict):
        raise KeyError(f"missing layer template {template_id!r}")
    return item


@profile
def scale_template_events(
    template: dict[str, Any], *, drum_names: set[str], velocity_scale: float
) -> None:
    for event in template.get("events", []) or []:
        if not isinstance(event, dict):
            continue
        drum = event.get("drum")
        if drum in drum_names and isinstance(event.get("velocity"), (int, float)):
            event["velocity"] = int(round(float(event["velocity"]) * velocity_scale))


@profile
def replace_layer_template(
    section: dict[str, Any], template: str, patch: dict[str, Any]
) -> None:
    for layer in section.get("layers", []) or []:
        if isinstance(layer, dict) and layer.get("template") == template:
            layer.update(patch)


@profile
def replace_named_layer(section: dict[str, Any], old_name: str, new_layer: Any) -> None:
    layers = section.get("layers", []) or []
    for index, layer in enumerate(layers):
        if layer == old_name:
            layers[index] = copy.deepcopy(new_layer)


@profile
def append_layer_once(
    section: dict[str, Any], marker_key: str, layer: dict[str, Any]
) -> None:
    layers = section.setdefault("layers", [])
    for existing in layers:
        if isinstance(existing, dict) and existing.get(marker_key) == layer.get(
            marker_key
        ):
            return
    layers.append(layer)


@profile
def apply_transition_lab_changes(score: dict[str, Any]) -> dict[str, Any]:
    score = copy.deepcopy(score)
    source_id = score.get("id", "first_goblin_tune_v2")
    score["id"] = "first_goblin_transition_lab"
    score["title"] = "First Goblin Transition Lab - Intro to Wave1"
    notes = str(score.get("notes", "")).strip()
    lab_notes = (
        "Transition-lab derivative of first_goblin_tune_v2. This score is "
        "intentionally isolated from scores/active so agents can tune the "
        "intro->wave1 handoff without clobbering the in-game cue. Goals: lower "
        "intro perceived loudness, reduce high-frequency reverb/noise floor, "
        "make the intro feel like a pickup into wave1, front-load wave1 energy for the runtime crossfade, and keep generated "
        "sections runtime-crossfade friendly."
    )
    score["notes"] = (
        f"Derived from {source_id}.\n\n{notes}\n\n{lab_notes}" if notes else lab_notes
    )

    # Global mastering: keep more headroom and reduce hiss-prone ambience. This
    # is not final mastering policy; it is a controlled experiment that makes
    # the transition easier to judge outside the game.
    post = score.setdefault("postprocess", {})
    deep_merge(
        post,
        {
            "gain_db": -1.8,
            "reverb_wet": 0.018,
            "reverb_decay_seconds": 0.36,
            "reverb_damping_hz": 3900,
            "stereo_width": 0.018,
            "compressor_threshold_db": -20.0,
            "compressor_ratio": 2.0,
            "compressor_makeup_db": 0.20,
            "limiter_drive": 0.66,
            "normalize": True,
            "target_peak_db": -4.8,
        },
    )

    stem_post = score.setdefault("stem_postprocess", {})
    deep_merge(
        stem_post,
        {
            "reverb_wet": 0.001,
            "reverb_decay_seconds": 0.18,
            "reverb_damping_hz": 4200,
            "stereo_width": 0.012,
            "limiter_drive": 0.70,
        },
    )

    # Darken groups that tend to expose synthetic noise / air.
    group_pp = score.setdefault("group_postprocess", {})
    for name, patch in {
        "winds": {
            "gain_db": 2.0,
            "lowpass_hz": 7800,
            "high_shelf_hz": 3600,
            "high_shelf_db": -1.0,
            "presence_db": 0.5,
            "reverb_wet": 0.001,
        },
        "percussion": {
            "gain_db": -2.5,
            "lowpass_hz": 6500,
            "high_shelf_hz": 3600,
            "high_shelf_db": -1.6,
            "reverb_wet": 0.004,
            "reverb_decay_seconds": 0.28,
        },
        "choir_pad": {
            "gain_db": -5.0,
            "lowpass_hz": 5600,
            "high_shelf_hz": 3600,
            "high_shelf_db": -2.0,
            "reverb_wet": 0.002,
        },
        "mallets": {
            "gain_db": -4.0,
            "lowpass_hz": 6800,
            "high_shelf_db": -1.4,
        },
        "strings": {
            "gain_db": 0.0,
            "lowpass_hz": 10500,
            "high_shelf_db": -0.3,
            "reverb_wet": 0.001,
        },
        "brass": {
            "gain_db": -1.4,
            "lowpass_hz": 7800,
            "high_shelf_db": -0.8,
            "reverb_wet": 0.001,
        },
    }.items():
        group_pp.setdefault(name, {})
        deep_merge(group_pp[name], patch)

    # Tame obviously hissy/noisy drum material.
    for template_id in ["pulse_drums_medium", "pulse_drums_heavy"]:
        try:
            scale_template_events(
                template_by_id(score, template_id),
                drum_names={"closed_hat", "crash"},
                velocity_scale=0.45,
            )
        except KeyError:
            pass

    intro = section_by_id(score, "intro")
    intro["label"] = "transition lab - quiet pickup warning"
    intro["intensity"] = min(float(intro.get("intensity", 0.38)), 0.28)
    intro["density"] = min(float(intro.get("density", 0.16)), 0.11)
    intro_pp = intro.setdefault("postprocess", {})
    deep_merge(
        intro_pp,
        {
            # The previous lab version still had a hot final 1-2 seconds. Keep
            # the intro audible, but stop the tail from cresting above wave1's
            # first bar.
            # Iteration 5: iteration 4 made the last intro bar too empty
            # (-30 dBFS tail) even though the high-band ratio stayed visible.
            # Bring back low/mid body, but keep the intro dry and dark.
            "gain_db": -6.0,
            "reverb_wet": 0.002,
            "reverb_decay_seconds": 0.09,
            "reverb_damping_hz": 2200,
            "target_peak_db": -8.0,
            "stereo_width": 0.002,
        },
    )
    replace_named_layer(
        intro,
        "expression_gentle",
        {
            "kind": "automation",
            "group": "strings",
            "automation": [
                {
                    "group": "strings",
                    "cc": "expression",
                    "from": 52,
                    "to": 44,
                    "curve": "smooth",
                    "points": 8,
                },
                {
                    "group": "brass",
                    "cc": "expression",
                    "from": 34,
                    "to": 20,
                    "curve": "smooth",
                    "points": 8,
                },
                {
                    "group": "winds",
                    "cc": "expression",
                    "from": 48,
                    "to": 22,
                    "curve": "smooth",
                    "points": 8,
                },
                {
                    "group": "choir_pad",
                    "cc": "expression",
                    "from": 10,
                    "to": 4,
                    "curve": "smooth",
                    "points": 8,
                },
            ],
        },
    )
    replace_layer_template(intro, "string_pad", {"velocity": 22})
    # Keep the warning motif, but remove the bar-3 restart that was making the
    # last second crest just before the wave1 handoff.
    replace_layer_template(intro, "low_goblin", {"velocity": 16, "starts": [[1, 0.5]]})
    replace_layer_template(intro, "harp_murmur", {"density": 0.035, "velocity": 12})
    for layer in intro.get("layers", []) or []:
        if isinstance(layer, dict) and layer.get("kind") == "drums":
            for event in layer.get("events", []) or []:
                if isinstance(event, dict) and isinstance(
                    event.get("velocity"), (int, float)
                ):
                    event["velocity"] = int(round(float(event["velocity"]) * 0.32))

    # Add a dark, sustained late final-bar bed so the actual crossfade window
    # has low/mid energy to hand off from. Earlier versions started this at
    # bar 3 beat 0, which improved broad tail RMS but ended before the last
    # ~0.65s runtime crossfade window. Start near beat 2.25 and hold through
    # the boundary instead. This raises seam energy without bringing back the
    # high-frequency haze that made the intro tail obvious.
    append_layer_once(
        intro,
        "transition_lab_marker",
        {
            "transition_lab_marker": "intro_tail_contrabass_bed",
            "kind": "root_hits",
            "instrument": "contrabass",
            "octave": 2,
            "velocity": 56,
            "articulation": "tenuto",
            "humanize_ms": 0.0,
            "humanize_velocity_pct": 0.0,
            "hits": [[3, 2.25, -12, 2.05]],
        },
    )
    append_layer_once(
        intro,
        "transition_lab_marker",
        {
            "transition_lab_marker": "intro_tail_celli_bed",
            "kind": "root_hits",
            "instrument": "celli",
            "octave": 2,
            "velocity": 44,
            "articulation": "tenuto",
            "humanize_ms": 0.0,
            "humanize_velocity_pct": 0.0,
            "hits": [[3, 2.25, 0, 2.05]],
        },
    )

    wave1 = section_by_id(score, "wave1")
    wave1["label"] = "transition lab - wave 1 pickup handoff"
    wave1["intensity"] = max(float(wave1.get("intensity", 0.42)), 0.50)
    wave1["density"] = max(float(wave1.get("density", 0.32)), 0.40)
    wave1_pp = wave1.setdefault("postprocess", {})
    deep_merge(
        wave1_pp,
        {
            # Do not make the whole loop huge, but give the first bar enough
            # mastered energy that the intro tail does not fall into a hole.
            "gain_db": 1.10,
            "reverb_wet": 0.008,
            "reverb_decay_seconds": 0.18,
            "reverb_damping_hz": 3200,
            "target_peak_db": -3.1,
            "stereo_width": 0.008,
        },
    )
    replace_layer_template(wave1, "string_pad", {"velocity": 48})
    replace_layer_template(wave1, "low_string_pulse", {"velocity": 68})
    replace_layer_template(
        wave1, "wind_goblin", {"starts": [[0, 0.0], [2, 0.0], [4, 0.0]], "velocity": 38}
    )
    replace_layer_template(wave1, "harp_murmur", {"density": 0.06, "velocity": 14})
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_downbeat_anchor",
            "kind": "drums",
            "instrument": "war_drums",
            "humanize_ms": 0.0,
            "events": [
                {"drum": "concert_bass_drum", "bars": [0], "beat": 0.0, "velocity": 74},
                {"drum": "floor_tom", "bars": [0], "beat": 0.0, "velocity": 48},
                {"drum": "low_tom", "bars": [0], "beat": 0.5, "velocity": 28},
            ],
        },
    )
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_intro_motif_echo",
            "template": "low_goblin",
            "starts": [[0, 0.0]],
            "velocity": 38,
        },
    )
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_low_root_support",
            "template": "tuba_roots_light",
            "hits": [[0, 0.0, -12, 0.95]],
            "velocity": 48,
        },
    )
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_timpani_floor_support",
            "template": "timpani_roots",
            "hits": [[0, 0.0, -12, 0.90]],
            "velocity": 44,
        },
    )
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_sustained_low_string_floor",
            "kind": "root_hits",
            "instrument": "contrabass",
            "octave": 2,
            "velocity": 66,
            "articulation": "tenuto",
            "humanize_ms": 0.0,
            "humanize_velocity_pct": 0.0,
            "hits": [[0, 0.0, -12, 1.70]],
        },
    )
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_sustained_celli_floor",
            "kind": "root_hits",
            "instrument": "celli",
            "octave": 2,
            "velocity": 58,
            "articulation": "tenuto",
            "humanize_ms": 0.0,
            "humanize_velocity_pct": 0.0,
            "hits": [[0, 0.0, 0, 1.60]],
        },
    )
    append_layer_once(
        wave1,
        "transition_lab_marker",
        {
            "transition_lab_marker": "wave1_sustained_harmony_pad",
            "kind": "pad_chords",
            "instruments": ["violas", "celli"],
            "instrument_octave_offsets": {"violas": 0, "celli": -1},
            "instrument_velocity_offsets": {"violas": -8, "celli": -12},
            "octave": 3,
            "duration_beats": 4.0,
            "velocity": 40,
            "articulation": "legato",
            "voicing": "open",
            "humanize_ms": 0.0,
            "humanize_velocity_pct": 0.0,
            "every_bars": 8,
        },
    )

    # Make wave1 a little less dependent on runtime gain compensation in the
    # experiment. The in-game cue may still use a different full-mix gain, but
    # the lab score should be judged by generated audio files first.
    state_map = score.setdefault("state_map", {})
    if isinstance(state_map.get("wave_1"), dict):
        stems = state_map["wave_1"].setdefault("stems", {})
        if isinstance(stems, dict):
            stems.update(
                {
                    "strings": 1.0,
                    "winds": 0.45,
                    "mallets": 0.03,
                    "percussion": 0.10,
                    "brass": 0.08,
                }
            )

    return score


class FirstGoblinTransitionLabConfig(kwconf.Config):
    """Create the first-goblin transition lab experiment score."""

    source: Path = kwconf.Value(DEFAULT_SOURCE, parser=Path)
    output: Path = kwconf.Value(DEFAULT_OUTPUT, parser=Path)
    force: bool = kwconf.Flag(False, help="overwrite an existing experiment score")

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        return run(cls.cli(argv=argv, data=kwargs))


@profile
def run(args: FirstGoblinTransitionLabConfig) -> int:
    if args.output.exists() and not args.force:
        rich_print(f"[yellow]kept existing experiment score[/yellow] {path_link(args.output)}")
        return 0
    if not args.source.exists():
        raise SystemExit(f"source score not found: {args.source}")
    score = yaml.safe_load(args.source.read_text(encoding="utf8"))
    if not isinstance(score, dict):
        raise SystemExit(f"source score did not parse as a mapping: {args.source}")
    experiment = apply_transition_lab_changes(score)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(experiment, sort_keys=False, width=100), encoding="utf8")
    rich_print(f"[green]wrote[/green] {path_link(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(FirstGoblinTransitionLabConfig.main())

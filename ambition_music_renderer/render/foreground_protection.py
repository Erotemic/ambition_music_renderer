"""Role-aware orchestral foreground protection for stem mixes.

MusicIR performance controls (velocity / CC expression) describe how a part is
played. They are not a reliable proxy for acoustic foreground, especially when
a solo wind shares pitches with a sampled string section. This module builds a
low-rate role-priority envelope and lets lower-priority groups yield only while
a more important group is sounding.

The policy is generic and score-authored. No cue or instrument name is baked
into the renderer.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pretty_midi


DEFAULT_ROLE_PRIORITIES = {
    "background": 0,
    "support": 1,
    "lead": 2,
    "foreground": 3,
}
DEFAULT_PROTECTED_ROLES = ("foreground", "lead")
DEFAULT_DUCKABLE_ROLES = ("support", "background")


def _instrument_specs_by_name(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("name")): row
        for row in (spec.get("instruments") or [])
        if isinstance(row, dict) and row.get("name") is not None
    }


def _role_priorities_from_config(spec: dict[str, Any]) -> dict[str, int]:
    cfg = dict(((spec.get("render") or {}).get("foreground_protection") or {}))
    raw = cfg.get("role_priorities") or DEFAULT_ROLE_PRIORITIES
    out = dict(DEFAULT_ROLE_PRIORITIES)
    out.update({str(role).lower(): int(value) for role, value in dict(raw).items()})
    return out


def build_group_role_activity(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    *,
    duration_s: float,
    hop_s: float,
    protected_roles: tuple[str, ...] = DEFAULT_PROTECTED_ROLES,
    duckable_roles: tuple[str, ...] = DEFAULT_DUCKABLE_ROLES,
) -> dict[str, dict[str, np.ndarray]]:
    """Return low-rate per-group role activity masks.

    Kept as a simple public primitive for diagnostics/tests. Foreground
    protection itself uses the richer role-priority representation below.
    """
    if hop_s <= 0.0:
        raise ValueError("hop_s must be positive")
    bins = max(1, int(math.ceil(max(0.0, duration_s) / hop_s)))
    group_names = sorted(set(groups.values()))
    out = {
        group: {
            "protected": np.zeros(bins, dtype=np.bool_),
            "duckable": np.zeros(bins, dtype=np.bool_),
            "any": np.zeros(bins, dtype=np.bool_),
        }
        for group in group_names
    }
    instrument_specs = _instrument_specs_by_name(spec)
    protected = {str(role).lower() for role in protected_roles}
    duckable = {str(role).lower() for role in duckable_roles}

    for inst in pm.instruments:
        group = groups.get(inst.name)
        if group not in out or not inst.notes:
            continue
        role = str((instrument_specs.get(inst.name) or {}).get("mix_role", "support")).lower()
        role_key = "protected" if role in protected else "duckable" if role in duckable else "any"
        for note in inst.notes:
            start = max(0, min(bins - 1, int(math.floor(note.start / hop_s))))
            end = max(start + 1, min(bins, int(math.ceil(note.end / hop_s))))
            out[group]["any"][start:end] = True
            if role_key != "any":
                out[group][role_key][start:end] = True
    return out


def build_group_role_priority(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    *,
    duration_s: float,
    hop_s: float,
) -> dict[str, np.ndarray]:
    """Return the highest active authored mix-role priority per group/bin.

    ``-1`` means the group is silent. Higher numbers mean greater foreground
    importance. When several desks in one family sound together, the most
    important active desk determines whether that family should yield.
    """
    if hop_s <= 0.0:
        raise ValueError("hop_s must be positive")
    bins = max(1, int(math.ceil(max(0.0, duration_s) / hop_s)))
    group_names = sorted(set(groups.values()))
    out = {group: np.full(bins, -1, dtype=np.int16) for group in group_names}
    instrument_specs = _instrument_specs_by_name(spec)
    priorities = _role_priorities_from_config(spec)

    for inst in pm.instruments:
        group = groups.get(inst.name)
        if group not in out or not inst.notes:
            continue
        role = str((instrument_specs.get(inst.name) or {}).get("mix_role", "support")).lower()
        priority = int(priorities.get(role, priorities.get("support", 1)))
        for note in inst.notes:
            start = max(0, min(bins - 1, int(math.floor(note.start / hop_s))))
            end = max(start + 1, min(bins, int(math.ceil(note.end / hop_s))))
            out[group][start:end] = np.maximum(out[group][start:end], priority)
    return out


def build_group_note_count(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    *,
    duration_s: float,
    hop_s: float,
) -> dict[str, np.ndarray]:
    """Return active sounding-note counts per group/control bin."""
    if hop_s <= 0.0:
        raise ValueError("hop_s must be positive")
    bins = max(1, int(math.ceil(max(0.0, duration_s) / hop_s)))
    out = {
        group: np.zeros(bins, dtype=np.int16)
        for group in sorted(set(groups.values()))
    }
    for inst in pm.instruments:
        group = groups.get(inst.name)
        if group not in out:
            continue
        for note in inst.notes:
            start = max(0, min(bins - 1, int(math.floor(note.start / hop_s))))
            end = max(start + 1, min(bins, int(math.ceil(note.end / hop_s))))
            out[group][start:end] += 1
    return out




def foreground_protection_mode(spec: dict[str, Any]) -> str:
    """Return the authored foreground-protection mode."""
    cfg = dict(((spec.get("render") or {}).get("foreground_protection") or {}))
    return str(cfg.get("mode", "group_density")).strip().lower().replace("-", "_")


def _configured_duck_groups(
    group_names: list[str],
    cfg: dict[str, Any],
) -> tuple[set[str], set[str]]:
    configured_groups = cfg.get("groups")
    duck_groups = set(map(str, configured_groups)) if configured_groups else set(group_names)
    excluded_groups = set(map(str, cfg.get("exclude_groups", ("percussion",))))
    return duck_groups, excluded_groups


def instrument_register_protection_gain_envelopes(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    *,
    duration_s: float,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Build per-instrument dB envelopes for register-aware foreground protection.

    Unlike the legacy group-density rider, this policy never ducks an entire
    family merely because another family has a higher authored role. A desk
    yields only while one of its sounding notes occupies approximately the same
    written register as a higher-priority note in another family.

    The detector operates on score pitch and role, while the gain itself is
    applied after synthesis. That keeps MIDI velocity/expression as performance
    controls and uses audio-domain gain only for orchestral front/back hierarchy.
    """
    cfg = dict(((spec.get("render") or {}).get("foreground_protection") or {}))
    enabled = bool(cfg.get("enabled", False))
    mode = foreground_protection_mode(spec)
    instrument_specs = _instrument_specs_by_name(spec)
    instrument_names = [inst.name for inst in pm.instruments]
    if not enabled or mode not in {"instrument_register", "register", "desk_register"}:
        return {name: np.zeros(1, dtype=np.float32) for name in instrument_names}, {
            "enabled": enabled,
            "mode": mode,
            "groups": {},
            "instruments": {},
        }

    max_duck_db = abs(float(cfg.get("max_duck_db", cfg.get("duck_db", -6.0))))
    duck_db_per_priority = abs(float(cfg.get("duck_db_per_priority", 3.0)))
    pitch_radius = max(0, int(cfg.get("pitch_radius_semitones", 2)))
    hop_ms = max(5.0, float(cfg.get("control_hop_ms", 20.0)))
    hop_s = hop_ms / 1000.0
    attack_ms = max(1.0, float(cfg.get("attack_ms", 25.0)))
    release_ms = max(1.0, float(cfg.get("release_ms", 100.0)))
    priorities_cfg = _role_priorities_from_config(spec)
    group_names = sorted(set(groups.values()))
    duck_groups, excluded_groups = _configured_duck_groups(group_names, cfg)
    bins = max(1, int(math.ceil(max(0.0, duration_s) / hop_s)))
    cache_key = (
        round(float(duration_s), 6),
        round(hop_ms, 6),
        round(max_duck_db, 6),
        round(duck_db_per_priority, 6),
        pitch_radius,
        round(attack_ms, 6),
        round(release_ms, 6),
        tuple(sorted(duck_groups)),
        tuple(sorted(excluded_groups)),
        tuple(sorted(priorities_cfg.items())),
        tuple(
            sorted(
                (name, str((row or {}).get("mix_role", "support")).lower())
                for name, row in instrument_specs.items()
            )
        ),
    )
    cache = getattr(pm, "_ambition_instrument_register_protection_cache", None)
    if isinstance(cache, dict) and cache_key in cache:
        return cache[cache_key]

    # For every family, keep the highest authored role priority sounding at each
    # score pitch/control bin. MIDI has only 128 pitches, so this representation
    # remains compact even for a long orchestral work.
    group_pitch_priority = {
        group: np.full((bins, 128), -1, dtype=np.int8)
        for group in group_names
    }
    for inst in pm.instruments:
        group = groups.get(inst.name)
        if group not in group_pitch_priority:
            continue
        role = str((instrument_specs.get(inst.name) or {}).get("mix_role", "support")).lower()
        priority = int(priorities_cfg.get(role, priorities_cfg.get("support", 1)))
        matrix = group_pitch_priority[group]
        for note in inst.notes:
            start = max(0, min(bins - 1, int(math.floor(note.start / hop_s))))
            end = max(start + 1, min(bins, int(math.ceil(note.end / hop_s))))
            pitch = max(0, min(127, int(note.pitch)))
            matrix[start:end, pitch] = np.maximum(matrix[start:end, pitch], priority)

    outside_priority: dict[str, np.ndarray] = {}
    for group in group_names:
        other = [matrix for other_group, matrix in group_pitch_priority.items() if other_group != group]
        if other:
            outside_priority[group] = np.maximum.reduce(other)
        else:
            outside_priority[group] = np.full((bins, 128), -1, dtype=np.int8)

    envelopes: dict[str, np.ndarray] = {}
    report_instruments: dict[str, Any] = {}
    group_duck_masks = {group: np.zeros(bins, dtype=np.bool_) for group in group_names}
    group_min_gain = {group: 0.0 for group in group_names}

    for inst in pm.instruments:
        group = groups.get(inst.name)
        inst_spec = instrument_specs.get(inst.name) or {}
        role = str(inst_spec.get("mix_role", "support")).lower()
        own_priority = int(priorities_cfg.get(role, priorities_cfg.get("support", 1)))
        target_gap = np.zeros(bins, dtype=np.int8)
        eligible = (
            group in duck_groups
            and group not in excluded_groups
            and group in outside_priority
            and bool(inst.notes)
        )
        if eligible:
            outside = outside_priority[group]
            for note in inst.notes:
                start = max(0, min(bins - 1, int(math.floor(note.start / hop_s))))
                end = max(start + 1, min(bins, int(math.ceil(note.end / hop_s))))
                pitch = max(0, min(127, int(note.pitch)))
                lo = max(0, pitch - pitch_radius)
                hi = min(128, pitch + pitch_radius + 1)
                if end <= start or hi <= lo:
                    continue
                higher = np.max(outside[start:end, lo:hi], axis=1)
                gap = np.maximum(higher.astype(np.int16) - own_priority, 0).astype(np.int8)
                target_gap[start:end] = np.maximum(target_gap[start:end], gap)

        target_db = -np.minimum(
            max_duck_db,
            target_gap.astype(np.float32) * duck_db_per_priority,
        )
        smoothed = _smooth_gain_db(
            target_db,
            hop_s=hop_s,
            attack_ms=attack_ms,
            release_ms=release_ms,
        )
        envelopes[inst.name] = smoothed
        ducked = smoothed < -0.25
        if group in group_duck_masks:
            group_duck_masks[group] |= ducked
            group_min_gain[group] = min(group_min_gain[group], float(np.min(smoothed)))
        report_instruments[inst.name] = {
            "group": group,
            "mix_role": role,
            "priority": own_priority,
            "ducked_seconds": round(float(np.count_nonzero(ducked) * hop_s), 3),
            "ducked_fraction": round(float(np.mean(ducked)) if ducked.size else 0.0, 6),
            "minimum_gain_db": round(float(np.min(smoothed)) if smoothed.size else 0.0, 3),
            "maximum_priority_gap": int(np.max(target_gap)) if target_gap.size else 0,
        }

    report_groups = {
        group: {
            "any_desk_ducked_seconds": round(float(np.count_nonzero(mask) * hop_s), 3),
            "any_desk_ducked_fraction": round(float(np.mean(mask)) if mask.size else 0.0, 6),
            "minimum_desk_gain_db": round(float(group_min_gain[group]), 3),
        }
        for group, mask in group_duck_masks.items()
    }
    report = {
        "enabled": True,
        "mode": "instrument_register",
        "max_duck_db": -max_duck_db,
        "duck_db_per_priority": -duck_db_per_priority,
        "pitch_radius_semitones": pitch_radius,
        "control_hop_ms": hop_ms,
        "attack_ms": attack_ms,
        "release_ms": release_ms,
        "role_priorities": priorities_cfg,
        "groups": report_groups,
        "instruments": report_instruments,
    }
    if not isinstance(cache, dict):
        cache = {}
        setattr(pm, "_ambition_instrument_register_protection_cache", cache)
    cache[cache_key] = (envelopes, report)
    return envelopes, report


def apply_instrument_foreground_protection(
    audio: np.ndarray,
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    instrument_name: str,
    sample_rate: int,
) -> np.ndarray:
    """Apply register-aware foreground protection to one rendered desk."""
    if audio.size == 0 or foreground_protection_mode(spec) not in {
        "instrument_register",
        "register",
        "desk_register",
    }:
        return audio.astype(np.float32, copy=False)
    cfg = dict(((spec.get("render") or {}).get("foreground_protection") or {}))
    group_names = sorted(set(groups.values()))
    duck_groups, excluded_groups = _configured_duck_groups(group_names, cfg)
    group = groups.get(instrument_name)
    if group not in duck_groups or group in excluded_groups:
        return audio.astype(np.float32, copy=False)
    duration_s = len(audio) / float(sample_rate) if sample_rate else 0.0
    envelopes, report = instrument_register_protection_gain_envelopes(
        pm, groups, spec, duration_s=duration_s
    )
    if not report.get("enabled"):
        return audio.astype(np.float32, copy=False)
    control_db = envelopes.get(instrument_name)
    if control_db is None or control_db.size == 0:
        return audio.astype(np.float32, copy=False)
    hop_frames = max(1, int(round(sample_rate * float(report["control_hop_ms"]) / 1000.0)))
    gain_db = np.repeat(control_db, hop_frames)[: len(audio)]
    if gain_db.size < len(audio):
        gain_db = np.pad(gain_db, (0, len(audio) - gain_db.size), mode="edge")
    gain = np.power(10.0, gain_db / 20.0).astype(np.float32)
    return (audio * gain[:, None]).astype(np.float32, copy=False)


def _smooth_gain_db(
    target_db: np.ndarray,
    *,
    hop_s: float,
    attack_ms: float,
    release_ms: float,
) -> np.ndarray:
    if target_db.size == 0:
        return target_db.astype(np.float32)
    attack_s = max(1e-4, float(attack_ms) / 1000.0)
    release_s = max(1e-4, float(release_ms) / 1000.0)
    attack_alpha = math.exp(-hop_s / attack_s)
    release_alpha = math.exp(-hop_s / release_s)
    out = np.empty_like(target_db, dtype=np.float32)
    current = 0.0
    for idx, target in enumerate(target_db.astype(float)):
        alpha = attack_alpha if target < current else release_alpha
        current = target + alpha * (current - target)
        out[idx] = current
    return out


def foreground_protection_gain_envelopes(
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    *,
    duration_s: float,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Build low-rate dB gain envelopes for role-priority ducking."""
    cfg = dict(((spec.get("render") or {}).get("foreground_protection") or {}))
    enabled = bool(cfg.get("enabled", False))
    group_names = sorted(set(groups.values()))
    if not enabled:
        return {group: np.zeros(1, dtype=np.float32) for group in group_names}, {
            "enabled": False,
            "groups": {},
        }

    max_duck_db = abs(float(cfg.get("max_duck_db", cfg.get("duck_db", -5.5))))
    duck_db_per_priority = abs(float(cfg.get("duck_db_per_priority", 2.75)))
    min_density_ratio = max(0.0, float(cfg.get("min_density_ratio", 1.0)))
    min_target_notes = max(1, int(cfg.get("min_target_notes", 1)))
    hop_ms = max(5.0, float(cfg.get("control_hop_ms", 20.0)))
    hop_s = hop_ms / 1000.0
    attack_ms = max(1.0, float(cfg.get("attack_ms", 30.0)))
    release_ms = max(1.0, float(cfg.get("release_ms", 180.0)))
    configured_groups = cfg.get("groups")
    duck_groups = set(map(str, configured_groups)) if configured_groups else set(group_names)
    excluded_groups = set(map(str, cfg.get("exclude_groups", ("percussion",))))
    priorities_cfg = _role_priorities_from_config(spec)

    priorities = build_group_role_priority(
        pm, groups, spec, duration_s=duration_s, hop_s=hop_s
    )
    note_counts = build_group_note_count(
        pm, groups, duration_s=duration_s, hop_s=hop_s
    )
    stack = np.stack(list(priorities.values()), axis=0) if priorities else np.full((1, 1), -1)
    global_priority = np.max(stack, axis=0)

    envelopes: dict[str, np.ndarray] = {}
    report_groups: dict[str, Any] = {}
    for group in group_names:
        own_priority = priorities[group]
        priority_gap = global_priority - own_priority
        active = own_priority >= 0
        priority_gap = np.where(active, np.maximum(priority_gap, 0), 0)
        own_count = note_counts[group].astype(np.float32)
        higher_count = np.zeros_like(own_count)
        for other_group, other_priority in priorities.items():
            if other_group == group:
                continue
            higher_count += np.where(
                other_priority > own_priority,
                note_counts[other_group],
                0,
            ).astype(np.float32)
        density_gate = (
            (higher_count > 0)
            & (own_count >= float(min_target_notes))
            & (own_count >= np.ceil(higher_count * min_density_ratio))
        )
        effective_gap = np.where(density_gate, priority_gap, 0)
        target = -np.minimum(max_duck_db, effective_gap.astype(np.float32) * duck_db_per_priority)
        if group not in duck_groups or group in excluded_groups:
            target[:] = 0.0
        smoothed = _smooth_gain_db(
            target.astype(np.float32),
            hop_s=hop_s,
            attack_ms=attack_ms,
            release_ms=release_ms,
        )
        envelopes[group] = smoothed
        ducked = smoothed < -0.25
        report_groups[group] = {
            "ducked_seconds": round(float(np.count_nonzero(ducked) * hop_s), 3),
            "ducked_fraction": round(float(np.mean(ducked)) if ducked.size else 0.0, 6),
            "minimum_gain_db": round(float(np.min(smoothed)) if smoothed.size else 0.0, 3),
            "maximum_priority_gap": int(np.max(priority_gap)) if priority_gap.size else 0,
            "maximum_effective_priority_gap": int(np.max(effective_gap)) if effective_gap.size else 0,
            "density_gate_fraction": round(float(np.mean(density_gate)) if density_gate.size else 0.0, 6),
        }

    report = {
        "enabled": True,
        "max_duck_db": -max_duck_db,
        "duck_db_per_priority": -duck_db_per_priority,
        "min_density_ratio": min_density_ratio,
        "min_target_notes": min_target_notes,
        "control_hop_ms": hop_ms,
        "attack_ms": attack_ms,
        "release_ms": release_ms,
        "role_priorities": priorities_cfg,
        "groups": report_groups,
    }
    return envelopes, report


def apply_foreground_protection(
    stem_audio: dict[str, np.ndarray],
    pm: pretty_midi.PrettyMIDI,
    groups: dict[str, str],
    spec: dict[str, Any],
    sample_rate: int,
) -> dict[str, Any]:
    """Apply score-authored foreground protection to group stem audio."""
    if not stem_audio:
        return {"enabled": False, "groups": {}}
    frame_count = max(len(audio) for audio in stem_audio.values())
    duration_s = frame_count / float(sample_rate) if sample_rate else 0.0
    if foreground_protection_mode(spec) in {"instrument_register", "register", "desk_register"}:
        # Instrument-register protection is applied while individual desks are
        # still separate inside render_group_audio. At group-mix time we only
        # reconstruct the score-derived report; another bus rider here would
        # double-duck the same material.
        _envelopes, report = instrument_register_protection_gain_envelopes(
            pm, groups, spec, duration_s=duration_s
        )
        return report
    envelopes_db, report = foreground_protection_gain_envelopes(
        pm, groups, spec, duration_s=duration_s
    )
    if not report.get("enabled"):
        return report
    hop_ms = float(report["control_hop_ms"])
    hop_frames = max(1, int(round(sample_rate * hop_ms / 1000.0)))
    for group, audio in list(stem_audio.items()):
        control_db = envelopes_db.get(group)
        if control_db is None or control_db.size == 0:
            continue
        gain_db = np.repeat(control_db, hop_frames)[: len(audio)]
        if gain_db.size < len(audio):
            gain_db = np.pad(gain_db, (0, len(audio) - gain_db.size), mode="edge")
        gain = np.power(10.0, gain_db / 20.0).astype(np.float32)
        stem_audio[group] = (audio * gain[:, None]).astype(np.float32, copy=False)
    return report

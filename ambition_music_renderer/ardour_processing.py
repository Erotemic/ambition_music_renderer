"""Compile canonical MusicIR processing plans into editable Ardour processors.

This module is an adapter, not a second processing language.  It consumes the
canonical :class:`ProcessingPlan` produced by ``processing.plans`` and maps
operations onto Ardour-native/LV2 processors where there is a useful editable
analogue.  Unsupported or analysis/offline-only operations remain explicit in
transport diagnostics instead of being silently approximated.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .audio_plugins import lv2_info
from .processing.catalog import canonical_pedalboard_effect_name
from .processing.model import ProcessingPlan
from .processing.plans import (
    processing_plan_for_group,
    processing_plan_for_master,
    processing_plan_for_section,
)


ACE_EQ_URI = "urn:ardour:a-eq"
ACE_COMPRESSOR_URI = "urn:ardour:a-comp"
ACE_REVERB_URI = "urn:ardour:a-reverb"
ACE_AMPLIFIER = "ACE Amplifier"
ACE_HILO_FILTER = "ACE High/Low Pass Filter"

# Stable public LV2 metadata for the Guitarix processors currently authored by
# Ambition.  Generic plugins still use lv2info; these are a deterministic
# fallback for environments where lv2info is not in PATH but the LV2 bundles
# are visible to Ardour.
_KNOWN_LV2_CONTROL_ORDINALS: dict[str, dict[str, int]] = {
    "http://guitarix.sourceforge.net/plugins/gxts9#ts9sim": {
        "fslider0_": 0,
        "fslider1_": 1,
        "fslider2_": 2,
        "BYPASS": 3,
    },
    "http://guitarix.sourceforge.net/plugins/gx_jcm800pre_st#_jcm800pre_st": {
        "P6v": 0,
        "Middle": 1,
        "Bass": 2,
        "Treble": 3,
        "WET_DRY": 4,
        "GAIN": 5,
    },
}


@dataclass(frozen=True)
class ArdourProcessorSpec:
    source_processor: str
    host_kind: str  # ``lv2`` or ``luaproc``
    plugin: str
    parameters: tuple[tuple[int, float], ...] = ()
    fidelity: str = "close"
    required: bool = True
    note: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return self.host_kind, self.plugin

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_processor": self.source_processor,
            "host_kind": self.host_kind,
            "plugin": self.plugin,
            "parameters": [[idx, value] for idx, value in self.parameters],
            "fidelity": self.fidelity,
            "required": self.required,
            "note": self.note,
        }


@dataclass(frozen=True)
class ArdourRouteProcessingPlan:
    route_name: str
    stage: str
    processors: tuple[ArdourProcessorSpec, ...]
    omitted: tuple[str, ...] = ()
    source_fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route_name,
            "stage": self.stage,
            "processors": [p.as_dict() for p in self.processors],
            "omitted": list(self.omitted),
            "source_fingerprint": self.source_fingerprint,
        }


@dataclass(frozen=True)
class ArdourProcessingTransportPlan:
    groups: Mapping[str, ArdourRouteProcessingPlan]
    master: ArdourRouteProcessingPlan
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "ambition.ardour_processing_transport.v1",
            "groups": {group: plan.as_dict() for group, plan in self.groups.items()},
            "master": self.master.as_dict(),
            "warnings": list(self.warnings),
        }


def group_bus_name(group: str) -> str:
    return f"AMB Group {group}"


COMPOSITION_BUS_NAME = "AMB Composition"


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _q_to_ace_bandwidth(q: float) -> float:
    # ACE EQ exposes bandwidth rather than Q.  The reciprocal is a useful local
    # approximation over the broad, low-Q mix bands used by Ambition.
    return _clamp(1.0 / max(float(q), 1e-6), 0.1, 4.0)


def _compressor_spec(p: Mapping[str, Any], *, source: str = "compressor") -> ArdourProcessorSpec:
    # ACE Compressor nth-parameter order: Attack, Release, Knee, Ratio,
    # Threshold, Makeup.
    return ArdourProcessorSpec(
        source_processor=source,
        host_kind="lv2",
        plugin=ACE_COMPRESSOR_URI,
        parameters=(
            (0, float(p.get("attack_ms", 10.0))),
            (1, float(p.get("release_ms", 100.0))),
            (2, float(p.get("knee_db", 6.0))),
            (3, float(p.get("ratio", 3.0))),
            (4, float(p.get("threshold_db", -18.0))),
            (5, float(p.get("makeup_db", 0.0))),
        ),
        fidelity="close",
        note="Same authored compressor controls; detector/envelope implementation is Ardour ACE.",
    )


def _reverb_spec(p: Mapping[str, Any], *, source: str = "reverb") -> ArdourProcessorSpec:
    wet = _clamp(float(p.get("wet", 0.18)), 0.0, 1.0)
    decay = max(0.0, float(p.get("decay_seconds", 1.4)))
    # ACE Reverb exposes Blend + Room Size rather than RT60/damping.  Preserve
    # wet level exactly and map RT60 monotonically into the useful room range.
    room_size = _clamp(0.5 + 0.5 * (1.0 - math.exp(-decay / 1.5)), 0.5, 1.0)
    return ArdourProcessorSpec(
        source_processor=source,
        host_kind="lv2",
        plugin=ACE_REVERB_URI,
        parameters=((0, wet), (1, room_size), (2, 1.0)),
        fidelity="approximate",
        note="Wet level is preserved; renderer RT60/damping are approximated by ACE Room Size.",
    )


def _filter_spec(name: str, cutoff: float) -> ArdourProcessorSpec:
    # ACE HP/LP processor parameter order:
    # hp order, hp cutoff, hp resonance, lp order, lp cutoff, lp resonance, enable.
    if name == "highpass":
        params = ((0, 1.0), (1, float(cutoff)), (2, 0.707), (3, 0.0), (6, 1.0))
    else:
        params = ((0, 0.0), (3, 1.0), (4, float(cutoff)), (5, 0.707), (6, 1.0))
    return ArdourProcessorSpec(
        source_processor=name,
        host_kind="luaproc",
        plugin=ACE_HILO_FILTER,
        parameters=params,
        fidelity="close",
        note="12 dB/oct Ardour filter mirrors the renderer's default second-order cutoff closely.",
    )


def _eq_spec_from_bands(bands: list[Mapping[str, Any]], *, source: str) -> list[ArdourProcessorSpec]:
    """Map shelves + up to four bell bands per ACE EQ instance."""
    specs: list[ArdourProcessorSpec] = []
    pending = [dict(b) for b in bands]
    while pending:
        params: dict[int, float] = {}
        peaks: list[dict[str, Any]] = []
        leftovers: list[dict[str, Any]] = []
        low_used = False
        high_used = False
        for band in pending:
            kind = str(band.get("type") or band.get("kind") or band.get("shape") or "peak").lower().replace("-", "_")
            hz = float(band.get("hz") or band.get("freq") or band.get("frequency_hz") or 1000.0)
            db = float(band.get("db") if band.get("db") is not None else band.get("gain_db", 0.0))
            if kind in {"low_shelf", "lowshelf", "shelf_low"} and not low_used:
                params[0] = hz
                params[1] = db
                low_used = True
            elif kind in {"high_shelf", "highshelf", "shelf_high"} and not high_used:
                params[14] = hz
                params[15] = db
                high_used = True
            elif len(peaks) < 4:
                peaks.append(band)
            else:
                leftovers.append(band)
        for index, band in enumerate(peaks):
            base = 2 + index * 3
            hz = float(band.get("hz") or band.get("freq") or band.get("frequency_hz") or 1000.0)
            db = float(band.get("db") if band.get("db") is not None else band.get("gain_db", 0.0))
            q = float(band.get("q") or band.get("Q") or 0.707)
            params[base] = hz
            params[base + 1] = db
            params[base + 2] = _q_to_ace_bandwidth(q)
        if params:
            specs.append(
                ArdourProcessorSpec(
                    source_processor=source,
                    host_kind="lv2",
                    plugin=ACE_EQ_URI,
                    parameters=tuple(sorted(params.items())),
                    fidelity="close",
                    note="Frequencies/gains preserved; renderer Q is mapped to ACE bandwidth.",
                )
            )
        pending = leftovers
        if not params and pending:
            break
    return specs


def _parse_lv2info_control_ordinals(text: str) -> dict[str, int]:
    ports: list[tuple[int, str, str]] = []
    current_index: int | None = None
    current_symbol: str | None = None
    current_type = ""
    for line in text.splitlines() + ["Port END:"]:
        match = re.match(r"\s*Port\s+(\d+)\s*:", line)
        if match or line.startswith("Port END"):
            if current_index is not None and current_symbol:
                ports.append((current_index, current_symbol, current_type))
            if match:
                current_index = int(match.group(1))
                current_symbol = None
                current_type = ""
            else:
                current_index = None
            continue
        if current_index is None:
            continue
        m = re.match(r"\s*Symbol:\s*(\S+)", line)
        if m:
            current_symbol = m.group(1).strip('"')
        m = re.match(r"\s*Type:\s*(.*)", line)
        if m:
            current_type += " " + m.group(1)
    controls = [row for row in sorted(ports) if "Control" in row[2]]
    return {symbol: ordinal for ordinal, (_idx, symbol, _type) in enumerate(controls)}


def _lv2_param_ordinals(uri: str, param_names: list[str]) -> tuple[dict[str, int], str | None]:
    known = _KNOWN_LV2_CONTROL_ORDINALS.get(uri)
    if known is not None and all(name in known for name in param_names):
        return dict(known), None
    info = lv2_info(uri)
    if not info.get("ok"):
        return {}, str(info.get("error") or info.get("stderr") or "lv2info failed")
    mapping = _parse_lv2info_control_ordinals(str(info.get("stdout") or ""))
    missing = [name for name in param_names if name not in mapping]
    if missing:
        return mapping, f"lv2info did not expose control symbol(s): {', '.join(missing)}"
    return mapping, None


def _translate_pedalboard_effect(raw: Mapping[str, Any]) -> tuple[list[ArdourProcessorSpec], list[str]]:
    row = dict(raw)
    effect = canonical_pedalboard_effect_name(str(row.get("effect") or row.get("processor") or row.get("kind") or ""))
    if effect == "gain":
        return [ArdourProcessorSpec(
            source_processor="pedalboard.gain",
            host_kind="luaproc",
            plugin=ACE_AMPLIFIER,
            parameters=((0, float(row.get("gain_db", 0.0))),),
            fidelity="exact",
        )], []
    if effect == "compressor":
        p = dict(row)
        p.setdefault("makeup_db", 0.0)
        p.setdefault("knee_db", 6.0)
        return [_compressor_spec(p, source="pedalboard.compressor")], []
    if effect in {"highpass", "lowpass"}:
        return [_filter_spec(effect, float(row.get("cutoff_hz", 80.0 if effect == "highpass" else 9000.0)))], []
    return [], [f"pedalboard effect {effect!r} has no Ardour transport yet"]


def translate_processing_plan(plan: ProcessingPlan) -> tuple[tuple[ArdourProcessorSpec, ...], tuple[str, ...]]:
    out: list[ArdourProcessorSpec] = []
    omitted: list[str] = []
    for op in plan.operations:
        name = op.processor
        p = dict(op.parameters)
        if name == "gain":
            out.append(ArdourProcessorSpec(
                source_processor="gain",
                host_kind="luaproc",
                plugin=ACE_AMPLIFIER,
                parameters=((0, float(p.get("gain_db", 0.0))),),
                fidelity="exact",
            ))
        elif name in {"highpass", "lowpass"}:
            out.append(_filter_spec(name, float(p.get("cutoff_hz", p.get("hz", 80.0 if name == "highpass" else 9000.0)))))
        elif name == "compressor":
            out.append(_compressor_spec(p))
        elif name == "reverb":
            out.append(_reverb_spec(p))
        elif name == "high_shelf":
            out.extend(_eq_spec_from_bands([{"type": "high_shelf", "hz": p.get("hz", 4500.0), "db": p.get("gain_db", p.get("db", 0.0)), "q": 0.707}], source="high_shelf"))
        elif name == "band_gain":
            low = max(20.0, float(p.get("low_hz", 2000.0)))
            high = max(low * 1.001, float(p.get("high_hz", 4500.0)))
            center = math.sqrt(low * high)
            bandwidth_oct = max(math.log2(high / low), 0.25)
            q = max(0.25, 1.0 / bandwidth_oct)
            out.extend(_eq_spec_from_bands([{"type": "peak", "hz": center, "db": p.get("gain_db", p.get("db", 0.0)), "q": q}], source="band_gain"))
        elif name == "parametric_eq":
            out.extend(_eq_spec_from_bands(list(p.get("bands") or []), source="parametric_eq"))
        elif name == "pedalboard":
            wet = float(p.get("wet_mix", 1.0))
            if abs(wet - 1.0) > 1e-9:
                omitted.append(f"pedalboard chain wet_mix={wet:g} is not represented separately in Ardour")
            for effect in p.get("effects") or []:
                specs, notes = _translate_pedalboard_effect(effect)
                out.extend(specs)
                omitted.extend(notes)
        elif name == "lv2":
            uri = str(p.get("plugin_uri") or "")
            params = dict(p.get("params") or {})
            required = bool(p.get("required", not bool(p.get("optional", False))))
            if not uri:
                omitted.append("LV2 operation has no plugin_uri")
                continue
            ordinals, error = _lv2_param_ordinals(uri, [str(k) for k in params])
            if error and params:
                omitted.append(f"LV2 {uri}: {error}; parameterized transport omitted")
                continue
            values = tuple(sorted((ordinals[str(key)], float(value)) for key, value in params.items()))
            wet = float(p.get("wet_mix", 1.0))
            note = None
            fidelity = "exact"
            if abs(wet - 1.0) > 1e-9:
                fidelity = "approximate"
                note = f"Plugin/parameters preserved, but renderer wet_mix={wet:g} becomes a serial Ardour insert."
            out.append(ArdourProcessorSpec(
                source_processor="lv2",
                host_kind="lv2",
                plugin=uri,
                parameters=values,
                fidelity=fidelity,
                required=required,
                note=note,
            ))
        elif name in {"transient_tame", "stereo_width", "limiter", "loudness", "vst3", "command"}:
            omitted.append(f"{name}: no faithful realtime Ardour transport yet")
        else:
            omitted.append(f"{name}: unsupported Ardour processing transport")
    return tuple(out), tuple(omitted)


def compile_processing_transport(compiled: Any) -> ArdourProcessingTransportPlan:
    groups_in_order = list(dict.fromkeys(str(group) for group in compiled.groups.values()))
    group_plans: dict[str, ArdourRouteProcessingPlan] = {}
    warnings: list[str] = []
    for group in groups_in_order:
        source_plan = processing_plan_for_group(compiled.normalized_spec, group)
        processors, omitted = translate_processing_plan(source_plan)
        group_plans[group] = ArdourRouteProcessingPlan(
            route_name=group_bus_name(group),
            stage="group_stem",
            processors=processors,
            omitted=omitted,
            source_fingerprint=source_plan.fingerprint(),
        )
        warnings.extend(f"{group}: {item}" for item in omitted)
    source_master = processing_plan_for_master(compiled.normalized_spec)
    master_processors, master_omitted = translate_processing_plan(source_master)
    master = ArdourRouteProcessingPlan(
        route_name="Master",
        stage="master",
        processors=master_processors,
        omitted=master_omitted,
        source_fingerprint=source_master.fingerprint(),
    )
    warnings.extend(f"master: {item}" for item in master_omitted)

    # Canonical section-bus DSP sits after the section mix rider but before the
    # one composition master. A static Ardour processor chain cannot express a
    # different chain per time range without automation/bypass semantics, so
    # report these plans explicitly rather than silently dropping them.
    for section in compiled.sections:
        section_id = str(section.get("id") or "")
        if not section_id:
            continue
        section_plan = processing_plan_for_section(compiled.normalized_spec, section_id)
        if section_plan is not None and section_plan.operations:
            warnings.append(
                f"section {section_id}: section-bus ProcessingPlan is not transported yet"
            )

    return ArdourProcessingTransportPlan(groups=group_plans, master=master, warnings=tuple(warnings))

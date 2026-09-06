"""Source-oriented validation for MusicIR v3 authoring graphs.

This is intentionally narrower than compilation.  It catches mistakes that can
be explained directly in terms of the authored YAML and leaves musical lowering
and renderer semantics to the canonical compiler.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from ..instrument_catalog import instrument_catalog
from ..instrument_resolution import backend_spec_from_instrument
from ..musicir.automation import AUTOMATION_INTERPOLATIONS
from ..musicir.generators import generator_specs
from ..musicir.graph import fraction_to_ticks
from ..musicir.pitch import GM_DRUM_NOTES, PITCH_KINDS, SCALE_INTERVALS
from ..render.score_core import CC_NUMBERS, controller_number
from ..technique_catalog import technique_specs, canonical_technique_name
from .diagnostics import (
    Diagnostic,
    SourceLocation,
    SourcePath,
    diagnostic,
    suggest_name,
    unknown_field_hint,
)


# Renderer/mix metadata is accepted at the source root even though it is not
# part of the v3 authoring graph.  These fields are consumed after compilation.
TOP_LEVEL_FIELDS = {
    "schema",
    "id",
    "title",
    "description",
    "notes",
    "seed",
    "timebase",
    "ppq",
    "meter",
    "tempo",
    "form",
    "end",
    "harmony",
    "instruments",
    "materials",
    "parts",
    "render",
    "postprocess",
    "processing",
    "stem_postprocess",
    "group_postprocess",
    "constraints",
    "playback",
    "state_map",
    "authoring",
    "provenance",
    "one_shot",
    "duration_target_seconds",
    "key",
}
PART_FIELDS = {"id", "instrument", "voices", "controls", "group", "technique_map"}
VOICE_FIELDS = {"id", "clips"}
CLIP_FIELDS = {
    "id",
    "at",
    "duration",
    "bars",
    "events",
    "use",
    "generate",
    "repeat",
    "transpose",
    "octave",
    "velocity_scale",
    "velocity_offset",
    "gate",
    "time_scale",
    "automation",
    "technique",
    "articulation",
    "instrument",
}
EVENT_FIELDS = {
    "id",
    "at",
    "dur",
    "duration",
    "pitch",
    "pitches",
    "velocity",
    "gate",
    "technique",
    "articulation",
    "instrument",
}
AUTOMATION_FIELDS = {
    "id", "at", "cc", "controller", "value", "pitch_bend", "bend", "instrument",
    "points", "interpolation", "curve", "resolution", "step",
}
MATERIAL_COMMON_FIELDS = {"id", "kind"}
MATERIAL_EVENT_FIELDS = MATERIAL_COMMON_FIELDS | {"events"}
MATERIAL_SEQUENCE_FIELDS = MATERIAL_COMMON_FIELDS | {"items"}
MATERIAL_SEQUENCE_ITEM_FIELDS = {
    "id", "use", "at", "repeat", "transpose", "octave", "velocity_scale",
    "velocity_offset", "gate", "time_scale", "technique", "articulation",
}
# Motif material is intentionally compatible with the established v1 motif
# performer; keep this set explicit so source errors do not disappear into that
# compatibility bridge.
MATERIAL_MOTIF_FIELDS = MATERIAL_COMMON_FIELDS | {
    "root",
    "intervals",
    "rhythm",
    "durations",
    "velocities",
    "articulation",
}
FORM_FIELDS = {
    "id", "from", "to", "bars", "start_tick", "end_tick", "label",
    "energy", "intensity", "density", "variation", "role", "loopable", "notes",
}
HARMONY_FIELDS = {"progression", "events", "start_bar", "every_bars", "cycle"}
HARMONY_EVENT_FIELDS = {"at", "bar", "beat", "tick", "chord", "harmony"}
TIMEBASE_FIELDS = {"ppq"}
KEY_FIELDS = {"tonic", "root", "mode"}
POSITION_FIELDS = {"bar", "beat", "tick", "offset"}
REPEAT_FIELDS = {"count", "every"}
DURATION_FIELDS = {"bars", "beats", "ticks"}



def _mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _list(value: Any) -> bool:
    return isinstance(value, list)


def _unknown_fields(
    row: Mapping[str, Any],
    allowed: Iterable[str],
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    code: str,
    subject: str,
) -> list[Diagnostic]:
    allowed_set = set(allowed)
    result: list[Diagnostic] = []
    for key in row:
        if key in allowed_set:
            continue
        result.append(
            diagnostic(
                code,
                f"unknown {subject} field `{key}`",
                path=(*path, str(key)),
                locations=locations,
                hint=unknown_field_hint(str(key), allowed_set),
            )
        )
    return result


def _missing(
    row: Mapping[str, Any],
    key: str,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    code: str,
    subject: str,
) -> Diagnostic | None:
    if key in row and row.get(key) not in (None, ""):
        return None
    return diagnostic(
        code,
        f"{subject} requires `{key}`",
        path=path,
        locations=locations,
        hint=f"add `{key}: ...` to this {subject}",
    )


def _unique_ids(
    rows: list[Any],
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    subject: str,
    code_prefix: str,
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    seen: dict[str, int] = {}
    for idx, raw in enumerate(rows):
        if not _mapping(raw):
            result.append(
                diagnostic(
                    f"{code_prefix}_TYPE",
                    f"{subject} entry must be a mapping",
                    path=(*path, idx),
                    locations=locations,
                )
            )
            continue
        value = str(raw.get("id", "")).strip()
        if not value:
            result.append(
                diagnostic(
                    f"{code_prefix}_ID",
                    f"every {subject} entry needs a stable `id`",
                    path=(*path, idx),
                    locations=locations,
                )
            )
            continue
        if value in seen:
            first = seen[value]
            result.append(
                diagnostic(
                    f"{code_prefix}_DUPLICATE_ID",
                    f"duplicate {subject} id `{value}`; first declared at index {first}",
                    path=(*path, idx, "id"),
                    locations=locations,
                    hint=f"give this {subject} a unique stable id",
                )
            )
        else:
            seen[value] = idx
    return result


def _validate_position(
    value: Any,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    code: str = "V3_POSITION",
) -> list[Diagnostic]:
    if isinstance(value, (int, float, str)):
        return []
    if not _mapping(value):
        return [
            diagnostic(
                code,
                "position must be a score position mapping or scalar tick/time expression",
                path=path,
                locations=locations,
            )
        ]
    result = _unknown_fields(
        value,
        POSITION_FIELDS,
        path=path,
        locations=locations,
        code=f"{code}_FIELD",
        subject="position",
    )
    if "bar" in value:
        try:
            if int(value["bar"]) < 1:
                raise ValueError
        except Exception:
            result.append(
                diagnostic(
                    code,
                    "position `bar` must be an integer >= 1",
                    path=(*path, "bar"),
                    locations=locations,
                )
            )
    return result


def _validate_duration(
    value: Any,
    *,
    ppq: int,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    allow_bars: bool = False,
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    if _mapping(value):
        allowed = DURATION_FIELDS if allow_bars else {"beats", "ticks"}
        result.extend(
            _unknown_fields(
                value,
                allowed,
                path=path,
                locations=locations,
                code="V3_DURATION_FIELD",
                subject="duration",
            )
        )
        if allow_bars and "bars" in value:
            try:
                if int(value["bars"]) <= 0:
                    raise ValueError
            except Exception:
                result.append(
                    diagnostic(
                        "V3_DURATION",
                        "duration `bars` must be a positive integer",
                        path=(*path, "bars"),
                        locations=locations,
                    )
                )
            return result
    try:
        ticks = fraction_to_ticks(value, ppq=ppq)
        if ticks <= 0:
            raise ValueError("duration must be positive")
    except Exception as ex:
        result.append(
            diagnostic(
                "V3_DURATION",
                f"invalid exact musical duration: {ex}",
                path=path,
                locations=locations,
                hint="use integer ticks, a fraction such as `1/4`, or `{beats: N}` / `{ticks: N}`",
            )
        )
    return result


def _pitch_mapping_kind(value: Mapping[str, Any]) -> str:
    kind = str(value.get("kind", "")).strip()
    if kind:
        return kind
    for candidate in PITCH_KINDS:
        if candidate in value:
            return candidate
    return ""


def _validate_pitch(
    value: Any,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    has_harmony: bool,
) -> list[Diagnostic]:
    if isinstance(value, bool):
        return [diagnostic("V3_PITCH", "boolean is not a pitch", path=path, locations=locations)]
    if isinstance(value, int):
        if 0 <= value <= 127:
            return []
        return [
            diagnostic(
                "V3_PITCH_RANGE",
                f"MIDI pitch {value} is outside 0..127",
                path=path,
                locations=locations,
            )
        ]
    if isinstance(value, str):
        # Note spelling itself is validated by compilation; static validation
        # still catches accidental structured values here.
        return []
    if not _mapping(value):
        return [
            diagnostic(
                "V3_PITCH",
                "pitch must be a MIDI integer, note name, or explicit pitch mapping",
                path=path,
                locations=locations,
            )
        ]
    kind = _pitch_mapping_kind(value)
    if kind not in PITCH_KINDS:
        suggestion = suggest_name(kind, PITCH_KINDS) if kind else None
        hint = f"did you mean `{suggestion}`?" if suggestion else f"expected one of {list(PITCH_KINDS)}"
        return [
            diagnostic(
                "V3_PITCH_KIND",
                f"unknown pitch kind `{kind}`",
                path=(*path, "kind") if "kind" in value else path,
                locations=locations,
                hint=hint,
            )
        ]
    result: list[Diagnostic] = []
    harmony_kinds = {"harmony_root", "chord_tone"}
    if kind in harmony_kinds and not has_harmony:
        result.append(
            diagnostic(
                "V3_PITCH_HARMONY",
                f"pitch kind `{kind}` needs score harmony",
                path=path,
                locations=locations,
                hint="add top-level `harmony:` or use an absolute/scale-relative pitch",
            )
        )
    if kind == "scale_degree":
        mode = str(value.get("mode", "major")).lower().replace("-", "_")
        if mode not in SCALE_INTERVALS:
            suggestion = suggest_name(mode, SCALE_INTERVALS)
            result.append(
                diagnostic(
                    "V3_SCALE_MODE",
                    f"unknown scale mode `{mode}`",
                    path=(*path, "mode"),
                    locations=locations,
                    hint=(f"did you mean `{suggestion}`?" if suggestion else f"known modes: {', '.join(sorted(SCALE_INTERVALS))}"),
                )
            )
    if kind == "drum":
        name = str(value.get("name", value.get("value", ""))).lower().replace("-", "_").replace(" ", "_")
        if name not in GM_DRUM_NOTES:
            suggestion = suggest_name(name, GM_DRUM_NOTES)
            result.append(
                diagnostic(
                    "V3_DRUM_NAME",
                    f"unknown GM percussion name `{name}`",
                    path=(*path, "name"),
                    locations=locations,
                    hint=(f"did you mean `{suggestion}`?" if suggestion else None),
                )
            )
    if kind == "guitar_fret":
        if value.get("string", value.get("open")) is None:
            result.append(
                diagnostic(
                    "V3_GUITAR_STRING",
                    "guitar_fret pitch needs `string`/`open`, e.g. `A2`",
                    path=path,
                    locations=locations,
                )
            )
        try:
            if int(value.get("fret", 0)) < 0:
                raise ValueError
        except Exception:
            result.append(
                diagnostic(
                    "V3_GUITAR_FRET",
                    "guitar fret must be an integer >= 0",
                    path=(*path, "fret"),
                    locations=locations,
                )
            )
    if kind in {"chord_tone", "scale_degree"}:
        try:
            if int(value.get("degree", 1)) == 0:
                raise ValueError
        except Exception:
            result.append(
                diagnostic(
                    "V3_DEGREE",
                    "musical degrees are one-based; degree 0 is invalid",
                    path=(*path, "degree"),
                    locations=locations,
                )
            )
    return result


def _validate_technique(
    value: Any,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    custom_names: Iterable[str] = (),
) -> list[Diagnostic]:
    name = str(value).strip()
    if not name:
        return [diagnostic("V3_TECHNIQUE", "technique name must not be empty", path=path, locations=locations)]
    if name in set(map(str, custom_names)):
        return []
    try:
        canonical_technique_name(name)
        return []
    except ValueError:
        known = set(technique_specs()) | {alias for spec in technique_specs().values() for alias in spec.aliases}
        suggestion = suggest_name(name, known)
        return [diagnostic(
            "V3_TECHNIQUE",
            f"unknown technique `{name}`",
            path=path,
            locations=locations,
            hint=(f"did you mean `{suggestion}`?" if suggestion else "use a checked-in technique name or add an explicit part.technique_map entry"),
        )]


def _validate_event(
    raw: Any,
    *,
    ppq: int,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    has_harmony: bool,
    custom_techniques: Iterable[str] = (),
) -> list[Diagnostic]:
    if isinstance(raw, (list, tuple)):
        if len(raw) < 4:
            return [
                diagnostic(
                    "V3_EVENT_COMPACT",
                    "compact event needs `[at, dur, pitch-or-pitches, velocity]`",
                    path=path,
                    locations=locations,
                )
            ]
        row = {"at": raw[0], "dur": raw[1], "pitch": raw[2], "velocity": raw[3]}
        compact = True
    elif _mapping(raw):
        row = raw
        compact = False
    else:
        return [
            diagnostic(
                "V3_EVENT_TYPE",
                "event must be a mapping or compact event list",
                path=path,
                locations=locations,
            )
        ]
    result: list[Diagnostic] = []
    if not compact:
        result.extend(
            _unknown_fields(
                row,
                EVENT_FIELDS,
                path=path,
                locations=locations,
                code="V3_EVENT_FIELD",
                subject="event",
            )
        )
    if "at" not in row:
        result.append(diagnostic("V3_EVENT_AT", "event requires `at`", path=path, locations=locations))
    dur_key = "dur" if "dur" in row else "duration" if "duration" in row else None
    if dur_key is None:
        result.append(diagnostic("V3_EVENT_DURATION", "event requires `dur`/`duration`", path=path, locations=locations))
    else:
        result.extend(_validate_duration(row[dur_key], ppq=ppq, path=(*path, dur_key), locations=locations))
    pitch_key = "pitches" if "pitches" in row else "pitch" if "pitch" in row else None
    if pitch_key is None:
        result.append(diagnostic("V3_EVENT_PITCH", "event requires `pitch` or `pitches`", path=path, locations=locations))
    else:
        values = row[pitch_key] if pitch_key == "pitches" else [row[pitch_key]]
        if pitch_key == "pitches" and not isinstance(values, (list, tuple)):
            result.append(diagnostic("V3_EVENT_PITCH", "`pitches` must be a list", path=(*path, pitch_key), locations=locations))
        else:
            for idx, pitch in enumerate(values):
                pitch_path = (*path, pitch_key, idx) if pitch_key == "pitches" else (*path, pitch_key)
                result.extend(_validate_pitch(pitch, path=pitch_path, locations=locations, has_harmony=has_harmony))
    if "velocity" in row:
        try:
            velocity = int(row["velocity"])
            if not 1 <= velocity <= 127:
                raise ValueError
        except Exception:
            result.append(
                diagnostic(
                    "V3_VELOCITY",
                    "event velocity must be an integer in 1..127",
                    path=(*path, "velocity"),
                    locations=locations,
                )
            )
    technique_key = "technique" if "technique" in row else "articulation" if "articulation" in row else None
    if technique_key:
        result.extend(_validate_technique(
            row[technique_key],
            path=(*path, technique_key),
            locations=locations,
            custom_names=custom_techniques,
        ))
    return result


def _validate_automation(
    raw: Any,
    *,
    ppq: int,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
) -> list[Diagnostic]:
    if not _mapping(raw):
        return [diagnostic("V3_AUTOMATION_TYPE", "automation item must be a mapping", path=path, locations=locations)]
    row = raw
    result = _unknown_fields(
        row,
        AUTOMATION_FIELDS,
        path=path,
        locations=locations,
        code="V3_AUTOMATION_FIELD",
        subject="automation",
    )
    if not str(row.get("id", "")).strip():
        result.append(diagnostic(
            "V3_AUTOMATION_ID",
            "automation item needs a stable `id` for source provenance",
            path=path, locations=locations,
        ))
    has_cc = "cc" in row or "controller" in row
    has_bend = "pitch_bend" in row or "bend" in row
    if has_cc == has_bend:
        result.append(diagnostic(
            "V3_AUTOMATION_KIND",
            "automation item must define exactly one of `cc` or `pitch_bend`",
            path=path, locations=locations,
        ))
    if has_cc:
        cc_key = "cc" if "cc" in row else "controller"
        cc = row[cc_key]
        try:
            controller_number(cc)
        except Exception:
            name = str(cc).strip().lower()
            suggestion = suggest_name(name, CC_NUMBERS)
            code = "V3_CC_NAME" if not name.isdigit() else "V3_CC_NUMBER"
            result.append(diagnostic(
                code,
                f"unknown controller `{cc}`" if code == "V3_CC_NAME" else "MIDI CC must be in 0..127",
                path=(*path, cc_key), locations=locations,
                hint=(f"did you mean `{suggestion}`?" if suggestion else "use a MIDI CC number 0..127 or a supported controller name"),
            ))
    is_curve = "points" in row
    if is_curve:
        points = row.get("points")
        if not isinstance(points, list) or len(points) < 2:
            result.append(diagnostic(
                "V3_AUTOMATION_CURVE_POINTS",
                "automation curve requires at least two `points`",
                path=(*path, "points"), locations=locations,
            ))
        else:
            seen_ticks: set[int] = set()
            for idx, point in enumerate(points):
                point_path = (*path, "points", idx)
                if isinstance(point, (list, tuple)) and len(point) == 2:
                    at, value = point
                elif _mapping(point) and "at" in point and "value" in point:
                    at, value = point["at"], point["value"]
                else:
                    result.append(diagnostic(
                        "V3_AUTOMATION_CURVE_POINT",
                        "curve point needs `[at, value]` or `{at: ..., value: ...}`",
                        path=point_path, locations=locations,
                    ))
                    continue
                try:
                    tick = fraction_to_ticks(at, ppq=ppq)
                    if tick in seen_ticks:
                        result.append(diagnostic(
                            "V3_AUTOMATION_CURVE_AT",
                            "curve point positions must be unique",
                            path=point_path, locations=locations,
                        ))
                    seen_ticks.add(tick)
                except Exception as ex:
                    result.append(diagnostic(
                        "V3_AUTOMATION_CURVE_AT", f"invalid curve position: {ex}",
                        path=point_path, locations=locations,
                    ))
                try:
                    number = int(value)
                    lo, hi = ((0, 127) if has_cc else (-8192, 8191))
                    if not lo <= number <= hi:
                        raise ValueError
                except Exception:
                    result.append(diagnostic(
                        "V3_CC_VALUE" if has_cc else "V3_PITCH_BEND",
                        "curve value must be in 0..127" if has_cc else "curve pitch bend must be in -8192..8191",
                        path=point_path, locations=locations,
                    ))
        interpolation = str(row.get("interpolation", row.get("curve", "linear"))).lower()
        if interpolation not in AUTOMATION_INTERPOLATIONS:
            suggestion = suggest_name(interpolation, AUTOMATION_INTERPOLATIONS)
            result.append(diagnostic(
                "V3_AUTOMATION_INTERPOLATION",
                f"unknown automation interpolation `{interpolation}`",
                path=(*path, "interpolation") if "interpolation" in row else path,
                locations=locations,
                hint=(f"did you mean `{suggestion}`?" if suggestion else f"use one of {list(AUTOMATION_INTERPOLATIONS)}"),
            ))
        resolution = row.get("resolution", row.get("step", "1/32"))
        try:
            if fraction_to_ticks(resolution, ppq=ppq) <= 0:
                raise ValueError
        except Exception:
            result.append(diagnostic(
                "V3_AUTOMATION_RESOLUTION",
                "automation curve resolution must be an exact duration > 0",
                path=(*path, "resolution") if "resolution" in row else path, locations=locations,
            ))
    else:
        if "at" not in row:
            result.append(diagnostic("V3_AUTOMATION_AT", "automation point requires `at`", path=path, locations=locations))
        if has_cc:
            if "value" not in row:
                result.append(diagnostic("V3_CC_VALUE", "CC automation requires `value`", path=path, locations=locations))
            else:
                try:
                    value = int(row["value"])
                    if not 0 <= value <= 127:
                        raise ValueError
                except Exception:
                    result.append(diagnostic("V3_CC_VALUE", "CC value must be in 0..127", path=(*path, "value"), locations=locations))
        if has_bend:
            bend_key = "pitch_bend" if "pitch_bend" in row else "bend"
            try:
                bend = int(row[bend_key])
                if not -8192 <= bend <= 8191:
                    raise ValueError
            except Exception:
                result.append(diagnostic("V3_PITCH_BEND", "pitch bend must be in -8192..8191", path=(*path, bend_key), locations=locations))
    return result


def _validate_generator(
    value: Any,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
    materials: Mapping[str, Any],
    has_harmony: bool,
) -> list[Diagnostic]:
    if not _mapping(value):
        return [diagnostic("V3_GENERATOR_TYPE", "`generate` must be a mapping", path=path, locations=locations)]
    specs = generator_specs()
    kind = str(value.get("kind", "")).strip()
    if kind not in specs:
        suggestion = suggest_name(kind, specs)
        return [
            diagnostic(
                "V3_GENERATOR_KIND",
                f"unknown generator kind `{kind}`",
                path=(*path, "kind"),
                locations=locations,
                hint=(f"did you mean `{suggestion}`?" if suggestion else f"known generators: {', '.join(sorted(specs))}"),
            )
        ]
    spec = specs[kind]
    allowed = {"kind", *spec.parameters}
    result = _unknown_fields(
        value,
        allowed,
        path=path,
        locations=locations,
        code="V3_GENERATOR_FIELD",
        subject=f"{kind} generator",
    )
    for name, meta in spec.parameters.items():
        if meta.get("required") and name not in value:
            result.append(
                diagnostic(
                    "V3_GENERATOR_REQUIRED",
                    f"generator `{kind}` requires parameter `{name}`",
                    path=path,
                    locations=locations,
                    hint=f"add `{name}: ...` under `generate:`",
                )
            )
    if spec.harmony == "required" and not has_harmony:
        result.append(
            diagnostic(
                "V3_GENERATOR_HARMONY",
                f"generator `{kind}` requires top-level harmony",
                path=path,
                locations=locations,
            )
        )
    material_id = value.get("material")
    if material_id is not None:
        material_id = str(material_id)
        if material_id not in materials:
            suggestion = suggest_name(material_id, materials)
            result.append(
                diagnostic(
                    "V3_GENERATOR_MATERIAL",
                    f"generator `{kind}` references unknown material `{material_id}`",
                    path=(*path, "material"),
                    locations=locations,
                    hint=(f"did you mean `{suggestion}`?" if suggestion else None),
                )
            )
        elif kind in {"melody.motif", "guitar.lead"} and str(materials[material_id].get("kind", "motif")) != "motif":
            result.append(
                diagnostic(
                    "V3_GENERATOR_MATERIAL_KIND",
                    f"generator `{kind}` requires a `kind: motif` material; `{material_id}` is `{materials[material_id].get('kind', 'events')}`",
                    path=(*path, "material"),
                    locations=locations,
                )
            )
    # Parameter domains come from the checked-in public generator catalog.
    for name, meta in spec.parameters.items():
        if name not in value:
            continue
        raw = value[name]
        typ = meta.get("type")
        number: float | None = None
        ok = True
        if typ == "integer":
            ok = isinstance(raw, int) and not isinstance(raw, bool)
            if ok:
                number = float(raw)
        elif typ == "number":
            ok = isinstance(raw, (int, float)) and not isinstance(raw, bool)
            if ok:
                number = float(raw)
        elif typ == "boolean":
            ok = isinstance(raw, bool)
        elif typ == "string":
            ok = isinstance(raw, str)
        elif typ == "array":
            ok = isinstance(raw, list)
            item_meta = meta.get("items") or {}
            if ok and item_meta:
                for item in raw:
                    item_type = item_meta.get("type")
                    item_number: float | None = None
                    item_ok = True
                    if item_type == "integer":
                        item_ok = isinstance(item, int) and not isinstance(item, bool)
                        if item_ok:
                            item_number = float(item)
                    elif item_type == "number":
                        item_ok = isinstance(item, (int, float)) and not isinstance(item, bool)
                        if item_ok:
                            item_number = float(item)
                    elif item_type == "string":
                        item_ok = isinstance(item, str)
                    if item_ok and item_meta.get("enum") is not None:
                        item_ok = item in item_meta["enum"]
                    if item_ok and item_number is not None:
                        if item_meta.get("minimum") is not None and item_number < float(item_meta["minimum"]):
                            item_ok = False
                        if item_meta.get("maximum") is not None and item_number > float(item_meta["maximum"]):
                            item_ok = False
                        if item_meta.get("exclusiveMinimum") is not None and item_number <= float(item_meta["exclusiveMinimum"]):
                            item_ok = False
                        if item_meta.get("exclusiveMaximum") is not None and item_number >= float(item_meta["exclusiveMaximum"]):
                            item_ok = False
                    if not item_ok:
                        ok = False
                        break
        elif typ == "object":
            ok = _mapping(raw)
        if ok and meta.get("enum") is not None:
            ok = raw in meta["enum"]
        if ok and number is not None:
            if meta.get("minimum") is not None and number < float(meta["minimum"]):
                ok = False
            if meta.get("maximum") is not None and number > float(meta["maximum"]):
                ok = False
            if meta.get("exclusiveMinimum") is not None and number <= float(meta["exclusiveMinimum"]):
                ok = False
            if meta.get("exclusiveMaximum") is not None and number >= float(meta["exclusiveMaximum"]):
                ok = False
        if not ok:
            constraints = []
            for key, op in (("minimum", ">="), ("maximum", "<="), ("exclusiveMinimum", ">"), ("exclusiveMaximum", "<")):
                if meta.get(key) is not None:
                    constraints.append(f"{op} {meta[key]}")
            if meta.get("enum") is not None:
                constraints.append(f"one of {meta['enum']}")
            detail = f" ({', '.join(constraints)})" if constraints else ""
            result.append(diagnostic(
                "V3_GENERATOR_VALUE",
                f"invalid `{kind}.{name}`; expected {typ or 'a valid value'}{detail}",
                path=(*path, name), locations=locations,
            ))
    return result



PROCESSING_FIELDS = {"stems", "groups", "master", "sections", "adaptive_sections", "mastering"}
PROCESSING_STAGE_FIELDS = {"chain"}
PROCESSING_POLICY_FIELDS = {"mode", "notes"}


def _validate_processing_step(
    raw: Any,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
) -> list[Diagnostic]:
    from ..processing.catalog import (
        canonical_pedalboard_effect_name,
        get_processor_spec,
        pedalboard_effect_catalog,
        processor_names,
    )

    result: list[Diagnostic] = []
    if not _mapping(raw):
        return [diagnostic("V3_PROCESSOR_TYPE", "processing chain entry must be a mapping", path=path, locations=locations)]
    raw_name = raw.get("processor", raw.get("kind", raw.get("effect", raw.get("type", raw.get("backend")))))
    if not raw_name:
        return [diagnostic("V3_PROCESSOR_NAME", "processing chain entry requires `processor`", path=path, locations=locations)]
    try:
        proc = get_processor_spec(str(raw_name))
    except ValueError:
        suggestion = suggest_name(str(raw_name), processor_names())
        return [diagnostic(
            "V3_PROCESSOR_NAME",
            f"unknown processor `{raw_name}`",
            path=(*path, "processor") if "processor" in raw else path,
            locations=locations,
            hint=(f"did you mean `{suggestion}`?" if suggestion else "use `processing list` to inspect the public processing vocabulary"),
        )]
    control_fields = {"processor", "kind", "effect", "type", "backend", "required", "optional", "label", "report_levels"}
    allowed = set(proc.parameters) | control_fields
    for key in raw:
        if key not in allowed:
            result.append(diagnostic(
                "V3_PROCESSOR_FIELD",
                f"unknown `{proc.name}` processor field `{key}`",
                path=(*path, str(key)),
                locations=locations,
                hint=unknown_field_hint(str(key), allowed),
            ))
    for key, meta in proc.parameters.items():
        if key not in raw:
            continue
        value = raw[key]
        typ = meta.get("type")
        ok = True
        if typ == "number":
            try:
                number = float(value)
            except Exception:
                ok = False
            else:
                if meta.get("minimum") is not None and number < float(meta["minimum"]):
                    ok = False
                if meta.get("maximum") is not None and number > float(meta["maximum"]):
                    ok = False
        elif typ == "boolean":
            ok = isinstance(value, bool)
        elif typ == "string":
            ok = isinstance(value, str)
        elif typ == "array":
            ok = isinstance(value, list)
        elif typ == "object":
            ok = _mapping(value)
        if not ok:
            bounds = []
            if meta.get("minimum") is not None:
                bounds.append(f">= {meta['minimum']}")
            if meta.get("maximum") is not None:
                bounds.append(f"<= {meta['maximum']}")
            suffix = f" ({', '.join(bounds)})" if bounds else ""
            result.append(diagnostic(
                "V3_PROCESSOR_PARAMETER",
                f"invalid `{proc.name}.{key}`; expected {typ or 'a valid value'}{suffix}",
                path=(*path, str(key)),
                locations=locations,
            ))
    if proc.name == "pedalboard":
        effects = raw.get("effects", raw.get("chain", raw.get("plugins", []))) or []
        if not isinstance(effects, list):
            result.append(diagnostic("V3_PEDALBOARD_EFFECTS", "pedalboard.effects must be a list", path=(*path, "effects"), locations=locations))
        else:
            catalog = pedalboard_effect_catalog()
            for idx, effect in enumerate(effects):
                effect_path = (*path, "effects", idx)
                if not _mapping(effect):
                    result.append(diagnostic("V3_PEDALBOARD_EFFECT", "Pedalboard effect must be a mapping", path=effect_path, locations=locations))
                    continue
                raw_effect = effect.get("effect", effect.get("kind", effect.get("type")))
                if not raw_effect:
                    result.append(diagnostic("V3_PEDALBOARD_EFFECT", "Pedalboard effect requires `effect`", path=effect_path, locations=locations))
                    continue
                try:
                    canonical_pedalboard_effect_name(str(raw_effect))
                except ValueError:
                    suggestion = suggest_name(str(raw_effect), catalog)
                    result.append(diagnostic(
                        "V3_PEDALBOARD_EFFECT",
                        f"unknown Pedalboard effect `{raw_effect}`",
                        path=(*effect_path, "effect"),
                        locations=locations,
                        hint=(f"did you mean `{suggestion}`?" if suggestion else None),
                    ))
    if proc.name == "vst3" and not (raw.get("plugin") or raw.get("path")):
        result.append(diagnostic("V3_VST3_REFERENCE", "vst3 processor requires `plugin` or `path`", path=path, locations=locations))
    if proc.name == "lv2" and not (raw.get("plugin_uri") or raw.get("uri")):
        result.append(diagnostic("V3_LV2_REFERENCE", "lv2 processor requires `plugin_uri`", path=path, locations=locations))
    if proc.name == "command" and not raw.get("command"):
        result.append(diagnostic("V3_COMMAND_PROCESSOR", "command processor requires `command`", path=path, locations=locations))
    return result


def _validate_processing(
    raw: Any,
    *,
    path: SourcePath,
    locations: Mapping[SourcePath, SourceLocation],
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    if raw is None:
        return result
    if not _mapping(raw):
        return [diagnostic("V3_PROCESSING", "processing must be a mapping", path=path, locations=locations)]
    result.extend(_unknown_fields(raw, PROCESSING_FIELDS, path=path, locations=locations, code="V3_PROCESSING_FIELD", subject="processing"))

    def validate_stage(block: Any, stage_path: SourcePath) -> None:
        if isinstance(block, list):
            chain = block
            chain_path = stage_path
        elif _mapping(block):
            result.extend(_unknown_fields(block, PROCESSING_STAGE_FIELDS, path=stage_path, locations=locations, code="V3_PROCESSING_STAGE_FIELD", subject="processing stage"))
            chain = block.get("chain") or []
            chain_path = (*stage_path, "chain")
        else:
            result.append(diagnostic("V3_PROCESSING_STAGE", "processing stage must be a list or `{chain: [...]}` mapping", path=stage_path, locations=locations))
            return
        if not isinstance(chain, list):
            result.append(diagnostic("V3_PROCESSING_CHAIN", "processing chain must be a list", path=chain_path, locations=locations))
            return
        for idx, step in enumerate(chain):
            result.extend(_validate_processing_step(step, path=(*chain_path, idx), locations=locations))

    for key in ("stems", "master"):
        if key in raw:
            validate_stage(raw[key], (*path, key))
    for family in ("groups", "sections"):
        blocks = raw.get(family)
        if blocks is None:
            continue
        if not _mapping(blocks):
            result.append(diagnostic("V3_PROCESSING_STAGE_MAP", f"processing.{family} must be a mapping", path=(*path, family), locations=locations))
            continue
        for name, block in blocks.items():
            validate_stage(block, (*path, family, str(name)))
    for key in ("adaptive_sections", "mastering"):
        block = raw.get(key)
        if block is None:
            continue
        if not _mapping(block):
            result.append(diagnostic("V3_MASTERING_POLICY", f"processing.{key} must be a mapping", path=(*path, key), locations=locations))
            continue
        result.extend(_unknown_fields(block, PROCESSING_POLICY_FIELDS, path=(*path, key), locations=locations, code="V3_MASTERING_POLICY_FIELD", subject="mastering policy"))
        mode = block.get("mode")
        if mode is not None and str(mode) not in {"composition_master", "legacy_section_postprocess", "global_master_slices", "section_postprocess"}:
            result.append(diagnostic("V3_MASTERING_MODE", f"unknown mastering mode `{mode}`", path=(*path, key, "mode"), locations=locations, hint="use `composition_master` for new v3 music"))
    return result


def diagnose_v3_spec(
    spec: Mapping[str, Any],
    *,
    locations: Mapping[SourcePath, SourceLocation] | None = None,
) -> list[Diagnostic]:
    """Return deterministic source diagnostics for one v3 mapping."""

    locations = locations or {}
    result: list[Diagnostic] = []
    result.extend(
        _unknown_fields(
            spec,
            TOP_LEVEL_FIELDS,
            path=(),
            locations=locations,
            code="V3_TOP_FIELD",
            subject="top-level",
        )
    )
    if str(spec.get("schema", "")) != "ambition.musicir.v3":
        result.append(
            diagnostic(
                "V3_SCHEMA",
                "v3 source validator requires `schema: ambition.musicir.v3`",
                path=("schema",),
                locations=locations,
            )
        )
    if not str(spec.get("id", "")).strip():
        result.append(diagnostic("V3_SCORE_ID", "score needs a stable top-level `id`", path=(), locations=locations))

    key_raw = spec.get("key")
    if key_raw is not None:
        if isinstance(key_raw, str):
            pieces = key_raw.replace("-", " ").split()
            mode = pieces[1].lower().replace("-", "_") if len(pieces) > 1 else "major"
            if mode not in SCALE_INTERVALS:
                suggestion = suggest_name(mode, SCALE_INTERVALS)
                result.append(diagnostic(
                    "V3_KEY_MODE", f"unknown score key mode `{mode}`",
                    path=("key",), locations=locations,
                    hint=(f"did you mean `{suggestion}`?" if suggestion else None),
                ))
        elif _mapping(key_raw):
            result.extend(_unknown_fields(
                key_raw, KEY_FIELDS, path=("key",), locations=locations,
                code="V3_KEY_FIELD", subject="key",
            ))
            tonic = key_raw.get("tonic", key_raw.get("root"))
            if tonic is None:
                result.append(diagnostic("V3_KEY_TONIC", "score key mapping requires `tonic`", path=("key",), locations=locations))
            mode = str(key_raw.get("mode", "major")).lower().replace("-", "_")
            if mode not in SCALE_INTERVALS:
                suggestion = suggest_name(mode, SCALE_INTERVALS)
                result.append(diagnostic(
                    "V3_KEY_MODE", f"unknown score key mode `{mode}`",
                    path=("key", "mode"), locations=locations,
                    hint=(f"did you mean `{suggestion}`?" if suggestion else None),
                ))
        else:
            result.append(diagnostic("V3_KEY", "score key must be a string or mapping", path=("key",), locations=locations))

    result.extend(_validate_processing(spec.get("processing"), path=("processing",), locations=locations))

    ppq = 960
    timebase = spec.get("timebase")
    if timebase is not None:
        if not _mapping(timebase):
            result.append(diagnostic("V3_TIMEBASE", "timebase must be a mapping", path=("timebase",), locations=locations))
        else:
            result.extend(_unknown_fields(timebase, TIMEBASE_FIELDS, path=("timebase",), locations=locations, code="V3_TIMEBASE_FIELD", subject="timebase"))
            try:
                ppq = int(timebase.get("ppq", 960))
                if ppq <= 0:
                    raise ValueError
            except Exception:
                result.append(diagnostic("V3_PPQ", "timebase.ppq must be a positive integer", path=("timebase", "ppq"), locations=locations))
                ppq = 960
    elif "ppq" in spec:
        try:
            ppq = int(spec["ppq"])
            if ppq <= 0:
                raise ValueError
        except Exception:
            result.append(diagnostic("V3_PPQ", "ppq must be a positive integer", path=("ppq",), locations=locations))
            ppq = 960

    has_harmony = bool(spec.get("harmony"))
    harmony = spec.get("harmony")
    if _mapping(harmony):
        result.extend(_unknown_fields(harmony, HARMONY_FIELDS, path=("harmony",), locations=locations, code="V3_HARMONY_FIELD", subject="harmony"))
        events = harmony.get("events") or []
        if events and not _list(events):
            result.append(diagnostic("V3_HARMONY_EVENTS", "harmony.events must be a list", path=("harmony", "events"), locations=locations))
        elif _list(events):
            for idx, event in enumerate(events):
                if _mapping(event):
                    result.extend(_unknown_fields(event, HARMONY_EVENT_FIELDS, path=("harmony", "events", idx), locations=locations, code="V3_HARMONY_EVENT_FIELD", subject="harmony event"))
                    if not event.get("chord", event.get("harmony")):
                        result.append(diagnostic("V3_HARMONY_CHORD", "harmony event requires `chord`", path=("harmony", "events", idx), locations=locations))
                elif not (isinstance(event, (list, tuple)) and len(event) >= 2):
                    result.append(diagnostic("V3_HARMONY_EVENT", "harmony event must be a mapping or `[bar, chord]`", path=("harmony", "events", idx), locations=locations))
    elif harmony is not None and not _list(harmony):
        result.append(diagnostic("V3_HARMONY", "harmony must be a progression list or mapping", path=("harmony",), locations=locations))

    instruments_raw = spec.get("instruments") or []
    instruments: list[Mapping[str, Any]] = []
    if not _list(instruments_raw):
        result.append(diagnostic("V3_INSTRUMENTS", "instruments must be a list", path=("instruments",), locations=locations))
    else:
        result.extend(_unique_ids([{"id": x.get("name") if _mapping(x) else None} if _mapping(x) else x for x in instruments_raw], path=("instruments",), locations=locations, subject="instrument", code_prefix="V3_INSTRUMENT"))
        instruments = [x for x in instruments_raw if _mapping(x)]
    instrument_names = {str(row.get("name")) for row in instruments if row.get("name")}
    groups = {str(row.get("group")) for row in instruments if row.get("group")}
    catalog_refs = instrument_catalog()
    for idx, row in enumerate(instruments):
        backend = backend_spec_from_instrument(row)
        ref = backend.get("library_ref")
        if ref and str(ref) not in catalog_refs and not backend.get("sfz"):
            suggestion = suggest_name(str(ref), catalog_refs)
            result.append(
                diagnostic(
                    "V3_INSTRUMENT_LIBRARY_REF",
                    f"unknown checked-in instrument library_ref `{ref}`",
                    path=("instruments", idx, "instrument_backend", "library_ref"),
                    locations=locations,
                    hint=(f"did you mean `{suggestion}`?" if suggestion else "use `instruments list` to inspect the supported sampled-instrument vocabulary"),
                )
            )

    materials_raw = spec.get("materials") or {}
    materials: dict[str, Mapping[str, Any]] = {}
    if _mapping(materials_raw):
        for key, raw in materials_raw.items():
            if not _mapping(raw):
                result.append(diagnostic("V3_MATERIAL_TYPE", f"material `{key}` must be a mapping", path=("materials", str(key)), locations=locations))
                continue
            row = raw
            material_id = str(row.get("id", key))
            materials[material_id] = row
            kind = str(row.get("kind", "events" if "events" in row else "motif"))
            allowed = (
                MATERIAL_EVENT_FIELDS if kind == "events"
                else MATERIAL_MOTIF_FIELDS if kind == "motif"
                else MATERIAL_SEQUENCE_FIELDS if kind == "sequence"
                else MATERIAL_COMMON_FIELDS
            )
            result.extend(_unknown_fields(row, allowed, path=("materials", str(key)), locations=locations, code="V3_MATERIAL_FIELD", subject=f"{kind} material"))
            if kind not in {"events", "motif", "sequence"}:
                suggestion = suggest_name(kind, ("events", "motif", "sequence"))
                result.append(diagnostic("V3_MATERIAL_KIND", f"unknown material kind `{kind}`", path=("materials", str(key), "kind"), locations=locations, hint=(f"did you mean `{suggestion}`?" if suggestion else None)))
            elif kind == "events":
                events = row.get("events") or []
                if not _list(events):
                    result.append(diagnostic("V3_MATERIAL_EVENTS", "event material requires an events list", path=("materials", str(key), "events"), locations=locations))
                else:
                    for event_idx, event in enumerate(events):
                        result.extend(_validate_event(event, ppq=ppq, path=("materials", str(key), "events", event_idx), locations=locations, has_harmony=has_harmony))
            elif kind == "sequence":
                items = row.get("items") or []
                if not _list(items):
                    result.append(diagnostic("V3_MATERIAL_SEQUENCE", "sequence material requires an items list", path=("materials", str(key), "items"), locations=locations))
                else:
                    for item_idx, item in enumerate(items):
                        item_path = ("materials", str(key), "items", item_idx)
                        if not _mapping(item):
                            result.append(diagnostic("V3_MATERIAL_SEQUENCE_ITEM", "sequence item must be a mapping", path=item_path, locations=locations))
                            continue
                        result.extend(_unknown_fields(item, MATERIAL_SEQUENCE_ITEM_FIELDS, path=item_path, locations=locations, code="V3_MATERIAL_SEQUENCE_FIELD", subject="sequence item"))
                        if not item.get("use"):
                            result.append(diagnostic("V3_MATERIAL_SEQUENCE_USE", "sequence item requires `use`", path=item_path, locations=locations))
                        if "at" in item:
                            try:
                                fraction_to_ticks(item["at"], ppq=ppq)
                            except Exception as ex:
                                result.append(diagnostic("V3_MATERIAL_SEQUENCE_AT", f"invalid sequence-item offset: {ex}", path=(*item_path, "at"), locations=locations))
                        for field in ("velocity_scale", "gate", "time_scale"):
                            if field in item:
                                try:
                                    value = float(item[field])
                                    if field == "velocity_scale":
                                        if value < 0:
                                            raise ValueError
                                    elif value <= 0:
                                        raise ValueError
                                except Exception:
                                    result.append(diagnostic("V3_MATERIAL_SEQUENCE_TRANSFORM", f"invalid sequence-item `{field}`", path=(*item_path, field), locations=locations))
    elif _list(materials_raw):
        result.extend(_unique_ids(materials_raw, path=("materials",), locations=locations, subject="material", code_prefix="V3_MATERIAL"))
        for idx, raw in enumerate(materials_raw):
            if _mapping(raw):
                materials[str(raw.get("id", ""))] = raw
    else:
        result.append(diagnostic("V3_MATERIALS", "materials must be a mapping or list", path=("materials",), locations=locations))

    form = spec.get("form") or []
    if not _list(form):
        result.append(diagnostic("V3_FORM", "form must be a list", path=("form",), locations=locations))
    else:
        result.extend(_unique_ids(form, path=("form",), locations=locations, subject="form region", code_prefix="V3_FORM"))
        for idx, row in enumerate(form):
            if _mapping(row):
                result.extend(_unknown_fields(row, FORM_FIELDS, path=("form", idx), locations=locations, code="V3_FORM_FIELD", subject="form region"))
                for field in ("energy", "intensity", "density", "variation"):
                    if field in row:
                        try:
                            value = float(row[field])
                            if not 0.0 <= value <= 1.0:
                                raise ValueError
                        except Exception:
                            result.append(diagnostic("V3_FORM_INTENT", f"form `{field}` must be in 0..1", path=("form", idx, field), locations=locations))

    parts = spec.get("parts") or []
    if not _list(parts):
        result.append(diagnostic("V3_PARTS", "parts must be a list", path=("parts",), locations=locations))
        return result
    result.extend(_unique_ids(parts, path=("parts",), locations=locations, subject="part", code_prefix="V3_PART"))
    for part_idx, raw_part in enumerate(parts):
        if not _mapping(raw_part):
            continue
        part = raw_part
        part_path = ("parts", part_idx)
        result.extend(_unknown_fields(part, PART_FIELDS, path=part_path, locations=locations, code="V3_PART_FIELD", subject="part"))
        part_instrument = part.get("instrument")
        if part_instrument is not None and str(part_instrument) not in instrument_names:
            suggestion = suggest_name(str(part_instrument), instrument_names)
            result.append(diagnostic("V3_PART_INSTRUMENT", f"part references unknown instrument `{part_instrument}`", path=(*part_path, "instrument"), locations=locations, hint=(f"did you mean `{suggestion}`?" if suggestion else None)))
        voices = part.get("voices") or []
        if not _list(voices):
            result.append(diagnostic("V3_VOICES", "part.voices must be a list", path=(*part_path, "voices"), locations=locations))
            continue
        result.extend(_unique_ids(voices, path=(*part_path, "voices"), locations=locations, subject="voice", code_prefix="V3_VOICE"))
        for voice_idx, raw_voice in enumerate(voices):
            if not _mapping(raw_voice):
                continue
            voice = raw_voice
            voice_path = (*part_path, "voices", voice_idx)
            result.extend(_unknown_fields(voice, VOICE_FIELDS, path=voice_path, locations=locations, code="V3_VOICE_FIELD", subject="voice"))
            clips = voice.get("clips") or []
            if not _list(clips):
                result.append(diagnostic("V3_CLIPS", "voice.clips must be a list", path=(*voice_path, "clips"), locations=locations))
                continue
            result.extend(_unique_ids(clips, path=(*voice_path, "clips"), locations=locations, subject="clip", code_prefix="V3_CLIP"))
            for clip_idx, raw_clip in enumerate(clips):
                if not _mapping(raw_clip):
                    continue
                clip = raw_clip
                clip_path = (*voice_path, "clips", clip_idx)
                result.extend(_unknown_fields(clip, CLIP_FIELDS, path=clip_path, locations=locations, code="V3_CLIP_FIELD", subject="clip"))
                source_fields = [name for name in ("events", "use", "generate") if name in clip]
                if len(source_fields) != 1:
                    result.append(diagnostic("V3_CLIP_SOURCE", f"clip must define exactly one of events/use/generate; found {source_fields}", path=clip_path, locations=locations))
                target = clip.get("instrument", part_instrument)
                if target is not None and str(target) not in instrument_names:
                    suggestion = suggest_name(str(target), instrument_names)
                    result.append(diagnostic("V3_CLIP_INSTRUMENT", f"clip references unknown instrument `{target}`", path=(*clip_path, "instrument") if "instrument" in clip else clip_path, locations=locations, hint=(f"did you mean `{suggestion}`?" if suggestion else None)))
                technique_key = "technique" if "technique" in clip else "articulation" if "articulation" in clip else None
                if technique_key:
                    result.extend(_validate_technique(
                        clip[technique_key],
                        path=(*clip_path, technique_key),
                        locations=locations,
                        custom_names=(part.get("technique_map") or {}).keys(),
                    ))
                if "at" in clip:
                    result.extend(_validate_position(clip["at"], path=(*clip_path, "at"), locations=locations))
                for field in ("velocity_scale", "gate", "time_scale"):
                    if field in clip:
                        try:
                            value = float(clip[field])
                            if field == "velocity_scale":
                                if value < 0:
                                    raise ValueError
                            elif value <= 0:
                                raise ValueError
                        except Exception:
                            op = ">= 0" if field == "velocity_scale" else "> 0"
                            result.append(diagnostic("V3_CLIP_TRANSFORM", f"clip `{field}` must be {op}", path=(*clip_path, field), locations=locations))
                if "repeat" in clip and _mapping(clip["repeat"]):
                    repeat = clip["repeat"]
                    result.extend(_unknown_fields(repeat, REPEAT_FIELDS, path=(*clip_path, "repeat"), locations=locations, code="V3_REPEAT_FIELD", subject="repeat"))
                    try:
                        if int(repeat.get("count", 1)) <= 0:
                            raise ValueError
                    except Exception:
                        result.append(diagnostic("V3_REPEAT_COUNT", "repeat.count must be a positive integer", path=(*clip_path, "repeat", "count"), locations=locations))
                if "use" in clip:
                    material_id = str(clip["use"])
                    if material_id not in materials:
                        suggestion = suggest_name(material_id, materials)
                        result.append(diagnostic("V3_CLIP_MATERIAL", f"clip references unknown material `{material_id}`", path=(*clip_path, "use"), locations=locations, hint=(f"did you mean `{suggestion}`?" if suggestion else None)))
                    elif str(materials[material_id].get("kind", "events" if "events" in materials[material_id] else "motif")) not in {"events", "sequence"}:
                        result.append(diagnostic("V3_CLIP_MATERIAL_KIND", f"`use:` expects an event/sequence material; `{material_id}` is a motif. Use a motif-aware generator instead", path=(*clip_path, "use"), locations=locations))
                if "events" in clip:
                    events = clip.get("events") or []
                    if not _list(events):
                        result.append(diagnostic("V3_CLIP_EVENTS", "clip.events must be a list", path=(*clip_path, "events"), locations=locations))
                    else:
                        event_ids = [str(e.get("id")) for e in events if _mapping(e) and e.get("id")]
                        dupes = {x for x, count in Counter(event_ids).items() if count > 1}
                        for event_idx, event in enumerate(events):
                            event_path = (*clip_path, "events", event_idx)
                            result.extend(_validate_event(
                                event, ppq=ppq, path=event_path, locations=locations,
                                has_harmony=has_harmony,
                                custom_techniques=(part.get("technique_map") or {}).keys(),
                            ))
                            if _mapping(event) and str(event.get("id")) in dupes:
                                result.append(diagnostic("V3_EVENT_DUPLICATE_ID", f"duplicate event id `{event.get('id')}` inside clip `{clip.get('id')}`", path=(*event_path, "id"), locations=locations))
                if "generate" in clip:
                    result.extend(_validate_generator(clip["generate"], path=(*clip_path, "generate"), locations=locations, materials=materials, has_harmony=has_harmony))
                    if "duration" not in clip and "bars" not in clip:
                        result.append(diagnostic("V3_GENERATOR_DURATION", "generated clip currently requires `duration: {bars: N}`", path=clip_path, locations=locations))
                    elif "duration" in clip:
                        result.extend(_validate_duration(clip["duration"], ppq=ppq, path=(*clip_path, "duration"), locations=locations, allow_bars=True))
                automation = clip.get("automation") or []
                if automation:
                    if not _list(automation):
                        result.append(diagnostic("V3_AUTOMATION", "clip.automation must be a list", path=(*clip_path, "automation"), locations=locations))
                    else:
                        result.extend(_unique_ids(automation, path=(*clip_path, "automation"), locations=locations, subject="automation point", code_prefix="V3_AUTOMATION"))
                        for auto_idx, point in enumerate(automation):
                            result.extend(_validate_automation(point, ppq=ppq, path=(*clip_path, "automation", auto_idx), locations=locations))

    return result

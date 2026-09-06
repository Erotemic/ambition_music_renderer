"""Compile score processing configuration into canonical processing plans."""
from __future__ import annotations

import copy
from typing import Any, Mapping

from .model import ProcessingPlan
from .legacy import legacy_processing_plan


def _chain_from_block(block: Any) -> list[dict[str, Any]] | None:
    if block is None:
        return None
    if isinstance(block, list):
        return [copy.deepcopy(dict(row)) for row in block]
    if isinstance(block, Mapping):
        if "chain" in block:
            raw = block.get("chain") or []
            if not isinstance(raw, list):
                raise TypeError("processing stage `chain` must be a list")
            return [copy.deepcopy(dict(row)) for row in raw]
    raise TypeError("processing stage must be a chain list or mapping with `chain`")


def canonical_processing_config(spec: Mapping[str, Any]) -> dict[str, Any]:
    raw = spec.get("processing") or {}
    if not isinstance(raw, Mapping):
        raise TypeError("top-level `processing` must be a mapping")
    return copy.deepcopy(dict(raw))


def processing_plan_for_group(spec: Mapping[str, Any], group: str) -> ProcessingPlan:
    cfg = canonical_processing_config(spec)
    base_block = cfg.get("stems")
    groups = cfg.get("groups") or {}
    group_block = groups.get(group) if isinstance(groups, Mapping) else None
    if base_block is not None or group_block is not None:
        chain: list[dict[str, Any]] = []
        if base_block is not None:
            chain.extend(_chain_from_block(base_block) or [])
        if group_block is not None:
            chain.extend(_chain_from_block(group_block) or [])
        return ProcessingPlan.from_chain(chain, stage="group_stem", source="processing", group=group)

    settings = dict(spec.get("stem_postprocess", {}) or {})
    settings.update((spec.get("group_postprocess", {}) or {}).get(group, {}))
    settings.setdefault("normalize", False)
    settings.setdefault("target_peak_db", -2.5)
    return legacy_processing_plan(settings, stage="group_stem", group=group)


def processing_plan_for_master(spec: Mapping[str, Any]) -> ProcessingPlan:
    cfg = canonical_processing_config(spec)
    if cfg.get("master") is not None:
        return ProcessingPlan.from_chain(
            _chain_from_block(cfg["master"]) or [],
            stage="master",
            source="processing",
        )
    settings = dict(spec.get("postprocess", {}) or {})
    settings.setdefault("normalize", True)
    settings.setdefault("target_peak_db", -1.2)
    return legacy_processing_plan(settings, stage="master")


def processing_plan_for_section(spec: Mapping[str, Any], section: str) -> ProcessingPlan | None:
    cfg = canonical_processing_config(spec)
    sections = cfg.get("sections") or {}
    if not isinstance(sections, Mapping) or section not in sections:
        return None
    return ProcessingPlan.from_chain(
        _chain_from_block(sections[section]) or [],
        stage="section_bus",
        source="processing",
        section=section,
    )


def processing_plan_summary(spec: Mapping[str, Any], groups: list[str] | tuple[str, ...] = (), sections: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "schema": "ambition.processing_plan_set.v1",
        "master": processing_plan_for_master(spec).as_dict(),
        "groups": {str(group): processing_plan_for_group(spec, str(group)).as_dict() for group in groups},
        "sections": {
            str(section): plan.as_dict()
            for section in sections
            if (plan := processing_plan_for_section(spec, str(section))) is not None
        },
    }

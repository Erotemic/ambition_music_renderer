from __future__ import annotations

import copy
import dataclasses as dc
import hashlib
import json
from typing import Any, Iterable, Mapping

from .catalog import normalize_processor_mapping


@dc.dataclass(frozen=True)
class ProcessingOperation:
    processor: str
    parameters: dict[str, Any]
    source: str = "canonical"

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, source: str = "canonical") -> "ProcessingOperation":
        row = normalize_processor_mapping(raw)
        name = str(row.pop("processor"))
        return cls(name, row, source=source)

    def as_dict(self) -> dict[str, Any]:
        return {
            "processor": self.processor,
            **copy.deepcopy(self.parameters),
            "_source": self.source,
        }


@dc.dataclass(frozen=True)
class ProcessingPlan:
    stage: str
    operations: tuple[ProcessingOperation, ...]
    source: str
    group: str | None = None
    section: str | None = None

    @classmethod
    def from_chain(
        cls,
        chain: Iterable[Mapping[str, Any]],
        *,
        stage: str,
        source: str = "canonical",
        group: str | None = None,
        section: str | None = None,
    ) -> "ProcessingPlan":
        return cls(
            stage=stage,
            operations=tuple(ProcessingOperation.from_mapping(row, source=source) for row in chain),
            source=source,
            group=group,
            section=section,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "ambition.processing_plan.v1",
            "stage": self.stage,
            "source": self.source,
            "group": self.group,
            "section": self.section,
            "chain": [op.as_dict() for op in self.operations],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), default=str).encode("utf8")
        return hashlib.sha256(payload).hexdigest()

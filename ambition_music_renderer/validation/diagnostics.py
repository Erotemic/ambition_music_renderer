"""Structured source diagnostics for MusicIR authoring.

The compiler remains the semantic authority.  This module provides a stable,
source-oriented vocabulary for explaining problems before or while compilation
fails.  Diagnostics deliberately carry YAML paths and line/column coordinates
so agents can repair source without reverse-engineering an exception traceback.
"""
from __future__ import annotations

import dataclasses as dc
import difflib
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


PathPart = str | int
SourcePath = tuple[PathPart, ...]


@dc.dataclass(frozen=True)
class SourceLocation:
    line: int
    column: int

    def as_dict(self) -> dict[str, int]:
        return {"line": int(self.line), "column": int(self.column)}


@dc.dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    path: SourcePath = ()
    location: SourceLocation | None = None
    hint: str | None = None

    @property
    def path_text(self) -> str:
        return format_source_path(self.path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "path": self.path_text,
            "path_parts": list(self.path),
            "location": self.location.as_dict() if self.location else None,
            "hint": self.hint,
        }

    def format(self, *, source: str | Path | None = None) -> str:
        where = ""
        if source is not None:
            where = str(source)
        if self.location is not None:
            pos = f"{self.location.line}:{self.location.column}"
            where = f"{where}:{pos}" if where else pos
        if self.path:
            where = f"{where} [{self.path_text}]" if where else self.path_text
        prefix = f"{self.severity.upper()} {self.code}"
        text = f"{prefix}: {self.message}"
        if where:
            text += f"\n  at {where}"
        if self.hint:
            text += f"\n  hint: {self.hint}"
        return text


class MusicIRValidationError(ValueError):
    """Validation failure carrying structured source diagnostics."""

    def __init__(
        self,
        diagnostics: Sequence[Diagnostic],
        *,
        source: str | Path | None = None,
    ) -> None:
        self.diagnostics = tuple(diagnostics)
        self.source = source
        super().__init__(self.format())

    def format(self) -> str:
        errors = [d for d in self.diagnostics if d.severity == "error"]
        header = f"MusicIR validation failed with {len(errors)} error(s)"
        if self.source is not None:
            header += f" in {self.source}"
        body = "\n\n".join(d.format(source=self.source) for d in self.diagnostics)
        return header + ("\n\n" + body if body else "")


def format_source_path(path: Iterable[PathPart]) -> str:
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            text = str(part)
            if not out:
                out = text
            elif text.isidentifier():
                out += f".{text}"
            else:
                out += f"[{text!r}]"
    return out or "$"


def suggest_name(value: str, choices: Iterable[str], *, cutoff: float = 0.68) -> str | None:
    candidates = sorted({str(item) for item in choices})
    matches = difflib.get_close_matches(str(value), candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def unknown_field_hint(value: str, choices: Iterable[str]) -> str | None:
    suggestion = suggest_name(value, choices)
    if suggestion:
        return f"did you mean `{suggestion}`?"
    return None


def yaml_location_map(text: str) -> dict[SourcePath, SourceLocation]:
    """Map YAML value/key paths to one-based source coordinates.

    PyYAML's normal ``safe_load`` discards source marks.  ``compose`` exposes
    them without requiring a second YAML dependency.  Mapping-key paths point
    at the key token, while collection paths point at the collection start.
    """

    root = yaml.compose(text)
    if root is None:
        return {}
    result: dict[SourcePath, SourceLocation] = {}

    def mark(node: yaml.Node) -> SourceLocation:
        return SourceLocation(node.start_mark.line + 1, node.start_mark.column + 1)

    def scalar_key(node: yaml.Node) -> str:
        if isinstance(node, yaml.ScalarNode):
            return str(node.value)
        return str(node.value)

    def walk(node: yaml.Node, path: SourcePath) -> None:
        result.setdefault(path, mark(node))
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = scalar_key(key_node)
                child_path = (*path, key)
                # Unknown-field diagnostics should land on the field spelling.
                result[child_path] = mark(key_node)
                walk(value_node, child_path)
        elif isinstance(node, yaml.SequenceNode):
            for idx, child in enumerate(node.value):
                child_path = (*path, idx)
                result[child_path] = mark(child)
                walk(child, child_path)

    walk(root, ())
    return result


def diagnostic(
    code: str,
    message: str,
    *,
    path: SourcePath = (),
    locations: Mapping[SourcePath, SourceLocation] | None = None,
    severity: str = "error",
    hint: str | None = None,
) -> Diagnostic:
    locations = locations or {}
    location = locations.get(path)
    if location is None and path:
        # Missing-field diagnostics naturally point at the nearest authored
        # parent rather than having no source coordinate at all.
        for end in range(len(path) - 1, -1, -1):
            location = locations.get(path[:end])
            if location is not None:
                break
    return Diagnostic(
        code=str(code),
        severity=str(severity),
        message=str(message),
        path=tuple(path),
        location=location,
        hint=hint,
    )

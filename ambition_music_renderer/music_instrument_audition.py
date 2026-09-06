"""Safe scratch-variant helpers for Stem Lab instrument auditions.

These helpers never modify the score a render came from.  An audition clones a
render snapshot/live fallback into a new scratch score, changes one authored
instrument definition, and leaves rendering/promotion as explicit later steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from .instrument_catalog import instrument_catalog
from .instrument_resolution import backend_spec_from_instrument
from .render.score_core import GM_PROGRAMS


@dataclass(frozen=True)
class InstrumentChoice:
    name: str
    group: str
    program: str | int
    backend_mode: str
    library_ref: str
    sfz_glob: str


def _backend_fields(row: Mapping[str, Any]) -> tuple[str, str, str]:
    backend = backend_spec_from_instrument(row)
    library_ref = str(backend.get("library_ref") or "")
    sfz_glob = str(backend.get("sfz") or "")
    if library_ref:
        mode = "sfz_library"
    elif sfz_glob:
        mode = "sfz_path"
    elif backend:
        mode = "custom_backend"
    else:
        mode = "gm"
    return mode, library_ref, sfz_glob


def instrument_choices(score_path: Path, group: str) -> tuple[InstrumentChoice, ...]:
    spec = yaml.safe_load(Path(score_path).read_text(encoding="utf8")) or {}
    rows = spec.get("instruments", []) if isinstance(spec, Mapping) else []
    result: list[InstrumentChoice] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping) or str(row.get("group") or "") != group:
            continue
        mode, library_ref, sfz_glob = _backend_fields(row)
        result.append(
            InstrumentChoice(
                name=str(row.get("name") or "instrument"),
                group=group,
                program=row.get("program", "string_ensemble_1"),
                backend_mode=mode,
                library_ref=library_ref,
                sfz_glob=sfz_glob,
            )
        )
    return tuple(result)


def gm_program_names() -> tuple[str, ...]:
    return tuple(GM_PROGRAMS)


def sfz_library_refs() -> tuple[str, ...]:
    return tuple(sorted(instrument_catalog()))


def safe_variant_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return text[:96] or "instrument_audition"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    # Preserve .music.yaml as a compound suffix when possible.
    if path.name.endswith(".music.yaml"):
        stem = path.name[:-len(".music.yaml")]
        suffix = ".music.yaml"
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find an unused variant path beside {path}")


def write_instrument_variant(
    *,
    source_score: Path,
    destination_score: Path,
    group: str,
    instrument_name: str,
    program: str | int,
    backend_mode: str,
    library_ref: str = "",
    sfz_glob: str = "",
) -> Path:
    """Clone *source_score* and change exactly one instrument definition.

    ``backend_mode`` is one of ``keep``, ``gm``, ``sfz_library``, or
    ``sfz_path``.  The destination is always made unique; the source is never
    overwritten even if the caller accidentally points both at the same path.
    """
    source_score = Path(source_score).resolve()
    destination_score = Path(destination_score).resolve()
    if source_score == destination_score:
        raise ValueError("instrument auditions must be written to a new score path")
    destination_score.parent.mkdir(parents=True, exist_ok=True)
    destination_score = _unique_path(destination_score)

    spec = yaml.safe_load(source_score.read_text(encoding="utf8")) or {}
    if not isinstance(spec, dict):
        raise ValueError(f"score is not a mapping: {source_score}")
    rows = spec.get("instruments")
    if not isinstance(rows, list):
        raise ValueError("score has no instruments list")

    target: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("group") or "") == group and str(row.get("name") or "") == instrument_name:
            target = row
            break
    if target is None:
        raise ValueError(f"instrument {instrument_name!r} in group {group!r} was not found")

    if isinstance(program, str):
        program = program.strip()
        if program and program not in GM_PROGRAMS:
            try:
                program = int(program)
            except ValueError as exc:
                raise ValueError(f"unknown GM program {program!r}") from exc
    if isinstance(program, int) and not 0 <= program <= 127:
        raise ValueError("numeric GM program must be between 0 and 127")
    target["program"] = program

    current_backend = backend_spec_from_instrument(target)
    if backend_mode == "keep":
        pass
    elif backend_mode == "gm":
        target.pop("instrument_backend", None)
    elif backend_mode == "sfz_library":
        ref = library_ref.strip()
        if not ref:
            raise ValueError("SFZ library mode requires a library reference")
        current_ref = str(current_backend.get("library_ref") or "")
        if current_ref == ref:
            backend = current_backend
            backend["kind"] = "sfz"
            backend["library_ref"] = ref
            backend.pop("sfz", None)
        else:
            backend = {"kind": "sfz", "library_ref": ref}
            if isinstance(current_backend.get("settings"), Mapping):
                backend["settings"] = dict(current_backend["settings"])
        target["instrument_backend"] = backend
    elif backend_mode == "sfz_path":
        glob = sfz_glob.strip()
        if not glob:
            raise ValueError("SFZ path mode requires an SFZ path/glob")
        current_path = str(current_backend.get("sfz") or "")
        if current_path == glob:
            backend = current_backend
            backend["kind"] = "sfz"
            backend["sfz"] = glob
            backend.pop("library_ref", None)
        else:
            backend = {"kind": "sfz", "sfz": glob}
            if isinstance(current_backend.get("settings"), Mapping):
                backend["settings"] = dict(current_backend["settings"])
        target["instrument_backend"] = backend
    else:
        raise ValueError(f"unsupported backend mode {backend_mode!r}")

    spec.setdefault("stem_lab", {})
    if isinstance(spec["stem_lab"], dict):
        spec["stem_lab"]["derived_from"] = str(source_score)
        spec["stem_lab"]["instrument_audition"] = {
            "group": group,
            "instrument": instrument_name,
            "program": program,
            "backend_mode": backend_mode,
            "library_ref": library_ref.strip(),
            "sfz_glob": sfz_glob.strip(),
        }

    destination_score.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110),
        encoding="utf8",
    )
    return destination_score

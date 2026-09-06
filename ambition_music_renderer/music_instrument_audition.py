"""Safe scratch-variant helpers for Stem Lab instrument auditions.

These helpers never modify the score a render came from. An audition clones a
render snapshot/live fallback into a new scratch score, changes one authored
instrument definition, and leaves rendering/promotion as explicit later steps.

MusicIR may also carry a small authoring-only candidate bank under
``authoring.instrument_candidates``. The active instrument definition remains
the render authority; candidates only describe deliberate A/B alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from .instrument_catalog import (
    get_instrument_catalog_entry,
    instrument_catalog,
    sfz_smoke_profile_specs,
)
from .instrument_resolution import backend_spec_from_instrument
from .render.score_core import GM_PROGRAMS


@dataclass(frozen=True)
class InstrumentCandidate:
    """One pre-renderable timbre candidate for an authored instrument."""

    key: str
    label: str
    family: str
    backend_mode: str
    library_ref: str = ""
    sfz_glob: str = ""
    summary: str = ""
    program: str | int | None = None
    primary: bool = False
    authored: bool = False


@dataclass(frozen=True)
class InstrumentChoice:
    name: str
    group: str
    program: str | int
    backend_mode: str
    library_ref: str
    sfz_glob: str
    candidates: tuple[InstrumentCandidate, ...] = ()



def _load_score(score_path: Path) -> dict[str, Any]:
    try:
        spec = yaml.safe_load(Path(score_path).read_text(encoding="utf8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return spec if isinstance(spec, dict) else {}



def _backend_fields(row: Mapping[str, Any]) -> tuple[str, str, str]:
    backend = backend_spec_from_instrument(row)
    library_ref = str(backend.get("library_ref") or "")
    sfz_glob = str(backend.get("sfz") or "")
    if library_ref:
        mode = "sfz_library"
    elif sfz_glob:
        mode = "sfz_path"
    elif str(backend.get("kind") or "").strip():
        mode = "custom_backend"
    else:
        mode = "gm"
    return mode, library_ref, sfz_glob



def _inferred_family_fields(
    *, name: str, group: str, program: str | int, library_ref: str = ""
) -> str | None:
    if library_ref:
        entry = get_instrument_catalog_entry(library_ref)
        if entry is not None:
            return entry.family
    text = " ".join((name, group, str(program))).lower()
    if "bass" in text:
        return "bass"
    if "guitar" in text or group in {"giant", "giant_riff", "giant_lead"}:
        return "guitar"
    if "harpsichord" in text or "organ" in text or "rhodes" in text:
        return "keys"
    if "piano" in text:
        return "piano"
    if "drum" in text or "percussion" in text:
        return "drums"
    if "brass" in text or "trumpet" in text or "horn" in text or "trombone" in text or "tuba" in text:
        return "brass"
    if "string" in text or "violin" in text or "viola" in text or "cello" in text:
        return "strings"
    return None



def _authored_candidate_rows(
    spec: Mapping[str, Any],
    *,
    instrument_name: str,
    group: str,
    program: str | int,
    library_ref: str,
) -> tuple[InstrumentCandidate, ...]:
    authoring = spec.get("authoring")
    if not isinstance(authoring, Mapping):
        return ()
    banks = authoring.get("instrument_candidates")
    if not isinstance(banks, Mapping):
        return ()
    bank = banks.get(instrument_name)
    if not isinstance(bank, Mapping):
        return ()
    rows = bank.get("candidates")
    if not isinstance(rows, list):
        return ()

    primary = str(bank.get("primary") or "")
    family_default = _inferred_family_fields(
        name=instrument_name,
        group=group,
        program=program,
        library_ref=library_ref,
    ) or "other"
    result: list[InstrumentCandidate] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            continue
        candidate_id = str(raw.get("id") or f"candidate_{index + 1}").strip()
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        mode, candidate_ref, sfz_glob = _backend_fields(raw)
        candidate_program = raw.get("program", program)
        if mode == "custom_backend":
            # The scratch editor currently exposes GM and SFZ realization
            # authorities. Leave other backend kinds to the manual editor.
            continue
        result.append(
            InstrumentCandidate(
                key=candidate_id,
                label=str(raw.get("label") or candidate_id.replace("_", " ").title()),
                family=str(raw.get("family") or family_default),
                backend_mode=mode,
                library_ref=candidate_ref,
                sfz_glob=sfz_glob,
                summary=str(raw.get("summary") or raw.get("notes") or ""),
                program=candidate_program,
                primary=candidate_id == primary,
                authored=True,
            )
        )
    if result and not any(row.primary for row in result):
        result[0] = InstrumentCandidate(**{**result[0].__dict__, "primary": True})
    return tuple(result)



def instrument_choices(score_path: Path, group: str) -> tuple[InstrumentChoice, ...]:
    spec = _load_score(score_path)
    rows = spec.get("instruments", []) if isinstance(spec, Mapping) else []
    result: list[InstrumentChoice] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping) or str(row.get("group") or "") != group:
            continue
        mode, library_ref, sfz_glob = _backend_fields(row)
        name = str(row.get("name") or "instrument")
        program = row.get("program", "string_ensemble_1")
        result.append(
            InstrumentChoice(
                name=name,
                group=group,
                program=program,
                backend_mode=mode,
                library_ref=library_ref,
                sfz_glob=sfz_glob,
                candidates=_authored_candidate_rows(
                    spec,
                    instrument_name=name,
                    group=group,
                    program=program,
                    library_ref=library_ref,
                ),
            )
        )
    return tuple(result)



def instrument_realization_label(choice: InstrumentChoice, *, include_name: bool = True) -> str:
    """Return a compact human-readable label for the active instrument realization."""
    if choice.backend_mode == "sfz_library" and choice.library_ref:
        realization = choice.library_ref
    elif choice.backend_mode == "sfz_path" and choice.sfz_glob:
        realization = Path(choice.sfz_glob).name or choice.sfz_glob
    elif choice.backend_mode == "gm":
        realization = f"GM {choice.program}"
    else:
        realization = f"{choice.backend_mode} · {choice.program}"
    return f"{choice.name}: {realization}" if include_name else realization




def _inferred_family(choice: InstrumentChoice) -> str | None:
    return _inferred_family_fields(
        name=choice.name,
        group=choice.group,
        program=choice.program,
        library_ref=choice.library_ref,
    )



def instrument_candidates(choice: InstrumentChoice) -> tuple[InstrumentCandidate, ...]:
    """Return deliberate authored candidates, or catalog suggestions as fallback.

    A score-authored bank is intentionally narrow and wins completely over
    catalog discovery. This keeps ``Render candidates`` bounded to alternatives
    the composer actually wants to compare. Catalog/smoke discovery remains a
    fallback for scores that have not authored a bank yet.
    """
    if choice.candidates:
        return choice.candidates

    family = _inferred_family(choice)
    candidates: list[InstrumentCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for entry in instrument_catalog().values():
        if family is not None and entry.family != family:
            continue
        key = ("sfz_library", entry.ref, "")
        if key in seen:
            continue
        seen.add(key)
        summary = str(entry.usage.get("summary") or "")
        candidates.append(
            InstrumentCandidate(
                key=f"library:{entry.ref}",
                label=f"{entry.ref} — {entry.role}",
                family=entry.family,
                backend_mode="sfz_library",
                library_ref=entry.ref,
                summary=summary,
            )
        )

    for profile in sfz_smoke_profile_specs():
        profile_family = str(profile.get("family") or "other")
        if family is not None and profile_family != family:
            continue
        candidate_ref = str(profile.get("library_ref") or "")
        path = str(profile.get("path") or "")
        if path:
            mode = "sfz_path"
            sfz_glob = path if any(ch in path for ch in "*?[") else f"**/{path.lstrip('/')}"
            dedupe = (mode, "", sfz_glob)
            candidate_ref = ""
        elif candidate_ref:
            mode = "sfz_library"
            sfz_glob = ""
            dedupe = (mode, candidate_ref, "")
        else:
            continue
        if dedupe in seen:
            continue
        seen.add(dedupe)
        name = str(profile.get("name") or Path(path).stem or candidate_ref)
        articulation = str(profile.get("articulation") or "patch")
        candidates.append(
            InstrumentCandidate(
                key=f"patch:{name}",
                label=f"patch: {name} — {articulation}",
                family=profile_family,
                backend_mode=mode,
                library_ref=candidate_ref,
                sfz_glob=sfz_glob,
                summary=f"Curated {articulation} patch from the checked-in smoke profile.",
            )
        )

    return tuple(sorted(candidates, key=lambda row: (row.family, row.label.lower(), row.key)))



def instrument_audition_root_source(score_path: Path) -> Path:
    """Follow scratch ``derived_from`` links back to the stable comparison base."""
    current = Path(score_path).resolve()
    seen: set[Path] = set()
    for _ in range(16):
        if current in seen or not current.is_file():
            break
        seen.add(current)
        spec = _load_score(current)
        stem_lab = spec.get("stem_lab")
        derived = stem_lab.get("derived_from") if isinstance(stem_lab, Mapping) else None
        if not derived:
            break
        parent = Path(str(derived)).expanduser()
        if not parent.is_absolute():
            parent = current.parent / parent
        parent = parent.resolve()
        if not parent.is_file():
            break
        current = parent
    return current



def candidate_key_for_score(
    score_path: Path,
    *,
    group: str,
    instrument_name: str,
    candidates: tuple[InstrumentCandidate, ...],
) -> str | None:
    """Identify which authored candidate a rendered score realizes."""
    spec = _load_score(score_path)
    stem_lab = spec.get("stem_lab")
    audition = stem_lab.get("instrument_audition") if isinstance(stem_lab, Mapping) else None
    if isinstance(audition, Mapping):
        if (
            str(audition.get("group") or "") == group
            and str(audition.get("instrument") or "") == instrument_name
        ):
            candidate_id = str(audition.get("candidate_id") or "")
            if any(row.key == candidate_id for row in candidates):
                return candidate_id

    rows = spec.get("instruments")
    target: Mapping[str, Any] | None = None
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("group") or "") == group and str(row.get("name") or "") == instrument_name:
                target = row
                break
    if target is None:
        return None
    mode, library_ref, sfz_glob = _backend_fields(target)
    program = target.get("program")
    for candidate in candidates:
        candidate_program = candidate.program if candidate.program is not None else program
        if candidate_program != program:
            continue
        if candidate.backend_mode != mode:
            continue
        if mode == "sfz_library" and candidate.library_ref == library_ref:
            return candidate.key
        if mode == "sfz_path" and candidate.sfz_glob == sfz_glob:
            return candidate.key
        if mode == "gm":
            return candidate.key
    return None



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
    if path.name.endswith(".music.yaml"):
        stem = path.name[:-len(".music.yaml")]
        suffix = ".music.yaml"
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find an unused variant path beside {path}")



def _startup_controls_for_backend(*, library_ref: str = "", sfz_glob: str = "") -> dict[int, int]:
    normalized_glob = sfz_glob.replace("\\", "/").lower()
    # Authored globs often omit an inventory-root prefix such as ``Karoryfer/``.
    # Match the concrete smoke-profile path by its literal suffix so a deliberate
    # patch candidate still inherits required startup controllers.
    glob_tail = re.sub(r"^[*?/]+", "", normalized_glob)
    matching: list[Mapping[str, Any]] = []
    for profile in sfz_smoke_profile_specs():
        profile_ref = str(profile.get("library_ref") or "")
        profile_path = str(profile.get("path") or "").replace("\\", "/").lower()
        if library_ref and profile_ref == library_ref:
            matching.append(profile)
        elif sfz_glob and profile_path and glob_tail and profile_path.endswith(glob_tail):
            matching.append(profile)
    controls: dict[int, int] = {}
    for profile in matching:
        raw = profile.get("startup_cc") or {}
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                controls[int(key)] = int(value)
    return controls



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
    candidate_id: str = "",
    candidate_label: str = "",
) -> Path:
    """Clone *source_score* and change exactly one instrument definition."""
    source_score = instrument_audition_root_source(Path(source_score))
    destination_score = Path(destination_score).resolve()
    if source_score == destination_score:
        raise ValueError("instrument auditions must be written to a new score path")
    destination_score.parent.mkdir(parents=True, exist_ok=True)
    destination_score = _unique_path(destination_score)

    spec = _load_score(source_score)
    if not spec:
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
    startup_controls: dict[int, int] = {}
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
        startup_controls = _startup_controls_for_backend(library_ref=ref)
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
        startup_controls = _startup_controls_for_backend(sfz_glob=glob)
    else:
        raise ValueError(f"unsupported backend mode {backend_mode!r}")

    if startup_controls:
        controls = target.get("controls")
        merged = dict(controls) if isinstance(controls, Mapping) else {}
        merged.update(startup_controls)
        target["controls"] = merged

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
            "candidate_id": candidate_id.strip(),
            "candidate_label": candidate_label.strip(),
        }

    destination_score.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110),
        encoding="utf8",
    )
    return destination_score

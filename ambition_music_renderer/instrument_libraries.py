"""Machine-local SFZ discovery for the checked-in instrument catalog.

Stable authoring identities and resolver hints live in ``instrument_catalog.yaml``.
This module owns only filesystem discovery and resolution against the current
machine.  Generated census/report files under ``AMBITION_AUDIO_TOOLS_ROOT`` are
evidence about that machine, not authoring vocabulary.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Iterable

from .instrument_catalog import (
    InstrumentCatalogEntry,
    ResolverHints,
    get_instrument_catalog_entry,
    instrument_catalog,
    instrument_source_catalog,
)


DEFAULT_AUDIO_TOOLS_ROOTS = (
    Path("/data/audio-tools"),
    Path.home() / "data" / "music",
)


def _normalize_text(value: str | Path) -> str:
    text = str(value).lower().replace("_", " ").replace("-", " ").replace(".", " ")
    return " ".join(text.split())


def _dedupe_roots(roots: Iterable[Path]) -> list[Path]:
    """Preserve root priority while removing duplicate spellings."""

    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        expanded = root.expanduser()
        if expanded in seen:
            continue
        seen.add(expanded)
        out.append(expanded)
    return out


def configured_sfz_roots(extra_roots: Iterable[str | Path] | None = None) -> list[Path]:
    """Return configured SFZ search roots in priority order.

    Explicit roots are treated as an override.  That keeps score-level
    ``library_roots`` and unit tests deterministic instead of accidentally
    discovering unrelated user libraries from ``/data/audio-tools``.  Environment
    variables override built-in defaults for the same reason.
    """

    if extra_roots:
        return _dedupe_roots(Path(root).expanduser() for root in extra_roots)

    env_roots: list[Path] = []
    for env_name in ("AMBITION_MUSIC_SFZ_ROOTS", "AMBITION_SFZ_ROOTS"):
        env_value = os.environ.get(env_name)
        if env_value:
            env_roots.extend(Path(part).expanduser() for part in env_value.split(os.pathsep) if part)
    if env_roots:
        return _dedupe_roots(env_roots)

    audio_tools_root = os.environ.get("AMBITION_AUDIO_TOOLS_ROOT")
    if audio_tools_root:
        root = Path(audio_tools_root).expanduser()
        return _dedupe_roots((root / "sfz", root))

    roots: list[Path] = []
    for root in DEFAULT_AUDIO_TOOLS_ROOTS:
        roots.append(root / "sfz")
        roots.append(root)
    return _dedupe_roots(roots)


@functools.lru_cache(maxsize=8)
def _discover_sfz_files_cached(root_keys: tuple[str, ...]) -> tuple[Path, ...]:
    """Scan the roots once per process.

    A full install is ~1800 .sfz files under a 24GB tree, and `rglob` over it
    costs seconds. Every instrument of every cue resolves through here, so an
    uncached scan turned a whole-catalogue question into minutes of repeated
    directory walking. Libraries do not appear mid-process, so caching for the
    life of the process is safe; a run that installs them must start again to
    see them, which is already true of the roots themselves.
    """
    out: list[Path] = []
    for key in root_keys:
        root = Path(key)
        if not root.exists():
            continue
        try:
            out.extend(path.resolve() for path in root.rglob("*.sfz") if path.is_file())
        except OSError:
            continue
    return tuple(sorted(set(out), key=lambda p: str(p).lower()))


def discover_sfz_files(roots: Iterable[str | Path] | None = None) -> list[Path]:
    """Discover SFZ files under configured local sample-library roots."""

    root_keys = tuple(str(root) for root in configured_sfz_roots(roots))
    return list(_discover_sfz_files_cached(root_keys))




def _candidate_text(path: Path, roots: Iterable[str | Path] | None = None) -> str:
    """Normalize the library-relative path, not the user's absolute prefix."""

    if roots is not None:
        for root in roots:
            try:
                rel = path.resolve().relative_to(Path(root).expanduser().resolve())
            except (OSError, ValueError):
                continue
            return _normalize_text(rel)
    return _normalize_text(path.name)

def _source_relative_tokens(source_info: dict[str, Any]) -> tuple[str, ...]:
    """Return stable directory tokens for one downloaded sample source.

    The installer owns concrete roots; the catalog owns only the relative
    source location below an audio-tools tree.  Matching directory tokens
    lets explicit/custom SFZ roots work without baking ``/data/audio-tools``
    into authoring semantics.
    """

    relative_root = str(source_info.get("relative_root") or "").strip()
    if not relative_root:
        return ()
    parts = list(Path(relative_root).parts)
    if parts and _normalize_text(parts[0]) == "sfz":
        parts = parts[1:]
    return tuple(norm for part in parts if (norm := _normalize_text(part)))


def _matches_source(path: Path, source_info: dict[str, Any]) -> bool:
    tokens = _source_relative_tokens(source_info)
    if not tokens:
        return False
    # Use the full path here on purpose. A caller may pass the package
    # directory itself as an explicit root, in which case a root-relative
    # candidate no longer contains the source-directory name.
    text = _normalize_text(path)
    return all(token in text for token in tokens)


def _prefer_catalog_source(
    candidates: list[Path],
    entry: InstrumentCatalogEntry | None,
) -> list[Path]:
    """Prefer the catalog-declared downloaded source when it is installed.

    A stable role may deliberately have broad compatibility fallbacks, but
    when its expected source is present it is the canonical realization.
    This prevents broad aliases such as ``vpo.violin`` or ``drums.rock``
    from selecting an unrelated compatible patch just because its filename
    scores well.
    """

    if entry is None or not entry.source or not entry.resolver.prefer_source:
        return candidates
    source_info = instrument_source_catalog().get(entry.source)
    if not source_info:
        return candidates
    preferred = [path for path in candidates if _matches_source(path, source_info)]
    return preferred or candidates


def _matches_required(path_text: str, alias: ResolverHints) -> bool:
    if not alias.required_any:
        return True
    return any(all(token in path_text for token in tokens) for tokens in alias.required_any)


def _score_candidate(
    path: Path,
    *,
    alias: ResolverHints | None,
    prefer: Iterable[str] = (),
    roots: Iterable[str | Path] | None = None,
) -> int:
    text = _candidate_text(path, roots)
    score = 0
    if alias is not None:
        for token in alias.prefer:
            norm = _normalize_text(token)
            if norm and norm in text:
                score += 12
        for token in alias.avoid:
            norm = _normalize_text(token)
            if norm and norm in text:
                score -= 16
    for token in prefer:
        norm = _normalize_text(token)
        if norm and norm in text:
            score += 20
    # Prefer shallower, human-facing patches over helper include files.
    lowered = text
    if "instrument" in lowered or "patch" in lowered:
        score += 2
    if "include" in lowered or "/libs/" in str(path).lower():
        score -= 30
    return score


def resolve_sfz_reference(
    value: str | Path | None = None,
    *,
    library_ref: str | None = None,
    prefer: Iterable[str] = (),
    base_dir: Path | None = None,
    roots: Iterable[str | Path] | None = None,
) -> Path | None:
    """Resolve an explicit SFZ path, glob, or named library reference."""

    explicit = str(value).strip() if value is not None else ""
    search_roots = configured_sfz_roots(roots)
    if explicit:
        p = Path(explicit).expanduser()
        direct_candidates: list[Path] = []
        if not p.is_absolute() and base_dir is not None:
            direct_candidates.append((base_dir / p).resolve())
        direct_candidates.append(p.resolve())
        for candidate in direct_candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        # Treat explicit strings containing glob metacharacters as a search pattern.
        if any(ch in explicit for ch in "*?["):
            glob_candidates: list[Path] = []
            for root in search_roots:
                if root.exists():
                    glob_candidates.extend(path.resolve() for path in root.glob(explicit))
            glob_candidates = [p for p in glob_candidates if p.is_file() and p.suffix.lower() == ".sfz"]
            if glob_candidates:
                return sorted(
                    glob_candidates,
                    key=lambda p: (
                        -_score_candidate(p, alias=None, prefer=prefer, roots=search_roots),
                        str(p),
                    ),
                )[0]
    if not library_ref:
        return None
    entry = get_instrument_catalog_entry(library_ref)
    alias = (
        entry.resolver
        if entry is not None
        else ResolverHints(required_any=(tuple(_normalize_text(library_ref).split()),))
    )
    candidates = []
    for path in discover_sfz_files(search_roots):
        text = _candidate_text(path, search_roots)
        if _matches_required(text, alias):
            candidates.append(path)
    if not candidates:
        return None
    candidates = _prefer_catalog_source(candidates, entry)
    return sorted(
        candidates,
        key=lambda p: (
            -_score_candidate(p, alias=alias, prefer=prefer, roots=search_roots),
            str(p),
        ),
    )[0]


def collect_sfz_library_diagnostics(*, limit: int = 200) -> dict[str, Any]:
    """Return a JSON-serializable report of configured SFZ libraries."""

    roots = configured_sfz_roots()
    files = discover_sfz_files(roots)
    alias_hits: dict[str, str | None] = {}
    expected_missing: list[str] = []
    catalog = instrument_catalog()
    for name, entry in sorted(catalog.items()):
        resolved = resolve_sfz_reference(library_ref=name, roots=roots)
        alias_hits[name] = str(resolved) if resolved is not None else None
        if entry.expected and resolved is None:
            expected_missing.append(name)

    source_hits: dict[str, str | None] = {}
    expected_sources_missing: list[str] = []
    for name, source_info in sorted(instrument_source_catalog().items()):
        hit = next((path for path in files if _matches_source(path, source_info)), None)
        source_hits[name] = str(hit) if hit is not None else None
        if bool(source_info.get("expected", False)) and hit is None:
            expected_sources_missing.append(name)

    return {
        "sfz_roots": [str(root) for root in roots],
        "sfz_count": len(files),
        "sfz_files": [str(path) for path in files[:limit]],
        "alias_hits": alias_hits,
        "expected_missing": expected_missing,
        "catalog_instrument_count": len(catalog),
        "source_hits": source_hits,
        "expected_sources_missing": expected_sources_missing,
        "catalog_source_count": len(instrument_source_catalog()),
    }

"""Local SFZ sample-library discovery for MusicIR instrument backends.

The renderer keeps high-quality sampled instruments optional.  Scores may ask
for named local libraries with ``instrument_backend.library_ref`` and the
renderer will use them when present, otherwise fall back to the existing MIDI /
SoundFont path with a warning.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_AUDIO_TOOLS_ROOTS = (
    Path("/data/audio-tools"),
    Path.home() / "data" / "music",
)


@dataclass(frozen=True)
class SfzLibraryAlias:
    """Search hints for a named SFZ library family."""

    ref: str
    required_any: tuple[tuple[str, ...], ...] = ()
    prefer: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()


ALIASES: dict[str, SfzLibraryAlias] = {
    # FreePats pianos downloaded by download_ambition_audio_tools.sh
    "freepats.upright_piano_kw": SfzLibraryAlias(
        ref="freepats.upright_piano_kw",
        required_any=(("upright", "pianokw"), ("upright", "piano", "kw")),
        prefer=("upright", "piano", "flac", "sfz"),
    ),
    "freepats.salamander_grand": SfzLibraryAlias(
        ref="freepats.salamander_grand",
        required_any=(("salamander",), ("grand", "piano")),
        prefer=("salamander", "grand", "piano", "flac", "sfz"),
        avoid=("16bit", "ogg"),
    ),
    "piano.acoustic": SfzLibraryAlias(
        ref="piano.acoustic",
        required_any=(("piano",), ("salamander",), ("upright",)),
        prefer=("salamander", "upright", "grand", "piano", "flac"),
    ),
    # Virtual Playing Orchestra downloaded by download_ambition_audio_tools.sh
    "vpo.strings": SfzLibraryAlias(
        ref="vpo.strings",
        required_any=(("virtual", "playing", "orchestra", "strings"), ("vpo", "strings"), ("strings",)),
        prefer=("all strings", "section", "sec", "panned", "sustain", "sus", "ensemble", "strings"),
        avoid=("pizz", "spicc", "stacc", "trem", "trill", "solo", "violin", "viola", "cello"),
    ),
    "vpo.violin": SfzLibraryAlias(
        ref="vpo.violin",
        required_any=(("virtual", "playing", "orchestra", "violin"), ("vpo", "violin"), ("violin",)),
        prefer=("solo", "sustain", "sus", "violin"),
        avoid=("pizz", "spicc", "stacc", "trem", "trill"),
    ),
    "vpo.brass": SfzLibraryAlias(
        ref="vpo.brass",
        required_any=(("virtual", "playing", "orchestra", "brass"), ("vpo", "brass"), ("brass",)),
        prefer=("all brass", "section", "sec", "panned", "sustain", "sus", "brass", "horns"),
        avoid=("stacc", "marcato", "fall", "solo", "trombone", "tuba"),
    ),
    "vpo.woodwinds": SfzLibraryAlias(
        ref="vpo.woodwinds",
        required_any=(("virtual", "playing", "orchestra", "woodwinds"), ("vpo", "woodwinds"), ("woodwinds",)),
        prefer=("sustain", "sus", "flute", "clarinet", "ensemble"),
        avoid=("stacc", "flutter", "trill"),
    ),
    "vpo.choir": SfzLibraryAlias(
        ref="vpo.choir",
        required_any=(("virtual", "playing", "orchestra", "vocals"), ("vpo", "vocals"), ("choir",), ("voice",)),
        prefer=("choir", "aah", "ooh", "sustain", "vocals"),
    ),
    # Manual-download families from the generated checklist.  These aliases are
    # deliberately broad so browser-downloaded archives under sfz/manual work.
    "guitar.clean": SfzLibraryAlias(
        ref="guitar.clean",
        required_any=(("guitar",), ("shinyguitar",), ("emilyguitar",), ("black", "green")),
        prefer=("clean", "sustain", "sus", "long", "shiny", "emily", "guitar"),
        avoid=("mute", "choke", "noise", "scrape"),
    ),
    "guitar.electric_lead": SfzLibraryAlias(
        ref="guitar.electric_lead",
        required_any=(("guitar",), ("shinyguitar",), ("emilyguitar",), ("black", "green")),
        prefer=("lead", "sustain", "sus", "long", "electric", "guitar", "shiny"),
        avoid=("mute", "choke", "noise", "scrape"),
    ),
    "bass.electric": SfzLibraryAlias(
        ref="bass.electric",
        required_any=(("electric", "bass"), ("bass", "guitar"), ("growlybass",), ("swagbass",), ("fashionbass",), ("pastabass",)),
        prefer=("finger", "pick", "sustain", "growly", "swag", "bass", "electric"),
        avoid=("slap", "mute", "noise", "trombone", "tuba", "brass", "cello", "orchestra", "strings"),
    ),
    "drums.rock": SfzLibraryAlias(
        ref="drums.rock",
        required_any=(("drum", "kit"), ("rock", "drum"), ("gogodze",), ("muldjord",), ("salamander", "drum")),
        prefer=("kit", "drum", "gm", "salamander", "muldjord", "gogodze", "rock"),
        avoid=("brush", "loop", "timpani", "orchestra", "cymbals only"),
    ),
    "vpo.percussion": SfzLibraryAlias(
        ref="vpo.percussion",
        required_any=(("virtual", "playing", "orchestra", "percussion"), ("vpo", "percussion"), ("percussion",)),
        prefer=("bassdrum snare cymbals", "snare", "bassdrum", "cymbals"),
        avoid=("timpani", "bells", "xylophone", "vibraphone"),
    ),
}


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


def discover_sfz_files(roots: Iterable[str | Path] | None = None) -> list[Path]:
    """Discover SFZ files under configured local sample-library roots."""

    out: list[Path] = []
    for root in configured_sfz_roots(roots):
        if not root.exists():
            continue
        try:
            out.extend(path.resolve() for path in root.rglob("*.sfz") if path.is_file())
        except OSError:
            continue
    return sorted(set(out), key=lambda p: str(p).lower())




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

def _matches_required(path_text: str, alias: SfzLibraryAlias) -> bool:
    if not alias.required_any:
        return True
    return any(all(token in path_text for token in tokens) for tokens in alias.required_any)


def _score_candidate(
    path: Path,
    *,
    alias: SfzLibraryAlias | None,
    prefer: Iterable[str] = (),
    roots: Iterable[str | Path] | None = None,
) -> int:
    text = _candidate_text(path, roots)
    score = 0
    if alias is not None:
        for token in alias.prefer:
            if token.lower() in text:
                score += 12
        for token in alias.avoid:
            if token.lower() in text:
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
                return sorted(glob_candidates, key=lambda p: (-_score_candidate(p, alias=None, prefer=prefer, roots=search_roots), str(p)))[0]
    if not library_ref:
        return None
    alias = ALIASES.get(library_ref, SfzLibraryAlias(ref=library_ref, required_any=(tuple(_normalize_text(library_ref).split()),)))
    candidates = []
    for path in discover_sfz_files(search_roots):
        text = _candidate_text(path, search_roots)
        if _matches_required(text, alias):
            candidates.append(path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: (-_score_candidate(p, alias=alias, prefer=prefer, roots=search_roots), str(p)))[0]


def collect_sfz_library_diagnostics(*, limit: int = 200) -> dict[str, Any]:
    """Return a JSON-serializable report of configured SFZ libraries."""

    roots = configured_sfz_roots()
    files = discover_sfz_files(roots)
    alias_hits: dict[str, str | None] = {}
    for name in sorted(ALIASES):
        resolved = resolve_sfz_reference(library_ref=name, roots=roots)
        alias_hits[name] = str(resolved) if resolved is not None else None
    return {
        "sfz_roots": [str(root) for root in roots],
        "sfz_count": len(files),
        "sfz_files": [str(path) for path in files[:limit]],
        "alias_hits": alias_hits,
    }

"""Canonical render-dependency identity for MusicIR audio generation.

A render is current when the *inputs that can change its audio* are current.
Historically that question was approximated by a hand-bumped renderer version,
raw YAML text, backend name, and SoundFont path.  That missed important changes
(sample libraries installed in place, SFZ sample files replaced, renderer code
edits without a version bump) while invalidating on harmless YAML formatting.

This module is the single authority for static render identity.  It combines:

* the canonical :class:`~ambition_music_renderer.musicir.model.CompiledScore`;
* audio/mix settings not represented by the compiled note/event contract;
* the concrete instrument-resolution plan for the current machine;
* identities of the SoundFont and SFZ/include/sample files actually referenced;
* renderer implementation source and relevant runtime/tool versions.

The resulting payload is intentionally inspectable and stored in render
manifests.  The short hash is only a filename/directory key; currentness checks
use the full SHA-256 fingerprint recorded in the manifest.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import importlib.metadata
import json
import os
import re
import shlex
import shutil
import sys
from urllib.parse import unquote, urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..instrument_resolution import (
    backend_prefers_sfizz,
    instrument_backend_spec,
    resolve_instrument_backend,
)
from ..musicir.compile import compile_score
from ..musicir.model import CompiledScore, compiled_score_fingerprint
from .score_core import RENDERER_VERSION, choose_soundfont


RENDER_DEPENDENCY_SCHEMA = "ambition.render_dependencies.v1"
RENDER_FINGERPRINT_ALGORITHM = "sha256"

_INCLUDE_RE = re.compile(r'#include\s+["<]([^">]+)[">]', re.IGNORECASE)
_DEFINE_RE = re.compile(r"#define\s+(\$[A-Za-z0-9_]+)\s+([^\s]+)", re.IGNORECASE)
_DEFAULT_PATH_RE = re.compile(r"\bdefault_path=([^\s<]+)", re.IGNORECASE)
_SAMPLE_RE = re.compile(r"\bsample=([^\n<]+?)(?=\s+[A-Za-z][A-Za-z0-9_]*=|\s*$)", re.IGNORECASE)
_FILE_URI_RE = re.compile(r"file://[^\s<>\"']+")

_CORE_RUNTIME_PACKAGES = (
    "numpy",
    "scipy",
    "numba",
    "pretty_midi",
    "pyfluidsynth",
    "soundfile",
    "mido",
)

_PEDALBOARD_EFFECTS = {
    "compressor", "compress", "limiter", "limit", "reverb", "chorus",
    "phaser", "gain", "volume", "level", "distortion", "distort", "drive",
    "clipping", "clip", "hard_clip", "bitcrush", "bit_crush", "crusher",
    "resample", "downsample", "sample_rate_reduce", "delay", "pitch_shift",
    "pitchshift", "highpass", "highpass_filter", "hp", "lowpass",
    "lowpass_filter", "lp",
}



def _json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(payload: Any) -> str:
    return hashlib.sha256(_json_text(payload).encode("utf8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_identity(path: str | Path | None, *, content_hash: bool = False) -> dict[str, Any] | None:
    """Return a deterministic local-file identity suitable for cache keys.

    Large sample/SoundFont files use path + size + nanosecond mtime so we do not
    hash gigabytes before every render.  Small control files such as SFZ/include
    programs request ``content_hash=True`` and therefore remain robust against a
    timestamp-preserving text edit.
    """

    if path is None or str(path) == "":
        return None
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        resolved = candidate
    payload: dict[str, Any] = {"path": str(resolved), "exists": resolved.is_file()}
    try:
        stat = resolved.stat()
    except OSError:
        return payload
    payload.update({"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)})
    if content_hash and resolved.is_file():
        try:
            payload["sha256"] = _sha256_file(resolved)
        except OSError:
            pass
    return payload


def path_dependency_identity(path: str | Path | None) -> dict[str, Any] | None:
    """Identity for a file or a small plugin bundle directory.

    VST3 plugins are commonly directories. Hashing their bytes on every render
    would be wasteful, so bundle identity uses relative path, size, and mtime for
    every contained file. Ordinary files reuse :func:`file_identity`.
    """

    if path is None or str(path) == "":
        return None
    candidate = Path(path).expanduser().resolve(strict=False)
    if candidate.is_file() or not candidate.exists():
        return file_identity(candidate)
    if not candidate.is_dir():
        return {"path": str(candidate), "exists": candidate.exists()}
    rows: list[tuple[str, int, int]] = []
    try:
        files = sorted(item for item in candidate.rglob("*") if item.is_file())
    except OSError:
        files = []
    for item in files:
        try:
            stat = item.stat()
            rel = item.relative_to(candidate).as_posix()
        except OSError:
            continue
        rows.append((rel, int(stat.st_size), int(stat.st_mtime_ns)))
    return {
        "path": str(candidate),
        "exists": candidate.is_dir(),
        "kind": "directory",
        "file_count": len(rows),
        "tree_fingerprint": _sha256_text(rows),
    }


def package_version_identity(name: str) -> dict[str, Any]:
    """Record an optional Python package version without requiring it."""

    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        version = None
    return {"package": name, "version": version}


def executable_identity(command: str | None) -> dict[str, Any] | None:
    """Describe the executable selected by one render dependency."""

    if not command:
        return None
    text = str(command)
    if os.path.sep in text:
        resolved = Path(text).expanduser()
        if not resolved.exists():
            return {"requested": text, "resolved": None}
        path = str(resolved.resolve())
    else:
        path = shutil.which(text)
        if path is None:
            return {"requested": text, "resolved": None}
    return {"requested": text, "resolved": path, "file": file_identity(path)}


def _renderer_package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _compute_renderer_implementation_identity(root: Path) -> dict[str, Any]:
    files = sorted(
        [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]
        + list((root / "data").glob("*.yaml"))
    )
    h = hashlib.sha256()
    included = 0
    for path in files:
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
        except OSError:
            continue
        h.update(rel.encode("utf8"))
        h.update(b"\0")
        h.update(hashlib.sha256(data).digest())
        h.update(b"\0")
        included += 1
    return {"fingerprint": h.hexdigest(), "file_count": included}


@functools.lru_cache(maxsize=1)
def _default_renderer_implementation_identity() -> dict[str, Any]:
    return _compute_renderer_implementation_identity(_renderer_package_root().resolve())


def renderer_implementation_identity(package_root: Path | None = None) -> dict[str, Any]:
    """Fingerprint production renderer source and checked-in renderer data.

    The normal renderer tree is process-static and cached after the first hash.
    Explicit roots (used by tests/tools) are recomputed so callers can compare
    source revisions in one process.
    """

    if package_root is None:
        return dict(_default_renderer_implementation_identity())
    return _compute_renderer_implementation_identity(Path(package_root).resolve())


def runtime_environment_identity(*, include_export_tools: bool = True) -> dict[str, Any]:
    """Versions/settings that can select different DSP or synthesis code."""

    versions: dict[str, str | None] = {}
    for name in _CORE_RUNTIME_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    payload = {
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "packages": versions,
        "environment": {
            "AMBITION_MUSIC_RENDERER_DISABLE_NUMBA": os.environ.get(
                "AMBITION_MUSIC_RENDERER_DISABLE_NUMBA"
            ),
        },
    }
    if include_export_tools:
        # Encoding can affect final OGG bytes and availability selects the
        # soundfile-vs-ffmpeg path in render.export.
        payload["ffmpeg"] = executable_identity("ffmpeg")
    return payload


def _clean_sfz_token(value: str) -> str:
    value = value.strip().strip('"').strip("'")
    return value.replace("\\", "/")


def _expand_sfz_macros(value: str, macros: Mapping[str, str]) -> str:
    out = value
    for key in sorted(macros, key=len, reverse=True):
        out = out.replace(key, macros[key])
    return out


def _resolve_sample_reference(sfz_file: Path, raw: str, default_path: str) -> Path | None:
    token = _clean_sfz_token(raw)
    if not token or token.startswith("*") or "$" in token:
        return None
    rel = Path(token)
    default = Path(_clean_sfz_token(default_path)) if default_path else Path()
    # Libraries disagree about whether sample paths in include fragments are
    # relative to the fragment, the top-level program, or a nearby ancestor.
    # Search the same useful ancestor space as the existing SFZ audits.
    for parent in (sfz_file.parent, *sfz_file.parents):
        for candidate in (parent / default / rel, parent / rel):
            try:
                resolved = candidate.resolve(strict=False)
            except OSError:
                resolved = candidate
            if resolved.is_file():
                return resolved
    return None


def sfz_dependency_identity(path: str | Path) -> dict[str, Any]:
    """Fingerprint one SFZ program and the sample files it can reference.

    Program/include text is content-hashed.  Referenced sample files are reduced
    to a digest of path/size/mtime identities, so changing one sample invalidates
    only cues/stems that use its SFZ instead of invalidating the whole installed
    library tree.
    """

    root = Path(path).expanduser().resolve(strict=False)
    seen: set[Path] = set()
    program_identities: list[dict[str, Any]] = []
    sample_paths: set[Path] = set()
    unresolved_samples: set[str] = set()

    # sfizz's include handling in these libraries is commonly rooted at the
    # top-level program directory; try current-file-relative first and then root.
    top_base = root.parent

    macros: dict[str, str] = {}

    def visit(current: Path) -> None:
        current = current.resolve(strict=False)
        if current in seen:
            return
        seen.add(current)
        identity = file_identity(current, content_hash=True)
        if identity is not None:
            program_identities.append(identity)
        try:
            text = current.read_text(encoding="utf8", errors="replace")
        except OSError:
            return
        for name, value in _DEFINE_RE.findall(text):
            macros[str(name)] = _clean_sfz_token(str(value))
        default_match = _DEFAULT_PATH_RE.search(text)
        default_path = (
            _expand_sfz_macros(_clean_sfz_token(default_match.group(1)), macros)
            if default_match
            else ""
        )

        for include in _INCLUDE_RE.findall(text):
            rel = Path(_expand_sfz_macros(_clean_sfz_token(include), macros))
            candidates = (current.parent / rel, top_base / rel)
            target = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
            visit(target)

        for raw in _SAMPLE_RE.findall(text):
            token = _expand_sfz_macros(_clean_sfz_token(raw), macros)
            if not token or token.startswith("*"):
                continue
            resolved = _resolve_sample_reference(current, token, default_path)
            if resolved is None:
                unresolved_samples.add(token)
            else:
                sample_paths.add(resolved)

    visit(root)
    program_identities.sort(key=lambda row: str(row.get("path")))
    sample_identities = [file_identity(path) for path in sorted(sample_paths, key=str)]
    sample_identities = [row for row in sample_identities if row is not None]
    sample_digest = _sha256_text(sample_identities)
    return {
        "program": file_identity(root, content_hash=True),
        "program_files": program_identities,
        "sample_file_count": len(sample_identities),
        "sample_files_fingerprint": sample_digest,
        "missing_or_dynamic_sample_count": len(unresolved_samples),
        "missing_or_dynamic_samples": sorted(unresolved_samples)[:8],
    }


def _audio_settings_payload(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Audio-affecting authored settings outside the compiled note contract."""

    section_mix_fields: list[dict[str, Any]] = []
    for raw in spec.get("sections", []) or []:
        if not isinstance(raw, Mapping):
            continue
        row = {"id": raw.get("id")}
        for key in ("mix_gain_db", "mix_gain_transition_beats", "postprocess"):
            if key in raw:
                row[key] = copy.deepcopy(raw.get(key))
        section_mix_fields.append(row)
    return {
        "render": copy.deepcopy(spec.get("render", {}) or {}),
        "stem_postprocess": copy.deepcopy(spec.get("stem_postprocess", {}) or {}),
        "group_postprocess": copy.deepcopy(spec.get("group_postprocess", {}) or {}),
        "postprocess": copy.deepcopy(spec.get("postprocess", {}) or {}),
        "section_audio": section_mix_fields,
        # These select full-length runtime/audition stem combinations.
        "state_map": copy.deepcopy(spec.get("state_map", {}) or {}),
        "playback": copy.deepcopy(spec.get("playback", {}) or {}),
    }


def _resolve_existing_token(raw: str, *, base_dir: Path) -> Path | None:
    if not raw or "{" in raw or "}" in raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        resolved = candidate
    return resolved if resolved.exists() else None


def command_dependency_identity(
    command: str | list[Any] | tuple[Any, ...] | None,
    *,
    base_dir: Path,
) -> dict[str, Any] | None:
    """Resolve executable and explicit file arguments in a command template."""

    if not command:
        return None
    if isinstance(command, str):
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = [command]
    else:
        parts = [str(item) for item in command]
    if not parts:
        return None
    executable = parts[0]
    explicit_files: list[dict[str, Any]] = []
    for token in parts[1:]:
        path = _resolve_existing_token(token, base_dir=base_dir)
        if path is not None:
            identity = path_dependency_identity(path)
            if identity is not None:
                explicit_files.append(identity)
    return {
        "executable": executable_identity(executable),
        "explicit_files": explicit_files,
    }


def _vst3_dependency_identity(raw: Any, *, base_dir: Path) -> dict[str, Any]:
    from ..audio_plugins import resolve_vst3_reference

    requested = str(raw)
    resolved = resolve_vst3_reference(requested, base_dir=base_dir)
    return {
        "requested": requested,
        "resolved": path_dependency_identity(resolved) if resolved is not None else None,
        "pedalboard": package_version_identity("pedalboard"),
    }


def _lv2_dependency_identity(spec: Mapping[str, Any]) -> dict[str, Any]:
    from ..audio_plugins import lv2_info

    binary = str(spec.get("binary") or "lv2proc")
    uri = str(spec.get("plugin_uri") or spec.get("uri") or "")
    payload: dict[str, Any] = {
        "host": executable_identity(binary),
        "plugin_uri": uri or None,
        "lv2info": executable_identity("lv2info"),
    }
    if uri and shutil.which("lv2info"):
        info = lv2_info(uri)
        stdout = str(info.get("stdout") or "")
        payload["plugin_metadata_fingerprint"] = _sha256_text(
            {
                "ok": info.get("ok"),
                "returncode": info.get("returncode"),
                "stdout": stdout,
                "stderr": info.get("stderr"),
            }
        )
        plugin_files: list[dict[str, Any]] = []
        for uri_text in sorted(set(_FILE_URI_RE.findall(stdout))):
            try:
                parsed = urlparse(uri_text)
                candidate = Path(unquote(parsed.path))
            except Exception:
                continue
            if candidate.exists():
                identity = path_dependency_identity(candidate)
                if identity is not None:
                    plugin_files.append(identity)
        if plugin_files:
            payload["plugin_files"] = plugin_files
    return payload


def processing_dependency_payload(
    spec: Mapping[str, Any],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    """Concrete optional processor/plugin dependencies requested by a score."""

    from ..audio_plugins import collect_effect_specs

    rows: dict[str, Any] = {}
    uses_pedalboard = False
    vst3_cache: dict[str, dict[str, Any]] = {}
    for path, raw_spec in collect_effect_specs(dict(spec)):
        effect_spec = dict(raw_spec or {})
        kind = str(
            effect_spec.get("kind")
            or effect_spec.get("type")
            or effect_spec.get("backend")
            or effect_spec.get("effect")
            or ""
        ).lower().strip()
        row: dict[str, Any] = {}
        if kind in {"pedalboard", "pb"} or kind in _PEDALBOARD_EFFECTS:
            uses_pedalboard = True
        if kind in {"vst3", "vst", "plugin"}:
            uses_pedalboard = True
            raw = effect_spec.get("path") or effect_spec.get("plugin")
            if raw:
                key = str(raw)
                if key not in vst3_cache:
                    vst3_cache[key] = _vst3_dependency_identity(raw, base_dir=base_dir)
                row["vst3"] = copy.deepcopy(vst3_cache[key])
        if kind in {"lv2", "lv2proc", "nam_lv2", "neural_amp_modeler"}:
            row["lv2"] = _lv2_dependency_identity(effect_spec)
        if kind in {"command", "external", "nam", "guitarix"} or effect_spec.get("command"):
            command = effect_spec.get("command")
            if command:
                row["command"] = command_dependency_identity(command, base_dir=base_dir)
        # Host/model/preset files can affect output while retaining the same
        # authored path. Only known file-like keys are interpreted here.
        files: dict[str, Any] = {}
        for key in ("model", "model_path", "preset", "preset_path", "ir", "impulse_response"):
            raw = effect_spec.get(key)
            if not isinstance(raw, (str, Path)):
                continue
            resolved = _resolve_existing_token(str(raw), base_dir=base_dir)
            if resolved is not None:
                files[key] = path_dependency_identity(resolved)
        if files:
            row["files"] = files
        if row:
            rows[path] = row
    return {
        "pedalboard": package_version_identity("pedalboard") if uses_pedalboard else None,
        "effects": rows,
    }


def _group_default_fallbacks(
    compiled: CompiledScore,
    *,
    backend: str,
    render_cfg: Mapping[str, Any],
) -> dict[str, str]:
    sfizz_cfg = dict(render_cfg.get("sfizz") or {})
    wants_sfizz = backend in {"sfizz", "sfizz-render"}
    grouped_names: dict[str, list[str]] = {}
    for inst in compiled.pm.instruments:
        grouped_names.setdefault(compiled.groups.get(inst.name, ""), []).append(str(inst.name))
    out: dict[str, str] = {}
    for group, names in grouped_names.items():
        has_sfizz = any(
            backend_prefers_sfizz(instrument_backend_spec(compiled.instrument_specs, name))
            for name in names
        )
        out[group] = str(
            sfizz_cfg.get(
                "fallback_backend",
                render_cfg.get(
                    "sfizz_fallback_backend",
                    "auto" if wants_sfizz or has_sfizz else backend,
                ),
            )
        )
    return out


def instrument_dependency_payload(
    compiled: CompiledScore,
    *,
    base_dir: Path,
    backend: str,
    render_cfg: Mapping[str, Any],
    instrument_names: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve the concrete machine dependencies for selected instruments."""

    sfizz_cfg = dict(render_cfg.get("sfizz") or {})
    wants_sfizz = backend in {"sfizz", "sfizz-render"}
    fallbacks = _group_default_fallbacks(compiled, backend=backend, render_cfg=render_cfg)
    rows: dict[str, Any] = {}
    sfz_binary_requests: set[str] = set()
    vst3_cache: dict[str, dict[str, Any]] = {}

    for inst in compiled.pm.instruments:
        name = str(inst.name)
        if instrument_names is not None and name not in instrument_names:
            continue
        group = str(compiled.groups.get(name, ""))
        raw_backend = instrument_backend_spec(compiled.instrument_specs, name)
        plan = resolve_instrument_backend(
            raw_backend,
            base_dir=base_dir,
            sfizz_cfg=sfizz_cfg,
            default_fallback_backend=fallbacks.get(group, backend),
            force_sfz=wants_sfizz,
        )
        settings = dict(plan.sfizz_settings)
        sfizz_execution: dict[str, Any] | None = None
        if plan.wants_sfz:
            binary = str(settings.get("binary") or "sfizz_render")
            sfz_binary_requests.add(binary)
            renderer = str(settings.get("renderer") or "auto").lower().strip()
            sfizz_execution = {
                "renderer": renderer,
                "cli": executable_identity(binary),
                "command": command_dependency_identity(
                    settings.get("command"), base_dir=base_dir
                ),
            }
            if renderer in {"auto", "vst3", "pedalboard", "sfizz_vst3"}:
                plugin_ref = (
                    settings.get("vst3_plugin")
                    or settings.get("plugin")
                    or settings.get("path")
                    or "sfizz"
                )
                cache_key = str(plugin_ref)
                if cache_key not in vst3_cache:
                    vst3_cache[cache_key] = _vst3_dependency_identity(
                        plugin_ref, base_dir=base_dir
                    )
                sfizz_execution["vst3"] = copy.deepcopy(vst3_cache[cache_key])
        rows[name] = {
            "group": group,
            "kind": plan.kind,
            "library_ref": plan.library_ref,
            "requested": plan.requested,
            "resolved_sfz": (
                sfz_dependency_identity(plan.resolved_sfz)
                if plan.resolved_sfz is not None
                else None
            ),
            "fallback_backend": plan.fallback_backend,
            "optional": bool(plan.optional),
            "wants_sfz": bool(plan.wants_sfz),
            "wants_procedural_fm": bool(plan.wants_procedural_fm),
            "sfizz_renderer": settings.get("renderer", "auto") if plan.wants_sfz else None,
            "sfizz_binary": settings.get("binary", "sfizz_render") if plan.wants_sfz else None,
            "sfizz_command": copy.deepcopy(settings.get("command")) if plan.wants_sfz else None,
            "sfizz_execution": sfizz_execution,
        }

    return {
        "instruments": rows,
        "executables": {
            binary: executable_identity(binary) for binary in sorted(sfz_binary_requests)
        },
    }


@dataclass(frozen=True)
class RenderDependencyFingerprint:
    """Inspectable full render identity plus compact filename hash."""

    payload: dict[str, Any]
    fingerprint: str

    @property
    def short_hash(self) -> str:
        return self.fingerprint[:16]

    def manifest_payload(self) -> dict[str, Any]:
        return {
            "schema": RENDER_DEPENDENCY_SCHEMA,
            "algorithm": RENDER_FINGERPRINT_ALGORITHM,
            "fingerprint": self.fingerprint,
            "short_hash": self.short_hash,
            # Kept for historical/debugging continuity only.  It is explicitly
            # not part of the fingerprint payload.
            "legacy_renderer_version": RENDERER_VERSION,
            "dependencies": copy.deepcopy(self.payload),
        }


def build_render_dependency_fingerprint(
    *,
    spec_path: Path,
    spec: Mapping[str, Any],
    compiled: CompiledScore,
    backend: str,
    soundfont: str,
    package_root: Path | None = None,
) -> RenderDependencyFingerprint:
    """Build the canonical static identity of one complete audio render."""

    render_cfg = dict(spec.get("render") or {})
    payload = {
        "schema": RENDER_DEPENDENCY_SCHEMA,
        "compiled_score_fingerprint": compiled_score_fingerprint(compiled),
        "backend": str(backend),
        "soundfont": file_identity(soundfont),
        "audio_settings": _audio_settings_payload(spec),
        "instrument_resolution": instrument_dependency_payload(
            compiled,
            base_dir=Path(spec_path).resolve().parent,
            backend=str(backend),
            render_cfg=render_cfg,
        ),
        "processing": processing_dependency_payload(
            spec, base_dir=Path(spec_path).resolve().parent
        ),
        "renderer_implementation": renderer_implementation_identity(package_root),
        "runtime_environment": runtime_environment_identity(),
    }
    return RenderDependencyFingerprint(payload=payload, fingerprint=_sha256_text(payload))


def render_dependency_fingerprint_for_score(
    spec_path: Path,
    backend: str,
    *,
    spec: dict[str, Any] | None = None,
    compiled: CompiledScore | None = None,
    package_root: Path | None = None,
    soundfont_override: str | None = None,
) -> RenderDependencyFingerprint:
    """Load/compile a score and compute the same identity used by rendering."""

    import yaml

    spec_path = Path(spec_path)
    if spec is None:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf8")) or {}
    # Preserve the historical preflight ordering: explicit render resources are
    # resolved before score construction, so a broken SoundFont path is reported
    # directly even when the score also has a structural error.
    render_cfg = dict(spec.get("render") or {})
    soundfont = (
        str(soundfont_override)
        if soundfont_override is not None
        else choose_soundfont(render_cfg.get("soundfont"))
    )
    if compiled is None:
        compiled = compile_score(spec)
    return build_render_dependency_fingerprint(
        spec_path=spec_path,
        spec=spec,
        compiled=compiled,
        backend=backend,
        soundfont=soundfont,
        package_root=package_root,
    )


def dependency_change_summary(
    recorded: Mapping[str, Any] | None,
    current: RenderDependencyFingerprint,
) -> list[str]:
    """Return concise top-level reasons a recorded render is no longer current."""

    if not recorded:
        return ["manifest has no render dependency record"]
    if recorded.get("schema") != RENDER_DEPENDENCY_SCHEMA:
        return [f"render dependency schema changed ({recorded.get('schema')!r} -> {RENDER_DEPENDENCY_SCHEMA!r})"]
    if recorded.get("fingerprint") == current.fingerprint:
        return []
    before = recorded.get("dependencies") or {}
    after = current.payload
    changed = [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
    if not changed:
        return ["render dependency fingerprint changed"]
    return [f"render dependencies changed: {', '.join(changed)}"]

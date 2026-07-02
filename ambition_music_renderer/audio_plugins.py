"""Discovery and validation helpers for optional music-renderer plugins.

The music renderer deliberately keeps LV2/VST/SFZ tooling optional.  This
module is the stable inspection surface for those optional tools: it can report
what is installed, list VST3 bundles/LV2 plugin URIs, and validate YAML scores
before a render tries to execute a host-specific effect chain.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

from .instrument_libraries import (
    collect_sfz_library_diagnostics,
    resolve_sfz_reference,
)


PYTHON_MODULES = ("pedalboard", "pyloudnorm", "pretty_midi", "soundfile")
EXTERNAL_BINARIES = (
    "sfizz_render",
    "lv2ls",
    "lv2info",
    "lv2proc",
    "jalv",
    "guitarix",
    "carla-single",
)


def _split_path_env(value: str | None) -> list[Path]:
    if not value:
        return []
    out: list[Path] = []
    for part in value.split(os.pathsep):
        if part.strip():
            out.append(Path(part).expanduser())
    return out


def common_vst3_dirs() -> list[Path]:
    """Return VST3 search directories in priority order.

    The list is intentionally conservative and filesystem based.  It does not
    scan plugin databases owned by a DAW; those are not portable across users or
    CI machines.
    """

    dirs: list[Path] = []
    dirs.extend(_split_path_env(os.environ.get("AMBITION_MUSIC_VST3_PATHS")))
    dirs.extend(_split_path_env(os.environ.get("VST3_PATH")))
    home = Path.home()
    dirs.extend(
        [
            home / ".vst3",
            home / ".local" / "lib" / "vst3",
            Path("/usr/local/lib/vst3"),
            Path("/usr/lib/vst3"),
        ]
    )
    # Preserve order while removing duplicates.
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        resolved = d.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def discover_vst3_plugins(search_dirs: Iterable[Path] | None = None) -> list[dict[str, Any]]:
    """Find local VST3 bundle paths without loading them."""

    plugins: list[dict[str, Any]] = []
    for directory in search_dirs or common_vst3_dirs():
        d = Path(directory).expanduser()
        if not d.exists():
            continue
        try:
            matches = sorted(d.rglob("*.vst3"))
        except OSError:
            continue
        for path in matches:
            plugins.append(
                {
                    "name": path.stem,
                    "path": str(path),
                    "is_dir": path.is_dir(),
                }
            )
    return plugins


def common_clap_dirs() -> list[Path]:
    """Return CLAP search directories in priority order."""

    dirs: list[Path] = []
    dirs.extend(_split_path_env(os.environ.get("AMBITION_MUSIC_CLAP_PATHS")))
    dirs.extend(_split_path_env(os.environ.get("CLAP_PATH")))
    audio_tools = os.environ.get("AMBITION_AUDIO_TOOLS_ROOT")
    if audio_tools:
        dirs.append(Path(audio_tools).expanduser() / "plugins" / "clap")
    dirs.append(Path("/data/audio-tools/plugins/clap"))
    home = Path.home()
    dirs.extend(
        [
            home / ".clap",
            home / ".local" / "lib" / "clap",
            Path("/usr/local/lib/clap"),
            Path("/usr/lib/clap"),
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        resolved = d.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def discover_clap_plugins(search_dirs: Iterable[Path] | None = None) -> list[dict[str, Any]]:
    """Find local CLAP plugin bundle paths without loading them."""

    plugins: list[dict[str, Any]] = []
    for directory in search_dirs or common_clap_dirs():
        d = Path(directory).expanduser()
        if not d.exists():
            continue
        try:
            matches = sorted(d.rglob("*.clap"))
        except OSError:
            continue
        for path in matches:
            plugins.append(
                {
                    "name": path.stem,
                    "path": str(path),
                    "is_dir": path.is_dir(),
                }
            )
    return plugins


def resolve_vst3_reference(ref: str | Path, *, base_dir: Path | None = None) -> Path | None:
    """Resolve a VST3 path or discovered plugin name.

    Returns ``None`` when the reference is name-like and no discovered plugin
    matches.  Existing relative paths are resolved against ``base_dir`` first.
    """

    p = Path(ref).expanduser()
    if not p.is_absolute() and base_dir is not None:
        candidate = (base_dir / p).resolve()
        if candidate.exists():
            return candidate
    if p.exists():
        return p.resolve()
    raw = str(ref).strip()
    for plugin in discover_vst3_plugins():
        if raw in {plugin["name"], Path(plugin["path"]).name, plugin["path"]}:
            return Path(plugin["path"]).resolve()
    return None


def _run_text(cmd: list[str], *, timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as ex:
        return 127, "", str(ex)
    except subprocess.TimeoutExpired as ex:
        return 124, ex.stdout or "", ex.stderr or f"timeout after {timeout:g}s"


def discover_lv2_plugins(*, binary: str = "lv2ls", limit: int | None = None) -> list[str]:
    """Return installed LV2 plugin URIs using ``lv2ls`` when available."""

    if not shutil.which(binary):
        return []
    code, stdout, _stderr = _run_text([binary])
    if code != 0:
        return []
    uris = [line.strip() for line in stdout.splitlines() if line.strip()]
    if limit is not None:
        uris = uris[: int(limit)]
    return uris


def lv2_info(uri: str, *, binary: str = "lv2info", timeout: float = 10.0) -> dict[str, Any]:
    """Inspect one LV2 plugin URI with ``lv2info``.

    The returned text is intentionally raw-ish because LV2 port/state semantics
    vary by plugin.  Higher-level adapters should parse only the plugins they
    know how to use.
    """

    if not shutil.which(binary):
        return {"ok": False, "uri": uri, "error": f"{binary!r} not found"}
    code, stdout, stderr = _run_text([binary, uri], timeout=timeout)
    return {
        "ok": code == 0,
        "uri": uri,
        "returncode": code,
        "stdout": stdout,
        "stderr": stderr,
    }


def _module_status(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    status: dict[str, Any] = {"available": spec is not None}
    if spec is not None:
        status["origin"] = spec.origin
    return status


def _binary_status(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"available": path is not None, "path": path}


def collect_plugin_diagnostics(*, probe_counts: bool = True) -> dict[str, Any]:
    """Collect a JSON-serializable optional-backend diagnostic report."""

    report: dict[str, Any] = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "modules": {name: _module_status(name) for name in PYTHON_MODULES},
        "binaries": {name: _binary_status(name) for name in EXTERNAL_BINARIES},
        "vst3_search_dirs": [str(p) for p in common_vst3_dirs()],
        "clap_search_dirs": [str(p) for p in common_clap_dirs()],
    }
    if probe_counts:
        vst3 = discover_vst3_plugins()
        report["vst3"] = {"count": len(vst3), "plugins": vst3[:100]}
        clap = discover_clap_plugins()
        report["clap"] = {"count": len(clap), "plugins": clap[:100]}
        lv2 = discover_lv2_plugins(limit=250)
        report["lv2"] = {"count": len(lv2), "uris": lv2}
        report["sfz_libraries"] = collect_sfz_library_diagnostics(limit=100)
    return report


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _walk_dicts(node: Any, path: str = "$") -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            child = f"{path}.{key}"
            yield from _walk_dicts(value, child)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from _walk_dicts(value, f"{path}[{idx}]")


def _collect_effect_specs(score: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    # `effect_chain` is the single cross-backend effects surface; its steps carry
    # nested `effects`/`chain`/`plugins` lists which add_spec() recurses into.
    keys = {"effect_chain"}

    def add_spec(spec_path: str, value: Any) -> None:
        if isinstance(value, dict):
            specs.append((spec_path, value))
            for nested_key in ("effects", "chain", "plugins"):
                if nested_key in value:
                    for nested_idx, nested in enumerate(_as_list(value.get(nested_key))):
                        add_spec(f"{spec_path}.{nested_key}[{nested_idx}]", nested)
        else:
            specs.append((spec_path, {"kind": str(value)}))

    for path, node in _walk_dicts(score):
        for key in keys:
            if key not in node:
                continue
            for idx, spec in enumerate(_as_list(node.get(key))):
                add_spec(f"{path}.{key}[{idx}]", spec)
    return specs


def _collect_instrument_backend_specs(score: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    instruments = score.get("instruments", [])
    if not isinstance(instruments, list):
        return specs
    for idx, inst in enumerate(instruments):
        if not isinstance(inst, dict):
            continue
        raw = inst.get("instrument_backend", inst.get("backend", None))
        if raw is None and "sfz" in inst:
            raw = {"sfz": inst.get("sfz")}
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = {"kind": raw}
        if not isinstance(raw, dict):
            raw = {}
        if "sfz" in inst and "sfz" not in raw:
            raw = {**raw, "sfz": inst["sfz"]}
        name = inst.get("name", idx)
        specs.append((f"$.instruments[{idx}]({name}).instrument_backend", raw))
    return specs


def _spec_missing_severity(spec: dict[str, Any]) -> str:
    if "required" in spec:
        return "error" if bool(spec.get("required")) else "warning"
    return "warning" if bool(spec.get("optional", True)) else "error"


def validate_instrument_backend_spec(
    spec: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Return warnings/errors for one instrument backend spec."""

    messages: list[dict[str, Any]] = []
    severity = _spec_missing_severity(spec)
    kind = str(spec.get("kind") or spec.get("type") or "").lower().strip()
    wants_sfz = kind in {"sfz", "sfizz", "sample", "sampled"} or any(
        key in spec for key in ("sfz", "sfz_path", "sfz_glob", "library_ref", "library")
    )
    if not wants_sfz:
        return messages
    settings = dict(spec.get("settings") or {})
    binary = str(spec.get("binary", settings.get("binary", "sfizz_render")))
    renderer = str(settings.get("renderer", spec.get("renderer", "auto"))).lower().strip()
    if not shutil.which(binary):
        vst3_plugin = settings.get("vst3_plugin") or spec.get("vst3_plugin") or "sfizz"
        vst3_path = resolve_vst3_reference(str(vst3_plugin), base_dir=base_dir)
        pedalboard_available = importlib.util.find_spec("pedalboard") is not None
        if renderer in {"auto", "vst3", "pedalboard", "sfizz_vst3"} and vst3_path is not None and pedalboard_available:
            messages.append({
                "severity": severity,
                "message": f"{binary!r} not found; SFZ rendering will try sfizz VST3: {vst3_path}",
            })
        else:
            messages.append({
                "severity": severity,
                "message": f"{binary!r} not found for SFZ instrument rendering",
            })
    prefer = spec.get("prefer") or spec.get("prefer_keywords") or []
    resolved = resolve_sfz_reference(
        spec.get("sfz") or spec.get("path") or spec.get("sfz_path") or spec.get("sfz_glob"),
        library_ref=spec.get("library_ref") or spec.get("library"),
        prefer=[str(item) for item in prefer],
        base_dir=base_dir,
        roots=spec.get("library_roots") or [],
    )
    if resolved is None:
        requested = spec.get("library_ref") or spec.get("library") or spec.get("sfz") or spec.get("sfz_path") or spec.get("sfz_glob")
        messages.append({
            "severity": severity,
            "message": f"SFZ library reference did not resolve: {requested!r}",
        })
    else:
        messages.append({
            "severity": "info",
            "message": f"SFZ instrument resolved: {resolved}",
        })
    return messages


def validate_effect_spec(
    spec: dict[str, Any],
    *,
    base_dir: Path | None = None,
    lv2_uris: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return warnings/errors for one effect spec."""

    messages: list[dict[str, Any]] = []
    # Match the renderer's skip rule (plugin_chain._is_optional_step): a step
    # is skippable when `optional: true` OR `required: false`, so a spec the
    # renderer would warn-and-skip must not validate as a hard error.
    optional = bool(spec.get("optional") or spec.get("required") is False)
    missing_optional_severity = "warning" if optional else "error"
    kind = str(
        spec.get("kind")
        or spec.get("type")
        or spec.get("backend")
        or spec.get("effect")
        or ""
    ).lower().strip()
    if kind in {"pedalboard", "vst3", "vst", "plugin"} or "path" in spec:
        if importlib.util.find_spec("pedalboard") is None:
            messages.append({"severity": missing_optional_severity, "message": "pedalboard Python package is not installed"})
    if kind in {"vst3", "vst", "plugin"} or ("path" in spec and str(spec.get("path", "")).endswith(".vst3")):
        raw_path = spec.get("path") or spec.get("plugin")
        if raw_path:
            resolved = resolve_vst3_reference(str(raw_path), base_dir=base_dir)
            if resolved is None:
                messages.append({"severity": missing_optional_severity, "message": f"VST3 plugin not found: {raw_path}"})
        else:
            messages.append({"severity": "warning", "message": "VST3 spec has no path/plugin reference"})
    if kind in {"clap", "clap_plugin"} or ("path" in spec and str(spec.get("path", "")).endswith(".clap")):
        raw_path = spec.get("path") or spec.get("plugin")
        if raw_path:
            wanted = str(raw_path)
            found = [p for p in discover_clap_plugins() if wanted in {p["name"], Path(p["path"]).name, p["path"]}]
            if not found:
                messages.append({"severity": missing_optional_severity, "message": f"CLAP plugin not found: {raw_path}"})
        messages.append({"severity": "warning", "message": "CLAP discovery is available, but CLAP hosting is not implemented yet; use LV2/VST3/command for renders"})
    if kind in {"lv2", "lv2proc", "nam_lv2", "neural_amp_modeler"}:
        binary = str(spec.get("binary", "lv2proc"))
        if not shutil.which(binary):
            messages.append({"severity": missing_optional_severity, "message": f"{binary!r} not found for LV2 processing"})
        uri = spec.get("plugin_uri") or spec.get("uri")
        if not uri:
            messages.append({"severity": missing_optional_severity, "message": "LV2 effect is missing plugin_uri/uri"})
        elif lv2_uris is not None and uri not in lv2_uris:
            messages.append({"severity": "warning", "message": f"LV2 URI not listed by lv2ls: {uri}"})
    if kind in {"command", "external", "guitarix", "nam"} or "command" in spec:
        command = spec.get("command")
        if command:
            first = command[0] if isinstance(command, list) and command else str(command).split()[0]
            if first and not shutil.which(str(first)) and not Path(str(first)).expanduser().exists():
                messages.append({"severity": "warning", "message": f"external command may not be on PATH: {first}"})
        elif kind in {"command", "external", "guitarix", "nam"}:
            messages.append({"severity": missing_optional_severity, "message": f"{kind} effect requires command"})
    return messages


def validate_score_plugins(score: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    specs = _collect_effect_specs(score)
    instrument_specs = _collect_instrument_backend_specs(score)
    lv2_uris: set[str] | None = None
    if shutil.which("lv2ls"):
        lv2_uris = set(discover_lv2_plugins())
    entries: list[dict[str, Any]] = []
    instrument_entries: list[dict[str, Any]] = []
    error_count = 0
    warning_count = 0

    def count_messages(messages: list[dict[str, Any]]) -> None:
        nonlocal error_count, warning_count
        for msg in messages:
            if msg.get("severity") == "error":
                error_count += 1
            elif msg.get("severity") == "warning":
                warning_count += 1

    for path, spec in specs:
        messages = validate_effect_spec(spec, base_dir=base_dir, lv2_uris=lv2_uris)
        count_messages(messages)
        entries.append({"path": path, "spec": spec, "messages": messages})
    for path, spec in instrument_specs:
        messages = validate_instrument_backend_spec(spec, base_dir=base_dir)
        count_messages(messages)
        instrument_entries.append({"path": path, "spec": spec, "messages": messages})
    return {
        "ok": error_count == 0,
        "effect_specs": entries,
        "effect_spec_count": len(entries),
        "instrument_backend_specs": instrument_entries,
        "instrument_backend_spec_count": len(instrument_entries),
        "errors": error_count,
        "warnings": warning_count,
    }


def load_score(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"score YAML did not load to a mapping: {path}")
    return data

"""Cross-version stem-bank discovery and fast audition mixing.

This module intentionally has no dependency on the music review UI.  Stem Lab
uses it to discover rendered variants, choose per-stem sources, and assemble a
playback-only hybrid from already-rendered audio.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


@dataclass(frozen=True)
class StemVersion:
    cue_id: str
    title: str
    label: str
    render_hash: str
    run_dir: Path
    manifest_path: Path
    full_mix_path: Path | None
    timeline_path: Path | None
    score_snapshot_path: Path | None
    sample_rate: int
    generated_at: float
    source_kind: str

    @property
    def display_hash(self) -> str:
        return self.render_hash[:16]

    @property
    def key(self) -> str:
        payload = f"{self.cue_id}\n{self.render_hash}\n{self.run_dir.resolve()}"
        return hashlib.sha256(payload.encode("utf8")).hexdigest()[:20]


@dataclass(frozen=True)
class StemAsset:
    group: str
    path: Path
    sample_rate: int
    kind: str

    @property
    def balance_faithful(self) -> bool:
        return self.kind in {"native", "review_native"}

    @property
    def quality_label(self) -> str:
        return "native level" if self.balance_faithful else "normalized fallback"


@dataclass(frozen=True)
class MixResult:
    path: Path
    sample_rate: int
    duration_seconds: float
    peak_before_guard: float
    used_normalized_fallback: bool


_REFERENCE_WORDS = (
    "canonical_original",
    "canonical original",
    "baseline",
    "reference",
    "original",
)


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, Mapping) else {}


def _preview_mapping(manifest: Mapping[str, object]) -> Mapping[str, object]:
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        return {}
    preview = files.get("preview")
    return preview if isinstance(preview, Mapping) else {}




def _authoring_mapping(manifest: Mapping[str, object]) -> Mapping[str, object]:
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        return {}
    authoring = files.get("authoring")
    return authoring if isinstance(authoring, Mapping) else {}


def _authoring_file(run_dir: Path, manifest: Mapping[str, object], key: str) -> Path | None:
    rel = _authoring_mapping(manifest).get(key)
    if not rel:
        return None
    path = run_dir / str(rel)
    return path.resolve() if path.is_file() else None


def _full_mix_path(run_dir: Path, manifest: Mapping[str, object]) -> Path | None:
    preview = _preview_mapping(manifest)
    for key in ("full_soundtrack", "simple_mix", "mastered_full_mix", "full_mix"):
        rel = preview.get(key)
        if rel:
            path = run_dir / str(rel)
            if path.is_file():
                return path.resolve()
    return None


def _version_label(run_dir: Path, manifest: Mapping[str, object], *, source_kind: str) -> str:
    explicit = manifest.get("variant_label") or manifest.get("variant")
    if explicit:
        return str(explicit)
    if source_kind == "scratch_render":
        return run_dir.name
    if source_kind == "folder":
        return run_dir.name
    render_hash = str(manifest.get("hash") or "")
    return f"latest generated ({render_hash[:8]})" if source_kind == "generated_latest" else render_hash[:16]


def version_from_manifest(
    manifest_path: Path,
    *,
    source_kind: str,
    label: str | None = None,
) -> StemVersion | None:
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_json(manifest_path)
    cue_id = str(manifest.get("id") or "")
    render_hash = str(manifest.get("hash") or "")
    if not cue_id or not render_hash:
        return None
    run_dir = manifest_path.parent
    try:
        sample_rate = int(manifest.get("sample_rate") or 48_000)
    except (TypeError, ValueError):
        sample_rate = 48_000
    try:
        generated_at = manifest_path.stat().st_mtime
    except OSError:
        generated_at = 0.0
    return StemVersion(
        cue_id=cue_id,
        title=str(manifest.get("title") or cue_id.replace("_", " ").title()),
        label=label or _version_label(run_dir, manifest, source_kind=source_kind),
        render_hash=render_hash,
        run_dir=run_dir,
        manifest_path=manifest_path,
        full_mix_path=_full_mix_path(run_dir, manifest),
        timeline_path=_authoring_file(run_dir, manifest, "note_timeline"),
        score_snapshot_path=_authoring_file(run_dir, manifest, "score_snapshot"),
        sample_rate=sample_rate,
        generated_at=generated_at,
        source_kind=source_kind,
    )


def _dedupe_versions(versions: Iterable[StemVersion]) -> list[StemVersion]:
    chosen: dict[tuple[str, str, str], StemVersion] = {}
    priority = {"scratch_render": 4, "folder": 3, "generated_latest": 2, "generated": 1}
    for version in versions:
        key = (version.cue_id, version.render_hash, str(version.run_dir.resolve()))
        current = chosen.get(key)
        if current is None or priority.get(version.source_kind, 0) > priority.get(current.source_kind, 0):
            chosen[key] = version
    return sorted(chosen.values(), key=lambda v: (v.cue_id, -v.generated_at, v.label.lower()))


def discover_versions(project_root: Path) -> list[StemVersion]:
    """Discover generated renders and explicit scratch ``agent/**/renders/*`` banks."""
    root = Path(project_root).resolve()
    versions: list[StemVersion] = []

    generated = root / "generated"
    if generated.is_dir():
        for manifest_path in generated.glob("*/latest/*.adaptive_manifest.json"):
            version = version_from_manifest(manifest_path, source_kind="generated_latest")
            if version is not None:
                versions.append(version)
        for manifest_path in generated.glob("*/.versioned/*/*.adaptive_manifest.json"):
            version = version_from_manifest(manifest_path, source_kind="generated")
            if version is not None:
                versions.append(version)

    agent = root / "agent"
    if agent.is_dir():
        for manifest_path in agent.glob("**/renders/*/*.adaptive_manifest.json"):
            version = version_from_manifest(manifest_path, source_kind="scratch_render")
            if version is not None:
                versions.append(version)

    return _dedupe_versions(versions)


def discover_versions_from_path(path: Path) -> list[StemVersion]:
    """Discover rendered variants under an explicitly selected directory."""
    selected = Path(path).expanduser().resolve()
    if selected.is_file():
        manifests = [selected] if selected.name.endswith(".adaptive_manifest.json") else []
    elif selected.is_dir():
        direct = sorted(selected.glob("*.adaptive_manifest.json"))
        manifests = direct or sorted(selected.rglob("*.adaptive_manifest.json"))
    else:
        manifests = []
    versions = [
        version
        for manifest in manifests
        if (version := version_from_manifest(manifest, source_kind="folder")) is not None
    ]
    return _dedupe_versions(versions)


def preferred_reference(versions: Iterable[StemVersion]) -> StemVersion | None:
    """Choose an explicitly named reference; never invent one for a new cue."""
    candidates: list[tuple[int, float, str, StemVersion]] = []
    for version in versions:
        normalized = version.label.lower().replace("-", "_")
        score = 0
        for index, word in enumerate(_REFERENCE_WORDS):
            if word in normalized:
                score = len(_REFERENCE_WORDS) - index
                break
        if score:
            candidates.append((score, version.generated_at, version.label.lower(), version))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return candidates[0][3]


def discover_stem_assets(version: StemVersion) -> dict[str, StemAsset]:
    """Return the best locally available full-length asset for each stem group."""
    manifest = _load_json(version.manifest_path)
    if not manifest:
        return {}
    groups = [str(group) for group in (manifest.get("stems") or [])]
    preview = _preview_mapping(manifest)
    if not groups:
        inferred: set[str] = set()
        for key in preview:
            text = str(key)
            for prefix in ("review_stem_", "audition_stem_"):
                if text.startswith(prefix):
                    inferred.add(text[len(prefix):])
        cue_hash = str(manifest.get("hash") or version.render_hash)
        cue_id = str(manifest.get("id") or version.cue_id)
        stem_prefix = f"{cue_id}_{cue_hash}."
        for path in (version.run_dir / "scratch_stems").glob(f"{cue_id}_{cue_hash}.*.npy"):
            name = path.name
            if name.startswith(stem_prefix) and name.endswith(".npy"):
                inferred.add(name[len(stem_prefix):-4])
        groups = sorted(inferred)
    assets: dict[str, StemAsset] = {}
    cue_hash = str(manifest.get("hash") or version.render_hash)
    cue_id = str(manifest.get("id") or version.cue_id)
    for group in groups:
        native = version.run_dir / "scratch_stems" / f"{cue_id}_{cue_hash}.{group}.npy"
        if native.is_file():
            assets[group] = StemAsset(group, native.resolve(), version.sample_rate, "native")
            continue
        review_rel = preview.get(f"review_stem_{group}")
        if review_rel:
            review = version.run_dir / str(review_rel)
            if review.is_file():
                assets[group] = StemAsset(group, review.resolve(), version.sample_rate, "review_native")
                continue
        audition_rel = preview.get(f"audition_stem_{group}")
        if audition_rel:
            audition = version.run_dir / str(audition_rel)
            if audition.is_file():
                assets[group] = StemAsset(group, audition.resolve(), version.sample_rate, "audition_normalized")
    return assets


def _coerce_stereo(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 1:
        return np.column_stack([arr, arr]).astype(np.float32, copy=False)
    if arr.ndim != 2:
        raise ValueError(f"expected mono/stereo audio, got shape={arr.shape}")
    if arr.shape[0] <= 2 and arr.shape[1] > 2:
        arr = arr.T
    if arr.shape[1] == 1:
        return np.repeat(arr, 2, axis=1).astype(np.float32, copy=False)
    if arr.shape[1] >= 2:
        return arr[:, :2].astype(np.float32, copy=False)
    raise ValueError(f"cannot coerce audio shape={arr.shape}")


def _read_asset(asset: StemAsset, target_sample_rate: int) -> np.ndarray:
    if asset.kind == "native":
        audio = _coerce_stereo(np.load(asset.path, mmap_mode="r"))
        source_rate = asset.sample_rate
    else:
        raw, source_rate = sf.read(asset.path, dtype="float32", always_2d=True)
        audio = _coerce_stereo(raw)
    if int(source_rate) == int(target_sample_rate):
        return audio
    divisor = math.gcd(int(source_rate), int(target_sample_rate))
    up = int(target_sample_rate) // divisor
    down = int(source_rate) // divisor
    return resample_poly(audio, up, down, axis=0).astype(np.float32, copy=False)


def mix_identity(selections: Mapping[str, tuple[StemVersion, StemAsset]]) -> str:
    rows = [
        f"{group}={version.key}:{asset.kind}:{asset.path}"
        for group, (version, asset) in sorted(selections.items())
    ]
    return hashlib.sha256("\n".join(rows).encode("utf8")).hexdigest()[:16]


def compose_stem_mix(
    selections: Mapping[str, tuple[StemVersion, StemAsset]],
    output_path: Path,
) -> MixResult:
    """Assemble selected full-length stems into one temporary WAV for audition."""
    if not selections:
        raise ValueError("cannot compose an empty stem mix")
    target_rate = max(asset.sample_rate for _, asset in selections.values())
    rendered: list[np.ndarray] = []
    used_fallback = False
    for _group, (_version, asset) in sorted(selections.items()):
        rendered.append(_read_asset(asset, target_rate))
        used_fallback |= not asset.balance_faithful
    max_len = max(len(audio) for audio in rendered)
    out = np.zeros((max_len, 2), dtype=np.float32)
    for audio in rendered:
        out[: len(audio)] += audio
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out *= np.float32(0.98 / peak)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, out, target_rate, subtype="FLOAT")
    return MixResult(
        path=output_path,
        sample_rate=target_rate,
        duration_seconds=max_len / float(target_rate),
        peak_before_guard=peak,
        used_normalized_fallback=used_fallback,
    )

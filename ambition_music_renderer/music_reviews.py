"""Version-exact human review records for Ambition music cues.

The renderer already gives each successful render a content/configuration hash.
That hash is useful, but a human review should identify the *audio actually
heard*, not merely the cue name.  This module therefore keys reviews by both:

* the renderer's ``render_hash`` from the adaptive/bundle manifest; and
* SHA-256 of the mastered preview bytes.

Review files are durable authoring data under ``reviews/music/<cue>/``.  They
remain useful after generated audio is cleaned, and multiple historical
versions of a cue can coexist without overwriting each other.

This module has no Qt dependency so agents and CI can query the review bank
headlessly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ._paths import SCORE_DIRS, project_root as default_project_root

REVIEW_SCHEMA = "ambition.music_review.v1"
RUBRIC: dict[int, tuple[str, str]] = {
    1: ("Replace", "Placeholder or actively weak; prefer a rewrite."),
    2: ("Major polish", "Works only provisionally; prioritize substantial revision."),
    3: ("Acceptable", "Good enough for now, but an obvious later polish candidate."),
    4: ("Strong", "Ship-quality; change only for a concrete reason."),
    5: ("Standout", "Benchmark/favorite; preserve its identity and use as a quality reference."),
}
ISSUE_TAGS = (
    "composition",
    "arrangement",
    "instrumentation",
    "mix-master",
    "loop-repetition",
    "game-fit",
    "technical-render",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        while chunk := file.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except (ValueError, OSError):
        return str(Path(path))


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf8")) or {}
    except Exception:
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf8"))
    except Exception:
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


@dataclass(frozen=True)
class ScoreSource:
    cue_id: str
    title: str
    path: Path
    scope: str


@dataclass
class RenderVersion:
    cue_id: str
    title: str
    render_hash: str
    preview_path: Path
    manifest_path: Path | None
    backend: str | None
    renderer_version: str | None
    generated_at: float
    is_latest: bool = False
    source_score: ScoreSource | None = None
    source_kind: str = "generated"
    _preview_sha256: str | None = field(default=None, init=False, repr=False)

    @property
    def preview_sha256(self) -> str:
        if self._preview_sha256 is None:
            self._preview_sha256 = sha256_file(self.preview_path)
        return self._preview_sha256

    @property
    def version_id(self) -> str:
        return f"{self.render_hash}:{self.preview_sha256[:12]}"

    @property
    def display_hash(self) -> str:
        return self.render_hash[:16]


@dataclass(frozen=True)
class ReviewValue:
    score: int
    notes: str = ""
    issues: tuple[str, ...] = ()
    furthest_played_seconds: float = 0.0
    furthest_played_fraction: float = 0.0
    reviewed_at: str = ""

    @property
    def label(self) -> str:
        return RUBRIC[self.score][0]


@dataclass
class ReviewDocument:
    path: Path
    data: dict[str, Any]

    @property
    def cue_id(self) -> str:
        return str((self.data.get("subject") or {}).get("cue_id") or "")

    @property
    def render_hash(self) -> str:
        return str((self.data.get("subject") or {}).get("render_hash") or "")

    @property
    def preview_sha256(self) -> str:
        return str((self.data.get("subject") or {}).get("preview_sha256") or "")

    @property
    def version_id(self) -> str:
        return f"{self.render_hash}:{self.preview_sha256[:12]}"

    @property
    def current(self) -> ReviewValue | None:
        raw = self.data.get("current") or {}
        try:
            score = int(raw.get("score"))
        except (TypeError, ValueError):
            return None
        if score not in RUBRIC:
            return None
        return ReviewValue(
            score=score,
            notes=str(raw.get("notes") or ""),
            issues=tuple(str(item) for item in (raw.get("issues") or [])),
            furthest_played_seconds=float(raw.get("furthest_played_seconds") or raw.get("auditioned_seconds") or 0.0),
            furthest_played_fraction=float(raw.get("furthest_played_fraction") or raw.get("audition_fraction") or 0.0),
            reviewed_at=str(raw.get("reviewed_at") or ""),
        )


def discover_score_sources(project_root: Path | None = None) -> dict[str, ScoreSource]:
    root = Path(project_root or default_project_root()).resolve()
    scores = root / "scores"
    found: dict[str, ScoreSource] = {}
    # Earlier SCORE_DIRS win: active should beat an archived copy of the same id.
    for scope in reversed(SCORE_DIRS):
        directory = scores / scope
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = _load_yaml(path)
            cue_id = str(data.get("id") or path.name.removesuffix(".music.yaml").removesuffix(".yaml"))
            title = str(data.get("title") or cue_id.replace("_", " ").title())
            found[cue_id] = ScoreSource(cue_id=cue_id, title=title, path=path.resolve(), scope=scope)
    return found


def _manifest_preview(run_dir: Path, cue_id: str, manifest_path: Path) -> tuple[Path | None, dict[str, Any]]:
    manifest = _load_json(manifest_path)
    files = manifest.get("files") or {}
    preview_rel = ((files.get("preview") or {}).get("full_soundtrack") or (files.get("preview") or {}).get("full_soundtrack_preview"))
    if preview_rel:
        candidate = run_dir / str(preview_rel)
        if candidate.is_file():
            return candidate.resolve(), manifest
    candidates = sorted((run_dir / "preview").glob(f"{cue_id}_*.full_soundtrack_preview.*")) if (run_dir / "preview").is_dir() else []
    candidates = [p for p in candidates if p.suffix.lower() in {".ogg", ".wav", ".flac", ".mp3"}]
    return (candidates[-1].resolve() if candidates else None), manifest


def _version_from_run(
    run_dir: Path,
    cue_id: str,
    *,
    source_score: ScoreSource | None,
    is_latest: bool,
    source_kind: str,
    bundle_manifest: Mapping[str, Any] | None = None,
) -> RenderVersion | None:
    manifests = sorted(run_dir.glob(f"{cue_id}_*.adaptive_manifest.json"))
    if not manifests:
        return None
    manifest_path = manifests[-1]
    preview, manifest = _manifest_preview(run_dir, cue_id, manifest_path)
    if preview is None:
        return None
    render_hash = str(manifest.get("hash") or "")
    if not render_hash:
        stem = manifest_path.name
        prefix = f"{cue_id}_"
        render_hash = stem[len(prefix):].split(".", 1)[0] if stem.startswith(prefix) else "unknown"
    bundle_manifest = dict(bundle_manifest or {})
    return RenderVersion(
        cue_id=cue_id,
        title=str(manifest.get("title") or (source_score.title if source_score else cue_id)),
        render_hash=render_hash,
        preview_path=preview,
        manifest_path=manifest_path.resolve(),
        backend=str(bundle_manifest.get("backend") or "") or None,
        renderer_version=str(manifest.get("renderer_version") or "") or None,
        generated_at=preview.stat().st_mtime,
        is_latest=is_latest,
        source_score=source_score,
        source_kind=source_kind,
    )


def discover_render_versions(project_root: Path | None = None, *, include_agent_bundles: bool = True) -> list[RenderVersion]:
    root = Path(project_root or default_project_root()).resolve()
    scores = discover_score_sources(root)
    versions: list[RenderVersion] = []
    seen: set[tuple[str, str, str]] = set()
    generated = root / "generated"
    if generated.is_dir():
        for cue_dir in sorted(p for p in generated.iterdir() if p.is_dir()):
            cue_id = cue_dir.name
            latest_real: Path | None = None
            latest = cue_dir / "latest"
            if latest.exists():
                try:
                    latest_real = latest.resolve()
                except OSError:
                    latest_real = None
            pointer = cue_dir / "latest.path"
            if latest_real is None and pointer.is_file():
                candidate = Path(pointer.read_text(encoding="utf8").strip())
                if candidate.exists():
                    latest_real = candidate.resolve()
            run_dirs: list[Path] = []
            versioned = cue_dir / ".versioned"
            if versioned.is_dir():
                run_dirs.extend(sorted(p for p in versioned.iterdir() if p.is_dir()))
            # Legacy/non-versioned output is still worth reviewing.
            if any(cue_dir.glob(f"{cue_id}_*.adaptive_manifest.json")):
                run_dirs.append(cue_dir)
            for run_dir in run_dirs:
                version = _version_from_run(
                    run_dir,
                    cue_id,
                    source_score=scores.get(cue_id),
                    is_latest=latest_real is not None and run_dir.resolve() == latest_real,
                    source_kind="generated",
                )
                if version is None:
                    continue
                key = (version.cue_id, version.render_hash, version.preview_sha256)
                if key not in seen:
                    seen.add(key)
                    versions.append(version)

    if include_agent_bundles:
        agent = root / "agent"
        if agent.is_dir():
            for bundle_dir in sorted(agent.glob("*_bundle")):
                bm_path = bundle_dir / "bundle_manifest.json"
                if not bm_path.is_file():
                    continue
                bm = _load_json(bm_path)
                cue_id = str(bm.get("cue") or "")
                render_hash = str(bm.get("render_hash") or "")
                if not cue_id or not render_hash:
                    continue
                manifests = sorted(bundle_dir.glob(f"{cue_id}_{render_hash}.adaptive_manifest.json"))
                if not manifests:
                    manifests = sorted(bundle_dir.glob(f"{cue_id}_*.adaptive_manifest.json"))
                if not manifests:
                    continue
                version = _version_from_run(
                    bundle_dir,
                    cue_id,
                    source_score=scores.get(cue_id),
                    is_latest=False,
                    source_kind="agent_bundle",
                    bundle_manifest=bm,
                )
                if version is None:
                    continue
                # The render hash deliberately does not include every bundle
                # option. Preserve two outputs with the same render hash when
                # their mastered preview bytes differ; the human heard audio,
                # not a hash label.
                key = (version.cue_id, version.render_hash, version.preview_sha256)
                if key not in seen:
                    seen.add(key)
                    versions.append(version)

    versions.sort(key=lambda item: (item.cue_id, -item.generated_at, item.render_hash))
    return versions


class ReviewStore:
    def __init__(self, project_root: Path | None = None, review_root: Path | None = None):
        self.project_root = Path(project_root or default_project_root()).resolve()
        self.review_root = Path(review_root or (self.project_root / "reviews" / "music")).resolve()

    def review_path(self, version: RenderVersion) -> Path:
        safe_cue = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in version.cue_id)
        return self.review_root / safe_cue / f"{version.render_hash}--{version.preview_sha256[:12]}.review.yaml"

    def load_for_version(self, version: RenderVersion) -> ReviewDocument | None:
        path = self.review_path(version)
        if not path.is_file():
            return None
        return ReviewDocument(path=path, data=_load_yaml(path))

    def load_all(self) -> list[ReviewDocument]:
        if not self.review_root.is_dir():
            return []
        docs: list[ReviewDocument] = []
        for path in sorted(self.review_root.glob("*/*.review.yaml")):
            data = _load_yaml(path)
            if data.get("schema") == REVIEW_SCHEMA:
                docs.append(ReviewDocument(path=path, data=data))
        return docs

    def save(
        self,
        version: RenderVersion,
        *,
        score: int,
        notes: str,
        issues: Iterable[str] = (),
        furthest_played_seconds: float = 0.0,
        furthest_played_fraction: float = 0.0,
    ) -> ReviewDocument:
        if score not in RUBRIC:
            raise ValueError(f"score must be 1..5, got {score!r}")
        issue_list = [str(item) for item in issues]
        unknown = [item for item in issue_list if item not in ISSUE_TAGS]
        if unknown:
            raise ValueError(f"unknown issue tags: {unknown}")
        path = self.review_path(version)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_yaml(path) if path.is_file() else {}
        history = list(existing.get("history") or [])
        previous = existing.get("current")
        reviewed_at = utc_now_iso()
        current = {
            "score": int(score),
            "label": RUBRIC[score][0],
            "notes": str(notes).rstrip(),
            "issues": issue_list,
            "furthest_played_seconds": round(max(0.0, float(furthest_played_seconds)), 3),
            "furthest_played_fraction": round(min(1.0, max(0.0, float(furthest_played_fraction))), 4),
            "reviewed_at": reviewed_at,
        }
        comparable_keys = ("score", "notes", "issues")
        if previous and any(previous.get(key) != current.get(key) for key in comparable_keys):
            history.append(previous)

        score_path = version.source_score.path if version.source_score else None
        score_sha = sha256_file(score_path) if score_path and score_path.is_file() else None
        manifest_sha = sha256_file(version.manifest_path) if version.manifest_path and version.manifest_path.is_file() else None
        data = {
            "schema": REVIEW_SCHEMA,
            "subject": {
                "cue_id": version.cue_id,
                "title": version.title,
                "version_id": version.version_id,
                "render_hash": version.render_hash,
                "preview_sha256": version.preview_sha256,
                "preview_path": safe_relative(version.preview_path, self.project_root),
                "manifest_path": safe_relative(version.manifest_path, self.project_root),
                "manifest_sha256": manifest_sha,
                "backend": version.backend,
                "renderer_version": version.renderer_version,
                "score_path": safe_relative(score_path, self.project_root),
                "score_sha256_at_review": score_sha,
                "score_scope": version.source_score.scope if version.source_score else None,
                "source_kind": version.source_kind,
                "was_latest_render_at_review": bool(version.is_latest),
            },
            "current": current,
            "history": history,
        }
        # Atomic replacement protects feedback from an interrupted GUI save.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf8")
        tmp.replace(path)
        return ReviewDocument(path=path, data=data)


def reviews_by_cue(documents: Iterable[ReviewDocument]) -> dict[str, list[ReviewDocument]]:
    result: dict[str, list[ReviewDocument]] = {}
    for doc in documents:
        result.setdefault(doc.cue_id, []).append(doc)
    for docs in result.values():
        docs.sort(key=lambda doc: (doc.current.reviewed_at if doc.current else "", doc.version_id), reverse=True)
    return result


def cue_summary(
    versions: Iterable[RenderVersion],
    documents: Iterable[ReviewDocument],
    score_sources: Mapping[str, ScoreSource] | None = None,
) -> list[dict[str, Any]]:
    versions_by_cue: dict[str, list[RenderVersion]] = {}
    for version in versions:
        versions_by_cue.setdefault(version.cue_id, []).append(version)
    docs_by_cue = reviews_by_cue(documents)
    score_sources = dict(score_sources or {})
    cue_ids = sorted(set(versions_by_cue) | set(docs_by_cue) | set(score_sources))
    rows: list[dict[str, Any]] = []
    for cue_id in cue_ids:
        cue_versions = sorted(versions_by_cue.get(cue_id, []), key=lambda version: version.generated_at, reverse=True)
        docs = docs_by_cue.get(cue_id, [])
        latest = next((version for version in cue_versions if version.is_latest), cue_versions[0] if cue_versions else None)
        latest_doc = None
        if latest is not None:
            latest_audio_sha = latest.preview_sha256
            for doc in docs:
                if doc.render_hash == latest.render_hash and doc.preview_sha256 == latest_audio_sha:
                    latest_doc = doc
                    break
        reviewed = [doc for doc in docs if doc.current is not None]
        best = max(reviewed, key=lambda doc: doc.current.score) if reviewed else None
        most_recent = reviewed[0] if reviewed else None
        source = score_sources.get(cue_id)
        title = latest.title if latest else (source.title if source else str((docs[0].data.get("subject") or {}).get("title") or cue_id))
        latest_current = latest_doc.current if latest_doc else None
        rows.append(
            {
                "cue_id": cue_id,
                "title": title,
                "latest_render_hash": latest.render_hash if latest else None,
                "latest_score": latest_current.score if latest_current else None,
                "latest_label": latest_current.label if latest_current else "Unrated",
                "most_recent_review_score": most_recent.current.score if most_recent else None,
                "best_score": best.current.score if best else None,
                "best_version_id": best.version_id if best else None,
                "reviewed_versions": len(reviewed),
                "playable_versions": len(cue_versions),
                "score_scope": source.scope if source else None,
            }
        )
    return rows


__all__ = [
    "ISSUE_TAGS",
    "REVIEW_SCHEMA",
    "RUBRIC",
    "RenderVersion",
    "ReviewDocument",
    "ReviewStore",
    "ReviewValue",
    "ScoreSource",
    "cue_summary",
    "discover_render_versions",
    "discover_score_sources",
    "reviews_by_cue",
    "sha256_file",
]

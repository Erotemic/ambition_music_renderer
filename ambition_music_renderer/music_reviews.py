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

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ._paths import SCORE_DIRS, project_root as default_project_root

REVIEW_SCHEMA_V1 = "ambition.music_review.v1"
REVIEW_SCHEMA = "ambition.music_review.v2"
PAIRWISE_SCHEMA = "ambition.music_pairwise_review.v1"
SUPPORTED_REVIEW_SCHEMAS = {REVIEW_SCHEMA_V1, REVIEW_SCHEMA}
MIN_SCORE = 1.0
MAX_SCORE = 10.0
POLISH_THRESHOLD = 6.0
RUBRIC_BANDS: tuple[tuple[float, float, str, str], ...] = (
    (1.0, 2.99, "Replace", "Placeholder or actively weak; prefer a rewrite."),
    (3.0, 4.99, "Major polish", "Works only provisionally; prioritize substantial revision."),
    (5.0, 6.99, "Acceptable", "Good enough for now, but an obvious later polish candidate."),
    (7.0, 8.99, "Strong", "Ship-quality; change only for a concrete reason."),
    (9.0, 10.0, "Standout", "Benchmark/favorite; preserve its identity and use as a quality reference."),
)
ISSUE_TAGS = (
    "composition",
    "arrangement",
    "instrumentation",
    "mix-master",
    "loop-repetition",
    "game-fit",
    "technical-render",
)


def normalize_score(value: float | int) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"score must be numeric, got {value!r}") from exc
    if not math.isfinite(score) or score < MIN_SCORE or score > MAX_SCORE:
        raise ValueError(f"score must be between {MIN_SCORE:g} and {MAX_SCORE:g}, got {value!r}")
    return round(score, 2)


def score_label(value: float | int) -> str:
    score = normalize_score(value)
    for low, high, label, _description in RUBRIC_BANDS:
        if low <= score <= high:
            return label
    return RUBRIC_BANDS[-1][2]


def score_description(value: float | int) -> str:
    score = normalize_score(value)
    for low, high, _label, description in RUBRIC_BANDS:
        if low <= score <= high:
            return description
    return RUBRIC_BANDS[-1][3]


def format_score(value: float | int | None) -> str:
    if value is None:
        return "—"
    score = float(value)
    return f"{score:.2f}".rstrip("0").rstrip(".")


def _score_from_document(raw_score: Any, schema: str) -> float:
    score = float(raw_score)
    if schema == REVIEW_SCHEMA_V1:
        score *= 2.0
    return normalize_score(score)


def migrate_review_data_v1_to_v2(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a v2 copy of a legacy 1–5 review without creating a new opinion.

    The migration is deliberately monotone and literal: every stored legacy
    score is multiplied by two. Notes, issue tags, playback provenance,
    timestamps, exact-version identity, and any pre-existing history remain
    untouched apart from their score/label representation.
    """

    migrated = deepcopy(dict(data))
    if migrated.get("schema") != REVIEW_SCHEMA_V1:
        return migrated
    migrated["schema"] = REVIEW_SCHEMA
    migrated["score_scale"] = {"min": MIN_SCORE, "max": MAX_SCORE, "legacy_v1_multiplier": 2.0}
    for key in ("current",):
        raw = migrated.get(key)
        if isinstance(raw, Mapping) and raw.get("score") is not None:
            value = normalize_score(float(raw["score"]) * 2.0)
            raw = dict(raw)
            raw["score"] = value
            raw["label"] = score_label(value)
            migrated[key] = raw
    history = []
    for raw in migrated.get("history") or []:
        item = dict(raw)
        if item.get("score") is not None:
            value = normalize_score(float(item["score"]) * 2.0)
            item["score"] = value
            item["label"] = score_label(value)
        history.append(item)
    migrated["history"] = history
    migrated["migration"] = {
        "from_schema": REVIEW_SCHEMA_V1,
        "score_transform": "score * 2",
        "preserved_existing_opinion": True,
    }
    return migrated



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
    score: float
    notes: str = ""
    issues: tuple[str, ...] = ()
    furthest_played_seconds: float = 0.0
    furthest_played_fraction: float = 0.0
    reviewed_at: str = ""
    created_at: str = ""

    @property
    def label(self) -> str:
        return score_label(self.score)


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
            score = _score_from_document(raw.get("score"), str(self.data.get("schema") or ""))
        except (TypeError, ValueError):
            return None
        return ReviewValue(
            score=score,
            notes=str(raw.get("notes") or ""),
            issues=tuple(str(item) for item in (raw.get("issues") or [])),
            furthest_played_seconds=float(raw.get("furthest_played_seconds") or raw.get("auditioned_seconds") or 0.0),
            furthest_played_fraction=float(raw.get("furthest_played_fraction") or raw.get("audition_fraction") or 0.0),
            reviewed_at=str(raw.get("updated_at") or raw.get("reviewed_at") or ""),
            created_at=str(raw.get("created_at") or raw.get("reviewed_at") or ""),
        )


@dataclass
class PairwiseDocument:
    path: Path
    data: dict[str, Any]

    @property
    def first(self) -> Mapping[str, Any]:
        return self.data.get("first") or {}

    @property
    def second(self) -> Mapping[str, Any]:
        return self.data.get("second") or {}

    @property
    def outcome(self) -> str:
        return str(self.data.get("outcome") or "")

    @property
    def updated_at(self) -> str:
        return str(self.data.get("updated_at") or self.data.get("reviewed_at") or "")

    @property
    def notes(self) -> str:
        return str(self.data.get("notes") or "")


def subject_key(subject: Mapping[str, Any]) -> str:
    return "|".join(
        (
            str(subject.get("cue_id") or ""),
            str(subject.get("render_hash") or ""),
            str(subject.get("preview_sha256") or ""),
        )
    )


def version_key(version: RenderVersion) -> str:
    return "|".join((version.cue_id, version.render_hash, version.preview_sha256))


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
        self.comparison_root = self.review_root / "_comparisons"

    def review_path(self, version: RenderVersion) -> Path:
        safe_cue = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in version.cue_id)
        return self.review_root / safe_cue / f"{version.render_hash}--{version.preview_sha256[:12]}.review.yaml"

    def _subject_for_version(self, version: RenderVersion) -> dict[str, Any]:
        score_path = version.source_score.path if version.source_score else None
        score_sha = sha256_file(score_path) if score_path and score_path.is_file() else None
        manifest_sha = sha256_file(version.manifest_path) if version.manifest_path and version.manifest_path.is_file() else None
        return {
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
        }

    def load_for_version(self, version: RenderVersion) -> ReviewDocument | None:
        path = self.review_path(version)
        if not path.is_file():
            return None
        data = _load_yaml(path)
        if data.get("schema") not in SUPPORTED_REVIEW_SCHEMAS:
            return None
        return ReviewDocument(path=path, data=data)

    def load_all(self) -> list[ReviewDocument]:
        if not self.review_root.is_dir():
            return []
        docs: list[ReviewDocument] = []
        for path in sorted(self.review_root.glob("*/*.review.yaml")):
            data = _load_yaml(path)
            if data.get("schema") in SUPPORTED_REVIEW_SCHEMAS:
                docs.append(ReviewDocument(path=path, data=data))
        return docs

    def migrate_legacy_reviews(self) -> list[Path]:
        """Rewrite v1 review files as v2 by multiplying every stored score by 2."""

        changed: list[Path] = []
        if not self.review_root.is_dir():
            return changed
        for path in sorted(self.review_root.glob("*/*.review.yaml")):
            data = _load_yaml(path)
            if data.get("schema") != REVIEW_SCHEMA_V1:
                continue
            migrated = migrate_review_data_v1_to_v2(data)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True, width=110), encoding="utf8")
            tmp.replace(path)
            changed.append(path)
        return changed

    def save(
        self,
        version: RenderVersion,
        *,
        score: float,
        notes: str,
        issues: Iterable[str] = (),
        furthest_played_seconds: float = 0.0,
        furthest_played_fraction: float = 0.0,
    ) -> ReviewDocument:
        score_value = normalize_score(score)
        issue_list = [str(item) for item in issues]
        unknown = [item for item in issue_list if item not in ISSUE_TAGS]
        if unknown:
            raise ValueError(f"unknown issue tags: {unknown}")
        path = self.review_path(version)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_yaml(path) if path.is_file() else {}
        if existing.get("schema") == REVIEW_SCHEMA_V1:
            existing = migrate_review_data_v1_to_v2(existing)
        previous = existing.get("current") or {}
        now = utc_now_iso()
        created_at = str(previous.get("created_at") or previous.get("reviewed_at") or now)
        current = {
            "score": score_value,
            "label": score_label(score_value),
            "notes": str(notes).rstrip(),
            "issues": issue_list,
            "furthest_played_seconds": round(max(0.0, float(furthest_played_seconds)), 3),
            "furthest_played_fraction": round(min(1.0, max(0.0, float(furthest_played_fraction))), 4),
            "created_at": created_at,
            "updated_at": now,
            # Keep reviewed_at for old tooling that has not learned updated_at.
            "reviewed_at": now,
        }
        data = {
            "schema": REVIEW_SCHEMA,
            "score_scale": {"min": MIN_SCORE, "max": MAX_SCORE},
            "subject": self._subject_for_version(version),
            "current": current,
            # Editing a rating is an edit, not a new review event. Preserve any
            # legacy history that already exists, but never append here.
            "history": list(existing.get("history") or []),
        }
        if existing.get("migration"):
            data["migration"] = existing["migration"]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf8")
        tmp.replace(path)
        return ReviewDocument(path=path, data=data)

    def _canonical_pair(self, first: RenderVersion, second: RenderVersion) -> tuple[RenderVersion, RenderVersion, bool]:
        if version_key(first) == version_key(second):
            raise ValueError("cannot compare a render version with itself")
        if version_key(first) <= version_key(second):
            return first, second, False
        return second, first, True

    def comparison_path(self, first: RenderVersion, second: RenderVersion) -> Path:
        a, b, _swapped = self._canonical_pair(first, second)
        digest = hashlib.sha256((version_key(a) + "\0" + version_key(b)).encode("utf8")).hexdigest()[:24]
        return self.comparison_root / f"{digest}.comparison.yaml"

    def load_comparison(self, first: RenderVersion, second: RenderVersion) -> PairwiseDocument | None:
        path = self.comparison_path(first, second)
        if not path.is_file():
            return None
        data = _load_yaml(path)
        if data.get("schema") != PAIRWISE_SCHEMA:
            return None
        return PairwiseDocument(path=path, data=data)

    def load_comparisons(self) -> list[PairwiseDocument]:
        if not self.comparison_root.is_dir():
            return []
        docs: list[PairwiseDocument] = []
        for path in sorted(self.comparison_root.glob("*.comparison.yaml")):
            data = _load_yaml(path)
            if data.get("schema") == PAIRWISE_SCHEMA:
                docs.append(PairwiseDocument(path=path, data=data))
        return docs

    def save_comparison(
        self,
        first: RenderVersion,
        second: RenderVersion,
        *,
        outcome: str,
        notes: str = "",
    ) -> PairwiseDocument:
        if outcome not in {"first", "second", "tie"}:
            raise ValueError("outcome must be 'first', 'second', or 'tie'")
        a, b, swapped = self._canonical_pair(first, second)
        canonical_outcome = outcome
        if swapped and outcome in {"first", "second"}:
            canonical_outcome = "second" if outcome == "first" else "first"
        path = self.comparison_path(a, b)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_yaml(path) if path.is_file() else {}
        now = utc_now_iso()
        data = {
            "schema": PAIRWISE_SCHEMA,
            "pair_id": path.stem.removesuffix(".comparison"),
            "first": self._subject_for_version(a),
            "second": self._subject_for_version(b),
            "outcome": canonical_outcome,
            "notes": str(notes).rstrip(),
            "created_at": str(existing.get("created_at") or now),
            "updated_at": now,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf8")
        tmp.replace(path)
        return PairwiseDocument(path=path, data=data)


def reviews_by_cue(documents: Iterable[ReviewDocument]) -> dict[str, list[ReviewDocument]]:
    result: dict[str, list[ReviewDocument]] = {}
    for doc in documents:
        result.setdefault(doc.cue_id, []).append(doc)
    for docs in result.values():
        docs.sort(key=lambda doc: (doc.current.reviewed_at if doc.current else "", doc.version_id), reverse=True)
    return result


def pairwise_rankings(documents: Iterable[PairwiseDocument]) -> list[dict[str, Any]]:
    """Compute a simple cycle-tolerant exact-version ranking from pairwise votes.

    This intentionally does not try to force a Condorcet-consistent global
    order. Each version receives one point for a win and half a point for a tie;
    ranking uses observed win-rate first, then Copeland net wins and comparison
    count as deterministic tie-breakers. Cycles remain visible in the W/L/T
    record instead of being 'solved' away.
    """

    stats: dict[str, dict[str, Any]] = {}

    def ensure(subject: Mapping[str, Any]) -> dict[str, Any]:
        key = subject_key(subject)
        if key not in stats:
            stats[key] = {
                "subject_key": key,
                "cue_id": str(subject.get("cue_id") or ""),
                "title": str(subject.get("title") or subject.get("cue_id") or ""),
                "version_id": str(subject.get("version_id") or ""),
                "render_hash": str(subject.get("render_hash") or ""),
                "preview_sha256": str(subject.get("preview_sha256") or ""),
                "wins": 0,
                "losses": 0,
                "ties": 0,
            }
        return stats[key]

    for doc in documents:
        first = ensure(doc.first)
        second = ensure(doc.second)
        if doc.outcome == "first":
            first["wins"] += 1
            second["losses"] += 1
        elif doc.outcome == "second":
            second["wins"] += 1
            first["losses"] += 1
        elif doc.outcome == "tie":
            first["ties"] += 1
            second["ties"] += 1

    rows = []
    for record in stats.values():
        comparisons = record["wins"] + record["losses"] + record["ties"]
        points = record["wins"] + 0.5 * record["ties"]
        row = dict(record)
        row.update(
            {
                "comparisons": comparisons,
                "pairwise_score": round(points / comparisons, 4) if comparisons else None,
                "copeland": record["wins"] - record["losses"],
            }
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            -(row["pairwise_score"] if row["pairwise_score"] is not None else -1.0),
            -row["copeland"],
            -row["comparisons"],
            row["cue_id"],
            row["version_id"],
        )
    )
    previous_key = None
    previous_rank = 0
    for index, row in enumerate(rows, 1):
        rank_key = (row["pairwise_score"], row["copeland"], row["comparisons"])
        if rank_key != previous_key:
            previous_rank = index
            previous_key = rank_key
        row["rank"] = previous_rank
    return rows


def cue_summary(
    versions: Iterable[RenderVersion],
    documents: Iterable[ReviewDocument],
    score_sources: Mapping[str, ScoreSource] | None = None,
    pairwise_documents: Iterable[PairwiseDocument] = (),
) -> list[dict[str, Any]]:
    versions_by_cue: dict[str, list[RenderVersion]] = {}
    for version in versions:
        versions_by_cue.setdefault(version.cue_id, []).append(version)
    docs_by_cue = reviews_by_cue(documents)
    score_sources = dict(score_sources or {})
    pair_rows = {row["subject_key"]: row for row in pairwise_rankings(pairwise_documents)}
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
        pair = pair_rows.get(version_key(latest)) if latest is not None else None
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
                "latest_pairwise_rank": pair["rank"] if pair else None,
                "latest_pairwise_score": pair["pairwise_score"] if pair else None,
                "latest_pairwise_wins": pair["wins"] if pair else 0,
                "latest_pairwise_losses": pair["losses"] if pair else 0,
                "latest_pairwise_ties": pair["ties"] if pair else 0,
                "latest_pairwise_comparisons": pair["comparisons"] if pair else 0,
            }
        )
    return rows


__all__ = [
    "ISSUE_TAGS",
    "MAX_SCORE",
    "MIN_SCORE",
    "PAIRWISE_SCHEMA",
    "POLISH_THRESHOLD",
    "REVIEW_SCHEMA",
    "REVIEW_SCHEMA_V1",
    "RUBRIC_BANDS",
    "PairwiseDocument",
    "RenderVersion",
    "ReviewDocument",
    "ReviewStore",
    "ReviewValue",
    "ScoreSource",
    "cue_summary",
    "discover_render_versions",
    "discover_score_sources",
    "format_score",
    "migrate_review_data_v1_to_v2",
    "normalize_score",
    "pairwise_rankings",
    "reviews_by_cue",
    "score_description",
    "score_label",
    "sha256_file",
    "subject_key",
    "version_key",
]

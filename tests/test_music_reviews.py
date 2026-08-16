from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ambition_music_renderer.music_reviews import (
    REVIEW_SCHEMA,
    ReviewStore,
    cue_summary,
    discover_render_versions,
    discover_score_sources,
)


def _write_score(root: Path, cue: str = "test_cue", title: str = "Test Cue") -> Path:
    path = root / "scores" / "active" / f"{cue}.music.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"schema": "ambition.musicir.v1", "id": cue, "title": title}), encoding="utf8")
    return path


def _write_render(root: Path, cue: str, render_hash: str, audio: bytes, *, latest: bool = False) -> Path:
    run = root / "generated" / cue / ".versioned" / render_hash
    preview = run / "preview" / f"{cue}_{render_hash}.full_soundtrack_preview.ogg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(audio)
    manifest = {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": "test-renderer-v1",
        "id": cue,
        "title": "Test Cue",
        "hash": render_hash,
        "files": {"preview": {"full_soundtrack": f"preview/{preview.name}"}},
    }
    (run / f"{cue}_{render_hash}.adaptive_manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    if latest:
        link = root / "generated" / cue / "latest"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(Path(".versioned") / render_hash, target_is_directory=True)
    return preview


def test_discovery_keeps_all_versioned_renders_and_marks_latest(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"old")
    _write_render(tmp_path, "test_cue", "bbbbbbbbbbbbbbbb", b"new", latest=True)
    versions = discover_render_versions(tmp_path, include_agent_bundles=False)
    assert [version.render_hash for version in versions] == ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa"]
    assert versions[0].is_latest is True
    assert versions[1].is_latest is False
    assert versions[0].source_score is not None
    assert versions[0].source_score.scope == "active"


def test_review_key_binds_render_hash_and_exact_audio_bytes(tmp_path: Path):
    _write_score(tmp_path)
    preview = _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"heard-this", latest=True)
    version = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    store = ReviewStore(tmp_path)
    path1 = store.review_path(version)
    expected = hashlib.sha256(b"heard-this").hexdigest()
    assert expected[:12] in path1.name

    # Same renderer hash but different audible bytes becomes a different review
    # identity rather than inheriting feedback accidentally.
    preview.write_bytes(b"different-audio")
    version2 = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    path2 = store.review_path(version2)
    assert path1 != path2


def test_save_preserves_prior_opinion_in_history(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"audio", latest=True)
    version = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    store = ReviewStore(tmp_path)
    first = store.save(version, score=3, notes="Fine for now", issues=["arrangement"], furthest_played_seconds=12, furthest_played_fraction=0.4)
    assert first.current is not None and first.current.score == 3
    second = store.save(version, score=4, notes="Polish worked", issues=[], furthest_played_seconds=30, furthest_played_fraction=1.0)
    assert second.current is not None and second.current.score == 4
    assert len(second.data["history"]) == 1
    assert second.data["history"][0]["score"] == 3
    assert second.data["schema"] == REVIEW_SCHEMA


def test_summary_distinguishes_latest_from_best_historical_version(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"old")
    _write_render(tmp_path, "test_cue", "bbbbbbbbbbbbbbbb", b"new", latest=True)
    versions = discover_render_versions(tmp_path, include_agent_bundles=False)
    by_hash = {version.render_hash: version for version in versions}
    store = ReviewStore(tmp_path)
    store.save(by_hash["aaaaaaaaaaaaaaaa"], score=5, notes="Keep this arrangement")
    store.save(by_hash["bbbbbbbbbbbbbbbb"], score=3, notes="Regressed")
    row = cue_summary(versions, store.load_all())[0]
    assert row["latest_score"] == 3
    assert row["best_score"] == 5
    assert row["best_version_id"].startswith("aaaaaaaaaaaaaaaa:")
    assert row["reviewed_versions"] == 2


def test_active_score_source_wins_over_archived_duplicate(tmp_path: Path):
    active = _write_score(tmp_path, title="Current")
    archived = tmp_path / "scores" / "archive" / active.name
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text(yaml.safe_dump({"id": "test_cue", "title": "Old"}), encoding="utf8")
    sources = discover_score_sources(tmp_path)
    assert sources["test_cue"].title == "Current"
    assert sources["test_cue"].scope == "active"


def test_same_render_hash_with_distinct_audio_is_preserved_as_distinct_version(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"generated", latest=True)
    bundle = tmp_path / "agent" / "test_cue_aaaaaaaaaaaaaaaa_bundle"
    preview = bundle / "preview" / "test_cue_aaaaaaaaaaaaaaaa.full_soundtrack_preview.ogg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"different-bundle-options")
    manifest = {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": "test-renderer-v1",
        "id": "test_cue",
        "title": "Test Cue",
        "hash": "aaaaaaaaaaaaaaaa",
        "files": {"preview": {"full_soundtrack": f"preview/{preview.name}"}},
    }
    (bundle / "test_cue_aaaaaaaaaaaaaaaa.adaptive_manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    (bundle / "bundle_manifest.json").write_text(json.dumps({"cue": "test_cue", "render_hash": "aaaaaaaaaaaaaaaa", "backend": "pretty-midi"}), encoding="utf8")
    versions = discover_render_versions(tmp_path, include_agent_bundles=True)
    assert len(versions) == 2
    assert len({version.version_id for version in versions}) == 2


def test_summary_can_include_active_score_without_local_preview(tmp_path: Path):
    _write_score(tmp_path, cue="unrendered", title="Unrendered Tune")
    sources = {cue: source for cue, source in discover_score_sources(tmp_path).items() if source.scope == "active"}
    rows = cue_summary([], [], sources)
    assert rows == [{
        "cue_id": "unrendered",
        "title": "Unrendered Tune",
        "latest_render_hash": None,
        "latest_score": None,
        "latest_label": "Unrated",
        "most_recent_review_score": None,
        "best_score": None,
        "best_version_id": None,
        "reviewed_versions": 0,
        "playable_versions": 0,
        "score_scope": "active",
    }]

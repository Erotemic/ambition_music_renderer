from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml

from ambition_music_renderer.music_reviews import (
    PAIRWISE_SCHEMA,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_V1,
    ReviewStore,
    cue_summary,
    discover_render_versions,
    discover_score_sources,
    pairwise_rankings,
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
        "title": cue.replace("_", " ").title(),
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
    """Newest first, and every older render kept.

    ⛔⛔ THE TWO RENDERS NEED DISTINCT MTIMES OR THIS TEST IS A COIN FLIP.
    `discover_render_versions` sorts by `(cue_id, -generated_at, render_hash)`
    and `generated_at` is the preview file's OWN mtime, so two files written
    microseconds apart can tie at the filesystem's resolution — and the tie-break
    is the hash, which puts `aaaa` first and reads as "the ordering broke". It
    had been failing exactly that way. Real renders are minutes apart; the
    fixture says so now instead of hoping.
    """
    _write_score(tmp_path)
    old_preview = _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"old")
    new_preview = _write_render(tmp_path, "test_cue", "bbbbbbbbbbbbbbbb", b"new", latest=True)
    os.utime(old_preview, (1_700_000_000, 1_700_000_000))
    os.utime(new_preview, (1_700_003_600, 1_700_003_600))
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

    preview.write_bytes(b"different-audio")
    version2 = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    path2 = store.review_path(version2)
    assert path1 != path2


def test_save_edits_current_review_in_place_without_appending_history(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"audio", latest=True)
    version = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    store = ReviewStore(tmp_path)
    first = store.save(version, score=6.0, notes="Fine for now", issues=["arrangement"], furthest_played_seconds=12, furthest_played_fraction=0.4)
    assert first.current is not None and first.current.score == 6.0
    created_at = first.data["current"]["created_at"]

    second = store.save(version, score=8.5, notes="Polish worked", issues=[], furthest_played_seconds=30, furthest_played_fraction=1.0)
    assert second.current is not None and second.current.score == 8.5
    assert second.data["history"] == []
    assert second.data["current"]["created_at"] == created_at
    assert second.data["schema"] == REVIEW_SCHEMA
    assert len(store.load_all()) == 1


def test_legacy_v1_review_reads_as_literal_double_score(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"audio", latest=True)
    version = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    store = ReviewStore(tmp_path)
    path = store.review_path(version)
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": REVIEW_SCHEMA_V1,
                "subject": {
                    "cue_id": version.cue_id,
                    "render_hash": version.render_hash,
                    "preview_sha256": version.preview_sha256,
                },
                "current": {"score": 3, "label": "Acceptable", "notes": "Keep me", "issues": []},
                "history": [],
            },
            sort_keys=False,
        ),
        encoding="utf8",
    )
    loaded = store.load_for_version(version)
    assert loaded is not None and loaded.current is not None
    assert loaded.current.score == 6.0
    assert loaded.current.notes == "Keep me"


def test_migrate_legacy_reviews_multiplies_all_existing_scores_without_new_history(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"audio", latest=True)
    version = discover_render_versions(tmp_path, include_agent_bundles=False)[0]
    store = ReviewStore(tmp_path)
    path = store.review_path(version)
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": REVIEW_SCHEMA_V1,
                "subject": {"cue_id": version.cue_id, "render_hash": version.render_hash, "preview_sha256": version.preview_sha256},
                "current": {"score": 4, "label": "Strong", "notes": "Existing note", "issues": []},
                "history": [{"score": 2, "label": "Major polish", "notes": "Old thought"}],
            },
            sort_keys=False,
        ),
        encoding="utf8",
    )
    changed = store.migrate_legacy_reviews()
    assert changed == [path]
    raw = yaml.safe_load(path.read_text())
    assert raw["schema"] == REVIEW_SCHEMA
    assert raw["current"]["score"] == 8.0
    assert raw["history"][0]["score"] == 4.0
    assert raw["current"]["notes"] == "Existing note"
    assert len(raw["history"]) == 1


def test_summary_distinguishes_latest_from_best_historical_version(tmp_path: Path):
    _write_score(tmp_path)
    _write_render(tmp_path, "test_cue", "aaaaaaaaaaaaaaaa", b"old")
    _write_render(tmp_path, "test_cue", "bbbbbbbbbbbbbbbb", b"new", latest=True)
    versions = discover_render_versions(tmp_path, include_agent_bundles=False)
    by_hash = {version.render_hash: version for version in versions}
    store = ReviewStore(tmp_path)
    store.save(by_hash["aaaaaaaaaaaaaaaa"], score=10.0, notes="Keep this arrangement")
    store.save(by_hash["bbbbbbbbbbbbbbbb"], score=6.0, notes="Regressed")
    row = cue_summary(versions, store.load_all())[0]
    assert row["latest_score"] == 6.0
    assert row["best_score"] == 10.0
    assert row["best_version_id"].startswith("aaaaaaaaaaaaaaaa:")
    assert row["reviewed_versions"] == 2


def test_pairwise_save_is_exact_unordered_pair_and_editable_in_place(tmp_path: Path):
    for cue in ("alpha", "beta"):
        _write_score(tmp_path, cue, cue.title())
    _write_render(tmp_path, "alpha", "aaaaaaaaaaaaaaaa", b"alpha", latest=True)
    _write_render(tmp_path, "beta", "bbbbbbbbbbbbbbbb", b"beta", latest=True)
    versions = {version.cue_id: version for version in discover_render_versions(tmp_path, include_agent_bundles=False)}
    store = ReviewStore(tmp_path)

    first = store.save_comparison(versions["alpha"], versions["beta"], outcome="first")
    assert first.data["schema"] == PAIRWISE_SCHEMA
    first_path = first.path
    second = store.save_comparison(versions["beta"], versions["alpha"], outcome="first")
    assert second.path == first_path
    assert len(store.load_comparisons()) == 1
    # The reverse-oriented edit now says beta won; canonical storage may call
    # that either first or second, but the winner subject must be beta.
    winner = second.first if second.outcome == "first" else second.second
    assert winner["cue_id"] == "beta"


def test_pairwise_ranking_handles_non_condorcet_data_with_simple_points(tmp_path: Path):
    for cue, h in (("alpha", "aaaaaaaaaaaaaaaa"), ("beta", "bbbbbbbbbbbbbbbb"), ("gamma", "cccccccccccccccc")):
        _write_score(tmp_path, cue, cue.title())
        _write_render(tmp_path, cue, h, cue.encode(), latest=True)
    versions = {version.cue_id: version for version in discover_render_versions(tmp_path, include_agent_bundles=False)}
    store = ReviewStore(tmp_path)
    store.save_comparison(versions["alpha"], versions["beta"], outcome="first")
    store.save_comparison(versions["alpha"], versions["gamma"], outcome="first")
    store.save_comparison(versions["beta"], versions["gamma"], outcome="first")
    rows = pairwise_rankings(store.load_comparisons())
    assert rows[0]["cue_id"] == "alpha"
    assert rows[0]["wins"] == 2
    assert rows[0]["pairwise_score"] == 1.0
    assert rows[-1]["cue_id"] == "gamma"


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
        "latest_pairwise_rank": None,
        "latest_pairwise_score": None,
        "latest_pairwise_wins": 0,
        "latest_pairwise_losses": 0,
        "latest_pairwise_ties": 0,
        "latest_pairwise_comparisons": 0,
    }]

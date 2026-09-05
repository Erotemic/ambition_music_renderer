from __future__ import annotations

import json
from pathlib import Path
import wave

from ambition_music_renderer.music_reviews import discover_render_versions
from ambition_music_renderer.music_stem_lab import build_parser


def _write_scratch_manifest(root: Path) -> None:
    run = root / "agent" / "ab" / "renders" / "A_canonical_original"
    preview = run / "preview" / "cue_aaaaaaaa.full_soundtrack_preview.wav"
    preview.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(preview), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 80)
    manifest = {
        "id": "cue",
        "title": "Cue",
        "hash": "aaaaaaaaaaaaaaaa",
        "files": {"preview": {"full_soundtrack": f"preview/{preview.name}"}},
        "stems": [],
    }
    (run / "cue_aaaaaaaa.adaptive_manifest.json").write_text(json.dumps(manifest), encoding="utf8")


def test_stem_lab_launcher_parser_does_not_require_qt():
    args = build_parser().parse_args(["--check", "--cue", "foo", "--library", "/tmp/x"])
    assert args.check is True
    assert args.cue == "foo"
    assert args.library == [Path("/tmp/x")]


def test_music_review_discovery_remains_unaware_of_stem_lab_scratch_bank(tmp_path: Path):
    _write_scratch_manifest(tmp_path)
    assert discover_render_versions(tmp_path) == []


def _write_session_version(root: Path, label: str, render_hash: str, groups: tuple[str, ...], mtime: float):
    import numpy as np
    from ambition_music_renderer.music_audition import version_from_manifest

    run = root / label
    scratch = run / "scratch_stems"
    scratch.mkdir(parents=True)
    for group in groups:
        np.save(scratch / f"cue_{render_hash}.{group}.npy", np.zeros((8, 2), dtype=np.float32))
    manifest = {
        "id": "cue",
        "title": "Cue",
        "hash": render_hash,
        "sample_rate": 8000,
        "stems": list(groups),
        "files": {"preview": {}},
    }
    path = run / f"cue_{render_hash}.adaptive_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf8")
    path.touch()
    import os
    os.utime(path, (mtime, mtime))
    version = version_from_manifest(path, source_kind="folder", label=label)
    assert version is not None
    return version


def test_stem_lab_session_owns_reference_loading_and_routes(tmp_path: Path):
    from ambition_music_renderer.music_stem_lab_model import StemLabSession

    reference = _write_session_version(
        tmp_path, "canonical_original", "aaaaaaaaaaaaaaaa", ("bass", "strings"), 10
    )
    newest = _write_session_version(
        tmp_path, "new_idea", "bbbbbbbbbbbbbbbb", ("bass", "lead"), 20
    )
    session = StemLabSession.from_versions([reference, newest])
    session.select_cue("cue")

    assert session.reference_key == reference.key
    assert set(session.loaded_keys) == {reference.key, newest.key}
    assert session.groups == ("bass", "lead", "strings")
    assert session.routes["bass"].version_key == newest.key
    assert session.routes["lead"].version_key == newest.key
    assert session.routes["strings"].version_key == reference.key

    session.route_reference()
    assert session.routes["bass"].version_key == reference.key
    assert session.routes["lead"].version_key == newest.key  # reference has no lead

    session.unload(reference.key)
    assert session.reference_key is None
    assert session.routes["bass"].version_key == newest.key
    assert "strings" not in session.routes



def test_bulk_route_enable_disable_and_main_comparison_source(tmp_path: Path):
    from ambition_music_renderer.music_stem_lab_model import StemLabSession

    first = _write_session_version(tmp_path, "first", "aaaaaaaaaaaaaaaa", ("bass", "lead"), 10)
    second = _write_session_version(tmp_path, "second", "bbbbbbbbbbbbbbbb", ("bass", "lead"), 20)
    session = StemLabSession.from_versions([first, second])
    session.select_cue("cue")
    session.load(first.key)

    # The currently routed source is the inspector's main comparison side.
    assert session.routed_source_for_group("lead") == second.key
    assert session.comparison_candidates_for_group("lead") == [first.key]

    session.set_route_source("lead", first.key)
    assert session.routed_source_for_group("lead") == first.key
    assert session.comparison_candidates_for_group("lead") == [second.key]

    assert all(route.enabled for route in session.routes.values())
    session.set_all_routes_enabled(False)
    assert not any(route.enabled for route in session.routes.values())
    assert session.selections() == {}

    session.set_all_routes_enabled(True)
    assert all(route.enabled for route in session.routes.values())
    assert set(session.selections()) == {"bass", "lead"}

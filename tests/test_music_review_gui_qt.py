from __future__ import annotations

import json
import os
from pathlib import Path
import wave

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ambition_music_renderer.music_review_gui_qt import ReviewWindow


def _project(tmp_path: Path) -> Path:
    score = tmp_path / "scores" / "active" / "tiny.music.yaml"
    score.parent.mkdir(parents=True)
    score.write_text(yaml.safe_dump({"id": "tiny", "title": "Tiny Tune"}), encoding="utf8")
    render_hash = "0123456789abcdef"
    run = tmp_path / "generated" / "tiny" / ".versioned" / render_hash
    preview = run / "preview" / f"tiny_{render_hash}.full_soundtrack_preview.wav"
    preview.parent.mkdir(parents=True)
    with wave.open(str(preview), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 800)
    manifest = {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": "test",
        "id": "tiny",
        "title": "Tiny Tune",
        "hash": render_hash,
        "files": {"preview": {"full_soundtrack": f"preview/{preview.name}"}},
    }
    (run / f"tiny_{render_hash}.adaptive_manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    latest = tmp_path / "generated" / "tiny" / "latest"
    latest.symlink_to(Path(".versioned") / render_hash, target_is_directory=True)
    return tmp_path


def test_review_window_discovers_preview_and_can_persist_score(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    root = _project(tmp_path)
    window = ReviewWindow(root, root / "reviews" / "music", initial_cue="tiny")
    try:
        assert window.cue_table.rowCount() == 1
        assert window.current_version is not None
        assert window.current_version.cue_id == "tiny"
        window.score_buttons[4].setChecked(True)
        window.notes.setPlainText("Ship it")
        window.save_review()
        docs = window.store.load_all()
        assert len(docs) == 1
        assert docs[0].current is not None
        assert docs[0].current.score == 4
    finally:
        window.close()
        app.processEvents()

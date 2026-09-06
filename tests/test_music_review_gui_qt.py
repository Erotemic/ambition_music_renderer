from __future__ import annotations

import json
import os
from pathlib import Path
import wave

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ambition_music_renderer.music_review_gui_qt import ReviewWindow


def _write_cue(tmp_path: Path, cue: str, render_hash: str, *, latest: bool = True) -> None:
    score = tmp_path / "scores" / "active" / f"{cue}.music.yaml"
    score.parent.mkdir(parents=True, exist_ok=True)
    score.write_text(yaml.safe_dump({"id": cue, "title": cue.replace("_", " ").title()}), encoding="utf8")
    run = tmp_path / "generated" / cue / ".versioned" / render_hash
    preview = run / "preview" / f"{cue}_{render_hash}.full_soundtrack_preview.wav"
    preview.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(preview), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 800)
    manifest = {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": "test",
        "id": cue,
        "title": cue.replace("_", " ").title(),
        "hash": render_hash,
        "files": {"preview": {"full_soundtrack": f"preview/{preview.name}"}},
    }
    (run / f"{cue}_{render_hash}.adaptive_manifest.json").write_text(json.dumps(manifest), encoding="utf8")
    if latest:
        link = tmp_path / "generated" / cue / "latest"
        link.symlink_to(Path(".versioned") / render_hash, target_is_directory=True)


def _project(tmp_path: Path) -> Path:
    _write_cue(tmp_path, "alpha", "0123456789abcdef")
    _write_cue(tmp_path, "beta", "fedcba9876543210")
    return tmp_path


def _select_cue(window: ReviewWindow, cue_id: str) -> None:
    for row in range(window.cue_table.rowCount()):
        item = window.cue_table.item(row, 4)
        if item and item.data(Qt.UserRole) == cue_id:  # Qt.UserRole = 256
            window.cue_table.selectRow(row)
            QApplication.processEvents()
            return
    raise AssertionError(f"cue not found: {cue_id}")


def test_review_window_supports_decimal_scores_edit_in_place_and_clears_unrated_state(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    root = _project(tmp_path)
    window = ReviewWindow(root, root / "reviews" / "music", initial_cue="alpha")
    try:
        assert window.cue_table.rowCount() == 2
        assert window.current_version is not None
        assert window.current_version.cue_id == "alpha"
        assert window.score_value.value() == 0.0

        window.score_value.setValue(8.5)
        window.notes.setPlainText("Strong but not done")
        window.save_review()
        docs = window.store.load_all()
        assert len(docs) == 1
        assert docs[0].current is not None
        assert docs[0].current.score == 8.5

        window.score_value.setValue(8.75)
        window.notes.setPlainText("Tiny improvement")
        window.save_review()
        docs = window.store.load_all()
        assert len(docs) == 1
        assert docs[0].current is not None and docs[0].current.score == 8.75
        assert docs[0].data["history"] == []

        _select_cue(window, "beta")
        assert window.current_version is not None and window.current_version.cue_id == "beta"
        assert window.score_value.value() == 0.0
        assert window.notes.toPlainText() == ""
        assert not any(box.isChecked() for box in window.issue_boxes.values())

        # Pairwise selection includes alpha; record beta < alpha and ensure the
        # exact pair is stored once.
        assert window.compare_combo.count() >= 1
        alpha_index = next(
            idx
            for idx in range(window.compare_combo.count())
            if window.compare_combo.itemData(idx).cue_id == "alpha"
        )
        window.compare_combo.setCurrentIndex(alpha_index)
        window._save_pairwise("second")
        comparisons = window.store.load_comparisons()
        assert len(comparisons) == 1
    finally:
        window.close()
        app.processEvents()

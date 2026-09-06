from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ambition_music_renderer.music_instrument_audition import instrument_choices
from ambition_music_renderer.music_instrument_audition_qt import InstrumentAuditionPanel
from ambition_music_renderer.music_stem_lab_qt import StemLabWindow


def _candidate_score(path: Path) -> Path:
    data = {
        "id": "candidate_ui",
        "authoring": {
            "instrument_candidates": {
                "lead": {
                    "primary": "base",
                    "candidates": [
                        {
                            "id": "base",
                            "label": "Baseline",
                            "program": "clean_guitar",
                            "instrument_backend": {"kind": "sfz", "library_ref": "guitar.clean"},
                        },
                        {
                            "id": "alt",
                            "label": "Alternate",
                            "program": "clean_guitar",
                            "instrument_backend": {"kind": "sfz", "library_ref": "guitar.electric_lead"},
                        },
                    ],
                }
            }
        },
        "instruments": [
            {
                "name": "lead",
                "group": "lead",
                "program": "clean_guitar",
                "instrument_backend": {"kind": "sfz", "library_ref": "guitar.clean"},
            }
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf8")
    return path


def test_candidate_panel_prefers_authored_bank_and_exposes_progress(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    source = _candidate_score(tmp_path / "score.music.yaml")
    panel = InstrumentAuditionPanel()
    try:
        choices = instrument_choices(source, "lead")
        panel.set_context(
            base_label="baseline",
            group="lead",
            source_score=source,
            exact_source=True,
            choices=choices,
            candidate_versions_by_instrument={"lead": {"base": "version-base"}},
            selected_candidate_by_instrument={"lead": "base"},
        )
        assert panel.manual_widget.isHidden()
        assert panel.candidate_combo.count() == 2
        assert panel.candidate_combo.itemText(0).startswith("★ Baseline")
        panel.candidate_combo.setCurrentIndex(1)
        request = panel.selected_candidate_request()
        assert request is not None
        assert request["candidate_id"] == "alt"

        panel.set_rendering(True, "Rendering 1/2", completed=1, total=2)
        assert not panel.progress.isHidden()
        assert panel.progress.maximum() == 2
        assert panel.progress.value() == 1
        panel.set_rendering(False, "Ready")
        assert panel.progress.isHidden()
    finally:
        panel.close()
        app.processEvents()


def test_stem_lab_keeps_play_actionable_for_generate_on_play(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = StemLabWindow(tmp_path, [])
    try:
        assert window.transport.play_button.isEnabled()
    finally:
        window.close()
        app.processEvents()



def test_candidate_panel_still_names_current_instrument_without_alternatives(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "fixed.music.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "id": "fixed_ui",
                "instruments": [
                    {"name": "bass", "group": "bass", "program": "picked_bass"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf8",
    )
    panel = InstrumentAuditionPanel()
    try:
        choices = instrument_choices(source, "bass")
        panel.set_context(
            base_label="baseline",
            group="bass",
            source_score=source,
            exact_source=True,
            choices=choices,
        )
        assert panel.candidate_combo.count() == 1
        assert "GM picked_bass" in panel.candidate_combo.itemText(0)
        assert "GM picked_bass" in panel.candidate_detail.text()
        assert not panel.candidate_combo.isEnabled()
    finally:
        panel.close()
        app.processEvents()

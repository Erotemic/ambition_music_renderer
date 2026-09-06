"""Quality brief surfaces severe foreground/support spectral masking."""

from __future__ import annotations

import json

from ambition_music_renderer.render.bundle_quality_brief import write_quality_brief


def test_quality_brief_includes_spectral_masking_warning(tmp_path):
    (tmp_path / "spectral_masking.json").write_text(
        json.dumps(
            {
                "warnings": [
                    {
                        "time_s": 35.0,
                        "lead_group": "woodwinds",
                        "support_group": "strings",
                        "band": "mid",
                        "lead_margin_db": -7.0,
                    }
                ]
            }
        ),
        encoding="utf8",
    )
    path, warnings = write_quality_brief(
        tmp_path,
        cue_id="demo",
        render_hash="abc",
        all_audits=False,
        spectrograms=False,
    )
    text = path.with_suffix(".txt").read_text(encoding="utf8")
    assert any("spectral masking" in warning for warning in warnings)
    assert "spectral masking" in text
    assert "35.0s" in text


def test_quality_brief_includes_foreground_underdrive_warning(tmp_path):
    (tmp_path / "spectral_masking.json").write_text(
        json.dumps(
            {
                "warnings": [],
                "underdriven_foreground": [
                    {
                        "time_s": 25.25,
                        "lead_group": "woodwinds",
                        "support_group": "strings",
                        "lead_relevant_peak_db": -78.5,
                    }
                ],
            }
        ),
        encoding="utf8",
    )
    path, warnings = write_quality_brief(
        tmp_path,
        cue_id="demo",
        render_hash="abc",
        all_audits=False,
        spectrograms=False,
    )
    text = path.with_suffix(".txt").read_text(encoding="utf8")
    assert any("foreground under-drive" in warning for warning in warnings)
    assert "foreground under-drive" in text
    assert "25.2s" in text or "25.3s" in text

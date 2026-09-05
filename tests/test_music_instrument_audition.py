from __future__ import annotations

from pathlib import Path
import yaml

from ambition_music_renderer.music_instrument_audition import (
    instrument_choices,
    safe_variant_slug,
    write_instrument_variant,
)


def _score(path: Path) -> Path:
    data = {
        "id": "cue",
        "instruments": [
            {"name": "lead", "group": "lead", "program": "clean_guitar", "instrument_backend": {"kind": "sfz", "library_ref": "guitar.emily", "prefer": ["clean"]}},
            {"name": "bass", "group": "bass", "program": "picked_bass"},
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf8")
    return path


def test_instrument_choices_read_group_and_backend(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    rows = instrument_choices(source, "lead")
    assert len(rows) == 1
    assert rows[0].name == "lead"
    assert rows[0].backend_mode == "sfz_library"
    assert rows[0].library_ref == "guitar.emily"


def test_write_instrument_variant_is_copy_only_and_can_switch_to_gm(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    before = source.read_bytes()
    output = write_instrument_variant(
        source_score=source,
        destination_score=tmp_path / "derived.music.yaml",
        group="lead",
        instrument_name="lead",
        program="distortion_guitar",
        backend_mode="gm",
    )
    assert source.read_bytes() == before
    data = yaml.safe_load(output.read_text())
    lead = data["instruments"][0]
    assert lead["program"] == "distortion_guitar"
    assert "instrument_backend" not in lead
    assert data["stem_lab"]["instrument_audition"]["group"] == "lead"


def test_write_instrument_variant_can_switch_library_and_never_overwrite(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    first = write_instrument_variant(
        source_score=source,
        destination_score=tmp_path / "derived.music.yaml",
        group="lead",
        instrument_name="lead",
        program="clean_guitar",
        backend_mode="sfz_library",
        library_ref="guitar.clean",
    )
    second = write_instrument_variant(
        source_score=source,
        destination_score=tmp_path / "derived.music.yaml",
        group="lead",
        instrument_name="lead",
        program="clean_guitar",
        backend_mode="sfz_library",
        library_ref="guitar.electric_lead",
    )
    assert first != second
    assert yaml.safe_load(first.read_text())["instruments"][0]["instrument_backend"] == {"kind": "sfz", "library_ref": "guitar.clean"}
    assert yaml.safe_load(second.read_text())["instruments"][0]["instrument_backend"] == {"kind": "sfz", "library_ref": "guitar.electric_lead"}


def test_safe_variant_slug():
    assert safe_variant_slug("T brass / Emily lead") == "T_brass_Emily_lead"

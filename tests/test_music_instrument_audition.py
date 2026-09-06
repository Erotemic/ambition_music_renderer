from __future__ import annotations

from pathlib import Path
import yaml

from ambition_music_renderer.music_instrument_audition import (
    candidate_key_for_score,
    instrument_candidates,
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


def test_instrument_candidates_include_curated_family_patches(tmp_path: Path):
    from ambition_music_renderer.music_instrument_audition import instrument_candidates

    source = _score(tmp_path / "source.music.yaml")
    lead = instrument_choices(source, "lead")[0]
    rows = instrument_candidates(lead)
    keys = {row.key for row in rows}
    assert "patch:emily_basic" in keys
    assert "patch:emily_clean" in keys
    assert "patch:shiny_electric" in keys
    assert "library:guitar.electric_lead" in keys
    assert not any(row.family == "bass" for row in rows)


def test_harpsichord_candidates_include_full_8ft_and_4ft(tmp_path: Path):
    from ambition_music_renderer.music_instrument_audition import InstrumentChoice, instrument_candidates

    choice = InstrumentChoice(
        name="harpsichord",
        group="harpsichord",
        program="harpsichord",
        backend_mode="sfz_path",
        library_ref="",
        sfz_glob="**/Harpsichord Full.sfz",
    )
    rows = instrument_candidates(choice)
    keys = {row.key for row in rows}
    assert {
        "patch:sonatina_harpsichord_full",
        "patch:sonatina_harpsichord_8ft",
        "patch:sonatina_harpsichord_4ft",
    } <= keys
    assert all(row.family == "keys" for row in rows)


def test_library_swap_applies_curated_startup_controls(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    output = write_instrument_variant(
        source_score=source,
        destination_score=tmp_path / "shiny.music.yaml",
        group="lead",
        instrument_name="lead",
        program="clean_guitar",
        backend_mode="sfz_library",
        library_ref="guitar.electric_lead",
    )
    lead = yaml.safe_load(output.read_text())["instruments"][0]
    assert lead["controls"][100] == 64
    assert lead["controls"][107] == 127


def test_authored_candidate_bank_is_bounded_and_marks_primary(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    data = yaml.safe_load(source.read_text())
    data["authoring"] = {
        "instrument_candidates": {
            "lead": {
                "primary": "emily_basic",
                "candidates": [
                    {
                        "id": "emily_basic",
                        "label": "Emily Basic",
                        "program": "clean_guitar",
                        "instrument_backend": {"kind": "sfz", "library_ref": "guitar.emily"},
                    },
                    {
                        "id": "shiny",
                        "label": "Shiny Lead",
                        "program": "clean_guitar",
                        "instrument_backend": {"kind": "sfz", "library_ref": "guitar.electric_lead"},
                    },
                ],
            }
        }
    }
    source.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf8")

    choice = instrument_choices(source, "lead")[0]
    rows = instrument_candidates(choice)
    assert [row.key for row in rows] == ["emily_basic", "shiny"]
    assert rows[0].primary is True
    assert rows[0].authored is True
    assert rows[1].primary is False
    # A score-authored bank wins over the much larger catalog fallback.
    assert not any(row.key.startswith("library:") or row.key.startswith("patch:") for row in rows)
    assert candidate_key_for_score(
        source, group="lead", instrument_name="lead", candidates=rows
    ) == "emily_basic"


def test_candidate_variant_records_identity_and_roots_at_original_source(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    first = write_instrument_variant(
        source_score=source,
        destination_score=tmp_path / "first.music.yaml",
        group="lead",
        instrument_name="lead",
        program="clean_guitar",
        backend_mode="sfz_library",
        library_ref="guitar.electric_lead",
        candidate_id="shiny",
        candidate_label="Shiny Lead",
    )
    second = write_instrument_variant(
        source_score=first,
        destination_score=tmp_path / "second.music.yaml",
        group="lead",
        instrument_name="lead",
        program="clean_guitar",
        backend_mode="sfz_library",
        library_ref="guitar.clean",
        candidate_id="clean",
        candidate_label="Clean Guitar",
    )
    data = yaml.safe_load(second.read_text())
    audition = data["stem_lab"]["instrument_audition"]
    assert Path(data["stem_lab"]["derived_from"]) == source.resolve()
    assert audition["candidate_id"] == "clean"
    assert audition["candidate_label"] == "Clean Guitar"


def test_patch_swap_applies_startup_controls_when_glob_omits_inventory_prefix(tmp_path: Path):
    source = _score(tmp_path / "source.music.yaml")
    output = write_instrument_variant(
        source_score=source,
        destination_score=tmp_path / "shiny_path.music.yaml",
        group="lead",
        instrument_name="lead",
        program="clean_guitar",
        backend_mode="sfz_path",
        sfz_glob="**/Shinyguitar/Shinyguitar/Programs/electric_five.sfz",
    )
    lead = yaml.safe_load(output.read_text())["instruments"][0]
    assert lead["controls"][100] == 64
    assert lead["controls"][107] == 127

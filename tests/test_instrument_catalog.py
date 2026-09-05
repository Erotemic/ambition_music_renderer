from __future__ import annotations

from importlib import resources
from pathlib import Path

from ambition_music_renderer.instrument_catalog import (
    describe_instrument,
    instrument_catalog,
    instrument_source_catalog,
    sfz_smoke_profile_specs,
)
from ambition_music_renderer.instrument_resolution import (
    backend_spec_from_instrument,
    normalize_backend_spec,
    resolve_instrument_backend,
)


def test_catalog_is_packaged_authoring_authority():
    resource = resources.files("ambition_music_renderer").joinpath("data/instrument_catalog.yaml")
    assert resource.is_file()

    catalog = instrument_catalog()
    assert catalog
    assert all(entry.expected for entry in catalog.values())
    assert {
        "freepats.salamander_grand",
        "guitar.emily",
        "bass.growly",
        "drums.big_rusty",
        "strings.violas",
        "orchestra.horns_sustain",
        "orchestra.vsco2",
    } <= set(catalog)


def test_every_catalog_instrument_has_known_download_source():
    sources = instrument_source_catalog()
    for ref, entry in instrument_catalog().items():
        assert entry.source in sources, ref
        source = sources[entry.source]
        assert source["expected"] is True
        assert source["install_profile"] in {"starter", "pro"}
        assert source["relative_root"], ref


def test_every_expected_source_maps_to_downloader_destination():
    repo_root = Path(__file__).resolve().parents[1]
    installer = (repo_root / "download_ambition_audio_tools.sh").read_text(encoding="utf8")
    for source_name, source in instrument_source_catalog().items():
        if not source.get("expected"):
            continue
        relative_root = str(source["relative_root"])
        assert relative_root.startswith("sfz/"), source_name
        installer_relative = relative_root.removeprefix("sfz/")
        assert installer_relative in installer, (source_name, installer_relative)


def test_describe_exposes_small_musicir_contract_and_library_nuance():
    description = describe_instrument("guitar.emily")
    assert description["musicir"] == {
        "instrument_backend": {"kind": "sfz", "library_ref": "guitar.emily"}
    }
    assert description["source_info"]["relative_root"].startswith("sfz/")
    assert any("chord" in note.lower() for note in description["source_info"]["notes"])
    assert any(row["name"] == "emily_chords" for row in description["known_patch_profiles"])
    assert "/data/audio-tools" not in str(description["musicir"])

    shiny = describe_instrument("guitar.electric_lead")
    shiny_profile = next(row for row in shiny["known_patch_profiles"] if row["name"] == "shiny_electric")
    assert shiny_profile["startup_cc"] == {"100": 64, "107": 127}


def test_smoke_profiles_are_catalog_data_and_reference_known_sources():
    sources = instrument_source_catalog()
    profiles = sfz_smoke_profile_specs()
    assert profiles
    by_name = {row["name"]: row for row in profiles}
    assert by_name["shiny_electric"]["startup_cc"] == {"100": 64, "107": 127}
    assert by_name["big_rusty"]["library_ref"] == "drums.big_rusty"
    for row in profiles:
        assert row["source"] in sources
        if row.get("library_ref"):
            assert row["library_ref"] in instrument_catalog()


def test_backend_aliases_normalize_once_and_resolve_through_catalog(tmp_path: Path):
    root = tmp_path / "sfz"
    sfz = root / "Karoryfer" / "Emilyguitar" / "Emilyguitar" / "emily_chords.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<group>\n", encoding="utf8")

    raw = {
        "type": "sample",
        "library": "guitar.emily",
        "prefer_keywords": ["chords"],
        "library_roots": str(root),
    }
    canonical = normalize_backend_spec(raw)
    assert canonical["kind"] == "sample"
    assert canonical["library_ref"] == "guitar.emily"
    assert canonical["prefer"] == ["chords"]
    assert canonical["library_roots"] == [str(root)]

    plan = resolve_instrument_backend(canonical)
    assert plan.resolved_sfz == sfz.resolve()
    assert plan.library_ref == "guitar.emily"
    assert plan.expected_catalog_instrument


def test_backend_spec_from_instrument_owns_legacy_top_level_sfz_alias():
    got = backend_spec_from_instrument({
        "name": "lead",
        "backend": "sfizz",
        "sfz": "relative/lead.sfz",
    })
    assert got["kind"] == "sfizz"
    assert got["sfz"] == "relative/lead.sfz"


def test_force_sfz_preserves_top_level_sfizz_default_behavior(tmp_path: Path):
    sfz = tmp_path / "default.sfz"
    sfz.write_text("<group>\n", encoding="utf8")
    plan = resolve_instrument_backend(
        {},
        base_dir=tmp_path,
        sfizz_cfg={"default_sfz": "default.sfz"},
        force_sfz=True,
    )
    assert plan.wants_sfz
    assert plan.resolved_sfz == sfz.resolve()

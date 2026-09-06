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
        "japan.shamisen",
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
        assert relative_root.startswith(("sfz/", "soundfonts/")), source_name
        installer_relative = relative_root.split("/", 1)[1]
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


def test_shamisen_catalog_uses_reproducible_per_instrument_soundfont(tmp_path: Path):
    description = describe_instrument("japan.shamisen")
    assert description["musicir"] == {
        "instrument_backend": {
            "kind": "soundfont",
            "renderer": "fluidsynth-cli",
            "library_ref": "japan.shamisen",
        },
        "program": 106,
    }
    sf2 = tmp_path / "soundfonts" / "Yukinisuzume" / "yukishami20v1.sf2"
    sf2.parent.mkdir(parents=True)
    sf2.write_bytes(b"RIFF-test-sf2")
    plan = resolve_instrument_backend({
        "kind": "soundfont",
        "library_ref": "japan.shamisen",
        "library_roots": [str(tmp_path / "soundfonts")],
    })
    assert plan.wants_soundfont
    assert plan.resolved_soundfont == sf2.resolve()


def test_installer_has_upstream_shamisen_and_raw_articulation_urls():
    repo_root = Path(__file__).resolve().parents[1]
    installer = (repo_root / "download_ambition_audio_tools.sh").read_text(encoding="utf8")
    assert "https://yukinisuzume.up.seesaa.net/image/yukishami20v1.sf2" in installer
    for name in ("shami-ff1.rar", "shami-f1.rar", "shamisen-p.rar", "shami-sukui1.rar", "shami-pizz1.rar"):
        assert name in installer


def test_group_routes_per_instrument_soundfont(monkeypatch, tmp_path: Path):
    import numpy as np
    import pretty_midi
    import ambition_music_renderer.render.group as group_mod

    sf2 = tmp_path / "shamisen.sf2"
    sf2.write_bytes(b"soundfont")
    pm = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=106, name="shamisen")
    inst.notes.append(pretty_midi.Note(velocity=96, pitch=64, start=0.0, end=0.25))
    pm.instruments.append(inst)
    calls = []
    def fake_render(pm_arg, backend, soundfont, sample_rate, midi_path, dry_wav_path, minimum_duration):
        calls.append((backend, soundfont, pm_arg.instruments[0].program))
        return np.ones((100, 2), dtype=np.float32) * 0.01
    monkeypatch.setattr(group_mod, "render_synth_audio", fake_render)
    audio = group_mod.render_group_audio(
        pm, {"shamisen": "lead"}, "lead", "fallback", "", 12000, tmp_path, 0.25, 120.0,
        base_dir=tmp_path,
        instrument_specs={"shamisen": {
            "name": "shamisen", "group": "lead", "program": 106,
            "instrument_backend": {
                "kind": "soundfont", "soundfont": str(sf2), "renderer": "fluidsynth-cli"
            },
        }},
    )
    assert len(audio) == 100
    assert calls == [("fluidsynth-cli", str(sf2.resolve()), 106)]

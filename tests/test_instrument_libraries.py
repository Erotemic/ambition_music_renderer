from __future__ import annotations

from pathlib import Path

from ambition_music_renderer.instrument_libraries import (
    collect_sfz_library_diagnostics,
    resolve_sfz_reference,
)
from ambition_music_renderer.audio_plugins import validate_instrument_backend_spec


def test_resolve_named_sfz_library_ref(tmp_path: Path):
    sfz = tmp_path / "sfz" / "FreePats" / "SalamanderGrandPiano" / "Salamander Grand Piano.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<group>\n", encoding="utf8")
    resolved = resolve_sfz_reference(
        library_ref="freepats.salamander_grand",
        prefer=["grand", "piano"],
        roots=[tmp_path / "sfz"],
    )
    assert resolved == sfz.resolve()


def test_validate_optional_sfz_backend_warns_on_missing_binary(tmp_path: Path):
    sfz = tmp_path / "manual" / "ShinyGuitar" / "ShinyGuitar sustain.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<group>\n", encoding="utf8")
    messages = validate_instrument_backend_spec(
        {
            "kind": "sfz",
            "library_ref": "guitar.clean",
            "prefer": ["shinyguitar", "sustain"],
            "library_roots": [str(tmp_path)],
            "optional": True,
            "binary": "definitely_missing_sfizz_render_binary",
        }
    )
    severities = {msg["severity"] for msg in messages}
    assert "warning" in severities
    assert any("resolved" in msg["message"] for msg in messages)


def test_collect_sfz_library_diagnostics_is_jsonable(tmp_path: Path, monkeypatch):
    sfz = tmp_path / "sfz" / "Virtual-Playing-Orchestra3" / "Strings" / "1st Violins Sustain.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<group>\n", encoding="utf8")
    monkeypatch.setenv("AMBITION_AUDIO_TOOLS_ROOT", str(tmp_path))
    report = collect_sfz_library_diagnostics(limit=10)
    assert report["sfz_count"] == 1
    assert report["alias_hits"]["vpo.strings"] == str(sfz.resolve())


def test_electric_bass_does_not_select_orchestral_bass_trombone(tmp_path: Path):
    trombone = tmp_path / "sfz" / "Virtual-Playing-Orchestra3" / "Brass" / "bass-trombone-SOLO-sustain.sfz"
    trombone.parent.mkdir(parents=True)
    trombone.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="bass.electric", roots=[tmp_path / "sfz"]) is None


def test_rock_drums_do_not_select_orchestral_percussion(tmp_path: Path):
    perc = tmp_path / "sfz" / "Virtual-Playing-Orchestra3" / "Percussion" / "bassdrum-snare-cymbals.sfz"
    perc.parent.mkdir(parents=True)
    perc.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="drums.rock", roots=[tmp_path / "sfz"]) is None
    assert resolve_sfz_reference(library_ref="vpo.percussion", roots=[tmp_path / "sfz"]) == perc.resolve()


def test_downloaded_role_aliases_resolve_from_stable_names(tmp_path: Path):
    cases = {
        "guitar.clean": "Karoryfer/Shinyguitar/Shinyguitar Sustain.sfz",
        "guitar.electric_lead": "Karoryfer/Shinyguitar/Shinyguitar Lead Sustain.sfz",
        "guitar.hollowbody": "Karoryfer/BlackAndGreenGuitars/Green Guitar Sustain.sfz",
        "bass.electric": "Karoryfer/Growlybass/Growlybass Finger Sustain.sfz",
        "drums.rock": "Karoryfer/GogodzePhuVolII/Gogodze Drum Kit.sfz",
        "folk.banjo": "SFZInstruments/Ganjo/ganjo.sfz",
        "folk.harp": "Versilian/EtherealwindsHarpII_CE/Etherealwinds Harp Normal Sustain.sfz",
        "brass.tuba": "Karoryfer/WarTuba/War Tuba Sustain.sfz",
        "strings.cello": "Karoryfer/BigcatCello/Bigcat Cello Sustain.sfz",
        "strings.cyborg": "Karoryfer/StringCyborgs/String Cyborgs Sustain.sfz",
        "folk.bass_tagelharpa": "Karoryfer/HorsePulse/Horse Pulse Bass Tagelharpa.sfz",
    }
    for ref, rel in cases.items():
        root = tmp_path / ref.replace(".", "_") / "sfz"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
        resolved = resolve_sfz_reference(library_ref=ref, roots=[root])
        assert resolved == path.resolve(), ref


def test_generic_aliases_avoid_wrong_vpo_roles(tmp_path: Path):
    root = tmp_path / "sfz"
    wrong_bass = root / "Virtual-Playing-Orchestra3" / "Brass" / "bass-trombone-SOLO-sustain.sfz"
    right_bass = root / "Karoryfer" / "Growlybass" / "Growlybass Finger Sustain.sfz"
    wrong_drum = root / "Virtual-Playing-Orchestra3" / "Percussion" / "bassdrum-snare-cymbals.sfz"
    right_drum = root / "Karoryfer" / "GogodzePhuVolII" / "Gogodze Drum Kit.sfz"
    for path in [wrong_bass, right_bass, wrong_drum, right_drum]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="bass.electric", roots=[root]) == right_bass.resolve()
    assert resolve_sfz_reference(library_ref="drums.rock", roots=[root]) == right_drum.resolve()

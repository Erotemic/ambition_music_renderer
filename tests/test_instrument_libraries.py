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


def test_orchestral_role_aliases_choose_matching_sonatina_and_vcsl_patches(tmp_path: Path):
    cases = {
        "orchestra.horns_sustain": "Sonatina/SymphonicOrchestra/Brass/Horns Sustain.sfz",
        "orchestra.horns_staccato": "Sonatina/SymphonicOrchestra/Brass/Horns Staccato.sfz",
        "orchestra.trumpets_sustain": "Sonatina/SymphonicOrchestra/Brass/Trumpets Sustain.sfz",
        "orchestra.trumpets_staccato": "Sonatina/SymphonicOrchestra/Brass/Trumpets Staccato.sfz",
        "orchestra.trombones_sustain": "Sonatina/SymphonicOrchestra/Brass/Trombones Sustain.sfz",
        "orchestra.trombones_staccato": "Sonatina/SymphonicOrchestra/Brass/Trombones Staccato.sfz",
        "orchestra.tuba_sustain": "Sonatina/SymphonicOrchestra/Brass/Tuba Sustain.sfz",
        "orchestra.flutes_sustain": "Sonatina/SymphonicOrchestra/Woodwinds/Flutes Sustain.sfz",
        "orchestra.oboes_sustain": "Sonatina/SymphonicOrchestra/Woodwinds/Oboes Sustain.sfz",
        "orchestra.clarinets_sustain": "Sonatina/SymphonicOrchestra/Woodwinds/Clarinets Sustain.sfz",
        "orchestra.timpani": "Sonatina/SymphonicOrchestra/Percussion/Timpani Hits.sfz",
        "strings.violins_1_staccato": "Sonatina/SymphonicOrchestra/Strings/1st Violins Staccato.sfz",
        "strings.violins_2_staccato": "Sonatina/SymphonicOrchestra/Strings/2nd Violins Staccato.sfz",
        "strings.celli_staccato": "Sonatina/SymphonicOrchestra/Strings/Celli Staccato.sfz",
        "orchestra.snare": "Versilian/VCSL/Membranophones/Struck Membranophones/Snare Drum, Rope Tension.sfz",
        "orchestra.bass_drum": "Versilian/VCSL/Membranophones/Struck Membranophones/Bass Drum 1.sfz",
        "orchestra.cymbal": "Versilian/VCSL/Idiophones/Struck Idiophones/Suspended Cymbal.sfz",
    }
    for ref, rel in cases.items():
        root = tmp_path / ref.replace(".", "_") / "sfz"
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
        assert resolve_sfz_reference(library_ref=ref, roots=[root]) == path.resolve(), ref


def test_orchestral_cymbal_alias_avoids_finger_cymbals(tmp_path: Path):
    root = tmp_path / "sfz"
    finger = root / "Versilian/VCSL/Idiophones/Struck Idiophones/Finger Cymbals.sfz"
    suspended = root / "Versilian/VCSL/Idiophones/Struck Idiophones/Suspended Cymbal.sfz"
    for path in (finger, suspended):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="orchestra.cymbal", roots=[root]) == suspended.resolve()


def test_vpo_male_choir_alias_prefers_actual_male_patch(tmp_path: Path):
    root = tmp_path / "sfz"
    female = root / "Virtual-Playing-Orchestra3" / "Vocals" / "choir-FEMALE-sustain.sfz"
    male = root / "Virtual-Playing-Orchestra3" / "Vocals" / "choir-MALE-sustain.sfz"
    for path in (female, male):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="vpo.choir_male", roots=[root]) == male.resolve()


def test_alto_sax_alias_avoids_neighboring_saxophones(tmp_path: Path):
    root = tmp_path / "sfz"
    alto = root / "SaxLibrary" / "Alto Sax Solo Sustain.sfz"
    tenor = root / "SaxLibrary" / "Tenor Sax Solo Sustain.sfz"
    for path in (alto, tenor):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="winds.alto_sax", roots=[root]) == alto.resolve()


def test_tenor_sax_alias_avoids_neighboring_saxophones(tmp_path: Path):
    root = tmp_path / "sfz"
    alto = root / "SaxLibrary" / "Alto Sax Solo Sustain.sfz"
    tenor = root / "SaxLibrary" / "Tenor Sax Solo Sustain.sfz"
    baritone = root / "SaxLibrary" / "Baritone Sax Solo Sustain.sfz"
    for path in (alto, tenor, baritone):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="winds.tenor_sax", roots=[root]) == tenor.resolve()


def test_marching_snare_alias_avoids_modern_single_hit(tmp_path: Path):
    root = tmp_path / "sfz"
    modern = root / "Versilian" / "VCSL" / "Snare Drum, Modern 1.sfz"
    rope = root / "Versilian" / "VCSL" / "Snare Drum, Rope Tension.sfz"
    for path in (modern, rope):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="orchestra.snare_march", roots=[root]) == rope.resolve()


def test_snare_roll_alias_prefers_actual_roll_patch(tmp_path: Path):
    root = tmp_path / "sfz"
    hit = root / "Versilian" / "VCSL" / "Snare Drum, Rope Tension.sfz"
    roll = root / "Versilian" / "VCSL" / "Snare Drum, Rope Tension Roll.sfz"
    for path in (hit, roll):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="orchestra.snare_roll", roots=[root]) == roll.resolve()


def test_marching_tenor_alias_chooses_drumline_patch_not_sax(tmp_path: Path):
    root = tmp_path / "sfz"
    sax = root / "SaxLibrary" / "Tenor Sax Solo Sustain.sfz"
    tenor = root / "Versilian" / "VCSL" / "Membranophones" / "Marching Tenor Drum.sfz"
    for path in (sax, tenor):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="orchestra.marching_tenor", roots=[root]) == tenor.resolve()


def test_upright_bass_alias_prefers_pizzicato_over_sustain(tmp_path: Path):
    root = tmp_path / "sfz"
    sustain = root / "Sonatina" / "SymphonicOrchestra" / "Strings" / "Basses Sustain.sfz"
    pizz = root / "Sonatina" / "SymphonicOrchestra" / "Strings" / "Basses Pizzicato.sfz"
    for path in (sustain, pizz):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="bass.upright", roots=[root]) == pizz.resolve()


def test_warm_acoustic_prefers_alternate_acoustic_over_shinyguitar(tmp_path: Path):
    root = tmp_path / "sfz"
    shiny = root / "Karoryfer" / "Shinyguitar" / "Programs" / "acoustic.sfz"
    warm = root / "Manual" / "Blue Jeans and Moonbeams" / "12 String Acoustic Guitar Sustain.sfz"
    for path in (shiny, warm):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    resolved = resolve_sfz_reference(library_ref="guitar.acoustic_warm", roots=[root])
    assert resolved == warm.resolve()


def test_warm_acoustic_can_fall_back_to_shinyguitar_when_it_is_only_sample(tmp_path: Path):
    root = tmp_path / "sfz"
    shiny = root / "Karoryfer" / "Shinyguitar" / "Programs" / "acoustic.sfz"
    shiny.parent.mkdir(parents=True, exist_ok=True)
    shiny.write_text("<group>\n", encoding="utf8")
    resolved = resolve_sfz_reference(library_ref="guitar.acoustic_warm", roots=[root])
    assert resolved == shiny.resolve()



def test_premium_acoustic_bass_alias_prefers_meatbass_pizz_program(tmp_path: Path):
    root = tmp_path / "sfz"
    sonatina = root / "Sonatina" / "SymphonicOrchestra" / "Strings" / "Basses Pizzicato.sfz"
    meatbass = root / "Karoryfer" / "Meatbass" / "Meatbass" / "Programs" / "04_pizz.sfz"
    helper = root / "Karoryfer" / "Meatbass" / "Meatbass" / "Programs" / "pizz_basic_map.sfz"
    for path in (sonatina, meatbass, helper):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")
    assert resolve_sfz_reference(library_ref="bass.meatbass_pizz", roots=[root]) == meatbass.resolve()


def test_vpo_solo_performance_aliases_choose_plain_perf_programs(tmp_path: Path):
    root = tmp_path / "sfz"
    cases = {
        "vpo.violin_solo_perf": (
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Strings/1st-violin-SOLO-PERF.sfz",
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Strings/1st-violin-SOLO-PERF-KS-C2.sfz",
        ),
        "vpo.flute_solo_perf": (
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Woodwinds/flute-SOLO-PERF.sfz",
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Woodwinds/alto-flute-SOLO-PERF.sfz",
        ),
        "vpo.oboe_solo_perf": (
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Woodwinds/oboe-SOLO-PERF.sfz",
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Woodwinds/oboe-SOLO-PERF-KS-C2.sfz",
        ),
        "vpo.clarinet_solo_perf": (
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Woodwinds/clarinet-SOLO-PERF.sfz",
            "Virtual-Playing-Orchestra3/Virtual-Playing-Orchestra3/Woodwinds/clarinet-SOLO-PERF-staccato.sfz",
        ),
    }
    for ref, (wanted_rel, distractor_rel) in cases.items():
        wanted = root / wanted_rel
        distractor = root / distractor_rel
        for path in (wanted, distractor):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<group>\n", encoding="utf8")
        assert resolve_sfz_reference(library_ref=ref, roots=[root]) == wanted.resolve(), ref

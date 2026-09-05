from __future__ import annotations

from pathlib import Path

from ambition_music_renderer.instrument_usage_census import (
    analyze_sfz_usage,
    build_usage_census,
    census_by_resolved_path,
    census_row_is_fresh,
)


def _touch_sample(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")


def test_usage_census_describes_required_controller_gate(tmp_path: Path):
    root = tmp_path / "sfz"
    sfz = root / "Library" / "Programs" / "Electric.sfz"
    sample = root / "Library" / "Programs" / "samples" / "c4.wav"
    sfz.parent.mkdir(parents=True)
    _touch_sample(sample)
    sfz.write_text(
        "\n".join([
            "<group> locc107=76 hicc107=100 gain_oncc1=6 xfin_locc11=0 xfin_hicc11=64",
            "<region> key=60 lovel=1 hivel=127 sample=samples/c4.wav",
        ]),
        encoding="utf8",
    )

    row = analyze_sfz_usage(sfz, roots=[root])
    assert row["key_span"] == [60, 60]
    assert row["suggested_default_controls"] == {"107": 88}
    assert row["controller_gates"] == [{
        "cc": 107,
        "allowed_ranges": [[76, 100]],
        "constrained_regions": 1,
        "all_regions_constrained": True,
        "coverage_fraction": 1.0,
    }]
    assert row["modulation_controllers"] == [{"cc": 1, "opcodes": ["gain"], "details": {"gain": {"amount_min": 6.0, "amount_max": 6.0}}}]
    assert row["crossfade_controllers"] == [{"cc": 11, "opcodes": ["xfin_hicc11", "xfin_locc11"], "breakpoints": {"xfin_hicc11": [64], "xfin_locc11": [0]}}]
    assert row["samples_found"] == 1
    assert row["role"] == "likely_entrypoint"


def test_usage_census_preserves_multiple_feasible_controller_zones(tmp_path: Path):
    root = tmp_path / "sfz"
    sfz = root / "Library" / "Programs" / "Articulations.sfz"
    sfz.parent.mkdir(parents=True)
    _touch_sample(sfz.parent / "a.wav")
    _touch_sample(sfz.parent / "b.wav")
    sfz.write_text(
        "\n".join([
            "<group> locc20=0 hicc20=63",
            "<region> lokey=48 hikey=72 sample=a.wav",
            "<group> locc20=64 hicc20=127",
            "<region> lokey=48 hikey=72 sample=b.wav",
        ]),
        encoding="utf8",
    )

    row = analyze_sfz_usage(sfz, roots=[root])
    assert row["controller_gates"][0]["allowed_ranges"] == [[0, 127]]
    presets = {tuple(sorted(preset["controls"].items())) for preset in row["control_presets"]}
    assert (("20", 32),) in presets
    assert (("20", 96),) in presets
    # CC20=0 already reaches one of the global zones, so there is no need to
    # invent an additional default merely to make the patch sound.
    assert row["suggested_default_controls"] == {}


def test_build_usage_census_skips_helper_sfzs_by_default(tmp_path: Path, monkeypatch):
    root = tmp_path / "sfz"
    program = root / "Synth" / "Programs" / "Main.sfz"
    helper = root / "Synth" / "modules" / "oscillator.sfz"
    for path in (program, helper):
        path.parent.mkdir(parents=True, exist_ok=True)
        _touch_sample(path.parent / "sample.wav")
        path.write_text("<region> key=60 sample=sample.wav\n", encoding="utf8")

    monkeypatch.setenv("AMBITION_MUSIC_SFZ_ROOTS", str(root))
    report = build_usage_census(jobs=1)
    paths = {Path(row["path"]).name for row in report["instruments"]}
    assert "Main.sfz" in paths
    assert "oscillator.sfz" not in paths
    assert report["skipped_likely_helpers"] == 1

    index = census_by_resolved_path(report)
    row = index[str(program.resolve())]
    assert census_row_is_fresh(row, program)
    program.write_text(program.read_text() + "// changed\n", encoding="utf8")
    assert not census_row_is_fresh(row, program)


def test_census_activation_zones_support_cheap_probe_preflight(tmp_path: Path):
    from ambition_music_renderer.music_instrument_inspector_model import (
        build_probe_request,
        sfz_probe_preflight_from_census,
    )

    root = tmp_path / "sfz"
    sfz = root / "Library" / "Programs" / "Gated.sfz"
    sample = sfz.parent / "sample.wav"
    sfz.parent.mkdir(parents=True)
    _touch_sample(sample)
    sfz.write_text(
        "<group> locc107=76 hicc107=100\n"
        "<region> lokey=60 hikey=72 lovel=1 hivel=127 sample=sample.wav\n",
        encoding="utf8",
    )
    row = analyze_sfz_usage(sfz, roots=[root])
    instrument = {
        "name": "test",
        "group": "test",
        "program": "acoustic_grand_piano",
        "instrument_backend": {"kind": "sfz", "sfz": str(sfz)},
    }
    request = build_probe_request(
        instrument=instrument,
        processing={},
        probe="C4",
        probe_template="single_note",
    )
    diag = sfz_probe_preflight_from_census(request, row, base_dir=tmp_path)
    assert diag["source"] == "usage_census"
    assert diag["status"] == "blocked"
    assert diag["suggested_controls"] == {"107": 88}

    instrument["controls"] = {107: 88}
    request = build_probe_request(
        instrument=instrument,
        processing={},
        probe="C4",
        probe_template="single_note",
    )
    diag = sfz_probe_preflight_from_census(request, row, base_dir=tmp_path)
    assert diag["status"] == "ok"

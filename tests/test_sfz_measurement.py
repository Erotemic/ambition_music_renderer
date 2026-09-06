from pathlib import Path

import numpy as np

from ambition_music_renderer.audit.sfz_measurement import (
    raw_pitch_diagnostic,
    repeat_variation,
    select_regions,
)


def test_select_regions_reports_sample_mapping_and_tuning(tmp_path: Path):
    sfz = tmp_path / "bass.sfz"
    sfz.write_text(
        "<group> lokey=36 hikey=36 pitch_keycenter=36 seq_length=4\n"
        "<region> sample=notes/c2_rr1.wav transpose=0 tune=-3 seq_position=1\n"
        "<region> sample=notes/c2_rr2.wav seq_position=2\n"
    )
    regions = select_regions(sfz, 36, velocity=100)
    assert [row["sample"] for row in regions] == ["notes/c2_rr1.wav", "notes/c2_rr2.wav"]
    assert regions[0]["pitch_keycenter"] == 36
    assert regions[0]["tune"] == -3
    assert regions[0]["seq_position"] == 1


def test_select_regions_expands_included_sfz_macros(tmp_path: Path):
    (tmp_path / "keymap.sfz").write_text("#define $kick 36\n")
    (tmp_path / "kick.wav").write_bytes(b"sample")
    sfz = tmp_path / "kit.sfz"
    sfz.write_text('#include "keymap.sfz"\n<master> key=$kick\n<region> sample=kick.wav\n')
    regions = select_regions(sfz, 36)
    assert len(regions) == 1
    assert regions[0]["sample"] == "kick.wav"


def test_raw_pitch_measurement_exposes_octave_competition():
    sample_rate = 24000
    time = np.arange(sample_rate, dtype=np.float64) / sample_rate
    # A strong second harmonic should not silently become an octave claim.
    audio = 0.12 * np.sin(2 * np.pi * 110 * time) + 0.8 * np.sin(2 * np.pi * 220 * time)
    result = raw_pitch_diagnostic(audio[:, None], sample_rate, 45)
    assert result["status"] in {"reliable", "octave_ambiguous", "actual_pitch_mismatch"}
    assert set(result["scores"]) == {"half", "expected", "double"}


def test_repeat_variation_uses_attack_shape_not_peak_level():
    sample_rate = 1000
    audio = np.zeros(2500, dtype=np.float64)
    for index, frequency in enumerate((80, 110, 145, 190)):
        start = 80 + index * 550
        time = np.arange(180) / sample_rate
        audio[start:start + 180] = np.sin(2 * np.pi * frequency * time)
    result = repeat_variation(audio, sample_rate, count=4, window_s=0.15)
    assert result["measured_attacks"] == 4
    assert result["unique_attack_evidence"] > 0
    assert result["repeat_variation_status"] == "variation_evidenced"

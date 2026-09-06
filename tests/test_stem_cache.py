from copy import deepcopy
from pathlib import Path

from ambition_music_renderer.render.score_layers import build_score
from ambition_music_renderer.render.stem_cache import stem_cache_key


def _score(*, left_intervals=(0, 4), left_humanize_ms=0.0, right_humanize_ms=0.0):
    return {
        "schema": "ambition.musicir.v1",
        "id": "stem_cache_test",
        "seed": 17,
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "left", "group": "left", "program": "acoustic_grand_piano"},
            {"name": "right", "group": "right", "program": "acoustic_grand_piano"},
        ],
        "motifs": [
            {
                "id": "left_phrase",
                "root": "C4",
                "intervals": list(left_intervals),
                "rhythm": [1.0] * len(left_intervals),
                "velocities": [1.0] * len(left_intervals),
            },
            {
                "id": "right_phrase",
                "root": "G4",
                "intervals": [0, 2],
                "rhythm": [1.0, 1.0],
                "velocities": [1.0, 1.0],
            },
        ],
        "sections": [
            {
                "id": "a",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {
                        "kind": "motif",
                        "instrument": "left",
                        "motif": "left_phrase",
                        "starts": [[0, 0.0]],
                        "velocity": 90,
                        "humanize_ms": left_humanize_ms,
                    },
                    {
                        "kind": "motif",
                        "instrument": "right",
                        "motif": "right_phrase",
                        "starts": [[0, 2.0]],
                        "velocity": 90,
                        "humanize_ms": right_humanize_ms,
                    },
                ],
            }
        ],
    }


def _keys(spec, tmp_path: Path):
    pm, groups, meta = build_score(spec)
    total = meta[-1]["end_seconds"]
    common = {
        "spec": spec,
        "spec_path": tmp_path / "cue.music.yaml",
        "pm": pm,
        "groups": groups,
        "backend": "pretty-midi",
        "soundfont": "/nonexistent/test.sf2",
        "sample_rate": 48000,
        "bpm": 120.0,
        "total_seconds": total,
    }
    return {
        group: stem_cache_key(group=group, **common)
        for group in sorted(set(groups.values()))
    }


def test_stem_cache_key_is_group_local_when_expanded_events_are_unchanged(tmp_path):
    base = _score()
    edited = deepcopy(base)
    edited["motifs"][0]["intervals"] = [0, 5]

    base_keys = _keys(base, tmp_path)
    edited_keys = _keys(edited, tmp_path)

    assert base_keys["left"] != edited_keys["left"]
    assert base_keys["right"] == edited_keys["right"]


def test_stem_cache_key_tracks_shared_humanization_rng_side_effects(tmp_path):
    base = _score(left_intervals=(0, 4), left_humanize_ms=5.0, right_humanize_ms=5.0)
    edited = _score(left_intervals=(0, 4, 7), left_humanize_ms=5.0, right_humanize_ms=5.0)

    base_keys = _keys(base, tmp_path)
    edited_keys = _keys(edited, tmp_path)

    assert base_keys["left"] != edited_keys["left"]
    # Adding a humanized note to the earlier layer advances the shared RNG, so
    # the later group's expanded timing changes too. The cache key must notice.
    assert base_keys["right"] != edited_keys["right"]


def test_stem_cache_roundtrip_rejects_wrong_shape(tmp_path):
    import numpy as np

    from ambition_music_renderer.render.stem_cache import (
        restore_cached_stem,
        store_cached_stem,
    )

    scratch = tmp_path / "scratch.npy"
    cached = tmp_path / "cache" / "stem.npy"
    restored = tmp_path / "restored.npy"
    audio = np.arange(24, dtype=np.float32).reshape(12, 2)
    np.save(scratch, audio)

    store_cached_stem(scratch, cached)
    assert cached.exists()
    assert restore_cached_stem(cached, restored, expected_samples=12)
    assert np.array_equal(np.load(restored), audio)

    wrong = tmp_path / "wrong.npy"
    np.save(wrong, np.zeros((11, 2), dtype=np.float32))
    assert not restore_cached_stem(wrong, tmp_path / "bad.npy", expected_samples=12)


def test_stem_cache_key_tracks_resolved_sfz_file_identity(tmp_path):
    sfz = tmp_path / "lead.sfz"
    sfz.write_text("<region> sample=lead.wav\n")
    spec = _score()
    spec["instruments"][0]["instrument_backend"] = {
        "kind": "sfz",
        "sfz": str(sfz),
    }

    before = _keys(spec, tmp_path)
    sfz.write_text("<region> sample=lead-v2.wav\n")
    after = _keys(spec, tmp_path)

    assert before["left"] != after["left"]
    assert before["right"] == after["right"]


def test_stem_cache_key_tracks_referenced_sfz_sample_identity(tmp_path):
    sample = tmp_path / "lead.wav"
    sample.write_bytes(b"sample-v1")
    sfz = tmp_path / "lead.sfz"
    sfz.write_text("<region> sample=lead.wav\n")
    spec = _score()
    spec["instruments"][0]["instrument_backend"] = {
        "kind": "sfz",
        "sfz": str(sfz),
    }

    before = _keys(spec, tmp_path)
    sample.write_bytes(b"sample-v2-with-different-size")
    after = _keys(spec, tmp_path)

    assert before["left"] != after["left"]
    assert before["right"] == after["right"]

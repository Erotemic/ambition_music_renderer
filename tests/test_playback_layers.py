from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ambition_music_renderer import cli
from ambition_music_renderer.render.playback_layers import (
    cut_section,
    layer_section_audio,
    mastered_section_audio,
    playback_layer_plan,
    select_runtime_export_stems,
    write_playback_layers,
)

SR = 1000
FORM = [
    {"id": "intro", "start_seconds": 0.0, "end_seconds": 1.0, "start_beat": 0.0, "end_beat": 4.0},
    {"id": "verse", "start_seconds": 1.0, "end_seconds": 3.0, "start_beat": 4.0, "end_beat": 12.0},
    {"id": "chorus", "start_seconds": 3.0, "end_seconds": 5.0, "start_beat": 12.0, "end_beat": 20.0},
]
GROUPS = ["bass", "drums", "lead"]


def _spec(layers, sections=None):
    playback = {"layers": layers}
    if sections is not None:
        playback["sections"] = sections
    return {"playback": playback}


def test_a_score_with_no_layers_asks_for_no_playback_files():
    assert playback_layer_plan({}, FORM, GROUPS) is None
    assert playback_layer_plan({"playback": {"exit_policy": {}}}, FORM, GROUPS) is None


def test_a_playback_section_is_a_span_of_the_form():
    plan = playback_layer_plan(
        _spec(
            {"bed": ["bass", "lead"], "kit": ["drums"]},
            [{"id": "intro"}, {"id": "loop", "form": ["verse", "chorus"], "loop": True}],
        ),
        FORM,
        GROUPS,
    )
    intro, loop = plan["sections"]
    assert (intro["start_seconds"], intro["end_seconds"], intro["loop"]) == (0.0, 1.0, False)
    assert (loop["start_seconds"], loop["end_seconds"], loop["loop"]) == (1.0, 5.0, True)
    assert loop["duration_beats"] == 16.0


def test_without_sections_each_form_section_is_a_playback_section():
    plan = playback_layer_plan(_spec({"all": GROUPS}), FORM, GROUPS)
    assert [section["id"] for section in plan["sections"]] == ["intro", "verse", "chorus"]


@pytest.mark.parametrize(
    "layers, sections, problem",
    [
        ({"bed": ["bass", "lead"]}, None, "in no layer"),
        ({"bed": GROUPS, "kit": ["drums"]}, None, "in layer"),
        ({"bed": GROUPS + ["strings"]}, None, "unknown group"),
        ({"full": GROUPS}, None, "reserved"),
        ({"bed": GROUPS}, [{"id": "loop", "form": ["intro", "chorus"]}], "consecutive"),
        ({"bed": GROUPS}, [{"id": "loop", "form": ["bridge"]}], "unknown form"),
        ({"bed": GROUPS}, [{"id": "intro"}, {"id": "intro"}], "two times"),
    ],
)
def test_a_block_that_cannot_give_a_complete_mix_is_refused(layers, sections, problem):
    with pytest.raises(ValueError, match=problem):
        playback_layer_plan(_spec(layers, sections), FORM, GROUPS)


def _stems():
    rng = np.random.default_rng(7)
    return {group: rng.uniform(-0.2, 0.2, size=(5 * SR, 2)).astype(np.float32) for group in GROUPS}


def test_the_layers_of_a_section_sum_to_its_stems_and_close_at_the_seam():
    stems = _stems()
    bed = layer_section_audio(stems, ["bass", "lead"], SR, 1.0, 5.0)
    kit = layer_section_audio(stems, ["drums"], SR, 1.0, 5.0)
    assert bed.shape == (4 * SR, 2)
    whole = sum(stems.values())[1 * SR:5 * SR]
    # Away from the two fades the layers are the mix, sample for sample.
    np.testing.assert_allclose((bed + kit)[10:-10], whole[10:-10], atol=1e-6)
    # A loop wraps from the last sample to the first: both are silent.
    assert np.all(bed[0] == 0.0) and np.all(bed[-1] == 0.0)


def test_layer_files_are_written_for_each_section_and_published_to_stable_paths(tmp_path, monkeypatch):
    plan = playback_layer_plan(
        _spec({"bed": ["bass", "lead"], "kit": ["drums"]}, [{"id": "loop", "form": ["verse", "chorus"], "loop": True}]),
        FORM,
        GROUPS,
    )
    outdir = tmp_path / "generated" / "probe"
    written: dict[Path, int] = {}

    def write_audio(audio, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ogg")
        written[path] = len(audio)

    files = write_playback_layers(plan, _stems(), SR, outdir, "probe_abc", write_audio)
    assert files == {"loop": {"bed": "playback/loop/probe_abc.loop.bed.ogg", "kit": "playback/loop/probe_abc.loop.kit.ogg"}}
    assert set(written.values()) == {4 * SR}

    manifest = outdir / "probe_abc.adaptive_manifest.json"
    manifest.write_text(json.dumps({"files": {"playback": files}}), encoding="utf8")
    monkeypatch.setattr(cli, "find_latest_manifest", lambda _outdir, _cue: manifest)
    dest = tmp_path / "published" / "probe"
    copied = cli.publish_playback_layers("probe", outdir, dest)
    assert sorted(path.relative_to(dest).as_posix() for path in copied) == [
        "playback/loop/loop.bed.ogg",
        "playback/loop/loop.kit.ogg",
    ]


def test_shared_runtime_gain_applies_equally_to_layer_groups_and_single_stems():
    native = _stems()
    shared = {group: audio * 0.33 for group, audio in native.items()}
    assert select_runtime_export_stems(native, shared, "native") is native
    assert select_runtime_export_stems(native, shared, "shared") is shared
    with pytest.raises(ValueError, match="unknown runtime stem gain mode"):
        select_runtime_export_stems(native, shared, "typo")

    plan = playback_layer_plan(
        _spec({"bed": ["bass", "lead"], "kit": ["drums"]},
              [{"id": "loop", "form": ["verse", "chorus"], "loop": True}]),
        FORM, GROUPS,
    )
    native_mix = sum(layer_section_audio(native, gs, SR, 1.0, 5.0)
                     for gs in plan["layers"].values())
    shared_mix = sum(layer_section_audio(
        select_runtime_export_stems(native, shared, "shared"), gs, SR, 1.0, 5.0
    ) for gs in plan["layers"].values())
    np.testing.assert_allclose(shared_mix, native_mix * 0.33, atol=1e-7)


RING_FORM = FORM + [
    {"id": "ring", "start_seconds": 5.0, "end_seconds": 6.0, "start_beat": 20.0, "end_beat": 24.0},
]


def _ringing_timeline():
    """A loop (verse + chorus, 1 s to 5 s) whose last note rings 0.8 s past its end into a silent tail."""
    t = np.arange(6 * SR) / SR
    audio = np.zeros((6 * SR, 2), dtype=np.float32)
    for onset in (1.0, 2.5, 4.6):
        on = t >= onset
        audio[on] += (np.sin(2 * np.pi * 7 * (t[on] - onset)) * np.exp(-(t[on] - onset) / 0.25))[:, None]
    loop_part = audio[1 * SR:5 * SR]
    ring = audio[5 * SR:6 * SR]
    return audio, loop_part, ring


def test_a_tail_must_be_the_form_section_after_the_span():
    with pytest.raises(ValueError, match="right after"):
        playback_layer_plan(
            _spec({"bed": GROUPS}, [{"id": "loop", "form": ["verse"], "loop": True, "tail": "ring"}]), RING_FORM, GROUPS
        )
    plan = playback_layer_plan(
        _spec({"bed": GROUPS}, [{"id": "loop", "form": ["verse", "chorus"], "loop": True, "tail": "ring"}]),
        RING_FORM,
        GROUPS,
    )
    assert plan["sections"][0]["tail_end_seconds"] == 6.0


def test_a_looped_section_carries_its_ring_across_its_seam():
    audio, loop_part, ring = _ringing_timeline()
    piece = cut_section(audio, SR, 1.0, 5.0, tail_end_seconds=6.0, loop=True)
    assert len(piece) == 4 * SR
    # Two passes are the loop played two times with the ring of the first under
    # the head of the second, and no fade at the join.
    expected = np.concatenate([loop_part, loop_part])
    expected[4 * SR:5 * SR] += ring
    np.testing.assert_allclose(np.concatenate([piece, piece])[4 * SR:], expected[4 * SR:], atol=1e-6)


def test_a_section_that_does_not_loop_plays_its_ring_after_its_end():
    audio, _, ring = _ringing_timeline()
    piece = cut_section(audio, SR, 1.0, 5.0, tail_end_seconds=6.0)
    assert len(piece) == 5 * SR
    np.testing.assert_allclose(piece[4 * SR:-10], ring[:-10], atol=1e-6)


def _leaky_master(audio: np.ndarray) -> np.ndarray:
    """A master with memory: a one-pole smoother, as a compressor or a reverb has state."""
    out = np.zeros_like(audio)
    state = np.zeros(audio.shape[1], dtype=np.float32)
    for i, frame in enumerate(audio):
        state = 0.9 * state + 0.1 * frame
        out[i] = state
    return out


def test_the_full_mix_of_a_loop_is_mastered_as_it_sounds_when_it_comes_round_again():
    audio, _, _ = _ringing_timeline()
    plan = playback_layer_plan(
        {"playback": {"full": True, "sections": [
            {"id": "intro"},
            {"id": "loop", "form": ["verse", "chorus"], "loop": True, "tail": "ring"},
        ]}},
        RING_FORM,
        GROUPS,
    )
    full = mastered_section_audio(plan, audio, SR, _leaky_master)
    one_pass = cut_section(audio, SR, 1.0, 5.0, tail_end_seconds=6.0, loop=True)
    steady = _leaky_master(np.concatenate([one_pass] * 3))[4 * SR:8 * SR]
    np.testing.assert_allclose(full["loop"], steady, atol=1e-5)
    # A section that does not loop is cut from the one mastered timeline.
    np.testing.assert_allclose(full["intro"][10:-10], _leaky_master(audio)[10:1 * SR - 10], atol=1e-6)


def _notes(onsets, seconds):
    """Decaying notes at ``onsets`` on a timeline ``seconds`` long; each rings under 1 s."""
    t = np.arange(int(seconds * SR)) / SR
    audio = np.zeros((len(t), 2), dtype=np.float32)
    for onset in onsets:
        on = t >= onset
        audio[on] += (np.sin(2 * np.pi * 7 * (t[on] - onset)) * np.exp(-(t[on] - onset) / 0.07))[:, None]
    return audio


def test_a_looped_section_sounds_as_the_loop_does_when_it_comes_round_again():
    # The loop is 1 s to 5 s. Its first note is humanized 10 ms early, into the
    # silent lead-in; its last note rings past its end into the silent tail.
    in_loop = (-0.01, 1.5, 3.6)
    timeline = _notes([1.0 + r for r in in_loop], 6.0)
    plan = playback_layer_plan(
        _spec({"bed": GROUPS}, [{"id": "loop", "form": ["verse", "chorus"], "loop": True,
                                 "lead_in": "intro", "tail": "ring"}]),
        RING_FORM,
        GROUPS,
    )
    (loop,) = plan["sections"]
    piece = cut_section(timeline, SR, loop["start_seconds"], loop["end_seconds"],
                        tail_end_seconds=loop["tail_end_seconds"],
                        lead_in_start_seconds=loop["lead_in_start_seconds"], loop=True)
    # The loop played on and on, one pass after another: its second pass.
    played_on = _notes([4.0 * k + r for k in range(4) for r in in_loop], 16.0)
    np.testing.assert_allclose(piece, played_on[4 * SR:8 * SR], atol=1e-5)
    with pytest.raises(ValueError, match="right before"):
        playback_layer_plan(
            _spec({"bed": GROUPS}, [{"id": "loop", "form": ["chorus"], "loop": True, "lead_in": "intro"}]),
            RING_FORM, GROUPS,
        )

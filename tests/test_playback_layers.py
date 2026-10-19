from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ambition_music_renderer import cli
from ambition_music_renderer.render.playback_layers import (
    layer_section_audio,
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

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.render.dependencies import (
    RENDER_DEPENDENCY_SCHEMA,
    build_render_dependency_fingerprint,
    dependency_change_summary,
    renderer_implementation_identity,
    sfz_dependency_identity,
)
from ambition_music_renderer.render.generated_layout import compute_score_render_hash


def _score(*, backend=None, velocity=90):
    instrument = {
        "name": "lead",
        "group": "lead",
        "program": "acoustic_grand_piano",
    }
    if backend is not None:
        instrument["instrument_backend"] = backend
    return {
        "schema": "ambition.musicir.v1",
        "id": "render_dependency_test",
        "title": "Render Dependency Test",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [instrument],
        "motifs": [
            {
                "id": "phrase",
                "root": "C4",
                "intervals": [0, 4],
                "rhythm": [1.0, 1.0],
                "velocities": [1.0, 1.0],
            }
        ],
        "sections": [
            {
                "id": "loop",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {
                        "kind": "motif",
                        "instrument": "lead",
                        "motif": "phrase",
                        "starts": [[0, 0.0]],
                        "velocity": velocity,
                    }
                ],
            }
        ],
    }


def _fake_renderer_root(tmp_path: Path) -> Path:
    root = tmp_path / "fake_renderer"
    (root / "data").mkdir(parents=True)
    (root / "engine.py").write_text("VALUE = 1\n", encoding="utf8")
    (root / "data" / "instrument_catalog.yaml").write_text("schema: test\n", encoding="utf8")
    return root


def _fingerprint(tmp_path: Path, spec: dict, *, soundfont="", package_root=None):
    score_path = tmp_path / "score.music.yaml"
    score_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf8")
    compiled = compile_score(spec)
    return build_render_dependency_fingerprint(
        spec_path=score_path,
        spec=spec,
        compiled=compiled,
        backend="pretty-midi",
        soundfont=soundfont,
        package_root=package_root,
    )


def test_render_fingerprint_uses_semantics_not_cosmetic_score_metadata(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    base = _score()
    renamed = deepcopy(base)
    renamed["title"] = "A different display title"
    edited = deepcopy(base)
    edited["sections"][0]["layers"][0]["velocity"] = 91
    processed = deepcopy(base)
    processed["postprocess"] = {"gain_db": -1.0}

    original = _fingerprint(tmp_path, base, package_root=renderer_root)
    assert _fingerprint(tmp_path, renamed, package_root=renderer_root).fingerprint == original.fingerprint
    assert _fingerprint(tmp_path, edited, package_root=renderer_root).fingerprint != original.fingerprint
    assert _fingerprint(tmp_path, processed, package_root=renderer_root).fingerprint != original.fingerprint


def test_renderer_source_changes_invalidate_without_manual_version_bump(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    before = _fingerprint(tmp_path, _score(), package_root=renderer_root)
    (renderer_root / "engine.py").write_text("VALUE = 2\n", encoding="utf8")
    after = _fingerprint(tmp_path, _score(), package_root=renderer_root)

    assert before.fingerprint != after.fingerprint
    assert "renderer_version" not in before.payload
    manifest = before.manifest_payload()
    assert manifest["schema"] == RENDER_DEPENDENCY_SCHEMA
    assert manifest["legacy_renderer_version"]


def test_soundfont_file_identity_invalidates_render(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    soundfont = tmp_path / "test.sf2"
    soundfont.write_bytes(b"soundfont-v1")
    before = _fingerprint(tmp_path, _score(), soundfont=str(soundfont), package_root=renderer_root)
    soundfont.write_bytes(b"soundfont-v2-with-different-size")
    after = _fingerprint(tmp_path, _score(), soundfont=str(soundfont), package_root=renderer_root)
    assert before.fingerprint != after.fingerprint


def test_sfz_dependency_tracks_referenced_samples_but_not_unrelated_files(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    sample = tmp_path / "lead.wav"
    unrelated = tmp_path / "unused.wav"
    sample.write_bytes(b"sample-v1")
    unrelated.write_bytes(b"unused-v1")
    sfz = tmp_path / "lead.sfz"
    sfz.write_text("<region> sample=lead.wav lokey=60 hikey=72\n", encoding="utf8")
    spec = _score(backend={"kind": "sfz", "sfz": str(sfz), "fallback_backend": "fallback"})

    first = _fingerprint(tmp_path, spec, package_root=renderer_root)
    sfz_info = sfz_dependency_identity(sfz)
    assert sfz_info["sample_file_count"] == 1

    unrelated.write_bytes(b"unused-v2-different")
    unrelated_changed = _fingerprint(tmp_path, spec, package_root=renderer_root)
    assert unrelated_changed.fingerprint == first.fingerprint

    sample.write_bytes(b"sample-v2-different-size")
    sample_changed = _fingerprint(tmp_path, spec, package_root=renderer_root)
    assert sample_changed.fingerprint != first.fingerprint


def test_dependency_change_summary_names_changed_authority(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    base = _fingerprint(tmp_path, _score(), package_root=renderer_root)
    changed_spec = _score()
    changed_spec["postprocess"] = {"gain_db": -2.0}
    changed = _fingerprint(tmp_path, changed_spec, package_root=renderer_root)

    assert dependency_change_summary(base.manifest_payload(), base) == []
    reasons = dependency_change_summary(base.manifest_payload(), changed)
    assert reasons == ["render dependencies changed: audio_settings"]


def test_generated_layout_hash_tracks_referenced_sfz_sample(tmp_path, monkeypatch):
    # This exercises the public generated-layout boundary rather than only the
    # dependency helper. Renderer implementation/runtime identity stays fixed
    # within the process; changing a referenced sample must still move the run.
    sample = tmp_path / "lead.wav"
    sample.write_bytes(b"sample-a")
    sfz = tmp_path / "lead.sfz"
    sfz.write_text("<region> sample=lead.wav\n", encoding="utf8")
    spec = _score(backend={"kind": "sfz", "sfz": str(sfz)})
    score_path = tmp_path / "cue.music.yaml"
    score_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf8")

    before = compute_score_render_hash(score_path, "pretty-midi", spec=spec)
    sample.write_bytes(b"sample-b-has-a-new-size")
    after = compute_score_render_hash(score_path, "pretty-midi", spec=spec)
    assert before != after


def test_sfz_dependency_expands_defined_sample_path_macros(tmp_path):
    samples = tmp_path / "Samples"
    samples.mkdir()
    sample = samples / "lead.wav"
    sample.write_bytes(b"sample-v1")
    sfz = tmp_path / "lead.sfz"
    sfz.write_text(
        "#define $SAMPLE_DIR Samples\n"
        "<region> sample=$SAMPLE_DIR/lead.wav lokey=60 hikey=72\n",
        encoding="utf8",
    )

    before = sfz_dependency_identity(sfz)
    assert before["sample_file_count"] == 1
    assert before["missing_or_dynamic_sample_count"] == 0

    sample.write_bytes(b"sample-v2-with-different-size")
    after = sfz_dependency_identity(sfz)
    assert before["sample_files_fingerprint"] != after["sample_files_fingerprint"]


def test_render_fingerprint_tracks_vst3_bundle_identity(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    plugin = tmp_path / "Amp.vst3"
    plugin.mkdir()
    binary = plugin / "Contents" / "x86_64-linux" / "Amp.so"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"plugin-v1")

    spec = _score()
    spec["postprocess"] = {
        "effect_chain": [
            {
                "kind": "vst3",
                "path": str(plugin),
                "parameters": {"gain": 0.5},
            }
        ]
    }
    before = _fingerprint(tmp_path, spec, package_root=renderer_root)
    binary.write_bytes(b"plugin-v2-with-different-size")
    after = _fingerprint(tmp_path, spec, package_root=renderer_root)

    assert before.fingerprint != after.fingerprint
    vst = before.payload["processing"]["effects"]["$.postprocess.effect_chain[0]"]["vst3"]
    assert vst["resolved"]["kind"] == "directory"


def test_render_fingerprint_tracks_external_processor_file(tmp_path):
    renderer_root = _fake_renderer_root(tmp_path)
    processor = tmp_path / "processor.py"
    processor.write_text("print('v1')\n", encoding="utf8")
    spec = _score()
    spec["postprocess"] = {
        "effect_chain": [
            {
                "kind": "command",
                "command": ["python", str(processor), "{input}", "{output}"],
            }
        ]
    }

    before = _fingerprint(tmp_path, spec, package_root=renderer_root)
    processor.write_text("print('version two')\n", encoding="utf8")
    after = _fingerprint(tmp_path, spec, package_root=renderer_root)
    assert before.fingerprint != after.fingerprint

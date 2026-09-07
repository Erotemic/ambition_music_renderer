"""Review-workflow contracts using synthetic music and a fake native renderer.

No real cue, sample library, named-song fingerprint, or musical acceptance test.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pytest
from scipy.io import wavfile
import yaml

from ambition_music_renderer.musicir.compile import compile_score
from ambition_music_renderer.musicir.model import compiled_score_fingerprint


def runner(tmp_path, monkeypatch, *, audit_error=False, clipped=False):
    path = Path(__file__).resolve().parents[1] / "dev" / "review_ninja_suite.py"
    module_spec = importlib.util.spec_from_file_location("suite_review_tool", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "CUES", ("fixture",))
    score = {
        "schema": "ambition.musicir.v3", "id": "fixture", "tempo": 120,
        "meter": "4/4", "timebase": {"ppq": 960}, "end": {"bar": 4},
        "form": [{"id": "intro", "from": {"bar": 1}, "to": {"bar": 2}},
                 {"id": "loop", "from": {"bar": 2}, "to": {"bar": 4}, "loopable": True}],
        "instruments": [{"name": "keys", "program": "acoustic_grand_piano"}],
        "materials": {"cell": {"events": [[0, "1/4", "C4", 90]]}},
        "parts": [{"id": "p", "instrument": "keys", "voices": [{"id": "v", "clips": [
            {"id": "a", "at": {"bar": 1}, "use": "cell"},
            {"id": "b", "at": {"bar": 2}, "use": "cell"},
            {"id": "c", "at": {"bar": 3}, "use": "cell"},
        ]}]}],
    }
    source = tmp_path / "scores" / "active" / "fixture.music.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(yaml.safe_dump(score), encoding="utf8")

    def fake_native(command, log_path):
        render = Path(command[command.index("--outdir") + 1])
        bundles = Path(command[command.index("--bundle_root") + 1])
        render.mkdir(parents=True)
        bundle = bundles / "fixture_native"
        bundle.mkdir(parents=True)
        log_path.write_text("synthetic renderer output\n", encoding="utf8")
        assert command[command.index("--backend") + 1] == "pretty-midi"
        assert "--publish" not in command
        x = np.full((32000, 2), 1.05 if clipped else .1, dtype=np.float32)
        wavfile.write(render / "loop.wav", 8000, x)
        shutil.copy2(render / "loop.wav", bundle / "loop.wav")
        (render / "fixture_synthetic.adaptive_manifest.json").write_text(json.dumps({
            "compiled_score": {"fingerprint": compiled_score_fingerprint(compile_score(score))},
            "files": {"adaptive": {"loop": {"full": "loop.wav"}}},
        }), encoding="utf8")
        (bundle / "bundle_manifest.json").write_text(json.dumps({
            "warnings": ["synthetic warning"],
            "commands": [{"name": "synthetic_audit", "returncode": int(audit_error)}],
        }), encoding="utf8")
    monkeypatch.setattr(module, "run_logged", fake_native)
    return module


def test_full_review_records_audio_and_report_archives_separately(tmp_path, monkeypatch):
    module = runner(tmp_path, monkeypatch)
    output = tmp_path / "review"
    assert module.main(["--output", str(output)]) == 0
    run = json.loads((output / "RUN.json").read_text())
    assert run["results"][0]["status"] == "rendered_and_measured"
    assert run["results"][0]["audit_warnings"] == ["synthetic warning"]
    with zipfile.ZipFile(output / "ninja_suite_review.zip") as archive:
        assert any(name.endswith("loop.wav") for name in archive.namelist())
        assert any(name.endswith("loop_seam.wav") for name in archive.namelist())
    with zipfile.ZipFile(output / "ninja_suite_report.zip") as archive:
        assert not any(Path(name).suffix in {".wav", ".mid"} for name in archive.namelist())
        assert any(name.endswith("loop_audio.json") for name in archive.namelist())


@pytest.mark.parametrize("options", [{"audit_error": True}, {"clipped": True}])
def test_failed_checks_still_preserve_audio_evidence(tmp_path, monkeypatch, options):
    module = runner(tmp_path, monkeypatch, **options)
    output = tmp_path / "review"
    assert module.main(["--output", str(output)]) == 1
    with zipfile.ZipFile(output / "ninja_suite_review.zip") as archive:
        assert any(name.endswith("failure.json") for name in archive.namelist())
        assert any(name.endswith("loop.wav") for name in archive.namelist())


def test_score_only_never_renders_and_output_cannot_reuse_old_run(tmp_path, monkeypatch):
    module = runner(tmp_path, monkeypatch)
    def forbidden(*args):
        raise AssertionError("score-only must not invoke synthesis")
    monkeypatch.setattr(module, "run_logged", forbidden)
    output = tmp_path / "review"
    assert module.main(["--score-only", "--output", str(output)]) == 0
    with pytest.raises(FileExistsError):
        module.main(["--score-only", "--output", str(output)])

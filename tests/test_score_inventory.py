"""Score inventory uses source metadata, without rendered files or libraries."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ambition_music_renderer import cli
from ambition_music_renderer.score_inventory import score_inventory, score_metadata


def test_inventory_keeps_score_policy_separate_from_section_loops(tmp_path, capsys):
    (tmp_path / "a.yaml").write_text('''id: "score_loop" # source identity
one_shot: false # section endings do not make the score a one-shot
sections:
  - {id: ending, loopable: false}
''')
    (tmp_path / "b.yml").write_text('''id: score_sting
one_shot: true
sections:
  - {id: body, loopable: true}
''')
    (tmp_path / "c.music.yaml").write_text('id: default_loop\n')

    report = score_inventory(tmp_path)
    assert report["scores"] == [
        {"cue_id": "default_loop", "score_one_shot": False, "source": "c.music.yaml"},
        {"cue_id": "score_loop", "score_one_shot": False, "source": "a.yaml"},
        {"cue_id": "score_sting", "score_one_shot": True, "source": "b.yml"},
    ]
    assert cli.main(["cue", "inventory", "--scores-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == report


@pytest.mark.parametrize("source", ["[]", "id: 42", "id: ''", "id: fixture\none_shot: 'false'"])
def test_inventory_rejects_invalid_score_metadata_with_its_source_path(tmp_path, source):
    path = tmp_path / "invalid.yaml"
    path.write_text(source)
    with pytest.raises(ValueError, match="invalid.yaml: score"):
        score_inventory(tmp_path)


def test_inventory_rejects_an_empty_roster_and_duplicate_identities(tmp_path):
    with pytest.raises(ValueError, match="no scores found"):
        score_inventory(tmp_path)
    (tmp_path / "a.yaml").write_text("id: repeated\n")
    (tmp_path / "b.yaml").write_text("id: repeated\n")
    with pytest.raises(ValueError, match="duplicate score id repeated"):
        score_inventory(tmp_path)


def test_source_export_does_not_load_synthesis_or_numerical_dependencies(tmp_path):
    (tmp_path / "fixture.yaml").write_text("id: fixture\none_shot: true\n")
    completed = subprocess.run(
        [sys.executable, "-c", '''import runpy, sys
sys.modules.update({name: None for name in ("numpy", "scipy", "pretty_midi", "fluidsynth", "soundfile")})
sys.argv = ["inventory", "--scores-dir", sys.argv[1]]
runpy.run_module("ambition_music_renderer.score_inventory", run_name="__main__")
''', str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
    )
    assert json.loads(completed.stdout)["scores"][0] == {
        **score_metadata({"id": "fixture", "one_shot": True}), "source": "fixture.yaml",
    }

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from ambition_music_renderer import cli


def test_bulk_render_preflight_stops_before_first_render(monkeypatch, tmp_path, capsys):
    score = tmp_path / "bad.music.yaml"
    score.write_text(
        "schema: ambition.musicir.v1\n"
        "id: bad\n"
        "render:\n"
        "  soundfont: /definitely/missing/fresh-clone-test.sf2\n",
        encoding="utf8",
    )

    monkeypatch.setattr(cli, "find_score", lambda cue: score)
    monkeypatch.setattr(cli, "needs_render", lambda cue, yaml_path, outdir: True)

    bulk_called = False

    def fake_run_bulk(args, cues, action):
        nonlocal bulk_called
        bulk_called = True
        return 0

    monkeypatch.setattr(cli, "_run_bulk", fake_run_bulk)
    config = SimpleNamespace(
        cue=["bad"],
        backend="pretty-midi",
        force_render=False,
        skip_render=False,
        dest_root=tmp_path,
    )

    rc = cli.run_bulk_cues(
        config, cues_factory=lambda: ("bad",), action="render-publish"
    )

    assert rc == 1
    assert not bulk_called
    stderr = capsys.readouterr().err
    assert "music render preflight failed before rendering any cue" in stderr
    assert "bad: soundfont does not exist" in stderr


def test_radio_scores_do_not_require_optional_data_soundfont_tree():
    offenders = []
    for cue in cli.radio_cues():
        score = cli.find_score(cue)
        if score is None:
            continue
        spec = yaml.safe_load(Path(score).read_text(encoding="utf8")) or {}
        soundfont = str((spec.get("render") or {}).get("soundfont") or "")
        if soundfont.startswith("/data/audio-tools/soundfonts/"):
            offenders.append(f"{cue}: {soundfont}")

    assert not offenders, (
        "radio cues must render on a fresh developer setup without the optional "
        "/data/audio-tools tree: " + ", ".join(offenders)
    )


def test_bulk_render_preflight_builds_score_before_first_render(monkeypatch, tmp_path, capsys):
    from ambition_music_renderer.render import score_layers

    score = tmp_path / "bad-score.music.yaml"
    score.write_text(
        "schema: ambition.musicir.v1\n"
        "id: bad_score\n"
        "tempo: {bpm: 120}\n"
        "meter: {beats_per_bar: 4}\n",
        encoding="utf8",
    )

    monkeypatch.setattr(cli, "find_score", lambda cue: score)
    monkeypatch.setattr(cli, "needs_render", lambda cue, yaml_path, outdir: True)
    monkeypatch.setattr(cli, "generated_run_layout", lambda *args, **kwargs: None)

    def reject_score(spec):
        raise ValueError("synthetic MusicIR construction failure")

    monkeypatch.setattr(score_layers, "build_score", reject_score)

    bulk_called = False

    def fake_run_bulk(args, cues, action):
        nonlocal bulk_called
        bulk_called = True
        return 0

    monkeypatch.setattr(cli, "_run_bulk", fake_run_bulk)
    config = SimpleNamespace(
        cue=["bad-score"],
        backend="pretty-midi",
        force_render=False,
        skip_render=False,
        dest_root=tmp_path,
    )

    rc = cli.run_bulk_cues(
        config, cues_factory=lambda: ("bad-score",), action="render-publish"
    )

    assert rc == 1
    assert not bulk_called
    stderr = capsys.readouterr().err
    assert "music render preflight failed before rendering any cue" in stderr
    assert "synthetic MusicIR construction failure" in stderr


def test_dependency_refresh_detects_non_yaml_mtime_render_inputs(tmp_path):
    from ambition_music_renderer.render.generated_layout import compute_score_render_dependencies

    score = tmp_path / "deps.music.yaml"
    spec = {
        "schema": "ambition.musicir.v1",
        "id": "deps",
        "tempo": {"bpm": 120},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {"name": "piano", "group": "music", "program": "acoustic_grand_piano"}
        ],
        "motifs": [
            {"id": "m", "root": "C4", "intervals": [0], "rhythm": [1.0], "velocities": [1.0]}
        ],
        "sections": [
            {
                "id": "loop",
                "bars": 1,
                "harmony": ["C"],
                "layers": [
                    {"kind": "motif", "instrument": "piano", "motif": "m", "starts": [[0, 0.0]], "velocity": 90}
                ],
            }
        ],
    }
    score.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf8")
    cue_dir = tmp_path / "generated" / "deps"
    deps = compute_score_render_dependencies(score, "pretty-midi", spec=spec)
    run_dir = cue_dir / ".versioned" / deps.short_hash
    run_dir.mkdir(parents=True)
    manifest = run_dir / f"deps_{deps.short_hash}.adaptive_manifest.json"
    manifest.write_text(
        __import__("json").dumps({"render_dependencies": deps.manifest_payload()}),
        encoding="utf8",
    )

    refresh, reason = cli.render_dependencies_need_refresh(score, cue_dir, "pretty-midi")
    assert not refresh
    assert reason == "render dependencies current"

    # An audio-domain setting changes the dependency identity even if callers
    # deliberately preserve the source mtime (the old coarse gate cannot see it).
    original_mtime = score.stat().st_mtime_ns
    spec["postprocess"] = {"gain_db": -1.5}
    score.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf8")
    import os
    os.utime(score, ns=(original_mtime, original_mtime))

    refresh, reason = cli.render_dependencies_need_refresh(score, cue_dir, "pretty-midi")
    assert refresh
    assert "dependency fingerprint" in reason or "dependencies changed" in reason

"""⭐⭐ A MACHINE MISSING ONE LIBRARY FAMILY MUST STOP, NOT SUBSTITUTE.

⛔⛔ THIS IS THE HALF THE ALL-OR-NOTHING GUARD DOES NOT COVER.
`test_refuses_the_general_midi_fallback.py` catches a machine with NO sampled
libraries. This catches the likelier and quieter case: libraries installed,
`_sampled_libraries_installed()` true, and ONE family absent — so the cues that
name it render through General MIDI while every other cue is correct. Same
`.ogg`, same registry entry, same playback, exit code 0.

⚠ **AND THE CATALOGUE CANNOT DEFEND ITSELF.** Measured 2026-09-03 over
`scores/active`: all **247** sfz instrument backends are `optional: True` — 231
explicitly, 16 by `_is_optional_instrument_backend`'s default — and only 2 of 75
scores set `render.strict_backends`. `group.py`'s guard is
`(wants_sfizz and not optional) or strict_backends`, which is FALSE for every
instrument in the shipped catalogue. Each one warns once to stderr and falls
back. That is why this gate ignores `optional:` rather than honouring it.

⭐ **AND IT COSTS A CORRECTLY-INSTALLED MACHINE NOTHING**, which is what makes a
gate legitimate here rather than a warning: on a box with the libraries present,
all 247 references resolve.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ambition_music_renderer import cli


NAMED_LIBRARY = "freepats.salamander_grand"


@pytest.fixture
def score(tmp_path):
    path = tmp_path / "cue.music.yaml"
    path.write_text(
        "schema: ambition.musicir.v1\n"
        "id: cue\n"
        "tracks:\n"
        "  - name: piano\n"
        "    instrument_backend:\n"
        "      kind: sfz\n"
        f"      library_ref: {NAMED_LIBRARY}\n"
        "      optional: true\n",
        encoding="utf8",
    )
    return path


def _wire(monkeypatch, score, *, resolves: bool):
    # ⚠ The score is deliberately MINIMAL — it declares one instrument backend
    # and nothing else — so the two builders the preflight runs before the
    # library check are stubbed. They are not what these arms are about, and a
    # fully-formed score would hide the thing under test behind score schema
    # churn.
    from ambition_music_renderer.render import score_layers

    monkeypatch.setattr(score_layers, "build_score", lambda spec: None)
    monkeypatch.setattr(cli, "generated_run_layout", lambda *a, **k: None)
    monkeypatch.setattr(cli, "find_score", lambda cue: score)
    monkeypatch.setattr(cli, "needs_render", lambda cue, yaml_path, outdir: True)
    monkeypatch.setattr(
        cli, "_sfz_reference_resolves", lambda *a, **k: resolves
    )
    rendered: list[str] = []
    monkeypatch.setattr(
        cli, "_run_bulk", lambda config, cues, action: rendered.append(action) or 0
    )
    return rendered


def _config(tmp_path):
    return SimpleNamespace(
        cue=["cue"],
        backend="pretty-midi",
        force_render=False,
        skip_render=False,
        dest_root=tmp_path,
    )


def test_a_named_library_this_machine_lacks_stops_the_render(
    monkeypatch, tmp_path, score, capsys
):
    rendered = _wire(monkeypatch, score, resolves=False)

    rc = cli.run_bulk_cues(
        _config(tmp_path), cues_factory=lambda: ("cue",), action="render"
    )

    assert rc == 1
    assert not rendered, (
        "the renderer was reached — this cue would have been written in the "
        "wrong instrument and reported as success"
    )
    err = capsys.readouterr().err
    # ⭐ It must name the LIBRARY, not just fail. "something is missing" sends
    # the reader to a 38 GB install they may already have most of.
    assert NAMED_LIBRARY in err
    assert "cue" in err, "it must say which cues wanted it"
    # ⛔ And it must say how to fix it, the same way the all-or-nothing refusal does.
    assert "run_developer_setup.sh" in err
    assert "download_ambition_audio_tools.sh" in err
    assert "AMBITION_MUSIC_ALLOW_GM_FALLBACK" in err


def test_optional_true_does_not_excuse_a_missing_library(monkeypatch, tmp_path, score):
    """⛔ THE WHOLE FINDING IN ONE ASSERTION.

    The fixture score says `optional: true`, exactly like all 247 backends in
    the shipped catalogue. If this gate honoured that flag it would be dead code
    on every cue Ambition ships.
    """
    _wire(monkeypatch, score, resolves=False)
    import yaml

    spec = yaml.safe_load(score.read_text())
    assert spec["tracks"][0]["instrument_backend"]["optional"] is True
    assert cli._unresolvable_sfz_references(spec, base_dir=score.parent) == [
        NAMED_LIBRARY
    ]


def test_a_machine_that_has_the_library_is_not_blocked(
    monkeypatch, tmp_path, score, capsys
):
    """⭐ THE CONTROL ARM. A gate that fires on a healthy box is a worse defect."""
    rendered = _wire(monkeypatch, score, resolves=True)

    rc = cli.run_bulk_cues(
        _config(tmp_path), cues_factory=lambda: ("cue",), action="render"
    )

    assert rc == 0
    assert rendered == ["render"]
    assert "missing sampled" not in capsys.readouterr().err


def test_the_walk_finds_a_backend_nested_at_any_depth():
    """⚠ Scores nest `instrument_backend` under tracks, sections and layers.

    A flat scan of one key would silently cover a fraction of the catalogue and
    look green — the failure mode this whole file exists to prevent.
    """
    spec = {
        "sections": [
            {"layers": {"a": {"instrument_backend": {"library_ref": "deep.one"}}}}
        ],
        "tracks": [{"instrument_backend": {"sfz": "flat/two.sfz"}}],
    }
    found = {
        tuple(sorted(backend.items()))
        for backend in cli._walk_instrument_backends(spec)
    }
    assert len(found) == 2

"""⭐⭐ A MACHINE WITHOUT THE SAMPLED LIBRARIES MUST REFUSE, NOT RENDER.

⛔⛔ THIS GUARDS A STANDING INSTRUCTION, NOT A PREFERENCE. Jon: *"I don't want
new machines to get bad fallbacks of songs."* Without the `.sfz` libraries every
cue that names one still SUCCEEDS — through General MIDI, which is not the
music — and nothing downstream can tell: the `.ogg` exists, the registry lists
it, the game plays it. A machine that renders the whole catalogue in the wrong
instruments and reports success is worse than one that stops and says what is
missing.

⚠ AND THE REFUSAL HAD NO TEST UNTIL NOW (added 2026-09-03). `cli.py` was the
only file in the repository naming `_sampled_libraries_installed` or
`AMBITION_MUSIC_ALLOW_GM_FALLBACK`, so the one check standing between a fresh
clone and a catalogue of wrong audio could have been deleted or inverted in
silence. The failure it prevents is invisible by construction, which is exactly
why it needs a guard rather than a reader.

⭐ THE ESCAPE HATCH IS TESTED TOO, and deliberately: a refusal with no way past
it is a different defect. `AMBITION_MUSIC_ALLOW_GM_FALLBACK=1` is for previews,
and it must still SAY it is doing that.
"""

from __future__ import annotations

from types import SimpleNamespace

from ambition_music_renderer import cli


def _config(tmp_path):
    return SimpleNamespace(
        cue=["anything"],
        backend="pretty-midi",
        force_render=False,
        skip_render=False,
        dest_root=tmp_path,
    )


def _no_libraries(monkeypatch):
    monkeypatch.setattr(cli, "_sampled_libraries_installed", lambda: False)


def _never_renders(monkeypatch):
    """Fail loudly if the command reaches the renderer at all."""
    calls = []

    def fake_run_bulk(config, cues, action):
        calls.append(action)
        return 0

    monkeypatch.setattr(cli, "_run_bulk", fake_run_bulk)
    monkeypatch.setattr(cli, "_preflight_bulk_render", lambda *a, **k: True)
    return calls


def test_render_refuses_when_no_sampled_library_is_installed(
    monkeypatch, tmp_path, capsys
):
    _no_libraries(monkeypatch)
    monkeypatch.delenv("AMBITION_MUSIC_ALLOW_GM_FALLBACK", raising=False)
    rendered = _never_renders(monkeypatch)

    rc = cli.run_bulk_cues(
        _config(tmp_path), cues_factory=lambda: ("anything",), action="render"
    )

    assert rc == 1, "a machine with no sampled libraries must not render"
    assert not rendered, (
        "the command reached the renderer — every cue naming a sampled patch "
        "would have been written through General MIDI and reported as success"
    )
    stderr = capsys.readouterr().err
    assert "refusing to render every cue" in stderr
    # ⭐ It must say HOW to fix it. A refusal that does not is a wall.
    assert "run_developer_setup.sh" in stderr
    assert "download_ambition_audio_tools.sh" in stderr


def test_render_publish_refuses_on_the_same_road(monkeypatch, tmp_path, capsys):
    """⛔ PUBLISH IS THE DANGEROUS ONE and must not be the arm that slips.

    `render` leaves wrong audio in a build directory; `render-publish` puts it
    in the tree the game ships. They are separate strings in the same condition,
    so one of them can be dropped without the other noticing.
    """
    _no_libraries(monkeypatch)
    monkeypatch.delenv("AMBITION_MUSIC_ALLOW_GM_FALLBACK", raising=False)
    rendered = _never_renders(monkeypatch)

    rc = cli.run_bulk_cues(
        _config(tmp_path), cues_factory=lambda: ("anything",), action="render-publish"
    )

    assert rc == 1 and not rendered


def test_the_documented_escape_hatch_still_works_and_announces_itself(
    monkeypatch, tmp_path, capsys
):
    """⚠ A refusal with no way past it is its own defect.

    The fallback is legitimate for previews and sound-design-free checks, so the
    env var must let the render through — and must SAY so, because the whole
    hazard is audio that looks identical to the real thing.
    """
    _no_libraries(monkeypatch)
    monkeypatch.setenv("AMBITION_MUSIC_ALLOW_GM_FALLBACK", "1")
    rendered = _never_renders(monkeypatch)

    rc = cli.run_bulk_cues(
        _config(tmp_path), cues_factory=lambda: ("anything",), action="render"
    )

    assert rc == 0
    assert rendered == ["render"], "the escape hatch must actually reach the renderer"
    assert "continuing with fallback audio" in capsys.readouterr().err


def test_publish_only_is_not_blocked_by_a_missing_library(
    monkeypatch, tmp_path, capsys
):
    """⭐ THE CONTROL ARM: the refusal is scoped to actions that RENDER.

    Publishing already-rendered audio needs no instruments, and a guard that
    blocked it would make the libraries a hard dependency of every command —
    which is what turns a correct refusal into one people route around with the
    env var permanently set.
    """
    _no_libraries(monkeypatch)
    monkeypatch.delenv("AMBITION_MUSIC_ALLOW_GM_FALLBACK", raising=False)
    rendered = _never_renders(monkeypatch)

    rc = cli.run_bulk_cues(
        _config(tmp_path), cues_factory=lambda: ("anything",), action="publish"
    )

    assert rc == 0
    assert rendered == ["publish"]
    assert "refusing to render" not in capsys.readouterr().err

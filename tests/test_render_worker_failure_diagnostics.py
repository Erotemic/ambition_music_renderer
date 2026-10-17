"""Generic diagnostics for silent SFZ parts and isolated worker failures."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pretty_midi
import pytest

from ambition_music_renderer.render import group_worker, isolated
from ambition_music_renderer.render.sfz_diagnostics import silent_sfz_diagnostic
from ambition_music_renderer.render.worker_failures import read_worker_failure, worker_failure_path


def test_silent_sfz_diagnostic_surfaces_keyspan_and_unset_cc_gate(tmp_path: Path):
    sfz = tmp_path / "electric.sfz"
    sfz.write_text(
        "<group> locc107=101 hicc100=126\n"
        "<region> sample=example.wav lokey=48 hikey=84\n",
        encoding="utf8",
    )
    inst = pretty_midi.Instrument(program=25, name="solo")
    inst.notes.append(pretty_midi.Note(100, 64, 1.0, 1.5))
    inst.control_changes.append(pretty_midi.ControlChange(100, 64, 0.0))
    message = silent_sfz_diagnostic(inst, sfz, library_ref="guitar.lead")
    assert "solo" in message
    assert "guitar.lead" in message
    assert "64 (E4)" in message
    assert "84 (C6)" in message
    assert "notes outside: 0/1" in message
    assert "CC107=UNSET" in message
    assert "CC107 >=101" in message
    assert "POSSIBLE ISSUE" in message


def test_silent_sfz_diagnostic_reports_all_notes_outside_span(tmp_path: Path):
    sfz = tmp_path / "low.sfz"
    sfz.write_text("<region> sample=example.wav lokey=24 hikey=42\n", encoding="utf8")
    inst = pretty_midi.Instrument(0, name="violin")
    inst.notes.append(pretty_midi.Note(70, 83, 0.0, 0.3))
    diagnostic = silent_sfz_diagnostic(inst, sfz)
    assert "notes outside: 1/1" in diagnostic
    assert "LIKELY ISSUE" in diagnostic


def test_worker_failure_path_sanitizes_group_and_reads_primary_cause(tmp_path: Path):
    report = worker_failure_path(tmp_path, "../evil/lead guitar")
    assert report.parent == tmp_path / "reports" / "group_workers"
    assert ".." not in report.name
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("group: test\nexception: RuntimeError: sample library mute\n  CC107=UNSET\n\nTraceback\n")
    cause, path = read_worker_failure(tmp_path, "../evil/lead guitar")
    assert cause == "RuntimeError: sample library mute\n  CC107=UNSET"
    assert path == report


def test_failed_phase_does_not_print_done(capsys):
    with pytest.raises(ValueError):
        with group_worker._visible_phase("lead", "render_group_audio"):
            raise ValueError("missing controller")
    stderr = capsys.readouterr().err
    assert "phase=render_group_audio FAILED" in stderr
    assert "phase=render_group_audio done" not in stderr


def test_worker_writes_reusable_diagnostic_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(group_worker, "_worker_main", lambda _cfg: (_ for _ in ()).throw(ValueError("silent")))
    cfg = SimpleNamespace(outdir=tmp_path, group="lead", spec=Path("cue.yaml"))
    with pytest.raises(ValueError, match="silent"):
        group_worker._run_with_failure_report(cfg)
    report = worker_failure_path(tmp_path, "lead")
    body = report.read_text()
    assert "exception: ValueError: silent" in body
    assert "Traceback" in body
    assert "cue.yaml" in body


def test_parent_includes_saved_worker_exception(tmp_path: Path):
    class Command:
        def run_subprocess(self, *, data):
            report = worker_failure_path(tmp_path, data["group"])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("exception: RuntimeError: SFZ controller CC107 unset\n")
            return subprocess.CompletedProcess(["python", "-m", "worker"], 1)

    plan = isolated.RenderWorkerPlan(
        spec_path=tmp_path / "score.yaml",
        outdir=tmp_path,
        backend="pretty-midi",
        render_hash="testhash",
        simple_mix=False,
        full_mix_only=False,
        profile_workers=False,
    )
    with pytest.raises(RuntimeError, match="CC107 unset") as info:
        isolated.run_worker_subprocess(Command(), plan, "lead")
    assert "render group 'lead' FAILED" in str(info.value)
    assert "group_workers/lead.failure.txt" in str(info.value)

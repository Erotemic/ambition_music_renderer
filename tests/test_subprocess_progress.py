"""Generic liveness reporting for long renderer subprocesses."""

from __future__ import annotations

import subprocess
import sys

from ambition_music_renderer.subprocess_progress import (
    communicate_with_heartbeat,
    wait_with_heartbeat,
)


def test_wait_with_heartbeat_emits_liveness():
    messages: list[str] = []
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.08)"])
    rc = wait_with_heartbeat(
        proc,
        label="test worker",
        heartbeat_s=0.02,
        emit=messages.append,
    )
    assert rc == 0
    assert messages
    assert any("test worker still running" in message for message in messages)
    assert all("pid=" in message and "elapsed=" in message for message in messages)


def test_communicate_with_heartbeat_preserves_captured_output():
    messages: list[str] = []
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys,time; print('out', flush=True); print('err', file=sys.stderr, flush=True); time.sleep(0.08)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = communicate_with_heartbeat(
        proc,
        label="test synth",
        heartbeat_s=0.02,
        emit=messages.append,
    )
    assert proc.returncode == 0
    assert stdout is not None and "out" in stdout
    assert stderr is not None and "err" in stderr
    assert messages

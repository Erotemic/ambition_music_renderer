"""The package's REAL entry point imports and answers `--help`.

⛔ WHY THIS EXISTS. The symlink-safe publisher shipped with four tests that
import ``publish_safely`` directly, and every one of them passed while
``ambition_music_renderer/cli.py`` did not parse at all: the new
``from .publish_safely import publish_copy`` had been inserted ABOVE
``from __future__ import annotations``, which Python rejects. A helper's tests
say nothing about whether the program that uses it still starts.

⇒ So this guards the entry point rather than a helper: the module compiles, the
package imports, and ``python -m ambition_music_renderer --help`` exits cleanly.
A syntax error anywhere on that import path fails here.
"""

from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_the_cli_module_parses() -> None:
    """The exact check that reproduced the break: `py_compile` on `cli.py`."""
    py_compile.compile(
        str(PACKAGE_ROOT / "ambition_music_renderer" / "cli.py"),
        doraise=True,
    )


def test_the_package_entry_point_answers_help() -> None:
    """`python -m ambition_music_renderer --help` runs the real program.

    Deliberately a SUBPROCESS on the module path, not an ``import cli``: the
    thing that was broken is what a person or a script actually invokes, and an
    in-process import can be satisfied by a module already in ``sys.modules``.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "ambition_music_renderer", "--help"],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, (
        "`python -m ambition_music_renderer --help` failed:\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "cue" in completed.stdout, (
        "the help text should name the `cue` subcommand group; got:\n"
        f"{completed.stdout}"
    )

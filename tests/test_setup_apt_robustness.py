"""`setup.sh` must survive a third-party apt repository with a bad signing key.

The failure this pins: `apt update` exits 100 when ANY repository fails (here the
sfizz OBS repository, `EXPKEYSIG ... home:sfztools OBS Project`), although every
other list refreshed, and `set -e` made that "setup failed". A keyring downloaded
on an earlier run was never looked at again, so the key stayed expired.

The fixtures put a fake `apt`, `sudo`, `curl` and `gpg` first on PATH, so nothing
is installed and nothing needs root.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPERS = ROOT / "apt_helpers.sh"
SETUP = ROOT / "setup.sh"

BAD_REPO = (
    "Err:8 https://download.opensuse.org/repositories/home:/sfztools:/sfizz/xUbuntu_24.04  InRelease\n"
    "  The following signatures were invalid: EXPKEYSIG 1DCC29D5F18761E8 home:sfztools OBS Project\n"
    "W: GPG error: https://download.opensuse.org/repositories/home:/sfztools:/sfizz/xUbuntu_24.04  InRelease: "
    "The following signatures were invalid: EXPKEYSIG 1DCC29D5F18761E8 home:sfztools OBS Project\n"
    "E: The repository 'https://download.opensuse.org/repositories/home:/sfztools:/sfizz/xUbuntu_24.04  InRelease' is not signed.\n"
)


def _script(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _fakes(tmp: Path, *, update_output: str = BAD_REPO, update_status: int = 100, key_bytes: str = "NEWKEY") -> dict:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "calls.log"
    _script(bin_dir / "sudo", 'exec "$@"\n')
    _script(
        bin_dir / "apt",
        f'echo "apt $*" >> "{log}"\n'
        'if [ "$1" = update ]; then\n'
        f"  printf '%s' '{update_output}'\n"
        f"  exit {update_status}\n"
        "fi\n",
    )
    _script(bin_dir / "curl", f'printf "{key_bytes}"\n')
    _script(bin_dir / "gpg", "cat\n")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    return {"env": env, "log": log}


def _bash(script: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f"set -euo pipefail\n. {HELPERS}\n{script}"],
        capture_output=True, text=True, env=env,
    )


def test_a_failing_apt_update_is_a_warning_that_names_the_repository(tmp_path):
    fakes = _fakes(tmp_path)
    result = _bash("apt_update_tolerant\necho survived\n", fakes["env"])
    assert result.returncode == 0, result.stderr
    assert "survived" in result.stdout
    assert "exited 100" in result.stderr
    assert "not signed" in result.stderr and "sfztools" in result.stderr


def test_a_clean_apt_update_says_nothing_alarming(tmp_path):
    fakes = _fakes(tmp_path, update_output="Reading package lists... Done\n", update_status=0)
    result = _bash("apt_update_tolerant\n", fakes["env"])
    assert result.returncode == 0 and "warning" not in result.stderr


def test_a_repository_that_fails_on_its_signature_is_switched_off_not_deleted(tmp_path):
    fakes = _fakes(tmp_path)
    listing = tmp_path / "sfizz.list"
    listing.write_text("deb [signed-by=/x] https://example.invalid /\n")
    result = _bash(f'apt_update_tolerant >/dev/null 2>&1\ndisable_apt_repo_if_unsigned "{listing}" sfztools\n', fakes["env"])
    assert result.returncode == 0, result.stderr
    assert not listing.exists() and (tmp_path / "sfizz.list.disabled").exists()


def test_a_failure_in_some_other_repository_is_not_blamed_on_ours(tmp_path):
    other = "E: The repository 'https://ppa.example/ubuntu noble InRelease' is not signed.\n"
    fakes = _fakes(tmp_path, update_output=other)
    listing = tmp_path / "sfizz.list"
    listing.write_text("deb https://example.invalid /\n")
    result = _bash(f'apt_update_tolerant >/dev/null 2>&1\ndisable_apt_repo_if_unsigned "{listing}" sfztools || echo kept\n', fakes["env"])
    assert listing.exists() and "kept" in result.stdout


def test_a_stale_keyring_is_replaced_by_the_vendors_current_key(tmp_path):
    fakes = _fakes(tmp_path, key_bytes="NEWKEY")
    keyring = tmp_path / "k.gpg"
    keyring.write_text("EXPIREDKEY")
    result = _bash(f'refresh_apt_keyring https://example.invalid/Release.key "{keyring}"\n', fakes["env"])
    assert result.returncode == 0, result.stderr
    assert keyring.read_text() == "NEWKEY"
    assert "Refreshing" in result.stdout


def test_an_unreachable_key_server_keeps_the_existing_keyring(tmp_path):
    fakes = _fakes(tmp_path)
    _script(tmp_path / "bin" / "curl", "exit 22\n")
    keyring = tmp_path / "k.gpg"
    keyring.write_text("EXISTING")
    result = _bash(f'refresh_apt_keyring https://example.invalid/Release.key "{keyring}"\n', fakes["env"])
    assert result.returncode == 0, result.stderr
    assert keyring.read_text() == "EXISTING"
    assert "could not download" in result.stderr


def test_apt_ensure_installs_after_a_failed_update(tmp_path):
    """The shipped function under `set -euo pipefail`: the update fails with 100
    and the install still runs, which is the sequence that used to abort."""
    fakes = _fakes(tmp_path)
    _script(tmp_path / "bin" / "dpkg-query", "exit 1\n")  # nothing is installed
    text = SETUP.read_text()
    function = re.search(r"^apt_ensure\(\)\{.*?^\}\n", text, re.S | re.M).group(0)
    result = _bash(function + "\nUPDATE=1 apt_ensure somepkg\necho done\n", fakes["env"])
    assert result.returncode == 0, result.stderr
    calls = fakes["log"].read_text().splitlines()
    assert "apt update -y" in calls and any(c.startswith("apt install") and "somepkg" in c for c in calls), calls
    assert "done" in result.stdout


def test_setup_no_longer_trusts_an_existing_keyring_without_looking():
    text = SETUP.read_text()
    assert "Already have sfizz OBS keyring" not in text
    assert "refresh_apt_keyring" in text and "apt_update_tolerant" in text
    assert not re.search(r"^\s*(\$\{_SUDO:\+\$_SUDO\}\s+)?apt update -y\s*$", text, re.M), "a bare fatal apt update is back"


def test_the_status_variables_exist_even_when_the_update_ran_in_a_subshell(tmp_path):
    """`apt_update_tolerant | tail` runs in a subshell; a caller under `set -u`
    must read an empty answer rather than die on an unbound variable."""
    fakes = _fakes(tmp_path)
    result = _bash(
        'apt_update_tolerant 2>&1 | tail -1 >/dev/null\n'
        'echo "status=$APT_UPDATE_STATUS output=[${APT_UPDATE_OUTPUT}]"\n'
        'disable_apt_repo_if_unsigned /nonexistent sfztools || echo not-disabled\n',
        fakes["env"],
    )
    assert result.returncode == 0, result.stderr
    assert "status=0 output=[]" in result.stdout and "not-disabled" in result.stdout

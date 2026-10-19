"""FreePats FSBS #1 catalog and download mechanics, without live network calls.

Tests exercise a general sampled-library integration; they do not snapshot any
specific composition or rendered cue.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import zipfile
from pathlib import Path

from ambition_music_renderer.instrument_catalog import describe_instrument, sfz_smoke_profile_specs
from ambition_music_renderer.instrument_libraries import resolve_sfz_reference


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "download_ambition_audio_tools.sh"
SOURCE_REF = "bbae17f0ad16f5edd7ec22178d181f3e3f6696fa"
RELEASE_SHA256 = "86715a19fc8da8e9145203be9457d99476c0fe896a64f2adf21e184519302b14"


def _shell_func(script: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", script, re.MULTILINE | re.DOTALL)
    assert match, f"missing shell function {name}"
    return match.group(0)


def _bash(tmp_path: Path, script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + script],
        cwd=tmp_path,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


def test_fsbs_catalog_registration_and_sampled_library_resolution(tmp_path: Path):
    info = describe_instrument("guitar.fsbs_distorted_1")
    assert info["musicir"] == {
        "instrument_backend": {"kind": "sfz", "library_ref": "guitar.fsbs_distorted_1"},
    }
    assert info["source_info"]["license"] == "CC0-1.0"
    assert info["source_info"]["expected"] is False
    assert info["expected"] is False
    assert info["source_info"]["install_profile"] == "pro"
    assert info["source_info"]["relative_root"] == "sfz/FreePats/FSBSDistorted1"
    assert any(row["name"] == "freepats_fsbs_distorted_1" for row in sfz_smoke_profile_specs())

    sfz_root = tmp_path / "sfz"
    fsbs = sfz_root / "FreePats" / "FSBSDistorted1" / "EGuitarFSBS-dist1 bridge 20220911.sfz"
    elsewhere = sfz_root / "FreePats" / "Elsewhere" / "EGuitarFSBS-dist1 bridge 20220911.sfz"
    dist2 = sfz_root / "FreePats" / "FSBSDistorted2" / "EGuitarFSBS-dist2 bridge 20220911.sfz"
    for path in (fsbs, elsewhere, dist2):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<group>\n", encoding="utf8")

    assert resolve_sfz_reference(library_ref="guitar.fsbs_distorted_1", roots=[sfz_root]) == fsbs.resolve()


def test_fsbs_upstream_archive_is_pinned_and_download_has_automatic_fallback():
    script = INSTALLER.read_text(encoding="utf8")
    assert "https://github.com/freepats/electric-guitar-FSBS-dist1/releases/download/2022-09-11/" in script
    assert "EGuitarFSBS-dist1-SFZ%2BFLAC-20220911.7z" in script
    assert RELEASE_SHA256 in script
    assert f"source_ref=\"{SOURCE_REF}\"" in script
    assert "https://codeload.github.com/freepats/electric-guitar-FSBS-dist1/zip/$source_ref" in script
    # Both formats contain the actual SFZ and recordings, not a GM soundfont.
    assert "SFZ/FLAC" in _shell_func(script, "install_freepats_fsbs_distorted_1")


def test_archive_sha256_mismatch_is_discarded_before_extraction(tmp_path: Path):
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as zip_file:
        zip_file.writestr("content.sfz", "<group>\n")
    actual_digest = hashlib.sha256(source.read_bytes()).hexdigest()

    installer = INSTALLER.read_text(encoding="utf8")
    downloader = _shell_func(installer, "download_and_extract")
    common = """
DRY_RUN=0
ARCHIVES="$PWD/archives"
mkdir -p "$ARCHIVES"
log() { :; }
already_extracted() { return 1; }
download() { cp "$SOURCE_ZIP" "$2"; }
extract_archive() { mkdir -p "$2"; unzip -q "$1" -d "$2"; }
"""
    env = {"SOURCE_ZIP": str(source)}
    bad = _bash(tmp_path, common + downloader + '\nif download_and_extract "test" unused test.zip target "' + "0" * 64 + '"; then exit 99; fi\n', env=env)
    assert bad.returncode == 0, bad.stderr
    assert not (tmp_path / "archives" / "test.zip").exists()
    assert not (tmp_path / "target" / "content.sfz").exists()

    good = _bash(tmp_path, common + downloader + '\ndownload_and_extract "test" unused test.zip target "' + actual_digest + '"\n', env=env)
    assert good.returncode == 0, good.stderr
    assert (tmp_path / "target" / "content.sfz").is_file()


def test_fsbs_fallback_accepts_complete_sfzs_and_flacs(tmp_path: Path):
    installer = INSTALLER.read_text(encoding="utf8")
    functions = "\n".join(
        _shell_func(installer, name)
        for name in ("freepats_fsbs_distorted_1_complete", "install_freepats_fsbs_distorted_1")
    )
    shell = """
DRY_RUN=0
SFZ_ROOT="$PWD/sfz"
log() { :; }
download_and_extract_optional() {
    echo "$3" >> "$PWD/downloads.txt"
    case "$3" in
      *.7z) return 1 ;;  # simulate failed release / missing 7z extractor
      *.zip)
        mkdir -p "$4/snapshot/samples/bridge"
        printf '<group>\\n' > "$4/snapshot/EGuitarFSBS-dist1 bridge 20220911.sfz"
        for i in $(seq 1 120); do : > "$4/snapshot/samples/bridge/$i.flac"; done
        return 0 ;;
    esac
    return 1
}
"""
    result = _bash(tmp_path, shell + functions + "\ninstall_freepats_fsbs_distorted_1\n")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "downloads.txt").read_text().splitlines()
    assert calls == ["EGuitarFSBS-dist1-SFZ+FLAC-20220911.7z", "freepats-fsbs-dist1-bbae17f0.zip"]
    assert (tmp_path / "sfz" / "FreePats" / "FSBSDistorted1" / "snapshot" / "EGuitarFSBS-dist1 bridge 20220911.sfz").is_file()

    again = _bash(tmp_path, shell + functions + "\ninstall_freepats_fsbs_distorted_1\n")
    assert again.returncode == 0
    assert (tmp_path / "downloads.txt").read_text().splitlines() == calls


def test_incomplete_download_is_not_registered_as_a_complete_instrument(tmp_path: Path):
    path = tmp_path / "sfz"
    path.mkdir()
    (path / "EGuitarFSBS-dist1 bridge 20220911.sfz").write_text("<group>\n")
    script = _shell_func(INSTALLER.read_text(), "freepats_fsbs_distorted_1_complete")
    proc = _bash(tmp_path, script + '\nfreepats_fsbs_distorted_1_complete "$PWD/sfz"\n')
    assert proc.returncode != 0

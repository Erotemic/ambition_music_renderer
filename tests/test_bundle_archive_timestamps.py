"""Regressions for source-file dates unsupported by the ZIP format."""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from ambition_music_renderer.render.bundle_archive import make_zip


def test_make_zip_clamps_pre_1980_mtimes_without_changing_source_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        bundle = root / "cue_hash_bundle"
        (bundle / "reports").mkdir(parents=True)
        old_report = bundle / "reports" / "report.txt"
        old_report.write_text("old timestamp, valid content", encoding="utf8")
        audio = bundle / "full.ogg"
        audio.write_bytes(b"ogg")

        # Reproduces files dated 1970-01-01 (common with imported assets).
        os.utime(old_report, (0, 0))
        original_mtime_ns = old_report.stat().st_mtime_ns

        for report_only in (False, True):
            zip_path = make_zip(
                bundle,
                root / ("report.zip" if report_only else "full.zip"),
                report_only=report_only,
            )
            with zipfile.ZipFile(zip_path) as zf:
                info = zf.getinfo("cue_hash_bundle/reports/report.txt")
                assert info.date_time[:3] == (1980, 1, 1)
                assert zf.read(info) == b"old timestamp, valid content"
                assert ("cue_hash_bundle/full.ogg" in zf.namelist()) is not report_only
                assert zf.testzip() is None

            # Source metadata must remain untouched; only the ZIP date is clamped.
            assert old_report.stat().st_mtime_ns == original_mtime_ns

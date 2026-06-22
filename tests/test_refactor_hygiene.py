from __future__ import annotations

from pathlib import Path


def test_render_package_has_no_dynamic_import_shims() -> None:
    root = Path(__file__).resolve().parents[1] / "ambition_music_renderer" / "render"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf8")
        if "globals().update" in text:
            offenders.append(f"{rel}: globals().update")
        if "import *" in text:
            offenders.append(f"{rel}: import *")
    assert not offenders


def test_removed_compatibility_facades_stay_removed() -> None:
    root = Path(__file__).resolve().parents[1] / "ambition_music_renderer" / "render"
    removed = ["score.py", "musicir_renderer.py", "bundle_reports.py"]
    assert not [name for name in removed if (root / name).exists()]

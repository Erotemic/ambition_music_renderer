"""Starter-score creation from the checked-in MusicIR v3 template."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
import re


def cue_id_slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip()).strip("_").lower()
    if not text:
        raise ValueError("cue name must contain at least one letter or number")
    return text


def template_text() -> str:
    return resources.files("ambition_music_renderer").joinpath("data/musicir_v3_new.music.yaml").read_text(encoding="utf8")


def render_v3_starter(name: str) -> tuple[str, str]:
    cue_id = cue_id_slug(name)
    text = template_text()
    text = text.replace("id: new_v3_cue", f"id: {cue_id}")
    text = text.replace("title: New MusicIR v3 cue", f"title: {json.dumps(str(name))}")
    return cue_id, text


def write_v3_starter(name: str, output: str | Path | None = None, *, force: bool = False) -> Path:
    cue_id, text = render_v3_starter(name)
    path = Path(output) if output is not None else Path(f"{cue_id}.music.yaml")
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path}; pass force=True")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path

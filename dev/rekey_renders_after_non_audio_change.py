#!/usr/bin/env python3
"""Carry each cue's current render over to a new render fingerprint, when the
only thing that changed is the renderer's code hash and the code that changed
cannot affect audio.

A render is keyed by its dependency fingerprint, which includes a hash of the
renderer's source (`renderer_implementation_identity`). Changing which modules
that hash covers (2026-10-30: orchestration and fingerprint modules left it,
`_NON_AUDIO_MODULES`) changes every fingerprint, and the next publish would
re-render the whole catalogue (about 2.5 hours on 6 workers) to reproduce the
same audio. This moves a render to its new key only when:

- everything in its recorded dependencies except `renderer_implementation`
  equals what the fingerprint computes now (score, instruments by content,
  settings, environment), and
- its recorded code hash is one of `--from-code`: a code state shown to have
  the same audio modules as the current tree (compute it from the commit's
  files with the old hashing, as in the commit that added this tool).

The new run directory is hard links of the old (only text files that name the
old key are rewritten, as new files), `latest` is pointed at it, and the old
directory is left as it was.

    source /data/audio-tools/env.sh
    python dev/rekey_renders_after_non_audio_change.py --from-code 1c3de5ab34595af9 [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

TEXT_SUFFIXES = {".json", ".yaml", ".yml", ".sh", ".txt", ".md"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-code", action="append", required=True, help="a recorded renderer code hash (16+ hex) known to be audio-equivalent")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    import regen_music_registry as registry
    from ambition_music_renderer.cli import find_latest_manifest, find_score, generated_root, resolve_latest_generated_dir
    from ambition_music_renderer.render.dependencies import dependency_scan
    from ambition_music_renderer.render.generated_layout import GeneratedRunLayout, compute_score_render_dependencies, replace_directory_symlink

    moved, current, refused = [], [], []
    with dependency_scan():
        for cue in registry.generation_cues():
            new = compute_score_render_dependencies(find_score(cue), "pretty-midi")
            manifest_path = find_latest_manifest(resolve_latest_generated_dir(generated_root() / cue), cue)
            if manifest_path is None:
                refused.append((cue, "no render"))
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf8"))
            recorded = manifest.get("render_dependencies") or {}
            if recorded.get("fingerprint") == new.fingerprint:
                current.append(cue)
                continue
            payload = recorded.get("dependencies") or {}
            code = (payload.get("renderer_implementation") or {}).get("fingerprint", "")
            if not any(code.startswith(prefix) for prefix in args.from_code):
                refused.append((cue, f"recorded code {code[:16]} is not a known audio-equivalent state"))
                continue
            without_code = lambda p: {k: v for k, v in p.items() if k != "renderer_implementation"}
            if without_code(payload) != json.loads(json.dumps(without_code(new.payload))):
                refused.append((cue, "its inputs changed: it needs a real render"))
                continue
            old_dir = manifest_path.parent
            old_short, new_short = recorded["short_hash"], new.short_hash
            if old_dir.name != old_short:
                refused.append((cue, f"render directory {old_dir.name} is not named by its key"))
                continue
            layout = GeneratedRunLayout(cue_dir=generated_root() / cue, hash_id=new_short)
            if layout.run_dir.exists():
                refused.append((cue, f"{layout.run_dir} already exists"))
                continue
            moved.append(cue)
            if not args.apply:
                continue
            for path in sorted(old_dir.rglob("*")):
                rel = Path(*(part.replace(old_short, new_short) for part in path.relative_to(old_dir).parts))
                target = layout.run_dir / rel
                if path.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                text = None
                if path.suffix in TEXT_SUFFIXES:
                    text = path.read_text(encoding="utf8", errors="surrogateescape")
                if text is not None and (old_short in text or recorded["fingerprint"] in text):
                    if path == manifest_path:
                        data = json.loads(text)
                        data["render_dependencies"] = new.manifest_payload()
                        text = json.dumps(data, indent=2, sort_keys=False)
                    text = text.replace(recorded["fingerprint"], new.fingerprint).replace(old_short, new_short)
                    target.write_text(text, encoding="utf8", errors="surrogateescape")
                    shutil.copystat(path, target)
                else:
                    os.link(path, target)
            replace_directory_symlink(layout.latest_link, layout.run_dir)

    verb = "moved" if args.apply else "would move"
    print(f"{verb} {len(moved)}; already current {len(current)}; refused {len(refused)}")
    for cue, why in refused:
        print(f"  refused {cue}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

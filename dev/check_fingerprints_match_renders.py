#!/usr/bin/env python3
"""Does every cue's render fingerprint, computed now, equal the one its
latest render recorded? And how long does computing them all take?

A change to how the fingerprint is computed (a cache, a faster parser) must
not change what a fingerprint says about a cue: its score, instruments,
settings and environment. Edits to hashed renderer source change every
fingerprint by design, so each cue is also compared with that one entry
(`renderer_implementation`) taken out. Run it after such a change, on a
machine whose renders are current:

    source /data/audio-tools/env.sh
    python dev/check_fingerprints_match_renders.py [--jobs 1]

It also checks each SFZ glob pattern the scores use resolves to the same
program as a fresh `Path.glob` walk of the library roots.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))


def main() -> int:
    import regen_music_registry as registry
    from ambition_music_renderer import instrument_libraries as libraries
    from ambition_music_renderer.cli import find_latest_manifest, find_score, generated_root, resolve_latest_generated_dir
    from ambition_music_renderer.render.dependencies import dependency_scan
    from ambition_music_renderer.render.generated_layout import compute_score_render_dependencies

    patterns: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    cached = libraries._resolve_sfz_glob_cached

    def recording(pattern, prefer, root_keys):
        patterns.add((pattern, prefer, root_keys))
        return cached(pattern, prefer, root_keys)

    libraries._resolve_sfz_glob_cached = recording

    cues = registry.generation_cues()
    mismatched, unrendered, code_only = [], [], []
    started = time.time()
    with dependency_scan():
        for cue in cues:
            current = compute_score_render_dependencies(find_score(cue), "pretty-midi")
            manifest = find_latest_manifest(resolve_latest_generated_dir(generated_root() / cue), cue)
            recorded = json.loads(manifest.read_text()).get("render_dependencies", {}) if manifest else {}
            if not recorded.get("fingerprint"):
                unrendered.append(cue)
            elif recorded["fingerprint"] != current.fingerprint:
                without_code = lambda payload: {k: v for k, v in payload.items() if k != "renderer_implementation"}
                if without_code(recorded.get("dependencies") or {}) == json.loads(json.dumps(without_code(current.payload))):
                    code_only.append(cue)
                else:
                    mismatched.append(cue)
    elapsed = time.time() - started

    glob_differs = []
    for pattern, prefer, root_keys in sorted(patterns):
        walked = [
            path.resolve()
            for key in root_keys
            if Path(key).exists()
            for path in Path(key).glob(pattern)
        ]
        walked = [p for p in walked if p.is_file() and p.suffix.lower() == ".sfz" and not libraries.is_transient_sfz_wrapper(p)]
        roots = [Path(key) for key in root_keys]
        expected = sorted(walked, key=lambda p: (-libraries._score_candidate(p, alias=None, prefer=prefer, roots=roots), str(p)))[:1]
        got = cached(pattern, prefer, root_keys)
        if (expected[0] if expected else None) != got:
            glob_differs.append((pattern, expected, got))

    print(f"{len(cues)} cues fingerprinted in {elapsed:.1f} s ({elapsed / max(1, len(cues)):.2f} s each)")
    print(f"matching their latest render: {len(cues) - len(mismatched) - len(unrendered) - len(code_only)}; "
          f"differing only in the renderer code's hash: {len(code_only)}; differing in anything else: {len(mismatched)}; "
          f"no render: {len(unrendered)}")
    for cue in mismatched:
        print(f"  DIFFERS {cue}")
    for cue in unrendered:
        print(f"  no render: {cue}")
    print(f"glob patterns checked against a fresh walk: {len(patterns)}; differing: {len(glob_differs)}")
    for row in glob_differs:
        print(f"  GLOB DIFFERS {row}")
    return int(bool(mismatched or glob_differs))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Internal isolated worker for one MusicIR stem.

This keeps long production renders robust by resetting Python/SciPy/FFmpeg state
between stems. It is intentionally a small command invoked by render_isolated.py.
"""

from __future__ import annotations
import argparse, json, math, os, sys, tempfile
from pathlib import Path
import numpy as np
import yaml
from . import musicir_renderer as r
from .profiler import PhaseTimer, profile


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--group", required=True)
    ap.add_argument("--backend", default="pretty-midi")
    ap.add_argument(
        "--skip-section-ogg",
        action="store_true",
        help=(
            "Skip writing per-section per-group OGGs. The temporary .npy "
            "stem buffer is still written (the parent process needs it to "
            "mix the mastered preview and/or per-section full mixes). Used "
            "by render_isolated --simple-mix / --full-mix-only to remove "
            "unused encoded outputs from the render budget."
        ),
    )
    ap.add_argument("--profile-out", type=Path, default=None, help="deprecated compatibility flag; use LINE_PROFILE=1 with line_profiler instead")
    ap.add_argument("--timings-out", type=Path, default=None, help="write worker phase timings to JSON")
    return ap


@profile
def _worker_main(ns: argparse.Namespace) -> int:
    timings = PhaseTimer()
    spec_path = Path(ns.spec)
    with timings.phase("load_spec_and_build_score"):
        spec = yaml.safe_load(spec_path.read_text())
        render_cfg = spec.get("render", {})
        sr = int(render_cfg.get("sample_rate", 48000))
        bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
        soundfont = r.choose_soundfont(render_cfg.get("soundfont"))
        cue_hash = r.spec_hash(spec_path, soundfont, ns.backend)
        quality = float(render_cfg.get("ogg_quality", 5.0))
        pm, groups, meta = r.build_score(spec)
        cue_metadata = r.section_chapter_metadata(
            cue_id=str(spec.get("id", spec_path.stem)),
            title=str(spec.get("title", spec.get("id", spec_path.stem))),
            sections=r.timeline_markers_from_spec(spec, meta),
        )
    total = meta[-1]["end_seconds"]
    target = int(math.ceil(total * sr))
    outdir = Path(ns.outdir)
    with tempfile.TemporaryDirectory() as td:
        with timings.phase("render_group_audio", group=ns.group, backend=ns.backend):
            raw = r.render_group_audio(
                pm, groups, ns.group, ns.backend, soundfont, sr, Path(td), total, bpm
            )
        with timings.phase("postprocess_group", group=ns.group):
            raw = r.ensure_audio_length(raw, target)
            settings = dict(spec.get("stem_postprocess", {}) or {})
            settings.update((spec.get("group_postprocess", {}) or {}).get(ns.group, {}))
            settings.setdefault("normalize", False)
            settings.setdefault("target_peak_db", -2.5)
            audio = r.post_process(raw, sr, settings)
    with timings.phase("write_scratch_npy", group=ns.group):
        npy = outdir / "scratch_stems" / f"{spec['id']}_{cue_hash}.{ns.group}.npy"
        npy.parent.mkdir(parents=True, exist_ok=True)
        np.save(npy, audio.astype("float32"))
    files = {}
    if not ns.skip_section_ogg:
        with timings.phase("write_section_oggs", group=ns.group, sections=len(meta)):
            for sec in meta:
                piece = r.slice_audio(audio, sr, sec["start_seconds"], sec["end_seconds"])
                path = (
                    outdir
                    / "adaptive"
                    / sec["id"]
                    / f"{spec['id']}_{cue_hash}.{sec['id']}.{ns.group}.ogg"
                )
                section_metadata = dict(cue_metadata)
                section_metadata.update(
                    r.section_chapter_metadata(
                        cue_id=str(spec.get("id", spec_path.stem)),
                        title=f"{spec.get('title', spec.get('id', spec_path.stem))} — {sec['id']} — {ns.group}",
                        section_id=str(sec["id"]),
                        section_start_s=float(sec.get("start_seconds", 0.0)),
                        section_end_s=float(sec.get("end_seconds", 0.0)),
                    )
                )
                section_metadata["STEM_GROUP"] = ns.group
                r.write_ogg_from_audio(piece, sr, path, quality=quality, keep_wav=False, metadata=section_metadata)
                files[sec["id"]] = str(path.relative_to(outdir))
    if ns.timings_out is not None:
        timings.write_json(ns.timings_out)
        timings.write_tsv(ns.timings_out.with_suffix(".tsv"))
        timings.write_summary(ns.timings_out.with_suffix(".txt"))
    print(
        json.dumps(
            {"group": ns.group, "npy": str(npy), "files": files, "hash": cue_hash}
        )
    )
    return 0


@profile
def main(argv=None) -> int:
    import time as _time

    total_start = _time.perf_counter()
    rc = 1
    try:
        ap = build_parser()
        ns = ap.parse_args(argv)
        if ns.profile_out is not None:
            print("render_group_worker: --profile-out is deprecated; use LINE_PROFILE=1 for line_profiler", file=sys.stderr)
        rc = _worker_main(ns)
        return rc
    finally:
        elapsed = _time.perf_counter() - total_start
        print(f"[ambition_music_renderer.render_group_worker] total_elapsed_s={elapsed:.3f}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

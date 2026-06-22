#!/usr/bin/env python3
"""Internal isolated worker for one MusicIR stem.

This keeps long production renders robust by resetting Python/SciPy/FFmpeg state
between stems. It is intentionally a small command invoked by render_isolated.py.
"""

from __future__ import annotations
import json
import math
import sys
import tempfile
from pathlib import Path
import kwconf
import numpy as np
import yaml
from .effects import post_process
from .export import section_chapter_metadata, timeline_markers_from_spec, write_ogg_from_audio
from .group import ensure_audio_length, render_group_audio, slice_audio
from .score_core import choose_soundfont
from .score_layers import build_score
from .synth import spec_hash
from ..profiler import PhaseTimer, profile


class RenderGroupWorkerConfig(kwconf.Config):
    """kwconf-backed config for one isolated/in-process render group."""


    spec: Path = kwconf.Value(None, position=1, parser=Path, help="MusicIR YAML spec")
    outdir: Path = kwconf.Value(None, parser=Path, required=True, help="render output directory")
    group: str = kwconf.Value(None, required=True, help="stem/group name to render")
    backend: str = kwconf.Value("pretty-midi", help="renderer backend")
    skip_section_ogg: bool = kwconf.Flag(
        False,
        help=(
            "Skip writing per-section per-group OGGs. The temporary .npy stem "
            "buffer is still written for parent full-mix assembly."
        ),
    )
    profile_out: Path | None = kwconf.Value(
        None,
        parser=Path,
        help="deprecated compatibility flag; use LINE_PROFILE=1 with line_profiler instead",
    )
    timings_out: Path | None = kwconf.Value(None, parser=Path, help="write worker phase timings to JSON")
    json: bool = kwconf.Flag(False, help="print worker JSON payload to stdout")

    def __post_init__(self) -> None:
        for key in ("spec", "outdir", "profile_out", "timings_out"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        if config.profile_out is not None:
            print("render_group_worker: --profile-out is deprecated; use LINE_PROFILE=1 for line_profiler", file=sys.stderr)
        return _worker_main(config)





@profile
def _worker_main(ns) -> int:
    timings = PhaseTimer()
    spec_path = Path(ns.spec)
    with timings.phase("load_spec_and_build_score"):
        spec = yaml.safe_load(spec_path.read_text())
        render_cfg = spec.get("render", {})
        sr = int(render_cfg.get("sample_rate", 48000))
        bpm = float(spec.get("tempo", {}).get("bpm", spec.get("bpm", 120)))
        soundfont = choose_soundfont(render_cfg.get("soundfont"))
        cue_hash = spec_hash(spec_path, soundfont, ns.backend)
        quality = float(render_cfg.get("ogg_quality", 5.0))
        pm, groups, meta = build_score(spec)
        cue_metadata = section_chapter_metadata(
            cue_id=str(spec.get("id", spec_path.stem)),
            title=str(spec.get("title", spec.get("id", spec_path.stem))),
            sections=timeline_markers_from_spec(spec, meta),
        )
    total = meta[-1]["end_seconds"]
    target = int(math.ceil(total * sr))
    outdir = Path(ns.outdir)
    with tempfile.TemporaryDirectory() as td:
        with timings.phase("render_group_audio", group=ns.group, backend=ns.backend):
            raw = render_group_audio(
                pm, groups, ns.group, ns.backend, soundfont, sr, Path(td), total, bpm
            )
        with timings.phase("postprocess_group", group=ns.group):
            raw = ensure_audio_length(raw, target)
            settings = dict(spec.get("stem_postprocess", {}) or {})
            settings.update((spec.get("group_postprocess", {}) or {}).get(ns.group, {}))
            settings.setdefault("normalize", False)
            settings.setdefault("target_peak_db", -2.5)
            audio = post_process(raw, sr, settings)
    with timings.phase("write_scratch_npy", group=ns.group):
        npy = outdir / "scratch_stems" / f"{spec['id']}_{cue_hash}.{ns.group}.npy"
        npy.parent.mkdir(parents=True, exist_ok=True)
        np.save(npy, audio.astype("float32"))
    files = {}
    if not ns.skip_section_ogg:
        with timings.phase("write_section_oggs", group=ns.group, sections=len(meta)):
            for sec in meta:
                piece = slice_audio(audio, sr, sec["start_seconds"], sec["end_seconds"])
                path = (
                    outdir
                    / "adaptive"
                    / sec["id"]
                    / f"{spec['id']}_{cue_hash}.{sec['id']}.{ns.group}.ogg"
                )
                section_metadata = dict(cue_metadata)
                section_metadata.update(
                    section_chapter_metadata(
                        cue_id=str(spec.get("id", spec_path.stem)),
                        title=f"{spec.get('title', spec.get('id', spec_path.stem))} — {sec['id']} — {ns.group}",
                        section_id=str(sec["id"]),
                        section_start_s=float(sec.get("start_seconds", 0.0)),
                        section_end_s=float(sec.get("end_seconds", 0.0)),
                    )
                )
                section_metadata["STEM_GROUP"] = ns.group
                write_ogg_from_audio(piece, sr, path, quality=quality, keep_wav=False, metadata=section_metadata)
                files[sec["id"]] = str(path.relative_to(outdir))
    if ns.timings_out is not None:
        timings.write_json(ns.timings_out)
        timings.write_tsv(ns.timings_out.with_suffix(".tsv"))
        timings.write_summary(ns.timings_out.with_suffix(".txt"))
    if getattr(ns, "json", False):
        print(
            json.dumps(
                {"group": ns.group, "npy": str(npy), "files": files, "hash": cue_hash}
            )
        )
    return 0


def render_group_worker_main(
    argv: list[str] | str | bool | None = None,
    *,
    cmdline: bool | None = None,
    **kwargs: object,
) -> int:
    """kwconf-backed Python/CLI entrypoint for one render group."""
    if cmdline is False:
        argv = False
    elif cmdline is True and argv is None:
        argv = True
    config = RenderGroupWorkerConfig.cli(argv=argv, data=kwargs)
    if config.profile_out is not None:
        print("render_group_worker: --profile-out is deprecated; use LINE_PROFILE=1 for line_profiler", file=sys.stderr)
    return _worker_main(config)


@profile
def main(argv=None) -> int:
    import time as _time

    total_start = _time.perf_counter()
    rc = 1
    try:
        rc = render_group_worker_main(argv=argv)
        return rc
    finally:
        elapsed = _time.perf_counter() - total_start
        print(f"[ambition_music_renderer.render.group_worker] total_elapsed_s={elapsed:.3f}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

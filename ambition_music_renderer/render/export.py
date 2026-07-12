"""Audio export, metadata, and timeline helpers for MusicIR renders."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from ..profiler import profile
from ..audio_utils import coerce_stereo
from .score_core import TempoMap

def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same sanitize as the OGG path: a NaN reaching PCM16 becomes garbage, and
    # the debug WAV should not differ from the OGG written beside it.
    pcm = np.nan_to_num(
        np.clip(coerce_stereo(audio), -1.0, 1.0), nan=0.0, posinf=0.0, neginf=0.0
    ).astype(np.float32, copy=False)
    sf.write(path, pcm, sample_rate, subtype="PCM_16")


def format_ogg_timestamp(seconds: float) -> str:
    """Return an OGM/Vorbis chapter timestamp like ``HH:MM:SS.mmm``."""
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, millis = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def ogg_metadata_args(metadata: dict[str, object] | None) -> list[str]:
    args: list[str] = []
    if not metadata:
        return args
    for key, value in metadata.items():
        if value is None:
            continue
        key_s = str(key).strip()
        if not key_s:
            continue
        args.extend(["-metadata", f"{key_s}={value}"])
    return args


def write_metadata_sidecar(ogg_path: Path, metadata: dict[str, object] | None) -> Path | None:
    """Write a small sidecar recording the metadata we attempted to embed.

    OGG/Vorbis chapter display varies by player.  The audio file gets Vorbis
    comments when ffmpeg supports them; this sidecar makes the render report
    auditable even when a player hides those comments.
    """
    if not metadata:
        return None
    try:
        sidecar = ogg_path.with_name(ogg_path.name + ".metadata.json")
        sidecar.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf8")
        return sidecar
    except Exception as ex:
        print(
            f"[ambition_music_renderer] could not write metadata sidecar for {ogg_path.name}: {ex}",
            file=sys.stderr,
        )
        return None


def timeline_markers_from_spec(
    spec: dict[str, Any],
    sections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return section/form markers suitable for OGG chapter comments.

    The default markers are section starts.  Cues may also define
    ``render.metadata_markers`` / ``render.markers`` entries with ``bar`` or
    ``seconds`` and an ``id``/``label``.  This lets long one-section pieces
    such as Emmy Extended expose A/B/return form markers even though the game
    still treats them as one loop component.
    """
    beats_per_bar = float(spec.get("meter", {}).get("beats_per_bar", 4))
    tempo = TempoMap.from_spec(spec)

    def bar_to_seconds(bar0: float) -> float:
        return tempo.beat_to_time(bar0 * beats_per_bar)
    markers: list[dict[str, Any]] = []
    for section in sections or []:
        sid = str(section.get("id", f"section_{len(markers)+1}"))
        label = str(section.get("label", sid))
        markers.append({
            "id": sid,
            "label": label,
            "start_seconds": float(section.get("start_seconds", 0.0) or 0.0),
            "kind": str(section.get("kind", "section")),
        })
    render_cfg = spec.get("render", {}) or {}
    explicit = render_cfg.get("metadata_markers", render_cfg.get("markers", []))
    if isinstance(explicit, list):
        for idx, item in enumerate(explicit, start=1):
            if not isinstance(item, dict):
                continue
            if "seconds" in item:
                start_s = float(item.get("seconds") or 0.0)
            elif "time_seconds" in item:
                start_s = float(item.get("time_seconds") or 0.0)
            elif "bar" in item:
                # Bar values are 1-based for human readability in YAML.
                start_s = max(0.0, bar_to_seconds(float(item.get("bar") or 1.0) - 1.0))
            elif "start_bar" in item:
                # start_bar remains 0-based for code-generated markers.
                start_s = max(0.0, bar_to_seconds(float(item.get("start_bar") or 0.0)))
            else:
                continue
            marker_id = str(item.get("id", item.get("name", f"marker_{idx}")))
            label = str(item.get("label", marker_id))
            markers.append({
                "id": marker_id,
                "label": label,
                "start_seconds": start_s,
                "kind": str(item.get("kind", "form_marker")),
            })
    # De-duplicate exact same id/time pairs and sort by time.
    seen: set[tuple[str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for marker in sorted(markers, key=lambda m: (float(m.get("start_seconds", 0.0)), str(m.get("id", "")))):
        key = (str(marker.get("id", "")), round(float(marker.get("start_seconds", 0.0)), 3))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(marker)
    return deduped


def section_chapter_metadata(
    *,
    cue_id: str,
    title: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    section_id: str | None = None,
    section_start_s: float | None = None,
    section_end_s: float | None = None,
) -> dict[str, object]:
    """Build Vorbis comments that VLC and tag tools can use as breadcrumbs.

    OGG/Vorbis does not have one universal chapter standard, but VLC and
    several tag readers understand the common ``CHAPTER001`` /
    ``CHAPTER001NAME`` Vorbis-comment convention.  We also write plain
    ``CUE_ID``/``SECTION_ID`` fields so the runtime asset can be traced even
    when a player ignores chapters.
    """
    meta: dict[str, object] = {
        "TITLE": title or cue_id,
        "ARTIST": "Ambition MusicIR",
        "ALBUM": "Ambition generated music",
        "CUE_ID": cue_id,
    }
    if section_id is not None:
        meta["SECTION_ID"] = section_id
    if section_start_s is not None:
        meta["SECTION_START"] = format_ogg_timestamp(float(section_start_s))
    if section_end_s is not None:
        meta["SECTION_END"] = format_ogg_timestamp(float(section_end_s))
    for idx, section in enumerate(sections or [], start=1):
        sid = str(section.get("id", f"section_{idx}"))
        label = str(section.get("label", sid))
        kind = str(section.get("kind", "section"))
        start_s = float(section.get("start_seconds", 0.0) or 0.0)
        meta[f"CHAPTER{idx:03d}"] = format_ogg_timestamp(start_s)
        meta[f"CHAPTER{idx:03d}NAME"] = label
        meta[f"CHAPTER{idx:03d}ID"] = sid
        meta[f"CHAPTER{idx:03d}KIND"] = kind
    meta["AMBITION_MARKER_COUNT"] = len(sections or [])
    return meta


def encode_ogg(wav_path: Path, ogg_path: Path, quality: float = 5.0, metadata: dict[str, object] | None = None) -> None:
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError("ffmpeg is required to encode OGG Vorbis")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-map_metadata",
        "-1",
        *ogg_metadata_args(metadata),
        "-c:a",
        "libvorbis",
        "-q:a",
        str(quality),
        str(ogg_path),
    ]
    subprocess.run(cmd, check=True)
    write_metadata_sidecar(ogg_path, metadata)


@profile
def write_ogg_from_audio(
    audio: np.ndarray,
    sample_rate: int,
    ogg_path: Path,
    *,
    quality: float = 5.0,
    keep_wav: bool = False,
    metadata: dict[str, object] | None = None,
) -> Path:
    """Write OGG Vorbis, preferring ffmpeg pipe encoding for reliability/speed."""
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.nan_to_num(
        np.clip(coerce_stereo(audio), -1.0, 1.0), nan=0.0, posinf=0.0, neginf=0.0
    ).astype(np.float32, copy=False)
    if not shutil.which("ffmpeg"):
        # Fallback for minimal environments. Some libsndfile builds are slow on
        # many OGG writes, but this keeps the renderer usable if ffmpeg is absent.
        sf.write(ogg_path, pcm, sample_rate, format="OGG", subtype="VORBIS")
        write_metadata_sidecar(ogg_path, metadata)
        if keep_wav:
            write_wav(ogg_path.with_suffix(".wav"), audio, sample_rate)
        return ogg_path
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        "2",
        "-i",
        "pipe:0",
        "-map_metadata",
        "-1",
        *ogg_metadata_args(metadata),
        "-c:a",
        "libvorbis",
        "-q:a",
        str(quality),
        str(ogg_path),
    ]
    proc = subprocess.run(
        cmd,
        input=pcm.tobytes(order="C"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf8", errors="replace"))
    write_metadata_sidecar(ogg_path, metadata)
    if keep_wav:
        write_wav(ogg_path.with_suffix(".wav"), audio, sample_rate)
    return ogg_path



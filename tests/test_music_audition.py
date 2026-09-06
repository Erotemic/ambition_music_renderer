from __future__ import annotations

import json
from pathlib import Path
import wave

import numpy as np
import soundfile as sf

from ambition_music_renderer.music_audition import (
    compose_stem_mix,
    discover_stem_assets,
    discover_versions,
    discover_versions_from_path,
    preferred_reference,
)


def _write_render(
    root: Path,
    variant: str,
    render_hash: str,
    stems: dict[str, np.ndarray],
    *,
    cue: str = "test_cue",
    under_agent: bool = True,
    keep_native: bool = True,
    write_review_stems: bool = False,
) -> Path:
    if under_agent:
        run = root / "agent" / "test_ab" / "renders" / variant
    else:
        run = root / "external" / variant
    preview_dir = run / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    full = preview_dir / f"{cue}_{render_hash}.full_soundtrack_preview.wav"
    with wave.open(str(full), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00\x00\x00" * 800)
    files = {"preview": {"full_soundtrack": f"preview/{full.name}"}}
    if keep_native:
        (run / "scratch_stems").mkdir(parents=True, exist_ok=True)
    for group, audio in stems.items():
        if keep_native:
            np.save(run / "scratch_stems" / f"{cue}_{render_hash}.{group}.npy", audio.astype(np.float32))
        if write_review_stems:
            review = preview_dir / f"{cue}_{render_hash}.review_stem_{group}.wav"
            sf.write(review, audio, 8000, subtype="FLOAT")
            files["preview"][f"review_stem_{group}"] = f"preview/{review.name}"
        audition = preview_dir / f"{cue}_{render_hash}.audition_stem_{group}.wav"
        sf.write(audition, audio, 8000, subtype="FLOAT")
        files["preview"][f"audition_stem_{group}"] = f"preview/{audition.name}"
    manifest = {
        "schema": "ambition.adaptive_music_manifest.v2",
        "renderer_version": "test",
        "id": cue,
        "title": "Test Cue",
        "hash": render_hash,
        "sample_rate": 8000,
        "stems": sorted(stems),
        "files": files,
    }
    manifest_path = run / f"{cue}_{render_hash}.adaptive_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    return manifest_path


def test_stem_lab_discovers_scratch_versions_without_review_bank_help(tmp_path: Path):
    audio = np.full((80, 2), 0.1, dtype=np.float32)
    _write_render(tmp_path, "A_canonical_original", "aaaaaaaaaaaaaaaa", {"bass": audio})
    _write_render(tmp_path, "G_strings_safe", "bbbbbbbbbbbbbbbb", {"bass": audio})

    versions = discover_versions(tmp_path)
    assert {version.label for version in versions} == {"A_canonical_original", "G_strings_safe"}
    reference = preferred_reference(versions)
    assert reference is not None
    assert reference.label == "A_canonical_original"


def test_reference_is_optional_for_new_compositions(tmp_path: Path):
    audio = np.full((80, 2), 0.1, dtype=np.float32)
    _write_render(tmp_path, "first_idea", "1111111111111111", {"bass": audio})
    _write_render(tmp_path, "second_idea", "2222222222222222", {"bass": audio})
    assert preferred_reference(discover_versions(tmp_path)) is None


def test_explicit_folder_discovery_is_separate_from_default_library(tmp_path: Path):
    audio = np.full((80, 2), 0.1, dtype=np.float32)
    manifest = _write_render(
        tmp_path,
        "outside_bank",
        "cccccccccccccccc",
        {"bass": audio},
        under_agent=False,
    )
    assert discover_versions(tmp_path) == []
    versions = discover_versions_from_path(manifest.parent)
    assert len(versions) == 1
    assert versions[0].label == "outside_bank"


def test_stem_discovery_prefers_native_level_buffers(tmp_path: Path):
    audio = np.full((80, 2), 0.1, dtype=np.float32)
    _write_render(tmp_path, "A_canonical_original", "aaaaaaaaaaaaaaaa", {"bass": audio})
    version = discover_versions(tmp_path)[0]
    assets = discover_stem_assets(version)
    assert assets["bass"].kind == "native"
    assert assets["bass"].balance_faithful is True


def test_stem_discovery_uses_compact_native_level_review_audio(tmp_path: Path):
    audio = np.full((80, 2), 0.1, dtype=np.float32)
    _write_render(
        tmp_path,
        "A_canonical_original",
        "aaaaaaaaaaaaaaaa",
        {"bass": audio},
        keep_native=False,
        write_review_stems=True,
    )
    version = discover_versions(tmp_path)[0]
    assets = discover_stem_assets(version)
    assert assets["bass"].kind == "review_native"
    assert assets["bass"].balance_faithful is True


def test_cross_version_stem_mix_uses_selected_sources(tmp_path: Path):
    bass = np.full((80, 2), 0.10, dtype=np.float32)
    strings = np.full((80, 2), 0.20, dtype=np.float32)
    _write_render(tmp_path, "A_canonical_original", "aaaaaaaaaaaaaaaa", {"bass": bass, "strings": bass})
    _write_render(tmp_path, "G_strings_safe", "bbbbbbbbbbbbbbbb", {"bass": strings, "strings": strings})
    versions = {version.label: version for version in discover_versions(tmp_path)}
    a_assets = discover_stem_assets(versions["A_canonical_original"])
    g_assets = discover_stem_assets(versions["G_strings_safe"])
    out = tmp_path / "mix.wav"
    result = compose_stem_mix(
        {
            "bass": (versions["A_canonical_original"], a_assets["bass"]),
            "strings": (versions["G_strings_safe"], g_assets["strings"]),
        },
        out,
    )
    mixed, sr = sf.read(out, dtype="float32", always_2d=True)
    assert sr == 8000
    assert result.used_normalized_fallback is False
    np.testing.assert_allclose(mixed[:80], 0.30, atol=1e-6)

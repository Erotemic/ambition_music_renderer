"""A shareable music bundle must include all runtime playback layer audio."""

from pathlib import Path

from ambition_music_renderer.render.bundle_base import (
    copy_manifest_referenced_files,
    manifest_audio_entries,
)


def _manifest():
    return {
        "files": {
            "preview": {"full": "preview/example.ogg"},
            "adaptive": {"main": {"full": "adaptive/main/example.ogg"}},
            "playback": {
                "intro": {"bed": "playback/intro/intro.bed.ogg"},
                "combat": {
                    "bed": "playback/combat/combat.bed.ogg",
                    "hook": "playback/combat/combat.hook.ogg",
                },
                "outro": {"bed": "playback/outro/outro.bed.ogg"},
            },
        }
    }


def test_all_manifest_playback_files_are_collected():
    entries = manifest_audio_entries(_manifest())
    playback = [e for e in entries if e["kind"] == "playback_audio"]
    assert {(e["section"], e["group"]) for e in playback} == {
        ("intro", "bed"), ("combat", "bed"), ("combat", "hook"), ("outro", "bed")
    }
    assert len(entries) == 6


def test_bundle_copies_declared_playback_audio_and_metadata(tmp_path: Path):
    source = tmp_path / "source"
    output = tmp_path / "bundle"
    paths = [e["path"] for e in manifest_audio_entries(_manifest())]
    for name in paths:
        f = source / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"test-audio")
    extra = source / "playback/combat/stale-other-hash.ogg"
    extra.write_bytes(b"stale")
    metadata = source / "playback/combat/combat.bed.ogg.metadata.json"
    metadata.write_text("{}", encoding="utf8")
    copied = copy_manifest_referenced_files(source, _manifest(), output)
    assert set(paths).issubset(copied)
    for name in paths:
        assert (output / name).read_bytes() == b"test-audio"
    assert (output / "playback/combat/combat.bed.ogg.metadata.json").exists()
    assert not (output / "playback/combat/stale-other-hash.ogg").exists()

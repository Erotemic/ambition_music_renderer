from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import mido
import pytest

from ambition_music_renderer.ardour_export import (
    ACE_REASONABLE_SYNTH_URI,
    ArdourExportError,
    export_ardour_session,
)
from ambition_music_renderer.musicir.compile import compile_score


def _constant_v1_score():
    return {
        "schema": "ambition.musicir.v1",
        "id": "ardour_generic_fixture",
        "tempo": {"bpm": 96},
        "meter": {"beats_per_bar": 4, "beat_unit": 4},
        "instruments": [
            {
                "name": "lead",
                "group": "melody",
                "program": "acoustic_grand_piano",
                "volume": 100,
            },
            {
                "name": "kit",
                "group": "rhythm",
                "program": "acoustic_grand_piano",
                "is_drum": True,
                "volume": 100,
            },
        ],
        "sections": [
            {
                "id": "main",
                "bars": 1,
                "layers": [
                    {
                        "instrument": "lead",
                        "kind": "notes",
                        "events": [
                            {"beat": 0, "duration": 1, "pitch": "C4", "velocity": 80},
                            {"beat": 2, "duration": 1, "pitch": "E4", "velocity": 88},
                        ],
                    },
                    {
                        "instrument": "kit",
                        "kind": "notes",
                        "events": [
                            {"beat": 0, "duration": 0.25, "pitch": 36, "velocity": 100},
                            {"beat": 2, "duration": 0.25, "pitch": 38, "velocity": 96},
                        ],
                    },
                ],
            }
        ],
    }


def _tempo_change_v2_score():
    return {
        "schema": "ambition.musicir.v2",
        "id": "ardour_tempo_change_fixture",
        "instruments": [
            {
                "name": "keys",
                "group": "keys",
                "program": "acoustic_grand_piano",
                "volume": 100,
            }
        ],
        "score": {
            "timebase": {"ppq": 480},
            "meter": [{"bar": 1, "signature": "4/4"}],
            "tempo": [
                {"tick": 0, "bpm": 120},
                {"tick": 960, "bpm": 90},
            ],
            "form": [
                {"id": "main", "from": {"bar": 1, "beat": 1}, "to": {"bar": 2, "beat": 1}}
            ],
            "end": {"bar": 2, "beat": 1},
        },
        "parts": [
            {
                "id": "keys_part",
                "instrument": "keys",
                "voices": [
                    {
                        "id": "right",
                        "events": [[0, 480, "C4", 80]],
                    }
                ],
            }
        ],
    }


def test_ardour_export_builds_semantic_audible_editing_session(tmp_path: Path):
    compiled = compile_score(_constant_v1_score())
    result = export_ardour_session(compiled, tmp_path / "session")

    assert result.session_file.exists()
    assert result.neutral_midi.exists()
    assert result.interchange_manifest.exists()
    assert result.export_manifest.exists()

    root = ET.parse(result.session_file).getroot()
    routes_node = root.find("Routes")
    assert routes_node is not None
    routes = list(routes_node)
    assert [route.get("name") for route in routes] == ["Master", "lead", "kit"]

    master = routes[0]
    assert not [proc for proc in master.findall("Processor") if proc.get("type") == "lv2"]
    master_outputs = [
        port
        for io in master.findall("IO")
        if io.get("direction") == "Output"
        for port in io.findall("Port")
    ]
    assert master_outputs
    assert all(not port.findall("ExtConnection") for port in master_outputs)

    for route in routes[1:]:
        plugins = [proc for proc in route.findall("Processor") if proc.get("type") == "lv2"]
        assert len(plugins) == 1
        assert plugins[0].get("name") == "ACE Reasonable Synth"
        assert plugins[0].get("unique-id") == ACE_REASONABLE_SYNTH_URI
        connections = [
            conn.get("other")
            for io in route.findall("IO")
            if io.get("direction") == "Output"
            for port in io.findall("Port")
            for conn in port.findall("Connection")
        ]
        assert "Master/audio_in 1" in connections
        assert "Master/audio_in 2" in connections

    sources = root.find("Sources")
    regions = root.find("Regions")
    playlists = root.find("Playlists")
    assert sources is not None and len(sources) == 2
    assert regions is not None and len(regions) == 2
    assert playlists is not None and len(playlists) == 2

    midi_dir = result.session_dir / "interchange" / "ardour_generic_fixture" / "midifiles"
    source_midis = sorted(midi_dir.glob("*.mid"))
    assert len(source_midis) == 2
    names = []
    for path in source_midis:
        mid = mido.MidiFile(str(path))
        assert len(mid.tracks) == 2
        names.extend(
            msg.name
            for msg in mid.tracks[1]
            if msg.type == "track_name"
        )
    assert names == ["lead", "kit"]

    manifest = json.loads(result.export_manifest.read_text())
    assert manifest["schema"] == "ambition.ardour_export.v1"
    assert manifest["generated_session"] is True
    assert manifest["audition"]["plugin"] == "ACE Reasonable Synth"
    assert [row["instrument"] for row in manifest["tracks"]] == ["lead", "kit"]


def test_ardour_export_does_not_clobber_unmarked_directory(tmp_path: Path):
    compiled = compile_score(_constant_v1_score())
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "notes.txt").write_text("keep me")

    with pytest.raises(ArdourExportError, match="already exists"):
        export_ardour_session(compiled, destination)
    with pytest.raises(ArdourExportError, match="not marked"):
        export_ardour_session(compiled, destination, force=True)
    assert (destination / "notes.txt").read_text() == "keep me"


def test_ardour_export_force_replaces_only_generated_session(tmp_path: Path):
    compiled = compile_score(_constant_v1_score())
    destination = tmp_path / "generated"
    export_ardour_session(compiled, destination)
    stale = destination / "stale.txt"
    stale.write_text("old")

    export_ardour_session(compiled, destination, force=True)
    assert not stale.exists()
    assert (destination / ".ambition-ardour-export.json").exists()


def test_ardour_export_rejects_tempo_map_until_session_serializer_supports_it(tmp_path: Path):
    compiled = compile_score(_tempo_change_v2_score())
    with pytest.raises(ArdourExportError, match="constant tempo"):
        export_ardour_session(compiled, tmp_path / "session")

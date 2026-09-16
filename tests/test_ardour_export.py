from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import mido
import pytest

from ambition_music_renderer.ardour_export import (
    ACE_FLUID_SYNTH_FILE_PROPERTY,
    ACE_FLUID_SYNTH_URI,
    ACE_REASONABLE_SYNTH_URI,
    ARDOUR_BEAT_TICKS,
    ARDOUR_SMF_PPQN,
    ARDOUR_SMF_TICKS_PER_BEAT_TICK,
    SFIZZ_FILE_PROPERTY,
    SFIZZ_URI,
    ArdourExportError,
    _serialized_instrument_state_errors,
    apply_ardour_instruments,
    apply_ardour_processing,
    export_ardour_session,
)
from ambition_music_renderer.ardour_processing import compile_processing_transport
from ambition_music_renderer.musicir.compile import compile_score




def _ardour_delta_to_beat_ticks(delta: int, ppq: int) -> int:
    """Mirror Temporal::Beats::ticks_at_rate for one SMF delta.

    Ardour's SMFSource::render applies this conversion to every delta before
    accumulating.  This deliberately truncates the fractional remainder.
    """

    return (int(delta) // int(ppq)) * ARDOUR_BEAT_TICKS + (
        (int(delta) % int(ppq)) * ARDOUR_BEAT_TICKS // int(ppq)
    )


def _note_on_positions_in_ardour_beat_ticks(path: Path, track_index: int) -> list[int]:
    mid = mido.MidiFile(str(path))
    position = 0
    out = []
    for message in mid.tracks[track_index]:
        position += _ardour_delta_to_beat_ticks(message.time, mid.ticks_per_beat)
        if message.type == "note_on" and message.velocity > 0:
            out.append(position)
    return out


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
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
    )

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
    channels = []
    for path in source_midis:
        mid = mido.MidiFile(str(path))
        assert len(mid.tracks) == 2
        names.extend(
            msg.name
            for msg in mid.tracks[1]
            if msg.type == "track_name"
        )
        channels.append(
            sorted(
                {msg.channel for msg in mid.tracks[1] if hasattr(msg, "channel")}
            )
        )
    assert names == ["lead", "kit"]
    # The DAW-specific per-track files preserve the neutral bundle's channels.
    # This fixture happens to use channel 1 for the first pitched track and the
    # conventional channel 10 for drums.
    assert channels == [[0], [9]]

    manifest = json.loads(result.export_manifest.read_text())
    assert manifest["schema"] == "ambition.ardour_export.v2"
    assert manifest["generated_session"] is True
    assert manifest["audition"]["plugin"] == "ACE Reasonable Synth"
    assert [row["instrument"] for row in manifest["tracks"]] == ["lead", "kit"]




def test_ardour_track_midis_use_lossless_ardour_smf_lattice(tmp_path: Path):
    """Dense tracks must not accumulate PPQ conversion loss in Ardour.

    PrettyMIDI v1 exports commonly use 220 PPQ.  Ardour's SMFSource::render
    converts each delta independently to its 1920-tick beat grid, so a 220-PPQ
    writable source creeps earlier as events accumulate.  Generated session
    sources therefore use Ardour's 19200 PPQ and constrain every event to its
    native 10-SMF-tick lattice.
    """

    spec = _constant_v1_score()
    spec["sections"] = [
        {
            "id": "dense",
            "bars": 16,
            "layers": [
                {
                    "instrument": "lead",
                    "kind": "notes",
                    "events": [
                        {
                            "beat": beat / 4.0,
                            "duration": 0.125,
                            "pitch": "C4" if beat % 2 == 0 else "E4",
                            "velocity": 80,
                        }
                        for beat in range(16 * 4 * 4)
                    ],
                },
                {
                    "instrument": "kit",
                    "kind": "notes",
                    "events": [
                        {
                            "beat": beat / 8.0,
                            "duration": 0.0625,
                            "pitch": 36 if beat % 4 == 0 else 42,
                            "velocity": 100,
                        }
                        for beat in range(16 * 4 * 8)
                    ],
                },
            ],
        }
    ]
    compiled = compile_score(spec)
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
    )

    neutral = mido.MidiFile(str(result.neutral_midi))
    assert neutral.ticks_per_beat == 220
    midi_dir = result.session_dir / "interchange" / "ardour_generic_fixture" / "midifiles"

    for index, path in enumerate(sorted(midi_dir.glob("*.mid")), start=1):
        ardour_mid = mido.MidiFile(str(path))
        assert ardour_mid.ticks_per_beat == ARDOUR_SMF_PPQN
        # Every generated delta lies exactly on Ardour's internal beat lattice.
        assert all(
            int(message.time) % ARDOUR_SMF_TICKS_PER_BEAT_TICK == 0
            for track in ardour_mid.tracks
            for message in track
        )

        source_abs = 0
        expected_note_ons = []
        for message in neutral.tracks[index]:
            source_abs += int(message.time)
            if message.type == "note_on" and message.velocity > 0:
                expected_note_ons.append(
                    int(round(source_abs * ARDOUR_BEAT_TICKS / neutral.ticks_per_beat))
                )

        observed_note_ons = _note_on_positions_in_ardour_beat_ticks(path, 1)
        assert observed_note_ons == expected_note_ons

    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert all(row["ardour_source_ppq"] == ARDOUR_SMF_PPQN for row in manifest["tracks"])


def test_ardour_export_realization_uses_known_good_scaffold_and_ardour_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    sfz = tmp_path / "library" / "lead.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<region> sample=lead.wav key=60\n", encoding="utf8")
    soundfont = tmp_path / "GeneralUser-GS.sf2"
    soundfont.write_bytes(b"fixture")
    monkeypatch.setenv("AMBITION_MUSIC_DEFAULT_SOUNDFONT", str(soundfont))

    spec = _constant_v1_score()
    spec["instruments"][0]["instrument_backend"] = {
        "kind": "sfz",
        "sfz": str(sfz),
    }
    compiled = compile_score(spec)
    result = export_ardour_session(compiled, tmp_path / "session")

    # The Python-written XML is deliberately the exact same one-instrument
    # audition scaffold that was validated interactively.  Arbitrary LV2
    # state is not hand-authored in Python.
    root = ET.parse(result.session_file).getroot()
    routes_node = root.find("Routes")
    assert routes_node is not None
    routes = {route.get("name"): route for route in routes_node}
    for name in ("lead", "kit"):
        plugins = [proc for proc in routes[name].findall("Processor") if proc.get("type") == "lv2"]
        assert [(proc.get("name"), proc.get("unique-id"), proc.get("active")) for proc in plugins] == [
            ("ACE Reasonable Synth", ACE_REASONABLE_SYNTH_URI, "1"),
        ]

    manifest = json.loads(result.export_manifest.read_text())
    tracks = {row["instrument"]: row for row in manifest["tracks"]}
    assert tracks["lead"]["ardour_realization"]["kind"] == "sfizz"
    assert tracks["lead"]["ardour_realization"]["plugin_uri"] == SFIZZ_URI
    assert tracks["lead"]["ardour_realization"]["asset_property"] == SFIZZ_FILE_PROPERTY
    assert tracks["lead"]["ardour_realization"]["asset"] == str(sfz.resolve())
    assert tracks["kit"]["ardour_realization"]["kind"] == "ace_fluidsynth_gm"
    assert tracks["kit"]["ardour_realization"]["plugin_uri"] == ACE_FLUID_SYNTH_URI
    assert tracks["kit"]["ardour_realization"]["asset_property"] == ACE_FLUID_SYNTH_FILE_PROPERTY
    assert tracks["kit"]["ardour_realization"]["asset"] == str(soundfont.resolve())
    assert manifest["instrument_realization"]["status"] == "pending"

    assert result.instrument_bootstrap is not None
    lua = result.instrument_bootstrap.read_text(encoding="utf8")
    assert "route:replace_processor" in lua
    assert "ARDOUR.LuaAPI.new_plugin" in lua
    assert "ARDOUR.LuaAPI.set_plugin_insert_property" in lua
    assert "ARDOUR.LuaAPI.get_plugin_insert_property" not in lua
    assert "wait_for_asset" not in lua
    assert "settle_seconds" in lua
    assert "Session:save_state('')" in lua
    assert SFIZZ_URI in lua
    assert SFIZZ_FILE_PROPERTY in lua
    assert str(sfz.resolve()) in lua
    assert ACE_FLUID_SYNTH_URI in lua
    assert ACE_FLUID_SYNTH_FILE_PROPERTY in lua
    assert str(soundfont.resolve()) in lua

    # This is the regression guard for the broken v2 attempt: Python must not
    # manufacture plugin state directories or put two instruments in series.
    assert not list((result.session_dir / "plugins").rglob("state.ttl"))


def test_apply_ardour_instruments_runs_native_bootstrap_and_marks_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    compiled = compile_score(_constant_v1_score())
    result = export_ardour_session(compiled, tmp_path / "session")
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")

    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        import subprocess

        return subprocess.CompletedProcess(command, 0, stdout="native realization ok\n", stderr="")

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._serialized_instrument_state_errors",
        lambda _result: [],
    )
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._graft_native_instruments_onto_scaffold",
        lambda _result, *, scaffold_bytes: None,
    )
    completed = apply_ardour_instruments(result, ardour_lua=arlua)
    assert completed.returncode == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        str(arlua.resolve()),
        str(result.instrument_bootstrap),
        str(result.session_dir),
        result.session_file.stem,
        "0.75",
    ]
    assert kwargs == {"text": True, "capture_output": True, "check": False}
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert manifest["instrument_realization"]["status"] == "applied"
    assert manifest["instrument_realization"]["ardour_lua"] == str(arlua.resolve())



def test_apply_ardour_instruments_accepts_nonzero_exit_when_serialized_state_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    compiled = compile_score(_constant_v1_score())
    result = export_ardour_session(compiled, tmp_path / "session")
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        import subprocess

        # Headless Ardour can report a non-zero process result even after the
        # requested plugin state has been serialized correctly.  Persisted
        # state, not the wrapper exit code, is the authoritative postcondition.
        return subprocess.CompletedProcess(
            command, 1, stdout="native realization serialized\n", stderr="nonfatal wrapper exit\n"
        )

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._serialized_instrument_state_errors",
        lambda _result: [],
    )
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._graft_native_instruments_onto_scaffold",
        lambda _result, *, scaffold_bytes: None,
    )

    completed = apply_ardour_instruments(result, ardour_lua=arlua)
    assert completed.returncode == 1
    assert len(calls) == 1
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert manifest["instrument_realization"]["status"] == "applied"
    assert "error" not in manifest["instrument_realization"]

def test_apply_ardour_instruments_failure_leaves_audition_xml_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    compiled = compile_score(_constant_v1_score())
    result = export_ardour_session(compiled, tmp_path / "session")
    before = result.session_file.read_bytes()
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")

    midi_dir = result.session_dir / "interchange" / result.session_file.stem / "midifiles"
    source = sorted(midi_dir.glob("*.mid"))[0]
    source_before = source.read_bytes()
    scratch = midi_dir / "Take1_native-rewrite.mid"

    def fake_run(command, **kwargs):
        import subprocess

        # Model a native pass that saved a partially-mutated session and MIDI
        # source before its post-save verification noticed the wrong asset.
        result.session_file.write_text("broken native save", encoding="utf8")
        source.write_bytes(b"native rewrite")
        scratch.write_bytes(b"native scratch take")
        plugin_state = result.session_dir / "plugins" / "123" / "state1"
        plugin_state.mkdir(parents=True)
        (plugin_state / "state.ttl").write_text("bad state", encoding="utf8")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="plugin unavailable")

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    with pytest.raises(ArdourExportError, match="rolled back"):
        apply_ardour_instruments(result, ardour_lua=arlua)
    assert result.session_file.read_bytes() == before
    assert source.read_bytes() == source_before
    assert not scratch.exists()
    assert not list((result.session_dir / "plugins").rglob("state.ttl"))
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert manifest["instrument_realization"]["status"] == "failed"
    assert "plugin unavailable" in manifest["instrument_realization"]["error"]


def test_ardour_export_rejects_renderer_default_sfz_as_real_instrument(
    tmp_path: Path,
):
    default_sfz = tmp_path / "DefaultInstrument.sfz"
    default_sfz.write_text("<region> sample=default.wav key=60\n", encoding="utf8")
    spec = _constant_v1_score()
    spec["render"] = {"sfizz": {"default_sfz": str(default_sfz)}}
    spec["instruments"][0]["instrument_backend"] = {
        "kind": "sfz",
        "sfz": str(tmp_path / "missing-real-instrument.sfz"),
        "optional": True,
    }
    compiled = compile_score(spec)
    result = export_ardour_session(compiled, tmp_path / "session")
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    lead = next(row for row in manifest["tracks"] if row["instrument"] == "lead")
    assert lead["resolution"]["resolved_sfz"] == str(default_sfz.resolve())
    assert lead["resolution"]["ardour_exact_resolved_sfz"] is None
    assert lead["ardour_realization"]["kind"] == "reasonable_synth"
    assert "renderer fallback was rejected" in lead["ardour_realization"]["fallback_reason"]



def test_ardour_export_preserves_neutral_channels_for_multiple_pitched_tracks(tmp_path: Path):
    spec = _constant_v1_score()
    spec["instruments"].insert(
        1,
        {
            "name": "second_lead",
            "group": "melody",
            "program": "harpsichord",
            "volume": 100,
        },
    )
    spec["sections"][0]["layers"].insert(
        1,
        {
            "instrument": "second_lead",
            "kind": "notes",
            "events": [{"beat": 1, "duration": 1, "pitch": "G4", "velocity": 84}],
        },
    )
    compiled = compile_score(spec)
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
    )
    midi_dir = result.session_dir / "interchange" / "ardour_generic_fixture" / "midifiles"
    channels = []
    for path in sorted(midi_dir.glob("*.mid")):
        mid = mido.MidiFile(str(path))
        channels.append(sorted({msg.channel for msg in mid.tracks[1] if hasattr(msg, "channel")}))
    # Neutral Type-1 allocation gives the two pitched tracks different channels;
    # the Ardour adapter must not rewrite them merely because routes are separate.
    assert channels == [[0], [1], [9]]


def test_serialized_state_verifier_rejects_default_and_accepts_expected_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    sfz = tmp_path / "library" / "lead.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<region> sample=lead.wav key=60\n", encoding="utf8")
    spec = _constant_v1_score()
    spec["instruments"][0]["instrument_backend"] = {"kind": "sfz", "sfz": str(sfz)}
    # Leave the drum track unsupported in this verifier fixture so only the lead
    # needs concrete LV2 state.
    compiled = compile_score(spec)
    monkeypatch.delenv("AMBITION_MUSIC_DEFAULT_SOUNDFONT", raising=False)
    result = export_ardour_session(compiled, tmp_path / "session")

    # Rewrite just the lead's known-good scaffold processor to model the XML
    # libardour writes after replacing it with sfizz.
    tree = ET.parse(result.session_file)
    root = tree.getroot()
    routes = {route.get("name"): route for route in root.find("Routes")}
    lead = routes["lead"]
    proc = next(proc for proc in lead.findall("Processor") if proc.get("type") == "lv2")
    proc.set("name", "sfizz")
    proc.set("unique-id", SFIZZ_URI)
    proc.set("id", "9001")
    proc.set("state-dir", "state1")
    tree.write(result.session_file, encoding="UTF-8", xml_declaration=True)

    state_dir = result.session_dir / "plugins" / "9001" / "state1"
    state_dir.mkdir(parents=True)
    (state_dir / "DefaultInstrument.sfz").write_text("<region> key=60\n", encoding="utf8")
    (state_dir / "state.ttl").write_text(
        '<http://sfztools.github.io/sfizz:sfzfile> <DefaultInstrument.sfz> ;\n',
        encoding="utf8",
    )
    errors = _serialized_instrument_state_errors(result)
    assert any("lead" in error and "lead.sfz" in error for error in errors)

    (state_dir / "DefaultInstrument.sfz").unlink()
    (state_dir / "lead.sfz").symlink_to(sfz)
    (state_dir / "state.ttl").write_text(
        '<http://sfztools.github.io/sfizz:sfzfile> <lead.sfz> ;\n',
        encoding="utf8",
    )
    errors = _serialized_instrument_state_errors(result)
    assert not [error for error in errors if error.startswith("lead:")]


def test_apply_ardour_instruments_retries_serialized_state_before_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    compiled = compile_score(_constant_v1_score())
    result = export_ardour_session(compiled, tmp_path / "session")
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")
    calls = []
    midi_dir = result.session_dir / "interchange" / result.session_file.stem / "midifiles"
    source = sorted(midi_dir.glob("*.mid"))[0]
    source_before = source.read_bytes()
    scratch = midi_dir / "Take1_native-rewrite.mid"

    def fake_run(command, **kwargs):
        import subprocess

        # Every retry must begin with the exact generated source bytes, not the
        # SMFSource rewrite saved by the previous headless Ardour attempt.
        assert source.read_bytes() == source_before
        assert not scratch.exists()
        calls.append(command)
        result.session_file.write_text(f"native attempt {len(calls)}", encoding="utf8")
        source.write_bytes(f"native rewrite {len(calls)}".encode())
        scratch.write_bytes(b"native scratch take")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    outcomes = iter(
        [
            ["stomp_kit: still DefaultInstrument.sfz"],
            ["stomp_kit: still DefaultInstrument.sfz"],
            [],
            [],
        ]
    )
    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._serialized_instrument_state_errors",
        lambda _result: next(outcomes),
    )
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._graft_native_instruments_onto_scaffold",
        lambda _result, *, scaffold_bytes: None,
    )
    completed = apply_ardour_instruments(result, ardour_lua=arlua)
    assert completed.returncode == 0
    assert [call[-1] for call in calls] == ["0.75", "3", "12"]
    assert source.read_bytes() == source_before
    assert not scratch.exists()
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert manifest["instrument_realization"]["status"] == "applied"

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


def test_ardour_export_force_accepts_previous_generated_marker_schema(tmp_path: Path):
    compiled = compile_score(_constant_v1_score())
    destination = tmp_path / "generated"
    result = export_ardour_session(compiled, destination)
    marker = json.loads(result.export_manifest.read_text(encoding="utf8"))
    marker["schema"] = "ambition.ardour_export.v1"
    result.export_manifest.write_text(json.dumps(marker), encoding="utf8")

    export_ardour_session(compiled, destination, force=True)
    refreshed = json.loads((destination / ".ambition-ardour-export.json").read_text(encoding="utf8"))
    assert refreshed["schema"] == "ambition.ardour_export.v2"


def test_ardour_export_rejects_tempo_map_until_session_serializer_supports_it(tmp_path: Path):
    compiled = compile_score(_tempo_change_v2_score())
    with pytest.raises(ArdourExportError, match="constant tempo"):
        export_ardour_session(compiled, tmp_path / "session")


def test_ardour_gm_prefers_portable_sf2_over_renderer_sf3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """ACE Fluid Synth must not inherit an SF3 the bundled decoder cannot load."""

    sf3 = tmp_path / "MuseScore_General_Full.sf3"
    sf3.write_bytes(b"sf3 fixture")
    sf2 = tmp_path / "GeneralUser-GS.sf2"
    sf2.write_bytes(b"sf2 fixture")
    monkeypatch.delenv("AMBITION_MUSIC_DEFAULT_SOUNDFONT", raising=False)
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export.choose_soundfont",
        lambda _path=None: str(sf3),
    )
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export.instrument_libraries.configured_soundfont_roots",
        lambda *_args, **_kwargs: [tmp_path],
    )

    compiled = compile_score(_constant_v1_score())
    result = export_ardour_session(compiled, tmp_path / "session")
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    tracks = {row["instrument"]: row for row in manifest["tracks"]}
    for name in ("lead", "kit"):
        realization = tracks[name]["ardour_realization"]
        assert realization["kind"] == "ace_fluidsynth_gm"
        assert realization["asset"] == str(sf2.resolve())
        assert realization["source"] == "audio-tools GeneralUser-GS"


def test_ardour_explicit_sf3_backend_stays_on_neutral_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Do not create an ACE Fluid Synth track for a non-portable SF3 asset."""

    sf3 = tmp_path / "future-bank.sf3"
    sf3.write_bytes(b"sf3 fixture")
    spec = _constant_v1_score()
    spec["instruments"][0]["instrument_backend"] = {
        "kind": "soundfont",
        "soundfont": str(sf3),
    }
    monkeypatch.delenv("AMBITION_MUSIC_DEFAULT_SOUNDFONT", raising=False)
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export.choose_soundfont",
        lambda _path=None: "",
    )
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export.instrument_libraries.configured_soundfont_roots",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export.instrument_libraries.discover_soundfont_files",
        lambda *_args, **_kwargs: [],
    )

    compiled = compile_score(spec)
    result = export_ardour_session(compiled, tmp_path / "session")
    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    lead = next(row for row in manifest["tracks"] if row["instrument"] == "lead")
    assert lead["resolution"]["ardour_exact_resolved_soundfont"] is None
    assert lead["resolution"]["ardour_incompatible_soundfont"] == str(sf3.resolve())
    assert lead["ardour_realization"]["kind"] == "reasonable_synth"
    assert "portable .sf2 subset" in lead["ardour_realization"]["fallback_reason"]


def test_native_realization_grafts_only_plugins_and_preserves_scaffold_timing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A headless Ardour save must not become authoritative for MIDI placement."""

    sfz = tmp_path / "library" / "lead.sfz"
    sfz.parent.mkdir(parents=True)
    sfz.write_text("<region> sample=lead.wav key=60\n", encoding="utf8")

    spec = _constant_v1_score()
    spec["instruments"][0]["instrument_backend"] = {
        "kind": "sfz",
        "sfz": str(sfz),
    }
    # Keep the second route on the neutral synth so this fixture has exactly
    # one concrete native plugin to graft.
    spec["instruments"][1]["instrument_backend"] = {
        "kind": "procedural_fm",
    }
    compiled = compile_score(spec)
    result = export_ardour_session(compiled, tmp_path / "session")

    before_root = ET.parse(result.session_file).getroot()
    before_playlist = before_root.find("Playlists")
    assert before_playlist is not None
    before_region = before_playlist.find("Playlist/Region")
    assert before_region is not None
    assert before_region.get("start") == "b0"

    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")

    def fake_run(command, **kwargs):
        import subprocess

        # Model libardour normalizing unrelated session state while saving the
        # valid plugin.  The exporter must retain the plugin but reject this
        # timing mutation by grafting it onto the pristine scaffold instead.
        tree = ET.parse(result.session_file)
        root = tree.getroot()
        playlists = root.find("Playlists")
        assert playlists is not None
        region = playlists.find("Playlist/Region")
        assert region is not None
        region.set("start", "b12345")

        routes = {route.get("name"): route for route in root.find("Routes")}
        lead = routes["lead"]
        proc = next(
            proc
            for proc in lead.findall("Processor")
            if proc.get("type") == "lv2" and proc.get("unique-id") == ACE_REASONABLE_SYNTH_URI
        )
        proc.set("name", "sfizz")
        proc.set("unique-id", SFIZZ_URI)
        proc.set("id", "9001")
        proc.set("state-dir", "state1")
        root.set("id-counter", "9100")
        tree.write(result.session_file, encoding="UTF-8", xml_declaration=True)

        state_dir = result.session_dir / "plugins" / "9001" / "state1"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "lead.sfz").symlink_to(sfz)
        (state_dir / "state.ttl").write_text(
            '<http://sfztools.github.io/sfizz:sfzfile> <lead.sfz> ;\n',
            encoding="utf8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="native realization ok\n", stderr="")

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    completed = apply_ardour_instruments(result, ardour_lua=arlua)
    assert completed.returncode == 0

    final_root = ET.parse(result.session_file).getroot()
    final_playlist = final_root.find("Playlists")
    assert final_playlist is not None
    final_region = final_playlist.find("Playlist/Region")
    assert final_region is not None
    assert final_region.get("start") == "b0"
    assert int(final_root.get("id-counter", "0")) >= 9100

    routes = {route.get("name"): route for route in final_root.find("Routes")}
    lead_plugins = [proc for proc in routes["lead"].findall("Processor") if proc.get("type") == "lv2"]
    assert [(proc.get("unique-id"), proc.get("id")) for proc in lead_plugins] == [(SFIZZ_URI, "9001")]
    kit_plugins = [proc for proc in routes["kit"].findall("Processor") if proc.get("type") == "lv2"]
    assert [proc.get("unique-id") for proc in kit_plugins] == [ACE_REASONABLE_SYNTH_URI]

    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert manifest["instrument_realization"]["status"] == "applied"
    assert manifest["instrument_realization"]["session_merge"] == "plugin_processor_graft_onto_pristine_scaffold"


def _mix_transport_score():
    spec = _constant_v1_score()
    spec["instruments"][0]["mix_gain_db"] = 6.0
    spec["sections"] = [
        {
            "id": "a",
            "bars": 1,
            "stem_mix_db": {"melody": -6.0, "rhythm": 1.0},
            "layers": [
                {
                    "instrument": "lead",
                    "kind": "notes",
                    "events": [{"beat": 0, "duration": 1, "pitch": "C4", "velocity": 80}],
                },
                {
                    "instrument": "kit",
                    "kind": "notes",
                    "events": [{"beat": 0, "duration": 0.25, "pitch": 36, "velocity": 100}],
                },
            ],
        },
        {
            "id": "b",
            "bars": 1,
            "stem_mix_db": {"melody": 2.0, "rhythm": -2.0},
            "layers": [
                {
                    "instrument": "lead",
                    "kind": "notes",
                    "events": [{"beat": 0, "duration": 1, "pitch": "E4", "velocity": 84}],
                },
                {
                    "instrument": "kit",
                    "kind": "notes",
                    "events": [{"beat": 0, "duration": 0.25, "pitch": 38, "velocity": 96}],
                },
            ],
        },
    ]
    spec["render"] = {"section_stem_mix_transition_beats": 0.5}
    spec["group_postprocess"] = {
        "melody": {
            "gain_db": 2.0,
            "highpass_hz": 90.0,
            "compressor_threshold_db": -20.0,
            "compressor_ratio": 2.0,
            "reverb_wet": 0.05,
            "stereo_width": 0.0,
            "limiter_enabled": False,
        },
        "rhythm": {
            "gain_db": 1.0,
            "highpass_hz": 35.0,
            "reverb_wet": 0.0,
            "stereo_width": 0.0,
            "limiter_enabled": False,
        },
    }
    spec["postprocess"] = {
        "highpass_hz": 30.0,
        "compressor_threshold_db": -18.0,
        "compressor_ratio": 3.0,
        "reverb_wet": 0.0,
        "stereo_width": 0.0,
        "limiter_enabled": False,
        "normalize": False,
    }
    return spec


def test_ardour_processing_transport_keeps_safe_scaffold_and_generates_native_bus_plan(tmp_path: Path):
    compiled = compile_score(_mix_transport_score())
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
        realize_processing=True,
    )

    root = ET.parse(result.session_file).getroot()
    routes = {route.get("name"): route for route in root.find("Routes")}
    # The initial file must remain the already-proven audible topology.  Audio
    # buses are born later through libardour rather than being guessed as XML.
    assert "AMB Group melody" not in routes
    assert "AMB Group rhythm" not in routes
    assert "AMB Composition" not in routes

    def output_connections(route):
        return {
            conn.get("other")
            for io in route.findall("IO")
            if io.get("direction") == "Output"
            for port in io.findall("Port")
            for conn in port.findall("Connection")
        }

    assert "Master/audio_in 1" in output_connections(routes["lead"])
    assert "Master/audio_in 1" in output_connections(routes["kit"])

    # Static instrument calibration remains visible on each MIDI-track fader.
    lead_amp = next(proc for proc in routes["lead"].findall("Processor") if proc.get("type") == "amp")
    lead_gain = lead_amp.find("Controllable[@name='gaincontrol']")
    assert lead_gain is not None
    assert float(lead_gain.get("value")) == pytest.approx(10 ** (6.0 / 20.0))

    manifest = json.loads(result.export_manifest.read_text(encoding="utf8"))
    processing = manifest["processing_transport"]
    assert processing["enabled"] is True
    assert processing["status"] == "pending"
    assert processing["method"] == "canonical_processing_plan_to_libardour_native_group_buses"
    assert processing["mix_routing"]["groups"]["melody"]["created_by"] == "libardour.Session:new_audio_route"
    assert manifest["tracks"][0]["output_route"] == "AMB Group melody"
    assert manifest["tracks"][0]["scaffold_output_route"] == "Master"
    melody_points = processing["mix_routing"]["groups"]["melody"]["section_gain_automation_db"]
    assert melody_points
    assert melody_points[0][1] == pytest.approx(-6.0)
    assert max(point[1] for point in melody_points) == pytest.approx(2.0)

    melody_plan = processing["plan"]["groups"]["melody"]
    plugins = [row["plugin"] for row in melody_plan["processors"]]
    assert "ACE Amplifier" in plugins
    assert "ACE High/Low Pass Filter" in plugins
    assert "urn:ardour:a-comp" in plugins
    assert result.processing_bootstrap is not None
    lua = result.processing_bootstrap.read_text(encoding="utf8")
    assert "Session:new_audio_route" in lua
    assert "ARDOUR.config():set_output_auto_connect(ARDOUR.AutoConnectOption.ManualConnect)" in lua
    assert "op:connect(ip:name())" in lua
    assert "op:connected_to(ip:name())" in lua
    assert "route:amp():gain_control()" in lua
    assert "ac:set_automation_state(ARDOUR.AutoState.Play)" in lua
    assert "route:add_processor_by_index" in lua
    assert "ARDOUR.LuaAPI.set_processor_param" in lua


def test_apply_ardour_processing_grafts_native_bus_graph_but_pristine_track_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    compiled = compile_score(_mix_transport_score())
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
        realize_processing=True,
    )
    before = result.session_file.read_bytes()
    before_root = ET.fromstring(before)
    before_routes = {route.get("name"): route for route in before_root.find("Routes")}
    before_master_output = next(
        io for io in before_routes["Master"].findall("IO") if io.get("direction") == "Output"
    )
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")

    def fake_run(command, **kwargs):
        import subprocess

        data = json.loads(result.export_manifest.read_text(encoding="utf8"))
        plan = data["processing_transport"]["plan"]
        mix = data["processing_transport"]["mix_routing"]
        tree = ET.parse(result.session_file)
        root = tree.getroot()
        routes_node = root.find("Routes")
        routes = {route.get("name"): route for route in routes_node}
        next_id = 9000

        def take_id():
            nonlocal next_id
            value = str(next_id)
            next_id += 1
            return value

        def make_native_bus(name, order, target):
            route = ET.Element(
                "Route",
                {
                    "version": "7003",
                    "id": take_id(),
                    "name": name,
                    "default-type": "audio",
                    "strict-io": "1",
                    "active": "1",
                    "native-normalized": "1",
                },
            )
            ET.SubElement(
                route,
                "PresentationInfo",
                {"order": str(order), "flags": "AudioBus,OrderSet"},
            )
            inp = ET.SubElement(
                route,
                "IO",
                {"name": name, "id": take_id(), "direction": "Input", "default-type": "audio"},
            )
            out = ET.SubElement(
                route,
                "IO",
                {"name": name, "id": take_id(), "direction": "Output", "default-type": "audio"},
            )
            for channel in (1, 2):
                ET.SubElement(
                    inp,
                    "Port",
                    {"name": f"{name}/audio_in {channel}", "type": "audio", "direction": "Input"},
                )
                port = ET.SubElement(
                    out,
                    "Port",
                    {"name": f"{name}/audio_out {channel}", "type": "audio", "direction": "Output"},
                )
                ET.SubElement(port, "Connection", {"other": f"{target}/audio_in {channel}"})
            ET.SubElement(
                route,
                "Processor",
                {"id": take_id(), "name": "internal-return", "active": "1", "type": "intreturn"},
            )
            ET.SubElement(
                route,
                "Processor",
                {"id": take_id(), "name": name, "active": "1", "type": "main-outs", "role": "Main"},
            )
            routes_node.append(route)
            routes[name] = route
            return route

        composition_name = mix["composition"]["route"]
        make_native_bus(
            composition_name,
            mix["composition"]["order"],
            "Master",
        )
        for row in mix["groups"].values():
            make_native_bus(row["route"], row["order"], composition_name)

        def rewire_output(source_name, target_name):
            route = routes[source_name]
            output = next(io for io in route.findall("IO") if io.get("direction") == "Output")
            for port in output.findall("Port"):
                if port.get("type") != "audio":
                    continue
                for connection in list(port.findall("Connection")):
                    port.remove(connection)
                channel = port.get("name").rsplit(" ", 1)[-1]
                ET.SubElement(port, "Connection", {"other": f"{target_name}/audio_in {channel}"})

        for row in mix["groups"].values():
            for track_name in row["tracks"]:
                rewire_output(track_name, row["route"])

        # Simulate Ardour's receiving-side connection serialization as well.
        master_input = next(
            io for io in routes["Master"].findall("IO") if io.get("direction") == "Input"
        )
        for port in master_input.findall("Port"):
            for connection in list(port.findall("Connection")):
                port.remove(connection)
            channel = port.get("name").rsplit(" ", 1)[-1]
            ET.SubElement(
                port,
                "Connection",
                {"other": f"{composition_name}/audio_out {channel}"},
            )

        route_plans = list(plan["groups"].values()) + [plan["master"]]
        for route_plan in route_plans:
            route = routes[route_plan["route"]]
            route.set("native-normalized", "1")
            position = 0
            for spec in route_plan["processors"]:
                attrs = {
                    "id": take_id(),
                    "name": spec["plugin"],
                    "active": "1",
                    "type": "lv2" if spec["host_kind"] == "lv2" else "luaproc",
                }
                if spec["host_kind"] == "lv2":
                    attrs["unique-id"] = spec["plugin"]
                route.insert(position, ET.Element("Processor", attrs))
                position += 1

        # A native headless save may know about Dummy outputs.  The final
        # portable session must retain the scaffold Master output IO.
        master_output = next(
            io for io in routes["Master"].findall("IO") if io.get("direction") == "Output"
        )
        first_port = master_output.find("Port")
        ET.SubElement(first_port, "Connection", {"other": "system:playback_1"})

        # Non-routing native mutations to MIDI tracks must not escape the mix
        # transaction; only the live-routed Output IO is allowed through.
        routes["lead"].set("native-track-mutation", "must-not-survive")
        root.set("id-counter", str(next_id + 1))
        tree.write(result.session_file, encoding="UTF-8", xml_declaration=True)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="processing ok\nAmbition Ardour native mix graph configured\nAmbition Ardour processing configured\n",
            stderr="",
        )

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    completed = apply_ardour_processing(result, ardour_lua=arlua)
    assert completed.returncode == 0
    assert result.session_file.read_bytes() != before
    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert data["processing_transport"]["status"] == "applied"
    assert (
        data["processing_transport"]["session_merge"]
        == "libardour_native_bus_graph_onto_pristine_timing_scaffold"
    )

    root = ET.parse(result.session_file).getroot()
    routes = {route.get("name"): route for route in root.find("Routes")}
    melody = routes["AMB Group melody"]
    assert melody.get("native-normalized") == "1"
    assert any(proc.get("type") == "intreturn" for proc in melody.findall("Processor"))
    assert any(proc.get("name") == "ACE Amplifier" for proc in melody.findall("Processor"))
    assert routes["AMB Composition"].get("native-normalized") == "1"
    assert routes["Master"].get("native-normalized") == "1"

    def output_connections(route):
        return {
            conn.get("other")
            for io in route.findall("IO")
            if io.get("direction") == "Output"
            for port in io.findall("Port")
            for conn in port.findall("Connection")
        }

    # MIDI track state stays pristine except for the Ardour-created live output
    # routing that is the purpose of this transaction.
    lead = routes["lead"]
    assert lead.get("native-track-mutation") is None
    assert "AMB Group melody/audio_in 1" in output_connections(lead)
    assert "AMB Group rhythm/audio_in 1" in output_connections(routes["kit"])
    assert "AMB Composition/audio_in 1" in output_connections(melody)
    assert "Master/audio_in 1" in output_connections(routes["AMB Composition"])
    assert any(proc.get("name") == "ACE Reasonable Synth" for proc in lead.findall("Processor"))

    # Dummy/headless hardware routing is not allowed into the portable session.
    master_output = next(
        io for io in routes["Master"].findall("IO") if io.get("direction") == "Output"
    )
    assert ET.tostring(master_output, encoding="unicode") == ET.tostring(
        before_master_output, encoding="unicode"
    )
    master_input = next(
        io for io in routes["Master"].findall("IO") if io.get("direction") == "Input"
    )
    assert any(
        conn.get("other") == "AMB Composition/audio_out 1"
        for port in master_input.findall("Port")
        for conn in port.findall("Connection")
    )


def test_apply_ardour_processing_rejects_missing_native_bus_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    compiled = compile_score(_mix_transport_score())
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
        realize_processing=True,
    )
    before = result.session_file.read_bytes()
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")

    def fake_run(command, **kwargs):
        import subprocess

        # Pretend the Lua pass reached save/close but failed to create any of
        # the required native buses.  The serialized graph verifier must reject
        # this instead of trusting a completion string alone.
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Ambition Ardour processing configured\n",
            stderr="",
        )

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    with pytest.raises(ArdourExportError, match="native group bus missing"):
        apply_ardour_processing(result, ardour_lua=arlua)
    assert result.session_file.read_bytes() == before
    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert data["processing_transport"]["status"] == "failed"

def test_apply_ardour_processing_requires_completion_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    compiled = compile_score(_mix_transport_score())
    result = export_ardour_session(
        compiled,
        tmp_path / "session",
        realize_instruments=False,
        realize_processing=True,
    )
    before = result.session_file.read_bytes()
    arlua = tmp_path / "arlua"
    arlua.write_text("#!/bin/sh\n", encoding="utf8")

    def fake_run(command, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(command, 1, stdout="", stderr="late native failure\n")

    monkeypatch.setattr("ambition_music_renderer.ardour_export.subprocess.run", fake_run)
    monkeypatch.setattr(
        "ambition_music_renderer.ardour_export._serialized_processing_errors",
        lambda _result: [],
    )

    with pytest.raises(ArdourExportError, match="completion marker"):
        apply_ardour_processing(result, ardour_lua=arlua)
    assert result.session_file.read_bytes() == before
    data = json.loads(result.export_manifest.read_text(encoding="utf8"))
    assert data["processing_transport"]["status"] == "failed"


def test_ardour_processing_transport_reports_section_bus_dsp_gap():
    spec = _mix_transport_score()
    spec["processing"] = {
        "sections": {
            "a": {"chain": [{"processor": "gain", "gain_db": -2.0}]},
        }
    }
    compiled = compile_score(spec)
    transport = compile_processing_transport(compiled)
    assert any(
        "section a: section-bus ProcessingPlan is not transported yet" in warning
        for warning in transport.warnings
    )

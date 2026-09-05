# Instrument usage census

The checked-in `data/instrument_catalog.yaml` answers **what Ambition expects
authors to be able to request**. `SFZ_LIBRARY_SUMMARY.txt` answers **what is
installed on this machine**. The usage census answers **how an installed SFZ
program can be triggered and controlled**.

Generate it after installing/updating `/data/audio-tools`:

```bash
cd tools/ambition_music_renderer
./instrument_usage_census.sh
```

By default this writes:

- `/data/audio-tools/SFZ_USAGE_CENSUS.json` — structured machine-readable handoff
- `/data/audio-tools/SFZ_USAGE_CENSUS.md` — human/LLM-readable companion

The JSON is authoritative for observations about the current machine. It is
not the supported-instrument registry. Remote agents can choose normal
instruments from the checked-in catalog without this file; attach the census
when they need exact workstation paths, controller/keyswitch details, or
installation-health evidence.

The census is intentionally static and does **not** synthesize audio. For each
likely program/entry point it records:

- resolved path and registered aliases;
- playable MIDI key and velocity ranges;
- SFZ startup controller state;
- hard `loccNN` / `hiccNN` controller gates;
- compact feasible controller presets;
- controller crossfade breakpoints;
- CC-driven modulation opcodes and modulation amounts;
- keyswitch ranges/states;
- round-robin / sequence opcodes;
- sample-reference counts and missing sample references;
- compact activation zones used by Instrument Inspector for cheap preflight;
- a recommended backend and a conservative probe note/velocity/controller state.

This is descriptive metadata, not a claim that every reported parameter setting
sounds good. A patch can expose several articulation/controller zones; the census
preserves those alternatives instead of collapsing them into one hidden default.
`recommended_probe.controls` only supplies startup controls plus controller values
needed to reach a globally gated playable zone.

Obvious `modules/`, `includes/`, `maps*`, and similar helper SFZ files are skipped
by default, while every registered alias target is retained. Use `--all` when a
complete deep inventory is needed:

```bash
./instrument_usage_census.sh --all
```

Use `--root` to census another tree, and `--jobs 1` for deterministic serial
progress while debugging a malformed third-party library.

## Instrument Inspector integration

Instrument Inspector loads `SFZ_USAGE_CENSUS.json` once at startup when it is
present. Library clicks use the census's alias resolution and compact activation
zones rather than expanding a large SFZ on the Qt UI thread. The authoritative
expanded-region preflight still runs in the render subprocess when Play/Render
is requested.

If the census is absent or stale for the selected file, browsing stays cheap and
the inspector says that deep diagnostics are deferred until Render/Play. Rerun
the census after changing installed SFZ files.

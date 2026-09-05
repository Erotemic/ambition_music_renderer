# Instrument catalog and local inventory

Ambition has two deliberately separate instrument authorities.

## Checked-in authoring authority

`ambition_music_renderer/data/instrument_catalog.yaml` is the repository-side
contract for sampled instruments. It answers questions an authoring agent must
be able to answer from a source archive alone:

- which stable `library_ref` names Ambition supports;
- which family and musical role each ref represents;
- which downloader source supplies it in the normal authoring environment;
- which install profile supplies that source;
- how the resolver recognizes and ranks the intended SFZ entry point, including
  the canonical downloaded source when it is present;
- whether the instrument is a drum mapping;
- curated usage notes and library-specific setup or articulation caveats;
- the real-library smoke probes used to verify important patches.

Every catalog entry is expected to be available after the normal audio-tools
installer has completed successfully. A missing catalog instrument on a local
machine is an installation/environment defect. It is not evidence that an agent
should rewrite a score to avoid that instrument.

An agent does not need `/data/audio-tools` in order to compose against the
catalog. Discover the vocabulary directly from the repository:

```bash
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer instruments list

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer instruments describe guitar.emily

uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer instruments describe strings.violas
```

The normal authored form is intentionally small:

```yaml
instrument_backend:
  kind: sfz
  library_ref: strings.violas
```

Do not copy resolver `prefer` folklore or absolute `/data/audio-tools` paths
into scores when the catalog already identifies the desired role. A score may
add a `prefer` override when it intentionally requests a different realization
within that stable role.

## Machine-local inventory authority

The generated files under `AMBITION_AUDIO_TOOLS_ROOT` answer a different
question: what concrete files are installed on this machine now?

Typical artifacts are:

- `SFZ_LIBRARY_SUMMARY.txt`;
- `REFERENCE_SFZ_LIBRARY_REPORT.txt`;
- `SFZ_USAGE_CENSUS.json`;
- `SFZ_USAGE_CENSUS.md`.

The usage census can contain exact paths, parsed SFZ regions, playable ranges,
startup controllers, controller gates, keyswitches, sample-reference health,
and recommended probes. Those are observations of an installation and are
regenerated when the audio-tools tree changes. They must not become a second
list of supported authoring identities.

Check the local environment against the checked-in contract with:

```bash
AMBITION_AUDIO_TOOLS_ROOT=/data/audio-tools \
uv run --project tools/ambition_music_renderer \
  python -m ambition_music_renderer instruments doctor
```

The command checks both expected downloaded sample sources and the stable
`library_ref` roles resolved from them. It exits nonzero when either layer is
incomplete. Use `--warn_only` when collecting diagnostics on a deliberately
incomplete remote or CI machine.

## Resolution authority

MusicIR compatibility spellings and filesystem resolution are normalized by
`instrument_resolution.py`. Rendering, audits, cache identity, plugin
validation, and Instrument Inspector should consume its
`InstrumentResolutionPlan` rather than reinterpreting `library_ref`, `sfz`,
`prefer`, roots, optional/required behavior, or fallback fields themselves.

The flow is:

```text
instrument_catalog.yaml              /data/audio-tools
supported vocabulary                 installed files / census
          |                                   |
          +------------+----------------------+
                       |
              InstrumentResolutionPlan
                       |
        +--------------+----------------+
        |              |                |
     renderer         audit          inspector/cache
```

The catalog owns intent. The local inventory supplies evidence. When a catalog
role's declared source is installed, the resolver prefers patches from that
source before considering compatible fallbacks; a catalog entry can explicitly
disable that preference when the role intentionally targets an alternate
realization. The resolution plan is the one interpretation consumed by the rest
of the renderer.

## Adding or changing an instrument

When adding a downloaded sample library:

1. Teach `download_ambition_audio_tools.sh` how to install it and preserve its
   license/attribution requirements.
2. Add the source and stable musical identities to
   `data/instrument_catalog.yaml`.
3. Put ordinary filename-selection heuristics in the catalog resolver hints,
   not in individual scores.
4. Add or update a catalog `smoke_profiles` entry when a real patch has startup
   CC, keyswitch, drum-map, pitch, or sample-layout behavior worth continuously
   checking. These profiles are also exposed by `instruments describe` so a
   source-only agent can see known patch-level controls without the sample tree.
5. Run `instruments doctor`, `plugins smoke_sfz`, and the targeted renderer
   tests.
6. Regenerate the usage census on a machine with the installed library when its
   parsed machine-local behavior changed.

Do not add a second hard-coded alias table, inspector list, or smoke-candidate
list. Those are consumers of the catalog.

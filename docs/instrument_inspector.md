# Instrument Inspector

`./instrument_inspector.sh` is a standalone, score-independent patch browser and
probe auditioner. It deliberately does not own or save a MusicIR score.

It reuses the renderer's existing instrument infrastructure:

- named GM/SoundFont programs, grouped by General MIDI family;
- registered `instrument_libraries.py` aliases, grouped by namespace;
- an optional scan of every installed `.sfz`, grouped by its library/directory hierarchy;
- the same per-instrument backend fields used by MusicIR (`instrument_backend`,
  controls, `mix_gain_db`, note remaps, backend settings, etc.);
- the same built-in group processing and ordered `effect_chain` surface used by
  score `group_postprocess` blocks.

The two YAML editors are authoritative. Clicking a concrete browser entry
immediately applies it to the disposable instrument document and invalidates
any previous probe audio; there is no second load/apply step. Load From Score
copies one instrument definition and that group's processing into the
inspector. Export writes reusable YAML snippets only; it never modifies the
source score.

## Audition phrases

Play means **audition the exact configuration currently shown**. If that
instrument definition, processing YAML, and audition phrase are already
rendered, playback starts immediately. If they are valid but dirty/unrendered,
Play first renders that exact probe and then starts playback automatically.
Any subsequent library selection, YAML edit, root/key change, phrase-template
change, or backend change forgets the old media. An unresolved SFZ selection
cannot be rendered or played as if it were the requested patch. If the
selection changes while a render is running, the completed stale render is not
attached or played.

Pitched instruments default to a repeatable **major scale + arpeggio** phrase.
A natural-minor equivalent and a single-note probe are also available. Drum
kits default to a deliberately plain **two-bar rock backbeat** with MIDI crash
49 on the entrance, eighth-note closed hi-hat, kick, and snare. A kit-essentials
one-shot walk and a single-key probe are also available.

The renderer writes both dry and processed versions under
`agent/instrument_inspector/probes/`, so the transport can A/B the instrument
against its current processing chain.

Effect templates are only starters. Once inserted, edit their YAML directly.
The normal renderer remains the schema authority for Pedalboard, VST3, LV2,
Guitarix/NAM command adapters, built-in EQ/compression/reverb, and wet/dry
parameters.

## Terminal behavior

The Instrument Inspector and Stem Lab install the same Qt SIGINT bridge. Ctrl+C
in the launching terminal closes the window through its normal close handler so
media and child render processes are torn down instead of leaving the Qt event
loop running.

## SFZ diagnostics

For an SFZ selection, the inspector preflights the canonical probe against the
expanded SFZ region map before enabling Render/Play. The diagnostics panel
reports the parsed key span, region count, whether the probe pitches and
velocities can select regions, referenced-sample availability, SFZ `set_cc`
defaults, and controller gates such as `locc107` / `hicc107`.

If every otherwise-eligible region is blocked by a controller value, Render and
Play are disabled instead of producing a known-silent probe. When the allowed
controller range is unambiguous, **Apply suggested controls** adds an explicit
`controls:` entry to the disposable Instrument YAML. The inspector does not
apply inferred controller state to scores or to the renderer globally.

Instrument Inspector renders SFZ probes with strict backend selection. A broken
or silent selected SFZ is therefore reported as that SFZ's failure; it is never
accepted as a successful probe merely because the normal score renderer could
fall back to GM/SoundFont.

## Usage census and browsing cost

For large installed SFZ trees, generate the machine-local usage census with
`./instrument_usage_census.sh`. The Inspector loads it at startup and uses its
compact activation metadata for library browsing and controller suggestions.
This keeps selection changes off the expensive expanded-SFZ parse path. The
full parser remains authoritative when a probe is actually rendered.

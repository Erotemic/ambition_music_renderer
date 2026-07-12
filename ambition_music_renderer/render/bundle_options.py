"""Shared cue-bundle option schema (lightweight, no heavy deps).

The single-cue renderer config (:class:`~.bundle_base.CueBundleConfig`) and the
multi-cue orchestrator (``cli.BundleCommand``) need the same per-cue knobs but
live in different modules with very different import weights. Declaring those
knobs once here — in a module that only imports ``kwconf`` and ``pathlib`` — lets
both inherit them without dragging numpy/yaml into the light top-level CLI and
without the two field lists drifting apart.
"""

from __future__ import annotations

from pathlib import Path

import kwconf

DEFAULT_BACKEND = "pretty-midi"
BACKEND_CHOICES = ("pretty-midi", "fluidsynth-cli", "fallback", "auto")
RUNTIME_STEM_GAIN_MODES = ("native", "shared")
PLOT_FORMATS = ("jpg", "png")
RENDER_AUDIO_MODES = ("full", "full-mix-only", "simple-mix")


class BundleOptions(kwconf.Config):
    """Per-cue bundle knobs shared by the single-cue and multi-cue configs.

    Deliberately declares no positional cue field and no ``jobs`` field. The
    one-cue renderer uses ``jobs`` for stem-group workers; the top-level command
    resolves ``jobs`` the same way for one cue but uses it for cue-level fan-out
    when several cues are supplied.
    """

    backend: str = kwconf.Value(DEFAULT_BACKEND, choices=list(BACKEND_CHOICES))
    runtime_stem_gain_mode: str = kwconf.Value(
        "native",
        choices=list(RUNTIME_STEM_GAIN_MODES),
        help=(
            "runtime adaptive stem export mode: native preserves current raw "
            "levels; shared applies one shared reference gain across all stems"
        ),
    )
    runtime_stem_max_gain_db: float | None = kwconf.Value(
        None,
        help="cap shared runtime stem gain; default is renderer policy or YAML render.runtime_stems.max_gain_db",
    )
    outdir: Path | None = kwconf.Value(None, parser=Path)
    bundle_root: Path | None = kwconf.Value(None, parser=Path)
    force: bool = kwconf.Flag(False, help="force render regeneration")
    publish: bool = kwconf.Flag(False, help="publish full.ogg to game assets after rendering")
    dest_root: Path | None = kwconf.Value(None, parser=Path, help="game music generated asset root")
    zip_bundle: bool = kwconf.Flag(
        False,
        alias=["zip"],
        help="write a complete uploadable bundle zip including manifest-referenced audio",
    )
    zip_report_bundle: bool = kwconf.Flag(
        False,
        alias=["zip_report"],
        help="write a compact report zip excluding OGG/WAV/NPY/MIDI binaries",
    )
    plot_format: str = kwconf.Value(
        "jpg",
        choices=list(PLOT_FORMATS),
        help="spectrogram image format for bundles; jpg is much smaller and reports keep numeric values",
    )
    jpeg_quality: int = kwconf.Value(84, help="JPEG quality for spectrogram plots")
    include_scratch_stems: bool = kwconf.Flag(
        False,
        help="include raw scratch_stems/*.npy in the bundle zip; useful but can be large",
    )
    skip_render: bool = kwconf.Flag(False, help="bundle/analyze existing outdir")
    spectrograms: bool = kwconf.Flag(False, help="write spectrogram plots; off by default")
    all_audits: bool = kwconf.Flag(False, help="run full cue-bundle diagnostic audits")
    render_audio_mode: str = kwconf.Value(
        "full",
        choices=list(RENDER_AUDIO_MODES),
        help=(
            "audio export scope for render_isolated. full preserves all adaptive "
            "stem/state preview OGGs; full-mix-only keeps scratch stems plus "
            "mastered preview and section full mixes; simple-mix writes only the "
            "mastered preview."
        ),
    )
    profile_render: bool = kwconf.Flag(
        False,
        help="enable LINE_PROFILE=1 and run render_isolated plus serial workers in-process for line_profiler",
    )
    render_in_process: bool = kwconf.Flag(
        False,
        help="debug/profiling mode: import and run render_isolated instead of launching it as a subprocess",
    )
    json: bool = kwconf.Flag(False, help="print the full bundle JSON payload to stdout")

    def __post_init__(self) -> None:
        self.jpeg_quality = int(self.jpeg_quality)
        for key in ("outdir", "bundle_root", "dest_root"):
            value = getattr(self, key)
            if value is not None and not isinstance(value, Path):
                setattr(self, key, Path(value))


#: Field names declared on :class:`BundleOptions`, used to copy passthrough
#: options between the orchestrator and a per-cue config without a hand-kept list.
PASSTHROUGH_FIELDS = tuple(BundleOptions.__annotations__)

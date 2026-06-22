"""kwconf command entry point for the low-level MusicIR renderer."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import kwconf

from .group import render_all

class MusicIRRenderConfig(kwconf.Config):
    """Render Ambition MusicIR YAML to adaptive OGG assets."""


    spec: Path = kwconf.Value(None, position=1, parser=Path, help="Path to .music.yaml source")
    outdir: Path = kwconf.Value(Path("output"), parser=Path, help="Output directory")
    backend: str | None = kwconf.Value(None, choices=["auto", "fallback", "fluidsynth-cli", "pretty-midi", "sfizz", "sfizz-render"])
    soundfont: str | None = kwconf.Value(None)
    keep_wav: bool = kwconf.Flag(False)
    keep_midi: bool = kwconf.Flag(False)
    verbose: bool = kwconf.Flag(False)

    @classmethod
    def main(cls, argv: list[str] | str | bool | None = True, **kwargs: object) -> int:
        config = cls.cli(argv=argv, data=kwargs)
        result = render_all(config)
        print(json.dumps(result, indent=2))
        return 0


def main(argv: list[str] | None = None) -> int:
    return MusicIRRenderConfig.main(argv=argv)


if __name__ == "__main__":
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(main())

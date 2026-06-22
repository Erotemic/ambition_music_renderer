#!/usr/bin/env python3
"""Compatibility facade for the split MusicIR renderer modules.

The implementation now lives in focused modules under ``ambition_music_renderer.render``:
``score``, ``synth``, ``effects``, ``export``, ``group``, and ``musicir_config``.
This module re-exports the historical public names so older imports such as
``from ambition_music_renderer.render import musicir_renderer as r`` keep working.
"""

from __future__ import annotations

from . import score as _score
from . import synth as _synth
from . import effects as _effects
from . import export as _export
from . import group as _group
from . import musicir_config as _musicir_config

globals().update({k: v for k, v in vars(_score).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_synth).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_effects).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_export).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_group).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_musicir_config).items() if not k.startswith("__")})

if __name__ == "__main__":
    raise SystemExit(main())

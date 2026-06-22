"""Compatibility facade for split MusicIR score modules."""

from __future__ import annotations

from . import score_core as _core
from . import score_theory as _theory
from . import score_events as _events
from . import score_layers as _layers

globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_theory).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_events).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_layers).items() if not k.startswith("__")})

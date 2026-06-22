"""Compatibility facade for split bundle report helpers."""

from __future__ import annotations

from . import bundle_audio_reports as _bundle_audio_reports
from . import bundle_spectral_reports as _bundle_spectral_reports
from . import bundle_adaptive_reports as _bundle_adaptive_reports
from . import bundle_spectrograms as _bundle_spectrograms

globals().update({k: v for k, v in vars(_bundle_audio_reports).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_bundle_spectral_reports).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_bundle_adaptive_reports).items() if not k.startswith("__")})
globals().update({k: v for k, v in vars(_bundle_spectrograms).items() if not k.startswith("__")})

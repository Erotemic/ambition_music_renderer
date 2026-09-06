#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$HERE" --with 'PySide6>=6.6' \
  python -m ambition_music_renderer.music_review_gui "$@"

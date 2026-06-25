#!/usr/bin/env bash
# Easy entry point
# Usage:
#   ./render_music.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f /data/audio-tools/env.sh ]]; then
    # Expose user-downloaded SFZ, LV2, VST3, and CLAP search paths.
    # shellcheck disable=SC1091
    source /data/audio-tools/env.sh
fi

uv run --project "$SCRIPT_DIR" \
    python -m ambition_music_renderer "$@"


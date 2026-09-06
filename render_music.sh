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

# The optional audio-tools environment prepends its private LV2 directory but
# must not hide the system Guitarix packages used by the amp-chain scores.
export LV2_PATH="${LV2_PATH:+${LV2_PATH}:}/usr/lib/lv2"

uv run --project "$SCRIPT_DIR" \
    python -m ambition_music_renderer "$@"

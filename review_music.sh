#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The GUI's Render button runs the renderer as a child process, which needs the
# same SFZ/LV2/VST3/CLAP search paths render_music.sh exposes.
if [[ -f "${AMBITION_AUDIO_TOOLS_ROOT:-/data/audio-tools}/env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${AMBITION_AUDIO_TOOLS_ROOT:-/data/audio-tools}/env.sh"
fi
# The audio-tools env prepends its private LV2 directory but must not hide the
# system Guitarix packages the amp-chain scores use.
export LV2_PATH="${LV2_PATH:+${LV2_PATH}:}/usr/lib/lv2"

# `--extra optional`: Render needs pedalboard for the `kind: pedalboard` chains.
exec uv run --project "$HERE" --extra optional --with 'PySide6>=6.6' \
  python -m ambition_music_renderer.music_review_gui "$@"

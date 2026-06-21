#!/usr/bin/env bash
# Render and analyze an isolated first-goblin intro->wave1 transition experiment.
#
# This intentionally does not edit scores/active and does not install into the
# sandbox crate asset tree. It is for debugging generated audio outside the game.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
renderer_dir="$repo_root/tools/ambition_music_renderer"
cd "$repo_root"

backend="${AMBITION_MUSIC_BACKEND:-pretty-midi}"
force=0
jobs=""
clean=0
transition_crossfade="0.65"
crossfade_shape="equal_power"
crossfade_explicit=0
source_score="$renderer_dir/scores/active/first_goblin_tune_v2.music.yaml"
experiment_score="$renderer_dir/scores/experiments/first_goblin_transition_lab.music.yaml"
outdir="$renderer_dir/generated/transition_lab/first_goblin_transition_lab"
keep_existing_score=0

usage() {
    sed -n '1,20p' "$0" | sed 's/^# \{0,1\}//'
    cat <<'EOF'

Usage:
  ./tools/ambition_music_renderer/render_first_goblin_transition_lab.sh [options]

Options:
  --force                 Force renderer regeneration.
  --clean                 Remove the experiment output directory first.
  --jobs N                Pass --jobs N to render_isolated.py.
  --backend NAME          pretty-midi|fluidsynth-cli|fallback|auto.
  --crossfade SECONDS     Transition-audit preview crossfade. Default: 0.65.
  --crossfade-shape SHAPE  linear|equal_power. Default: equal_power.
  --source PATH           Active/base score to derive from.
  --score PATH            Experiment score path to write/use.
  --outdir PATH           Experiment render output directory.
  --keep-existing-score   Do not overwrite an existing experiment score.
  -h, --help              Show this help.

Outputs:
  tools/ambition_music_renderer/scores/experiments/first_goblin_transition_lab.music.yaml
  tools/ambition_music_renderer/generated/transition_lab/first_goblin_transition_lab/
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) force=1; shift ;;
        --clean) clean=1; shift ;;
        --jobs|-j) jobs="$2"; shift 2 ;;
        --backend) backend="$2"; shift 2 ;;
        --crossfade) transition_crossfade="$2"; crossfade_explicit=1; shift 2 ;;
        --crossfade-shape) crossfade_shape="$2"; crossfade_explicit=1; shift 2 ;;
        --source) source_score="$2"; shift 2 ;;
        --score) experiment_score="$2"; shift 2 ;;
        --outdir) outdir="$2"; shift 2 ;;
        --keep-existing-score) keep_existing_score=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ "$clean" -eq 1 ]]; then
    rm -rf "$outdir"
fi

make_args=(
    --source "$source_score"
    --output "$experiment_score"
)
if [[ "$keep_existing_score" -eq 0 ]]; then
    make_args+=(--force)
fi
python "$renderer_dir/make_first_goblin_transition_lab.py" "${make_args[@]}"

render_args=(
    "$experiment_score"
    --outdir "$outdir"
    --backend "$backend"
)
if [[ "$force" -eq 1 ]]; then
    render_args+=(--force)
fi
if [[ -n "$jobs" ]]; then
    render_args+=(--jobs "$jobs")
fi

(
    cd "$renderer_dir"
    python -m ambition_music_renderer.render_isolated "${render_args[@]}"
)

python "$renderer_dir/audit_cue_balance.py" "$outdir" || true

# Keep alternate crossfade previews side-by-side. The default run keeps the
# historical transition_audit/ path, but explicit --crossfade runs write into a
# labeled sibling so 0.35s and 0.65s reports do not silently overwrite each other.
audit_outdir="$outdir/transition_audit"
if [[ "$crossfade_explicit" -eq 1 ]]; then
    crossfade_label="${transition_crossfade//./p}"
    crossfade_label="${crossfade_label//[^0-9p]/_}"
    shape_label="${crossfade_shape//-/_}"
    audit_outdir="$outdir/transition_audit_xfade_${crossfade_label}_${shape_label}"
else
    audit_outdir="$outdir/transition_audit_equal_power"
fi
python "$renderer_dir/transition_audit.py" "$outdir" --sections intro wave1 --crossfade "$transition_crossfade" --crossfade-shape "$crossfade_shape" --outdir "$audit_outdir"

cat <<EOF

Experiment score:
  $experiment_score

Generated output:
  $outdir

Audition previews:
  $audit_outdir/intro_to_wave1_runtime_preview.wav
  $audit_outdir/intro_to_wave1_level_matched_preview.wav

EOF

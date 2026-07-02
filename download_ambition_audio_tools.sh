#!/usr/bin/env bash
# Download/install free SFZ sample libraries and open plugin bundles for the
# Ambition music renderer.
# Usage:
#   ./download_ambition_audio_tools.sh [ROOT]
#   MODE=starter ./download_ambition_audio_tools.sh /data/audio-tools
#   MODE=pro     ./download_ambition_audio_tools.sh /data/audio-tools
#   MODE=all     ./download_ambition_audio_tools.sh /data/audio-tools
#   PLUGINS=0    ./download_ambition_audio_tools.sh /data/audio-tools
#   ORCHESTRA_EXTRAS=0 ./download_ambition_audio_tools.sh /data/audio-tools
#   DRY_RUN=1    ./download_ambition_audio_tools.sh /data/audio-tools

set -euo pipefail

ROOT="${1:-/data/audio-tools}"
MODE="${MODE:-pro}"  # starter | pro | all
DRY_RUN="${DRY_RUN:-0}"
PLUGINS="${PLUGINS:-1}"
SOUNDFONTS="${SOUNDFONTS:-1}"
ORCHESTRA_EXTRAS="${ORCHESTRA_EXTRAS:-1}"
ARCHIVES="$ROOT/archives"
SFZ_ROOT="$ROOT/sfz"
SOUNDFONT_ROOT="$ROOT/soundfonts"
PLUGIN_ROOT="$ROOT/plugins"
PLUGIN_ARCHIVES="$ARCHIVES/plugins"
PLUGIN_UNPACKED="$PLUGIN_ROOT/unpacked"
CLAP_ROOT="$PLUGIN_ROOT/clap"
LV2_ROOT="$PLUGIN_ROOT/lv2"
VST3_ROOT="$PLUGIN_ROOT/vst3"
INBOX="$ROOT/inbox"
LOG_DIR="$ROOT/logs"
MANUAL="$ROOT/MANUAL_DOWNLOADS.md"
SUMMARY="$ROOT/SFZ_LIBRARY_SUMMARY.txt"
PLUGIN_SUMMARY="$ROOT/PLUGIN_LIBRARY_SUMMARY.txt"
REFERENCE_SUMMARY="$ROOT/REFERENCE_SFZ_LIBRARY_REPORT.txt"
SOUNDFONT_SUMMARY="$ROOT/SOUNDFONT_SUMMARY.txt"
PYTHON_TOOLS_REPORT="$ROOT/PYTHON_AUDIO_TOOLS_REPORT.txt"
APT_HINTS="$ROOT/APT_AUDIO_PLUGIN_PACKAGES.md"
ENV_FILE="$ROOT/env.sh"

mkdir -p "$ARCHIVES" "$SFZ_ROOT" "$SOUNDFONT_ROOT" "$PLUGIN_ARCHIVES" "$PLUGIN_UNPACKED" "$CLAP_ROOT" "$LV2_ROOT" "$VST3_ROOT" "$INBOX" "$LOG_DIR"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

need_cmds=(curl unzip tar find sed awk file python3)
missing=()
for c in "${need_cmds[@]}"; do
    if ! have_cmd "$c"; then
        missing+=("$c")
    fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing required commands: ${missing[*]}" >&2
    echo "Install them first, then rerun." >&2
    exit 2
fi

if ! have_cmd 7z && ! have_cmd 7za; then
    echo "Warning: 7z/7za not found. FreePats Upright Piano KW is a .7z archive." >&2
    echo "On Debian/Ubuntu: sudo apt install p7zip-full" >&2
fi

seven_zip() {
    if have_cmd 7z; then
        7z "$@"
    else
        7za "$@"
    fi
}

log() { printf '[audio-tools] %s\n' "$*"; }

safe_name_from_url() {
    local url="$1"
    basename "${url%%\?*}" | sed 's/%2B/+/g; s/%20/_/g'
}

download() {
    local url="$1"
    local dest="$2"
    local label="$3"
    if [[ -s "$dest" ]]; then
        log "archive exists: $dest"
        return 0
    fi
    log "downloading: $label"
    log "url: $url"
    if [[ "$DRY_RUN" == "1" ]]; then
        log "dry-run: would download to $dest"
        return 0
    fi
    local tmp="$dest.partial"
    rm -f "$tmp"
    if ! curl --fail --location --retry 5 --retry-delay 2 --continue-at - --output "$tmp" "$url"; then
        rm -f "$tmp"
        log "download failed: $label"
        return 1
    fi
    mv "$tmp" "$dest"
}

is_zip_file() {
    local path="$1"
    [[ -s "$path" ]] || return 1
    file "$path" | grep -qiE 'Zip archive|Microsoft OOXML|Java archive'
}

# Marker is per-archive: several archives can legitimately share one dest
# (VPO extracts its SFZ-scripts zip AND its wave-files zip into the same
# tree). A single shared marker made whichever archive arrived second a
# silent no-op - that is how a scripts-only (silent) VPO install happens.
# The legacy shared marker is still honored for single-archive dests so a
# pre-existing install does not re-download everything.
extraction_marker() {
    local archive_name="$1"
    local dest="$2"
    printf '%s/.ambition_audio_tools_extracted.%s' "$dest" "$(basename "$archive_name")"
}

already_extracted() {
    local archive_name="$1"
    local dest="$2"
    if [[ -e "$(extraction_marker "$archive_name" "$dest")" ]]; then
        return 0
    fi
    if [[ -e "$dest/.ambition_audio_tools_extracted" && "$dest" != *Virtual-Playing-Orchestra* ]]; then
        return 0
    fi
    return 1
}

extract_archive() {
    local archive="$1"
    local dest="$2"
    local label="$3"
    local marker
    marker="$(extraction_marker "$archive" "$dest")"
    if already_extracted "$archive" "$dest"; then
        log "already extracted: $label -> $dest"
        return 0
    fi
    mkdir -p "$dest"
    log "extracting: $label -> $dest"
    case "$archive" in
        *.tar.gz|*.tgz)
            tar -xzf "$archive" -C "$dest" --strip-components=1 || tar -xzf "$archive" -C "$dest"
            ;;
        *.tar.xz|*.txz)
            tar -xJf "$archive" -C "$dest" --strip-components=1 || tar -xJf "$archive" -C "$dest"
            ;;
        *.zip)
            unzip -o "$archive" -d "$dest"
            ;;
        *.7z)
            if have_cmd 7z || have_cmd 7za; then
                seven_zip x -y "-o$dest" "$archive"
            else
                log "cannot extract .7z without p7zip-full: $archive"
                return 1
            fi
            ;;
        *.deb)
            if have_cmd dpkg-deb; then
                dpkg-deb -x "$archive" "$dest"
            else
                log "cannot extract .deb without dpkg-deb: $archive"
                return 1
            fi
            ;;
        *)
            log "unknown archive type: $archive"
            return 1
            ;;
    esac
    date -Iseconds > "$marker"
}

download_and_extract() {
    local label="$1"
    local url="$2"
    local archive_name="$3"
    local dest_dir="$4"
    local archive="$ARCHIVES/$archive_name"
    # An installed library must not force a re-download just because the
    # archive cache was pruned (VCSL alone is ~4 GB).
    if [[ "$DRY_RUN" != "1" ]] && already_extracted "$archive_name" "$dest_dir"; then
        log "already extracted (skipping download): $label -> $dest_dir"
        return 0
    fi
    download "$url" "$archive" "$label"
    if [[ "$DRY_RUN" == "1" ]]; then
        return 0
    fi
    extract_archive "$archive" "$dest_dir" "$label"
}

download_and_extract_optional() {
    local label="$1"
    local url="$2"
    local archive_name="$3"
    local dest_dir="$4"
    if ! download_and_extract "$label" "$url" "$archive_name" "$dest_dir"; then
        log "optional download failed or could not be extracted: $label"
        log "manual fallback may be listed in $MANUAL"
        return 1
    fi
}

download_file_optional() {
    local label="$1"
    local url="$2"
    local archive_name="$3"
    local dest_path="$4"
    local archive="$ARCHIVES/$archive_name"
    if [[ -s "$dest_path" ]]; then
        log "file exists: $dest_path"
        return 0
    fi
    if ! download "$url" "$archive" "$label"; then
        log "optional download failed: $label"
        log "manual fallback may be listed in $MANUAL"
        return 1
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        return 0
    fi
    mkdir -p "$(dirname "$dest_path")"
    cp -f "$archive" "$dest_path"
}

want_pro() { [[ "$MODE" == "pro" || "$MODE" == "all" ]]; }
want_all() { [[ "$MODE" == "all" ]]; }

github_latest_asset_url() {
    local repo="$1"
    local pattern="$2"
    python3 - "$repo" "$pattern" <<'PY'
import json
import re
import sys
import urllib.request
repo, pattern = sys.argv[1:3]
rx = re.compile(pattern, re.I)
url = f"https://api.github.com/repos/{repo}/releases/latest"
try:
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.load(resp)
except Exception as ex:
    print(f"ERROR {repo}: {ex}", file=sys.stderr)
    raise SystemExit(1)
assets = data.get("assets") or []
for asset in assets:
    name = asset.get("name") or ""
    if rx.search(name):
        print(asset.get("browser_download_url") or "")
        raise SystemExit(0)
print(f"ERROR {repo}: no asset matched {pattern!r}. Assets: " + ", ".join(a.get("name", "") for a in assets), file=sys.stderr)
raise SystemExit(1)
PY
}

download_github_release_asset() {
    local label="$1"
    local repo="$2"
    local pattern="$3"
    local dest_dir="$4"
    log "locating latest GitHub release asset: $label ($repo)"
    if [[ "$DRY_RUN" == "1" ]]; then
        log "dry-run: would query GitHub releases for $repo and extract matching assets to $dest_dir"
        return 0
    fi
    local url
    if ! url="$(github_latest_asset_url "$repo" "$pattern")"; then
        log "could not locate GitHub release asset for $label"
        return 1
    fi
    local archive_name
    archive_name="$(safe_name_from_url "$url")"
    download_and_extract_optional "$label" "$url" "$archive_name" "$dest_dir"
}

try_download_vpo_zip() {
    local label="$1"
    local url="$2"
    local archive_name="$3"
    local dest_dir="$4"
    local archive="$ARCHIVES/$archive_name"
    if [[ "$DRY_RUN" != "1" ]] && already_extracted "$archive_name" "$dest_dir"; then
        log "already extracted (skipping download): $label -> $dest_dir"
        return 0
    fi
    if [[ ! -s "$archive" ]]; then
        if ! download "$url" "$archive" "$label"; then
            log "VPO auto-download failed; see $MANUAL"
            return 1
        fi
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        return 0
    fi
    if ! is_zip_file "$archive"; then
        log "VPO URL did not yield a zip file: $archive"
        log "Keeping it for inspection and writing manual instructions."
        return 1
    fi
    extract_archive "$archive" "$dest_dir" "$label"
}

try_download_vpo_zip_from_sources() {
    local label="$1"
    local archive_name="$2"
    local dest_dir="$3"
    shift 3
    local base stem ext index url tagged_archive
    base="$archive_name"
    stem="${base%.zip}"
    ext=".zip"
    index=0
    for url in "$@"; do
        index=$((index + 1))
        tagged_archive="${stem}.source${index}${ext}"
        if try_download_vpo_zip "$label source $index" "$url" "$tagged_archive" "$dest_dir"; then
            log "VPO source $index succeeded for: $label"
            return 0
        fi
    done
    log "all VPO auto-download sources failed for: $label"
    log "manual fallback is required; see $MANUAL"
    return 1
}

archive_list() {
    local archive="$1"
    case "$archive" in
        *.zip)
            unzip -l "$archive" 2>/dev/null | awk '{print $4}'
            ;;
        *.tar.gz|*.tgz)
            tar -tzf "$archive" 2>/dev/null
            ;;
        *.tar.xz|*.txz)
            tar -tJf "$archive" 2>/dev/null
            ;;
        *.7z)
            if have_cmd 7z || have_cmd 7za; then
                seven_zip l "$archive" 2>/dev/null | awk '{print $NF}'
            fi
            ;;
        *.deb)
            if have_cmd dpkg-deb; then
                dpkg-deb -c "$archive" 2>/dev/null | awk '{print $NF}'
            fi
            ;;
    esac
}

archive_contains_pattern() {
    local archive="$1"
    local pattern="$2"
    archive_list "$archive" | grep -Eiq "$pattern"
}

normalize_vpo_tree() {
    # The VPO script zips and wave zip disagree about nesting (some carry a
    # top-level Virtual-Playing-Orchestra3/ folder, some do not). The SFZ
    # scripts reference samples as ..\libs\..., so libs/ must live NEXT TO the
    # instrument folders (Strings/, Brass/, ...). Find where the instrument
    # folders actually are and move a stray sibling libs/ in with them.
    local dest="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        return 0
    fi
    [[ -d "$dest" ]] || return 0
    local inner=""
    if [[ -d "$dest/Strings" ]]; then
        inner="$dest"
    else
        inner="$(find "$dest" -mindepth 1 -maxdepth 3 -type d -name Strings 2>/dev/null | head -n 1)"
        inner="${inner%/Strings}"
    fi
    [[ -n "$inner" ]] || return 0
    if [[ ! -d "$inner/libs" ]]; then
        local libs
        libs="$(find "$dest" -mindepth 1 -maxdepth 3 -type d -name libs -not -path "$inner/*" 2>/dev/null | head -n 1)"
        if [[ -n "$libs" ]]; then
            log "VPO: moving $libs -> $inner/libs so ..\\libs\\ sample paths resolve"
            mv "$libs" "$inner/libs"
        fi
    fi
}

validate_vpo_install() {
    local dest="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        return 0
    fi
    local sfz_count sample_count nbo_count libs_count
    sfz_count="$(find "$dest" -type f -iname '*.sfz' 2>/dev/null | wc -l | tr -d ' ')"
    sample_count="$(find "$dest" -type f \( -iname '*.wav' -o -iname '*.flac' -o -iname '*.ogg' \) 2>/dev/null | wc -l | tr -d ' ')"
    nbo_count="$(find "$dest" -type f -path '*/libs/NoBudgetOrch/*' \( -iname '*.wav' -o -iname '*.flac' -o -iname '*.ogg' \) 2>/dev/null | wc -l | tr -d ' ')"
    libs_count="$(find "$dest" -type d -name libs 2>/dev/null | wc -l | tr -d ' ')"
    log "VPO check: sfz=$sfz_count samples=$sample_count libs_dirs=$libs_count NoBudgetOrch_samples=$nbo_count"
    if [[ "$sfz_count" -gt 0 && "$sample_count" -eq 0 ]]; then
        log "WARNING: VPO scripts are present but wave samples are missing; vpo.* aliases will resolve but render silent."
        log "Download the VPO Wave Files archive in a browser, put it in $INBOX, and rerun this script."
        return 1
    fi
    if [[ "$sfz_count" -gt 0 && "$nbo_count" -eq 0 ]]; then
        log "WARNING: VPO NoBudgetOrch samples were not found under libs/NoBudgetOrch."
        log "The VPO install is incomplete or extracted with the wrong nesting; vpo strings/brass/choir may be silent."
        return 1
    fi
    return 0
}

write_reference_sfz_report() {
    if [[ "$DRY_RUN" == "1" ]]; then
        return 0
    fi
    python3 - "$ROOT" "$SFZ_ROOT" "$REFERENCE_SUMMARY" <<'PY_AUDIT'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sfz_root = Path(sys.argv[2])
out_path = Path(sys.argv[3])

sample_rx = re.compile(r"(?:^|\s)sample=([^\s>]+)")
default_rx = re.compile(r"(?:^|\s)default_path=([^\s>]+)")

sample_exts = {".wav", ".flac", ".ogg", ".aif", ".aiff"}


def norm_rel(value: str) -> Path:
    value = value.strip().strip('"').strip("'")
    value = value.replace('\\\\', '/').replace('\\', '/')
    return Path(value)


def audit_sfz(path: Path) -> tuple[int, int, list[str]]:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return 0, 0, []
    default_path = Path("")
    m = default_rx.search(text)
    if m:
        default_path = norm_rel(m.group(1))
    total = 0
    missing = []
    for m in sample_rx.finditer(text):
        raw = m.group(1).strip().strip('"').strip("'")
        if not raw:
            continue
        rel = norm_rel(raw)
        total += 1
        candidates = []
        if rel.is_absolute():
            candidates.append(rel)
        else:
            candidates.append(path.parent / default_path / rel)
            candidates.append(path.parent / rel)
            candidates.append(path.parent.parent / "Samples" / rel)
            candidates.append(path.parent.parent.parent / "Samples" / rel)
        try:
            found = any(c.exists() for c in candidates)
        except OSError:
            # Transient EMFILE on virtiofs must not kill the whole report;
            # treat the sample as present rather than false-positive it.
            found = True
        if not found:
            if len(missing) < 8:
                missing.append(raw)
    return total, total - len(missing), missing


def count_files(base: Path, pattern: str) -> int:
    if not base.exists():
        return 0
    return sum(1 for _ in base.rglob(pattern))

checks = []
checks.append(("FreePats Salamander", count_files(sfz_root / "FreePats" / "SalamanderGrandPiano", "*.sfz"), count_files(sfz_root / "FreePats" / "SalamanderGrandPiano", "*.flac")))
checks.append(("FreePats Upright Piano KW", count_files(sfz_root / "FreePats" / "UprightPianoKW", "*.sfz"), count_files(sfz_root / "FreePats" / "UprightPianoKW", "*.flac")))
checks.append(("VPO", count_files(sfz_root / "Virtual-Playing-Orchestra3", "*.sfz"), count_files(sfz_root / "Virtual-Playing-Orchestra3", "*.wav")))
checks.append(("Karoryfer Shinyguitar", count_files(sfz_root / "Karoryfer" / "Shinyguitar", "*.sfz"), count_files(sfz_root / "Karoryfer" / "Shinyguitar", "*.wav")))
checks.append(("Karoryfer WarTuba", count_files(sfz_root / "Karoryfer" / "WarTuba", "*.sfz"), count_files(sfz_root / "Karoryfer" / "WarTuba", "*.wav")))
checks.append(("Karoryfer BlackAndGreenGuitars", count_files(sfz_root / "Karoryfer" / "BlackAndGreenGuitars", "*.sfz"), count_files(sfz_root / "Karoryfer" / "BlackAndGreenGuitars", "*.wav")))

sfz_files = sorted(sfz_root.rglob("*.sfz")) if sfz_root.exists() else []
problem_rows = []
for sfz in sfz_files:
    total, present_est, missing = audit_sfz(sfz)
    if total and missing:
        problem_rows.append((len(missing), total, sfz, missing))
problem_rows.sort(key=lambda row: (-row[0], str(row[2]).lower()))

vpo_root = sfz_root / "Virtual-Playing-Orchestra3"
# NB: the audio files live several levels below NoBudgetOrch (Section/Articulation/
# file.wav); a single-level "NoBudgetOrch/*" glob sees only the subdirectories and
# reported a healthy install as sample-less.
nbo_samples = list(vpo_root.rglob("NoBudgetOrch/**/*")) if vpo_root.exists() else []
nbo_audio = [p for p in nbo_samples if p.suffix.lower() in sample_exts and p.is_file()]

lines = []
lines.append("Ambition reference SFZ library report")
lines.append(f"Root: {root}")
lines.append(f"SFZ root: {sfz_root}")
lines.append(f"Total SFZ files: {len(sfz_files)}")
lines.append("")
lines.append("Reference-family inventory:")
for name, sfz_count, sample_count in checks:
    lines.append(f"- {name}: sfz={sfz_count} audio_samples={sample_count}")
lines.append(f"- VPO libs/NoBudgetOrch audio sample files: {len(nbo_audio)}")
lines.append("")
if count_files(vpo_root, "*.sfz") and not nbo_audio:
    lines.append("WARNING: VPO SFZ scripts are installed, but libs/NoBudgetOrch samples were not found.")
    lines.append("         vpo.strings, vpo.violin, vpo.brass, and vpo.choir may resolve but render silent.")
    lines.append("")
lines.append("Top SFZ files with unresolved sample= references, heuristic only:")
if not problem_rows:
    lines.append("- none found by this heuristic")
else:
    for missing_count, total, sfz, missing in problem_rows[:40]:
        try:
            rel = sfz.relative_to(sfz_root)
        except ValueError:
            rel = sfz
        lines.append(f"- {rel}: unresolved_examples={missing_count}/{total}; examples={missing[:3]}")
lines.append("")
lines.append("Notes:")
lines.append("- This is a path/sample integrity report, not an audible musical probe.")
lines.append("- A file can pass this report and still need a keyswitch, CC, or playable MIDI range.")

out_path.write_text("\n".join(lines) + "\n")
PY_AUDIT
}

download_generaluser_gs() {
    if [[ "$SOUNDFONTS" == "0" ]]; then
        log "soundfont downloads disabled by SOUNDFONTS=0"
        return 0
    fi
    # GeneralUser GS has no GitHub releases; the .sf2 is stored directly in the repository.
    download_file_optional \
        "GeneralUser GS SoundFont" \
        "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2" \
        "GeneralUser-GS.sf2" \
        "$SOUNDFONT_ROOT/GeneralUser-GS.sf2" || true
    if [[ "$DRY_RUN" != "1" && -s "$SOUNDFONT_ROOT/GeneralUser-GS.sf2" ]]; then
        ln -sfn "GeneralUser-GS.sf2" "$SOUNDFONT_ROOT/default-GM.sf2"
    fi
}

write_soundfont_report() {
    {
        echo "Ambition audio-tools SoundFont summary"
        echo "Root: $ROOT"
        echo "Generated: $(date -Iseconds)"
        echo
        echo "SoundFont files:"
        find "$SOUNDFONT_ROOT" -type f \( -iname '*.sf2' -o -iname '*.sf3' \) -print | sort || true
        echo
        echo "Recommended MusicIR setting for non-SFZ fallback instruments:"
        echo "  render:"
        echo "    soundfont: $SOUNDFONT_ROOT/GeneralUser-GS.sf2"
        echo
        echo "Note: the current renderer only auto-detects hard-coded system paths."
        echo "This installer exports AMBITION_MUSIC_DEFAULT_SOUNDFONT in env.sh, but the"
        echo "renderer must be taught to read it or scores must set render.soundfont explicitly."
    } > "$SOUNDFONT_SUMMARY"
}

write_python_tools_report() {
    {
        echo "Ambition Python audio tools report"
        echo "Root: $ROOT"
        echo "Generated: $(date -Iseconds)"
        echo
        python3 - <<'PY_TOOL_REPORT'
import importlib.util
for name in ["pyloudnorm", "matchering", "soundfile", "pedalboard", "pretty_midi", "music21"]:
    spec = importlib.util.find_spec(name)
    print(f"{name}: {'available' if spec else 'missing'}" + (f" ({spec.origin})" if spec and spec.origin else ""))
PY_TOOL_REPORT
        echo
        cat <<'PY_TOOL_NOTES'
Install notes:
- pyloudnorm is already part of the renderer dependency set; the installer only checks it.
- matchering is not an apt or curl-only asset. Its supported Python-library install path is pip.
- On Ubuntu/Debian, install its system dependencies with:
    sudo apt install libsndfile1 python3-pip ffmpeg
PY_TOOL_NOTES
    } > "$PYTHON_TOOLS_REPORT"
}

collect_plugin_bundles() {
    log "indexing CLAP/LV2/VST3 bundles under $PLUGIN_UNPACKED"
    find "$CLAP_ROOT" "$LV2_ROOT" "$VST3_ROOT" -type l -delete 2>/dev/null || true
    while IFS= read -r -d '' bundle; do
        ln -sfn "$bundle" "$LV2_ROOT/$(basename "$bundle")"
    done < <(find "$PLUGIN_UNPACKED" -type d -name '*.lv2' -print0 2>/dev/null)
    while IFS= read -r -d '' bundle; do
        ln -sfn "$bundle" "$VST3_ROOT/$(basename "$bundle")"
    done < <(find "$PLUGIN_UNPACKED" -type d -name '*.vst3' -print0 2>/dev/null)
    while IFS= read -r -d '' bundle; do
        ln -sfn "$bundle" "$CLAP_ROOT/$(basename "$bundle")"
    done < <(find "$PLUGIN_UNPACKED" \( -type f -o -type d \) -name '*.clap' -print0 2>/dev/null)
}

write_environment_file() {
    cat > "$ENV_FILE" <<ENV_EOF
# Source this file before running the renderer to expose /data audio tools.
export AMBITION_AUDIO_TOOLS_ROOT="$ROOT"
export AMBITION_MUSIC_SOUNDFONT_ROOT="$SOUNDFONT_ROOT"
export AMBITION_MUSIC_DEFAULT_SOUNDFONT="$SOUNDFONT_ROOT/GeneralUser-GS.sf2"
export AMBITION_MUSIC_CLAP_PATHS="$CLAP_ROOT\${AMBITION_MUSIC_CLAP_PATHS:+:\$AMBITION_MUSIC_CLAP_PATHS}"
export AMBITION_MUSIC_VST3_PATHS="$VST3_ROOT\${AMBITION_MUSIC_VST3_PATHS:+:\$AMBITION_MUSIC_VST3_PATHS}"
export CLAP_PATH="$CLAP_ROOT\${CLAP_PATH:+:\$CLAP_PATH}"
export LV2_PATH="$LV2_ROOT\${LV2_PATH:+:\$LV2_PATH}"
export VST3_PATH="$VST3_ROOT\${VST3_PATH:+:\$VST3_PATH}"
ENV_EOF
}

write_apt_hints() {
    cat > "$APT_HINTS" <<'APT_EOF'
# Useful open audio plugin and audio-render packages

These distro packages complement the downloaded SFZ/SF2/CLAP/LV2/VST3 assets.
Package availability varies by distro/release, so install the subset that exists
on your machine.

```bash
sudo apt update
sudo apt install \
  curl unzip tar p7zip-full git file \
  fluidsynth libfluidsynth3 fluid-soundfont-gm fluid-soundfont-gs \
  sfizz lv2proc jalv carla guitarix drumgizmo \
  calf-plugins mda-lv2 zam-plugins lsp-plugins \
  dragonfly-reverb dpf-plugins x42-plugins \
  tap-plugins invada-studio-plugins-lv2 swh-plugins \
  ffmpeg libsndfile1 python3-pip python3-venv
```

Optional packages when available in your distro/release:

```bash
sudo apt install dexed surge-xt cardinal
```

Notes:
- GeneralUser GS is not normally an apt package; this script downloads the sf2 via curl.
- CHOW Tape Model is not normally an apt package; this script probes GitHub releases.
- Matchering is pip-based, not apt-based. Use MATCHERING=1 for an opt-in pip install.

After installing packages or downloading bundles, run:

```bash
source /data/audio-tools/env.sh
python -m ambition_music_renderer plugins list_lv2 --limit=160
python -m ambition_music_renderer plugins list_vst3
python -m ambition_music_renderer plugins list_clap
```
APT_EOF
}

download_open_plugin_bundles() {
    if [[ "$PLUGINS" == "0" ]]; then
        log "plugin downloads disabled by PLUGINS=0"
        write_environment_file
        return 0
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
        log "dry-run: would locate and download open CLAP/LV2/VST3 plugin bundles"
        collect_plugin_bundles
        write_environment_file
        return 0
    fi
    # Asset names vary between projects, so failures are non-fatal.  The manual
    # checklist names package-manager fallbacks for the same tools.
    download_github_release_asset "LSP Plugins Linux bundle" "lsp-plugins/lsp-plugins" "(linux|x86_64|amd64).*(clap|lv2|vst3)?.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/LSP" || true
    download_github_release_asset "Surge XT Linux plugin bundle" "surge-synthesizer/surge" "(linux|ubuntu|debian|x86_64|amd64).*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/SurgeXT" || true
    download_github_release_asset "Cardinal modular synth/effects" "DISTRHO/Cardinal" "linux.*x86_64.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/Cardinal" || true
    download_github_release_asset "DISTRHO DPF plugin collection" "DISTRHO/DPF-Plugins" "linux.*x86_64.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/DPF-Plugins" || true
    download_github_release_asset "CHOW Tape Model" "jatinchowdhury18/AnalogTapeModel" "(linux|x86_64|amd64).*(clap|lv2|vst3)?.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/CHOWTapeModel" || true
    download_github_release_asset "Dexed DX7 FM synth" "asb2m10/dexed" "(linux|lnx|ubuntu|debian|x86_64|amd64).*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/Dexed" || true
    download_github_release_asset "BYOD guitar/effects processor" "Chowdhury-DSP/BYOD" "linux.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/BYOD" || true
    download_github_release_asset "Dragonfly Reverb" "michaelwillis/dragonfly-reverb" "linux.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/DragonflyReverb" || true
    download_github_release_asset "Airwindows consolidated plugins" "airwindows/airwindows" "(linux|clap|lv2|vst).*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/Airwindows" || true
    download_github_release_asset "Wolf Shaper distortion" "wolf-plugins/wolf-shaper" "linux.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/WolfShaper" || true
    collect_plugin_bundles
    write_environment_file
}

write_manual_checklist() {
    {
        printf '# Manual audio-tools download checklist\n\n'
        printf 'Root: `%s`\n' "$ROOT"
        printf 'Inbox for browser downloads: `%s`\n\n' "$INBOX"
        cat <<'MANUAL_EOF'
The script automatically downloads direct archives where possible. Some valuable
free libraries are hosted behind shop, Google Drive, OneDrive, or anti-bot pages.
For those, download in a browser and place the zip/7z/tar archive in the inbox
folder listed above. Then rerun this script with the same root path.

## SFZ instrument libraries

Starter/pro modes download or attempt: FreePats Upright Piano KW, Salamander
Grand Piano, Virtual Playing Orchestra, Shinyguitar, jRhodes3c Rhodes, Black And
Green Guitars, Growlybass, Swagbass, Gogodze Phu Vol II drums, Ganjo,
Etherealwinds Harp II CE, War Tuba, Bigcat Cello, String Cyborgs, Horse Pulse,
VCSL, and Sonatina Symphonic Orchestra.

Important VPO note: the scripts alone are not enough. VPO must have both the
Wave Files archive and the Standard and/or Performance SFZ scripts extracted into
the same Virtual-Playing-Orchestra3 tree. A healthy install contains a `libs/`
directory, including `libs/NoBudgetOrch/`. The script now downloads the wave
files automatically (the primary /go/ slug redirects to archive.org, which
serves plain zips). If every auto source fails, download the Wave Files archive
in a browser from https://virtualplaying.com/virtual-playing-orchestra/, place
it in the inbox folder above, and rerun this script.

Useful catalog pages for manual extras:
- https://sfzinstruments.github.io/guitars/
- https://sfzinstruments.github.io/basses/
- https://sfzinstruments.github.io/drums/
- https://sfzinstruments.github.io/folk/
- https://sfzinstruments.github.io/brass/
- https://sfzinstruments.github.io/vocals/
- https://sfzinstruments.github.io/pianos/

## Open plugin bundles: CLAP / LV2 / VST3

The script tries to download and index open Linux plugin bundles into:

- plugins/clap
- plugins/lv2
- plugins/vst3

The renderer can list CLAP bundles and can already use LV2/VST3 in effect chains.
CLAP hosting is discovery-only for now; current renders should prefer LV2/VST3
or command steps until CLAP hosting is implemented.

Automatic release-asset probes include:
- LSP Plugins: EQ, dynamics, multiband processors, analyzers
- Surge XT: expressive synths and modulation sources
- Cardinal: modular synth/effects environment
- DPF Plugins: open LV2/VST/CLAP plugin collection
- CHOW Tape Model: reel-to-reel tape saturation / lofi character
- Dexed: DX7-style FM electric pianos and synth leads
- BYOD: guitar/effects tone shaping
- Dragonfly Reverb: reverbs for room/plate/hall spaces

If a release asset cannot be auto-detected, use distro packages first:

```bash
sudo apt install lsp-plugins surge-xt cardinal dragonfly-reverb dpf-plugins dexed
```

## SoundFonts and reference mastering

The script downloads GeneralUser GS to `soundfonts/GeneralUser-GS.sf2` and writes
`SOUNDFONT_SUMMARY.txt`. The current renderer does not automatically read the
installer's `AMBITION_MUSIC_DEFAULT_SOUNDFONT` environment variable, so for now
put this in MusicIR files that should use GeneralUser for non-SFZ stems:

```yaml
render:
  soundfont: /data/audio-tools/soundfonts/GeneralUser-GS.sf2
```

Matchering is not installed by apt or curl alone. To opt into pip installation:

```bash
sudo apt install libsndfile1 python3-pip ffmpeg
MATCHERING=1 ./download_ambition_audio_tools.sh /data/audio-tools
```

Then rerun:

```bash
source /data/audio-tools/env.sh
python -m ambition_music_renderer plugins list_lv2 --limit=120
python -m ambition_music_renderer plugins list_clap
python -m ambition_music_renderer plugins list_vst3
```
MANUAL_EOF
    } > "$MANUAL"
}

ingest_inbox_archives() {
    shopt -s nullglob
    local archives=("$INBOX"/*.zip "$INBOX"/*.7z "$INBOX"/*.tar.gz "$INBOX"/*.tgz "$INBOX"/*.tar.xz "$INBOX"/*.deb)
    if [[ ${#archives[@]} -eq 0 ]]; then
        return 0
    fi
    log "ingesting browser-downloaded archives from $INBOX"
    for archive in "${archives[@]}"; do
        local base stem dest kind
        base="$(basename "$archive")"
        stem="$base"
        stem="${stem%.tar.gz}"
        stem="${stem%.tar.xz}"
        stem="${stem%.tgz}"
        stem="${stem%.zip}"
        stem="${stem%.7z}"
        stem="${stem%.deb}"
        kind="sfz"
        if archive_contains_pattern "$archive" '\.(lv2|vst3)(/|$)|\.clap$'; then
            kind="plugin"
        elif archive_contains_pattern "$archive" '\.sfz$'; then
            kind="sfz"
        elif archive_contains_pattern "$archive" '\.(wav|flac|ogg)$'; then
            kind="sfz"
        fi
        if [[ "$kind" == "plugin" ]]; then
            dest="$PLUGIN_UNPACKED/manual/$stem"
        else
            dest="$SFZ_ROOT/manual/$stem"
        fi
        extract_archive "$archive" "$dest" "manual/$stem ($kind)" || true
    done
}

write_manual_checklist
write_apt_hints
log "install root: $ROOT"
log "mode: $MODE"

# Direct / robust SFZ downloads.
download_and_extract "FreePats Upright Piano KW SFZ/FLAC" "https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-SFZ%2BFLAC-20220221.7z" "UprightPianoKW-SFZ+FLAC-20220221.7z" "$SFZ_ROOT/FreePats/UprightPianoKW"

if want_pro; then
    download_and_extract "FreePats Salamander Grand Piano SFZ/FLAC" "https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SFZ%2BFLAC-V3%2B20200602.tar.gz" "SalamanderGrandPiano-SFZ+FLAC-V3+20200602.tar.gz" "$SFZ_ROOT/FreePats/SalamanderGrandPiano"
fi

VPO_DEST="$SFZ_ROOT/Virtual-Playing-Orchestra3"
# The wave files (~600 MB, version 3.2) are the part earlier revisions of this
# script never actually landed: the old v3-1 /go/ slugs are 404 and the shared
# extraction marker skipped the zip even when it arrived. The primary /go/
# slug 301s to archive.org, which serves the zip to plain curl; the direct
# archive.org URL is the fallback if virtualplaying.com rearranges its slugs
# again, and the Google Drive slug is a last resort (may serve an HTML
# interstitial, which is_zip_file rejects).
try_download_vpo_zip_from_sources "Virtual Playing Orchestra wave files (v3.2)" "Virtual-Playing-Orchestra3-2-wave-files.zip" "$VPO_DEST" \
    "https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-wave-files-archive/" \
    "https://archive.org/download/virtual-playing-orchestra-3-2-wave-files/Virtual-Playing-Orchestra3-2-wave-files.zip" \
    "https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-wave-files-gdrive/" || true
try_download_vpo_zip_from_sources "Virtual Playing Orchestra standard SFZ scripts (v3.3)" "Virtual-Playing-Orchestra3-3-standard-scripts.zip" "$VPO_DEST" \
    "https://virtualplaying.com/go/virtual-playing-orchestra-v3-3-standard-scripts/" \
    "https://virtualplaying.com/vp-downloads/Virtual-Playing-Orchestra3-3-standard-scripts.zip" || true
if want_pro; then
    try_download_vpo_zip_from_sources "Virtual Playing Orchestra performance SFZ scripts (v3.3)" "Virtual-Playing-Orchestra3-3-performance-scripts.zip" "$VPO_DEST" \
        "https://virtualplaying.com/go/virtual-playing-orchestra-v3-3-performance-scripts/" \
        "https://virtualplaying.com/vp-downloads/Virtual-Playing-Orchestra3-3-performance-scripts.zip" || true
fi
normalize_vpo_tree "$VPO_DEST"
validate_vpo_install "$VPO_DEST" || true

download_and_extract_optional "Karoryfer Shinyguitar" "https://github.com/sfzinstruments/karoryfer.shinyguitar/releases/download/v1.002/Karoryfer.Shinyguitar.v1.002.zip" "Karoryfer.Shinyguitar.v1.002.zip" "$SFZ_ROOT/Karoryfer/Shinyguitar" || true
download_and_extract_optional "Karoryfer Growlybass" "https://github.com/sfzinstruments/karoryfer.growlybass/releases/download/v1.002/Karoryfer.Growlybass.v1.002.zip" "Karoryfer.Growlybass.v1.002.zip" "$SFZ_ROOT/Karoryfer/Growlybass" || true
download_and_extract_optional "Karoryfer Gogodze Phu Vol II drums" "https://github.com/sfzinstruments/karoryfer.gogodze-phu-vol-ii/releases/download/v1.001/Karoryfer_Gogodze_Phu_vol_II.v1.001.zip" "Karoryfer_Gogodze_Phu_vol_II.v1.001.zip" "$SFZ_ROOT/Karoryfer/GogodzePhuVolII" || true
download_and_extract_optional "Ganjo guitar-banjo" "https://github.com/sfzinstruments/ganjo/archive/refs/heads/master.zip" "sfzinstruments.ganjo.master.zip" "$SFZ_ROOT/SFZInstruments/Ganjo" || download_and_extract_optional "Ganjo guitar-banjo" "https://github.com/sfzinstruments/ganjo/archive/refs/heads/main.zip" "sfzinstruments.ganjo.main.zip" "$SFZ_ROOT/SFZInstruments/Ganjo" || true
download_and_extract_optional "jRhodes3c Rhodes Mark I SFZ/FLAC" "https://github.com/sfzinstruments/jlearman.jRhodes3c/archive/refs/heads/master.zip" "sfzinstruments.jRhodes3c.master.zip" "$SFZ_ROOT/SFZInstruments/jRhodes3c" || download_and_extract_optional "jRhodes3c Rhodes Mark I SFZ/FLAC" "https://github.com/sfzinstruments/jlearman.jRhodes3c/archive/refs/heads/main.zip" "sfzinstruments.jRhodes3c.main.zip" "$SFZ_ROOT/SFZInstruments/jRhodes3c" || true

if want_pro; then
    download_and_extract_optional "Karoryfer Black And Green Guitars" "https://github.com/sfzinstruments/karoryfer.black-and-green-guitars/releases/download/v1.000/Karoryfer_Black_And_Green_Guitars_1000.zip" "Karoryfer_Black_And_Green_Guitars_1000.zip" "$SFZ_ROOT/Karoryfer/BlackAndGreenGuitars" || true
    download_and_extract_optional "Karoryfer Swagbass" "https://github.com/sfzinstruments/karoryfer.swagbass/releases/download/v1.001/Karoryfer.Swagbass.v1.001.zip" "Karoryfer.Swagbass.v1.001.zip" "$SFZ_ROOT/Karoryfer/Swagbass" || true
    download_and_extract_optional "Etherealwinds Harp II CE" "https://versilian-studios.com/Distro/EWHarp2CE_SFZ-Raw.zip" "EWHarp2CE_SFZ-Raw.zip" "$SFZ_ROOT/Versilian/EtherealwindsHarpII_CE" || true
    download_and_extract_optional "Karoryfer War Tuba" "https://github.com/sfzinstruments/karoryfer.war-tuba/releases/download/v1.002/Karoryfer_War_Tuba_v1002.zip" "Karoryfer_War_Tuba_v1002.zip" "$SFZ_ROOT/Karoryfer/WarTuba" || true
    download_and_extract_optional "Karoryfer x bigcat cello" "https://github.com/sfzinstruments/karoryfer-bigcat.cello/releases/download/v1.001/Karoryfer_Bigcat_cello.v1.001.zip" "Karoryfer_Bigcat_cello.v1.001.zip" "$SFZ_ROOT/Karoryfer/BigcatCello" || true
    download_and_extract_optional "Karoryfer String Cyborgs" "https://github.com/sfzinstruments/karoryfer.string-cyborgs/releases/download/v1.001/Karoryfer.String_Cyborgs.v1.001.zip" "Karoryfer.String_Cyborgs.v1.001.zip" "$SFZ_ROOT/Karoryfer/StringCyborgs" || true
    download_and_extract_optional "Karoryfer Horse Pulse" "https://github.com/sfzinstruments/Karoryfer.HorsePulse/releases/download/v1.000/Karoryfer_Horse_Pulse_1000.zip" "Karoryfer_Horse_Pulse_1000.zip" "$SFZ_ROOT/Karoryfer/HorsePulse" || true
    download_and_extract_optional "Karoryfer Meatbass (bowed double bass)" "https://github.com/sfzinstruments/karoryfer.meatbass/releases/download/v1.001/Karoryfer.Meatbass.v1.001.zip" "Karoryfer.Meatbass.v1.001.zip" "$SFZ_ROOT/Karoryfer/Meatbass" || true
    download_and_extract_optional "Karoryfer Weresax (baritone/alto saxophones)" "https://github.com/sfzinstruments/karoryfer.weresax/releases/download/v1.003/Karoryfer.Weresax.v.1.003.zip" "Karoryfer.Weresax.v.1.003.zip" "$SFZ_ROOT/Karoryfer/Weresax" || true
    if [[ "$ORCHESTRA_EXTRAS" != "0" ]]; then
        # VCSL / Sonatina ship their samples in the repo itself; their GitHub
        # "releases" carry NO uploaded asset (only the auto-generated source
        # zipball), so download_github_release_asset finds nothing. Pull the
        # codeload zipball directly (with a branch-archive fallback). ~4GB / ~500MB.
        download_and_extract_optional "VCSL (Versilian Community Sample Library)" \
            "https://codeload.github.com/sgossner/VCSL/zip/refs/tags/v1.2.2-RC" \
            "VCSL-v1.2.2-RC.zip" "$SFZ_ROOT/Versilian/VCSL" \
          || download_and_extract_optional "VCSL (Versilian Community Sample Library)" \
            "https://codeload.github.com/sgossner/VCSL/zip/refs/heads/master" \
            "VCSL-master.zip" "$SFZ_ROOT/Versilian/VCSL" || true
        download_and_extract_optional "Sonatina Symphonic Orchestra" \
            "https://codeload.github.com/peastman/sso/zip/refs/tags/v4.0" \
            "Sonatina-SSO-v4.0.zip" "$SFZ_ROOT/Sonatina/SymphonicOrchestra" \
          || download_and_extract_optional "Sonatina Symphonic Orchestra" \
            "https://codeload.github.com/peastman/sso/zip/refs/heads/master" \
            "Sonatina-SSO-master.zip" "$SFZ_ROOT/Sonatina/SymphonicOrchestra" || true
    else
        log "orchestra extras disabled by ORCHESTRA_EXTRAS=0"
    fi
fi

download_generaluser_gs
download_open_plugin_bundles

ingest_inbox_archives
if [[ "$PLUGINS" != "0" ]]; then
    collect_plugin_bundles
fi
write_reference_sfz_report
write_soundfont_report
write_python_tools_report

{
    echo "Ambition audio-tools SFZ summary"
    echo "Root: $ROOT"
    echo "Generated: $(date -Iseconds)"
    echo
    echo "SFZ files:"
    find "$SFZ_ROOT" -type f -iname '*.sfz' | sort || true
} > "$SUMMARY"

{
    echo "Ambition audio-tools plugin summary"
    echo "Root: $ROOT"
    echo "Generated: $(date -Iseconds)"
    echo
    echo "CLAP bundles:"
    find "$CLAP_ROOT" -maxdepth 1 -name '*.clap' -print | sort || true
    echo
    echo "LV2 bundles:"
    find "$LV2_ROOT" -maxdepth 1 -name '*.lv2' -print | sort || true
    echo
    echo "VST3 bundles:"
    find "$VST3_ROOT" -maxdepth 1 -name '*.vst3' -print | sort || true
} > "$PLUGIN_SUMMARY"

log "summary: $SUMMARY"
log "plugin summary: $PLUGIN_SUMMARY"
log "reference SFZ report: $REFERENCE_SUMMARY"
log "soundfont summary: $SOUNDFONT_SUMMARY"
log "python audio tools report: $PYTHON_TOOLS_REPORT"
log "environment file: $ENV_FILE"
log "apt hints: $APT_HINTS"
log "manual checklist: $MANUAL"
log "sfz count: $(find "$SFZ_ROOT" -type f -iname '*.sfz' | wc -l | tr -d ' ')"
log "soundfont count: $(find "$SOUNDFONT_ROOT" -type f \( -iname '*.sf2' -o -iname '*.sf3' \) | wc -l | tr -d ' ')"
log "clap count: $(find "$CLAP_ROOT" -maxdepth 1 -name '*.clap' | wc -l | tr -d ' ')"
log "lv2 count: $(find "$LV2_ROOT" -maxdepth 1 -name '*.lv2' | wc -l | tr -d ' ')"
log "vst3 count: $(find "$VST3_ROOT" -maxdepth 1 -name '*.vst3' | wc -l | tr -d ' ')"
log "done"

#!/usr/bin/env bash
# Download/install free SFZ sample libraries and open plugin bundles for the
# Ambition music renderer.
# Usage:
#   ./download_ambition_audio_tools.sh [ROOT]
#   MODE=starter ./download_ambition_audio_tools.sh /data/audio-tools
#   MODE=pro     ./download_ambition_audio_tools.sh /data/audio-tools
#   MODE=all     ./download_ambition_audio_tools.sh /data/audio-tools
#   PLUGINS=0    ./download_ambition_audio_tools.sh /data/audio-tools
#   DRY_RUN=1    ./download_ambition_audio_tools.sh /data/audio-tools

set -euo pipefail

ROOT="${1:-/data/audio-tools}"
MODE="${MODE:-pro}"  # starter | pro | all
DRY_RUN="${DRY_RUN:-0}"
PLUGINS="${PLUGINS:-1}"
ARCHIVES="$ROOT/archives"
SFZ_ROOT="$ROOT/sfz"
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
APT_HINTS="$ROOT/APT_AUDIO_PLUGIN_PACKAGES.md"
ENV_FILE="$ROOT/env.sh"

mkdir -p "$ARCHIVES" "$SFZ_ROOT" "$PLUGIN_ARCHIVES" "$PLUGIN_UNPACKED" "$CLAP_ROOT" "$LV2_ROOT" "$VST3_ROOT" "$INBOX" "$LOG_DIR"

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

extract_archive() {
    local archive="$1"
    local dest="$2"
    local label="$3"
    local marker="$dest/.ambition_audio_tools_extracted"
    if [[ -e "$marker" ]]; then
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
export AMBITION_MUSIC_CLAP_PATHS="$CLAP_ROOT\${AMBITION_MUSIC_CLAP_PATHS:+:\$AMBITION_MUSIC_CLAP_PATHS}"
export AMBITION_MUSIC_VST3_PATHS="$VST3_ROOT\${AMBITION_MUSIC_VST3_PATHS:+:\$AMBITION_MUSIC_VST3_PATHS}"
export CLAP_PATH="$CLAP_ROOT\${CLAP_PATH:+:\$CLAP_PATH}"
export LV2_PATH="$LV2_ROOT\${LV2_PATH:+:\$LV2_PATH}"
export VST3_PATH="$VST3_ROOT\${VST3_PATH:+:\$VST3_PATH}"
ENV_EOF
}

write_apt_hints() {
    cat > "$APT_HINTS" <<'APT_EOF'
# Useful open audio plugin packages

These packages are distro-managed complements to the downloaded SFZ/CLAP/LV2/VST3
bundles.  Package availability varies by distro/release, so install the subset
that exists on your machine.

```bash
sudo apt update
sudo apt install \
  sfizz lv2proc jalv carla guitarix drumgizmo \
  calf-plugins mda-lv2 zam-plugins lsp-plugins \
  dragonfly-reverb dpf-plugins x42-plugins \
  tap-plugins invada-studio-plugins-lv2 swh-plugins
```

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
    download_github_release_asset "CHOW Tape Model" "Chowdhury-DSP/ChowTapeModel" "linux.*\.(tar\.gz|tar\.xz|zip|deb)$" "$PLUGIN_UNPACKED/CHOWTapeModel" || true
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
Grand Piano, Virtual Playing Orchestra, Shinyguitar, Black And Green Guitars,
Growlybass, Swagbass, Gogodze Phu Vol II drums, Ganjo, Etherealwinds Harp II CE,
War Tuba, Bigcat Cello, String Cyborgs, and Horse Pulse.

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
- CHOW Tape Model and BYOD: saturation, tape, guitar/effects tone shaping
- Dragonfly Reverb: reverbs for room/plate/hall spaces

If a release asset cannot be auto-detected, use distro packages first:

```bash
sudo apt install lsp-plugins surge-xt cardinal dragonfly-reverb dpf-plugins
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
        local base stem dest
        base="$(basename "$archive")"
        stem="$base"
        stem="${stem%.tar.gz}"
        stem="${stem%.tar.xz}"
        stem="${stem%.tgz}"
        stem="${stem%.zip}"
        stem="${stem%.7z}"
        stem="${stem%.deb}"
        dest="$SFZ_ROOT/manual/$stem"
        extract_archive "$archive" "$dest" "manual/$stem" || true
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
try_download_vpo_zip "Virtual Playing Orchestra wave files" "https://virtualplaying.com/go/virtual-playing-orchestra-v3-1-wave-files-onedrive/" "Virtual-Playing-Orchestra3-Wave-Files.zip" "$VPO_DEST" || true
try_download_vpo_zip "Virtual Playing Orchestra standard SFZ scripts" "https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-4-standard-scripts/" "Virtual-Playing-Orchestra3-Standard-SFZ-Scripts.zip" "$VPO_DEST" || true
if want_pro; then
    try_download_vpo_zip "Virtual Playing Orchestra performance SFZ scripts" "https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-4-performance-scripts/" "Virtual-Playing-Orchestra3-Performance-SFZ-Scripts.zip" "$VPO_DEST" || true
fi

download_and_extract_optional "Karoryfer Shinyguitar" "https://github.com/sfzinstruments/karoryfer.shinyguitar/releases/download/v1.002/Karoryfer.Shinyguitar.v1.002.zip" "Karoryfer.Shinyguitar.v1.002.zip" "$SFZ_ROOT/Karoryfer/Shinyguitar" || true
download_and_extract_optional "Karoryfer Growlybass" "https://github.com/sfzinstruments/karoryfer.growlybass/releases/download/v1.002/Karoryfer.Growlybass.v1.002.zip" "Karoryfer.Growlybass.v1.002.zip" "$SFZ_ROOT/Karoryfer/Growlybass" || true
download_and_extract_optional "Karoryfer Gogodze Phu Vol II drums" "https://github.com/sfzinstruments/karoryfer.gogodze-phu-vol-ii/releases/download/v1.001/Karoryfer_Gogodze_Phu_vol_II.v1.001.zip" "Karoryfer_Gogodze_Phu_vol_II.v1.001.zip" "$SFZ_ROOT/Karoryfer/GogodzePhuVolII" || true
download_and_extract_optional "Ganjo guitar-banjo" "https://github.com/sfzinstruments/ganjo/archive/refs/heads/master.zip" "sfzinstruments.ganjo.master.zip" "$SFZ_ROOT/SFZInstruments/Ganjo" || download_and_extract_optional "Ganjo guitar-banjo" "https://github.com/sfzinstruments/ganjo/archive/refs/heads/main.zip" "sfzinstruments.ganjo.main.zip" "$SFZ_ROOT/SFZInstruments/Ganjo" || true

if want_pro; then
    download_and_extract_optional "Karoryfer Black And Green Guitars" "https://github.com/sfzinstruments/karoryfer.black-and-green-guitars/releases/download/v1.000/Karoryfer_Black_And_Green_Guitars_1000.zip" "Karoryfer_Black_And_Green_Guitars_1000.zip" "$SFZ_ROOT/Karoryfer/BlackAndGreenGuitars" || true
    download_and_extract_optional "Karoryfer Swagbass" "https://github.com/sfzinstruments/karoryfer.swagbass/releases/download/v1.001/Karoryfer.Swagbass.v1.001.zip" "Karoryfer.Swagbass.v1.001.zip" "$SFZ_ROOT/Karoryfer/Swagbass" || true
    download_and_extract_optional "Etherealwinds Harp II CE" "https://versilian-studios.com/Distro/EWHarp2CE_SFZ-Raw.zip" "EWHarp2CE_SFZ-Raw.zip" "$SFZ_ROOT/Versilian/EtherealwindsHarpII_CE" || true
    download_and_extract_optional "Karoryfer War Tuba" "https://github.com/sfzinstruments/karoryfer.war-tuba/releases/download/v1.002/Karoryfer_War_Tuba_v1002.zip" "Karoryfer_War_Tuba_v1002.zip" "$SFZ_ROOT/Karoryfer/WarTuba" || true
    download_and_extract_optional "Karoryfer x bigcat cello" "https://github.com/sfzinstruments/karoryfer-bigcat.cello/releases/download/v1.001/Karoryfer_Bigcat_cello.v1.001.zip" "Karoryfer_Bigcat_cello.v1.001.zip" "$SFZ_ROOT/Karoryfer/BigcatCello" || true
    download_and_extract_optional "Karoryfer String Cyborgs" "https://github.com/sfzinstruments/karoryfer.string-cyborgs/releases/download/v1.001/Karoryfer.String_Cyborgs.v1.001.zip" "Karoryfer.String_Cyborgs.v1.001.zip" "$SFZ_ROOT/Karoryfer/StringCyborgs" || true
    download_and_extract_optional "Karoryfer Horse Pulse" "https://github.com/sfzinstruments/Karoryfer.HorsePulse/releases/download/v1.000/Karoryfer_Horse_Pulse_1000.zip" "Karoryfer_Horse_Pulse_1000.zip" "$SFZ_ROOT/Karoryfer/HorsePulse" || true
fi

download_open_plugin_bundles

ingest_inbox_archives

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
log "environment file: $ENV_FILE"
log "apt hints: $APT_HINTS"
log "manual checklist: $MANUAL"
log "sfz count: $(find "$SFZ_ROOT" -type f -iname '*.sfz' | wc -l | tr -d ' ')"
log "clap count: $(find "$CLAP_ROOT" -maxdepth 1 -name '*.clap' | wc -l | tr -d ' ')"
log "lv2 count: $(find "$LV2_ROOT" -maxdepth 1 -name '*.lv2' | wc -l | tr -d ' ')"
log "vst3 count: $(find "$VST3_ROOT" -maxdepth 1 -name '*.vst3' | wc -l | tr -d ' ')"
log "done"

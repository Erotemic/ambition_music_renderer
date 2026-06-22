#!/usr/bin/env bash
# Download/install free SFZ sample libraries for the Ambition music renderer.
# Usage:
#   bash download_ambition_audio_tools.sh [ROOT]
#   MODE=starter bash download_ambition_audio_tools.sh /data/audio-tools
#   MODE=pro     bash download_ambition_audio_tools.sh /data/audio-tools
#   MODE=all     bash download_ambition_audio_tools.sh /data/audio-tools
#
# The script is idempotent: existing archives/extracted folders are reused.
# It downloads direct/redirectable archives automatically and writes a manual
# checklist for libraries that require browser/checkout pages.

set -euo pipefail

ROOT="${1:-/data/audio-tools}"
MODE="${MODE:-pro}"  # starter | pro | all
DRY_RUN="${DRY_RUN:-0}"  # set to 1 to only create dirs/checklists without downloading
ARCHIVES="$ROOT/archives"
SFZ_ROOT="$ROOT/sfz"
INBOX="$ROOT/inbox"
LOG_DIR="$ROOT/logs"
MANUAL="$ROOT/MANUAL_DOWNLOADS.md"
SUMMARY="$ROOT/SFZ_LIBRARY_SUMMARY.txt"

mkdir -p "$ARCHIVES" "$SFZ_ROOT" "$INBOX" "$LOG_DIR"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

need_cmds=(curl unzip tar find sed awk file)
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

log() {
    printf '[audio-tools] %s\n' "$*"
}

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
        return 1
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
    extract_archive "$archive" "$dest_dir" "$label"
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
    if ! is_zip_file "$archive"; then
        log "VPO URL did not yield a zip file: $archive"
        log "Keeping it for inspection and writing manual instructions."
        return 1
    fi
    extract_archive "$archive" "$dest_dir" "$label"
}

write_manual_checklist() {
    # Use printf for the variable-bearing lines and a single-quoted heredoc for
    # the Markdown body. Plain backticks inside an unquoted heredoc trigger
    # shell command substitution, which caused paths like /data/audio-tools to
    # be executed as commands.
    {
        printf '# Manual SFZ download checklist\n\n'
        printf 'Root: `%s`\n' "$ROOT"
        printf 'Inbox for browser downloads: `%s`\n\n' "$INBOX"
        cat <<'MANUAL_EOF'
The script automatically downloads direct archives where possible. Some valuable
free libraries are hosted behind shop, Google Drive, OneDrive, or anti-bot pages.
For those, download in a browser and place the zip/7z/tar archive in the inbox
folder listed above.

Then rerun this script with the same root path.

## High-priority browser downloads

### Virtual Playing Orchestra
Official page: https://virtualplaying.com/virtual-playing-orchestra/

Needed files:
- Wave Files, about 603 MB
- Standard Orchestra SFZ Scripts, about 536 KB
- Optional Performance Orchestra SFZ Scripts, about 357 KB

Put all VPO zip files into the inbox folder. The script will also try the
official redirect URLs automatically, but browser download may be more reliable.

### Guitar SFZ libraries
Catalog page: https://sfzinstruments.github.io/guitars/

Good first choices:
- Shinyguitar, CC0, about 352 MB
- Black And Green Guitars, CC0, about 500 MB
- Emilyguitar, CC0, size varies by package page

These usually require a browser/free checkout from Karoryfer Samples.

### Bass SFZ libraries
Catalog page: https://sfzinstruments.github.io/basses/

Good first choices:
- Growlybass, CC0, about 160 MB
- Swagbass, CC0, about 138 MB
- Fashionbass, CC0, about 302 MB
- Pastabass, CC0, about 301 MB
- Black And Blue Basses, CC0, about 961 MB

### Drum SFZ libraries
Catalog page: https://sfzinstruments.github.io/drums/

Good first choices:
- Gogodze Phu Vol II, CC0, about 133 MB
- Muldjord Kit SFZ port, CC-BY-4.0, about 347 MB
- DRS Kit SFZ port, CC-BY-4.0, about 754 MB
- Salamander Drumkit, CC-BY-SA-3.0, about 370 MB
- SM Drums, Public Domain, 2.2 GB+

### Extra piano/key libraries
Catalog page: https://sfzinstruments.github.io/pianos/

Already scripted:
- FreePats Upright Piano KW
- FreePats Salamander Grand Piano when MODE=pro or MODE=all

Potential extras:
- VCSL Keys, CC0, about 680 MB
- Estate Grand LE, free version, about 650 MB
- Headroom Piano, CC-BY-4.0, about 156 MB

MANUAL_EOF
    } > "$MANUAL"
}

ingest_inbox_archives() {
    shopt -s nullglob
    local archives=("$INBOX"/*.zip "$INBOX"/*.7z "$INBOX"/*.tar.gz "$INBOX"/*.tgz)
    if [[ ${#archives[@]} -eq 0 ]]; then
        return 0
    fi
    log "ingesting browser-downloaded archives from $INBOX"
    for archive in "${archives[@]}"; do
        local base
        base="$(basename "$archive")"
        local stem="$base"
        stem="${stem%.tar.gz}"
        stem="${stem%.tgz}"
        stem="${stem%.zip}"
        stem="${stem%.7z}"
        local dest="$SFZ_ROOT/manual/$stem"
        extract_archive "$archive" "$dest" "manual/$stem" || true
    done
}

write_manual_checklist

log "install root: $ROOT"
log "mode: $MODE"

# Direct / robust downloads.
download_and_extract \
    "FreePats Upright Piano KW SFZ/FLAC" \
    "https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-SFZ%2BFLAC-20220221.7z" \
    "UprightPianoKW-SFZ+FLAC-20220221.7z" \
    "$SFZ_ROOT/FreePats/UprightPianoKW"

if [[ "$MODE" == "pro" || "$MODE" == "all" ]]; then
    download_and_extract \
        "FreePats Salamander Grand Piano SFZ/FLAC" \
        "https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SFZ%2BFLAC-V3%2B20200602.tar.gz" \
        "SalamanderGrandPiano-SFZ+FLAC-V3+20200602.tar.gz" \
        "$SFZ_ROOT/FreePats/SalamanderGrandPiano"
fi

# VPO official redirect URLs. These can fail depending on OneDrive/Google Drive
# behavior; manual fallback is written above.
VPO_DEST="$SFZ_ROOT/Virtual-Playing-Orchestra3"
try_download_vpo_zip \
    "Virtual Playing Orchestra wave files" \
    "https://virtualplaying.com/go/virtual-playing-orchestra-v3-1-wave-files-onedrive/" \
    "Virtual-Playing-Orchestra3-Wave-Files.zip" \
    "$VPO_DEST" || true
try_download_vpo_zip \
    "Virtual Playing Orchestra standard SFZ scripts" \
    "https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-4-standard-scripts/" \
    "Virtual-Playing-Orchestra3-Standard-SFZ-Scripts.zip" \
    "$VPO_DEST" || true
if [[ "$MODE" == "pro" || "$MODE" == "all" ]]; then
    try_download_vpo_zip \
        "Virtual Playing Orchestra performance SFZ scripts" \
        "https://virtualplaying.com/go/virtual-playing-orchestra-v3-2-4-performance-scripts/" \
        "Virtual-Playing-Orchestra3-Performance-SFZ-Scripts.zip" \
        "$VPO_DEST" || true
fi

ingest_inbox_archives

# Produce a summary the renderer config work can consume later.
{
    echo "Ambition audio-tools SFZ summary"
    echo "Root: $ROOT"
    echo "Generated: $(date -Iseconds)"
    echo
    echo "SFZ files:"
    find "$SFZ_ROOT" -type f -iname '*.sfz' | sort || true
} > "$SUMMARY"

log "summary: $SUMMARY"
log "manual checklist: $MANUAL"
log "sfz count: $(find "$SFZ_ROOT" -type f -iname '*.sfz' | wc -l | tr -d ' ')"
log "done"


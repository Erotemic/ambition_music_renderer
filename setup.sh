#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

_sudo_prefix(){
    if [ "$(whoami)" != "root" ]; then
        printf 'sudo'
    fi
}

apt_ensure(){
    ARGS=("$@")
    MISS_PKGS=()
    HIT_PKGS=()
    _SUDO="$(_sudo_prefix)"

    for PKG_NAME in "${ARGS[@]}"; do
        if dpkg-query -W -f='${Status}' "$PKG_NAME" 2>/dev/null | grep -q "install ok installed"; then
            echo "Already have PKG_NAME='$PKG_NAME'"
            HIT_PKGS+=("$PKG_NAME")
        else
            echo "Do not have PKG_NAME='$PKG_NAME'"
            MISS_PKGS+=("$PKG_NAME")
        fi
    done

    if [ "${#MISS_PKGS[@]}" -gt 0 ]; then
        if [ "${UPDATE:-}" != "" ]; then
            ${_SUDO:+$_SUDO} apt update -y
        fi
        DEBIAN_FRONTEND=noninteractive ${_SUDO:+$_SUDO} apt install -y "${MISS_PKGS[@]}"
    else
        echo "No missing packages"
    fi
}

apt_ensure_if_available(){
    MISS_PKGS=()
    for PKG_NAME in "$@"; do
        if apt-cache show "$PKG_NAME" >/dev/null 2>&1; then
            MISS_PKGS+=("$PKG_NAME")
        else
            echo "Apt package not available here: $PKG_NAME"
        fi
    done

    if [ "${#MISS_PKGS[@]}" -gt 0 ]; then
        apt_ensure "${MISS_PKGS[@]}"
    fi
}

preseed_jack_no_realtime(){
    _SUDO="$(_sudo_prefix)"

    # Offline rendering does not need JACK realtime privileges. This avoids the
    # interactive jackd2 debconf prompt when JACK arrives as a transitive dep.
    echo "jackd2 jackd/tweak_rt_limits boolean false" | ${_SUDO:+$_SUDO} debconf-set-selections || true
}

install_sfizz_obs_repo(){
    _SUDO="$(_sudo_prefix)"
    UBUNTU_CODENAME="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-}")"

    case "$UBUNTU_CODENAME" in
        noble)
            SFIZZ_OBS_DIST="xUbuntu_24.04"
            ;;
        jammy)
            SFIZZ_OBS_DIST="xUbuntu_22.04"
            ;;
        focal)
            SFIZZ_OBS_DIST="xUbuntu_20.04"
            ;;
        *)
            echo "[setup] ERROR: No known sfizz OBS mapping for UBUNTU_CODENAME='$UBUNTU_CODENAME'" >&2
            echo "[setup] Install sfizz manually or set INSTALL_SFIZZ_OBS=0 to skip." >&2
            return 1
            ;;
    esac

    REPO_URL="https://download.opensuse.org/repositories/home:/sfztools:/sfizz/${SFIZZ_OBS_DIST}/"
    KEY_URL="https://download.opensuse.org/repositories/home:sfztools:sfizz/${SFIZZ_OBS_DIST}/Release.key"
    KEYRING="/usr/share/keyrings/home_sfztools_sfizz.gpg"
    LIST_FILE="/etc/apt/sources.list.d/home_sfztools_sfizz.list"

    apt_ensure curl gpg ca-certificates

    if [ ! -f "$KEYRING" ]; then
        echo "[setup] Installing sfizz OBS keyring: $KEYRING"
        curl -fsSL "$KEY_URL" | gpg --dearmor | ${_SUDO:+$_SUDO} tee "$KEYRING" >/dev/null
    else
        echo "[setup] Already have sfizz OBS keyring: $KEYRING"
    fi

    DESIRED_LINE="deb [signed-by=$KEYRING] $REPO_URL /"

    if [ ! -f "$LIST_FILE" ] || ! grep -Fxq "$DESIRED_LINE" "$LIST_FILE"; then
        echo "[setup] Installing sfizz OBS apt source: $LIST_FILE"
        echo "$DESIRED_LINE" | ${_SUDO:+$_SUDO} tee "$LIST_FILE" >/dev/null
    else
        echo "[setup] Already have sfizz OBS apt source: $LIST_FILE"
    fi

    UPDATE=1 apt_ensure sfizz
    ensure_sfizz_render_compat_shim

    if ! command -v sfizz_render >/dev/null 2>&1; then
        echo "[setup] WARNING: sfizz installed, but sfizz_render was not found." >&2
        echo "[setup] Available sfizz binaries:" >&2
        command -v sfizz || true >&2
        command -v sfizz-render || true >&2
        dpkg -L sfizz 2>/dev/null | grep -E '/bin/|sfizz.*render' || true >&2
    fi
}

echo "[setup] Installing baseline native audio tools"
UPDATE="${UPDATE:-1}" apt_ensure \
    ffmpeg \
    fluidsynth \
    fluid-soundfont-gm \
    fluid-soundfont-gs \
    timgm6mb-soundfont \
    libsndfile1 \
    sox \
    rubberband-cli

echo "[setup] Installing optional LV2/plugin-host tooling"
preseed_jack_no_realtime

# These vary by Ubuntu release / enabled repositories, so skip gracefully.
UPDATE="${UPDATE:-1}" apt_ensure_if_available \
    lilv-utils \
    lv2proc \
    jalv \
    carla \
    guitarix \
    guitarix-lv2 \
    lsp-plugins \
    lsp-plugins-lv2 \
    x42-plugins \
    calf-plugins \
    zam-plugins \
    mda-lv2 \
    swh-lv2

if [ "${INSTALL_SFIZZ_OBS:-0}" = "1" ]; then
    echo "[setup] Installing sfizz from OBS apt repository"
    install_sfizz_obs_repo
else
    echo "[setup] Skipping sfizz OBS repo. Set INSTALL_SFIZZ_OBS=1 to enable it."
    echo "[setup] Trying distro sfizz package if already available."
    apt_ensure_if_available sfizz sfizz-tools
fi

# Local developer setup. Assumes uv is installed.
# Local developer setup. Assumes uv is installed.
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
VENV_DIR="${VENV_DIR:-.venv}"

python_major_minor(){
    "$1" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

ensure_uv(){
    if ! command -v uv >/dev/null 2>&1; then
        echo "[setup] ERROR: uv is required but was not found on PATH." >&2
        echo "[setup] Install uv first, then rerun this setup script." >&2
        exit 1
    fi
}

ensure_venv(){
    ensure_uv

    if [ -d "$VENV_DIR" ]; then
        if [ ! -x "$VENV_DIR/bin/python" ]; then
            echo "[setup] ERROR: Found '$VENV_DIR', but '$VENV_DIR/bin/python' is missing or not executable." >&2
            echo "[setup] Refusing to repair it automatically. Remove '$VENV_DIR' yourself if you want it recreated." >&2
            exit 1
        fi

        HAVE_PYTHON_VERSION="$(python_major_minor "$VENV_DIR/bin/python")"

        if [ "$HAVE_PYTHON_VERSION" != "$PYTHON_VERSION" ]; then
            echo "[setup] ERROR: Existing '$VENV_DIR' uses Python $HAVE_PYTHON_VERSION, but this renderer requires Python $PYTHON_VERSION." >&2
            echo "[setup] Refusing to recreate it automatically." >&2
            echo "[setup] To fix intentionally: rm -rf '$VENV_DIR' && ./setup.sh" >&2
            exit 1
        fi

        echo "[setup] Reusing '$VENV_DIR' with Python $HAVE_PYTHON_VERSION"
    else
        echo "[setup] Creating '$VENV_DIR' with Python $PYTHON_VERSION"
        UV_LINK_MODE=copy uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
    fi
}

ensure_venv
source "$VENV_DIR/bin/activate"

echo "[setup] Installing Python renderer extras"
UV_LINK_MODE=copy uv pip install -e ".[all]"

echo
echo "[setup] final plugin/tool status:"
python -m ambition_music_renderer plugins doctor --fast || true

#!/usr/bin/env bash
# apt helpers for setup.sh. Sourced, never executed; defines functions only.
#
# ⛔ ONE THIRD-PARTY REPOSITORY MUST NOT BE ABLE TO STOP SETUP. `apt update`
# exits 100 when ANY repository fails, even though it refreshed every other one,
# and `set -e` turned that into "setup failed" on a machine whose only problem
# was an expired signing key on the sfizz OBS repository
# (`EXPKEYSIG ... home:sfztools OBS Project`). The key had been downloaded on an
# earlier run and "Already have sfizz OBS keyring" never looked at it again.
#
# ⚠ MEASURED 2026-10-07 ON A MACHINE WITH THE SAME REPOSITORY: re-downloading the
# vendor's `Release.key` changed nothing ("keyring is current") and `apt update`
# still reported EXPKEYSIG, because the key the vendor PUBLISHES was itself
# expired. A refresh cannot fix that; renaming the list file is what restored
# `apt update` to exit 0. The refresh stays, for the case where the vendor has
# renewed a key that a machine downloaded earlier.
#
# So: an update that fails is a WARNING that names the failing repositories;
# the install that follows is what decides whether setup can go on. A managed
# repository that stays unusable is switched off (renamed, not deleted), so it
# stops failing every later `apt update` on the machine, and the caller falls
# back to building from source.

# Defined up front so a caller under `set -u` that ran the update in a subshell
# (for example piped into `tail`) reads an empty answer, not an unbound variable.
APT_UPDATE_OUTPUT="${APT_UPDATE_OUTPUT:-}"
APT_UPDATE_STATUS="${APT_UPDATE_STATUS:-0}"

_sudo_prefix(){
    if [ "$(whoami)" != "root" ]; then
        printf 'sudo'
    fi
}

# Run `apt update`; never fail. Leaves the output in APT_UPDATE_OUTPUT and the
# exit status in APT_UPDATE_STATUS so a caller can look for a particular repo.
apt_update_tolerant(){
    local sudo_prefix rc=0
    sudo_prefix="$(_sudo_prefix)"
    APT_UPDATE_OUTPUT=""
    if APT_UPDATE_OUTPUT="$(${sudo_prefix:+$sudo_prefix} apt update -y 2>&1)"; then
        rc=0
    else
        rc=$?
    fi
    APT_UPDATE_STATUS=$rc
    printf '%s\n' "$APT_UPDATE_OUTPUT"
    if [ "$rc" -ne 0 ]; then
        echo "[setup] warning: 'apt update' exited $rc; continuing with the package lists that did refresh." >&2
        printf '%s\n' "$APT_UPDATE_OUTPUT" | grep -E '^(E|W): ' | sed 's/^/[setup]   /' >&2 || true
        echo "[setup] (a package that needs a repository that failed will fail at install, not here)" >&2
    fi
    return 0
}

# Download a repository signing key and install it as a binary keyring, replacing
# an existing one only when the content changed. An expired key is the common
# failure, and the vendor's current key file is the fix. If the download fails
# the existing keyring is left as it was.
#   refresh_apt_keyring KEY_URL KEYRING_PATH
refresh_apt_keyring(){
    local key_url="$1" keyring="$2" sudo_prefix tmp
    sudo_prefix="$(_sudo_prefix)"
    tmp="$(mktemp)"
    if curl -fsSL "$key_url" | gpg --dearmor > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
        if [ ! -f "$keyring" ]; then
            echo "[setup] Installing apt keyring: $keyring"
            ${sudo_prefix:+$sudo_prefix} install -m 644 "$tmp" "$keyring"
        elif ! cmp -s "$tmp" "$keyring"; then
            echo "[setup] Refreshing apt keyring (the vendor's key changed): $keyring"
            ${sudo_prefix:+$sudo_prefix} install -m 644 "$tmp" "$keyring"
        else
            echo "[setup] apt keyring is current: $keyring"
        fi
    else
        echo "[setup] warning: could not download $key_url; keeping the existing keyring if any" >&2
    fi
    rm -f "$tmp"
}

# After `apt_update_tolerant`: if the repository whose failing lines match
# PATTERN failed on its SIGNATURE, rename its list file so it stops failing every
# later `apt update`. Returns 0 when it disabled the repository.
#   disable_apt_repo_if_unsigned LIST_FILE PATTERN
disable_apt_repo_if_unsigned(){
    local list_file="$1" pattern="$2" sudo_prefix
    sudo_prefix="$(_sudo_prefix)"
    if printf '%s\n' "${APT_UPDATE_OUTPUT:-}" | grep -E "$pattern" \
        | grep -Eiq 'not signed|EXPKEYSIG|NO_PUBKEY|KEYEXPIRED|signatures were invalid|invalid signature'; then
        if [ -f "$list_file" ]; then
            ${sudo_prefix:+$sudo_prefix} mv "$list_file" "$list_file.disabled"
            echo "[setup] warning: $list_file is unusable (its signature does not verify); renamed to $list_file.disabled" >&2
            echo "[setup]          move it back once the vendor republishes a valid key." >&2
        fi
        return 0
    fi
    return 1
}

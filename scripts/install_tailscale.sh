#!/bin/bash
# Optional, manual installation only. Never called by the monitor setup.
set -euo pipefail

if [[ $# -ne 0 ]]; then
    echo 'Usage: sudo bash scripts/install_tailscale.sh' >&2
    exit 1
fi
if [[ $EUID -ne 0 ]]; then
    echo 'Run this script with sudo.' >&2
    exit 1
fi

# Refuse to install this distribution-specific source on another platform.
source /etc/os-release
if [[ ${ID:-} != raspbian || ${VERSION_CODENAME:-} != buster || $(dpkg --print-architecture) != armhf ]]; then
    echo 'This script requires Raspbian Buster armhf.' >&2
    exit 1
fi

apt-get update
apt-get install -y ca-certificates curl
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Keep the repository signing key scoped to this source (APT on Buster
# supports ASCII-armored keyrings), rather than using global apt-key trust.
curl --fail --silent --show-error --location \
    https://pkgs.tailscale.com/stable/raspbian/buster.asc \
    -o "$TEMP_DIR/tailscale.asc"
install -d -m 0755 /usr/share/keyrings /etc/apt/sources.list.d
install -m 0644 "$TEMP_DIR/tailscale.asc" /usr/share/keyrings/obm-tailscale.asc
echo 'deb [signed-by=/usr/share/keyrings/obm-tailscale.asc] https://pkgs.tailscale.com/stable/raspbian buster main' \
    > /etc/apt/sources.list.d/obm-tailscale.list
apt-get update
apt-get install -y tailscale
systemctl enable --now tailscaled

# No authentication or changes to an existing tailnet configuration here.
echo 'Installed. Review the tailnet access policy before joining.'
echo 'Then run manually and authenticate in your browser:'
echo 'sudo tailscale up --ssh=false --advertise-exit-node=false --advertise-routes= --accept-routes=false --exit-node='
echo 'No auth key is required by this script. See docs/remote-access.md.'

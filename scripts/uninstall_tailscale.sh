#!/bin/bash
# Optional removal; preserve local identity state for a deliberate cleanup.
set -euo pipefail

if [[ $# -ne 0 ]]; then
    echo 'Usage: sudo bash scripts/uninstall_tailscale.sh' >&2
    exit 1
fi
if [[ $EUID -ne 0 ]]; then
    echo 'Run this script with sudo.' >&2
    exit 1
fi

# Works again after removal. Do not hide a real stop/removal failure.
if systemctl list-unit-files tailscaled.service --no-legend | grep -q '^tailscaled.service'; then
    systemctl disable --now tailscaled
fi
if dpkg-query -W -f='${Status}' tailscale 2>/dev/null | grep -q '^install ok installed$'; then
    apt-get remove -y tailscale
fi
rm -f /etc/apt/sources.list.d/obm-tailscale.list
rm -f /usr/share/keyrings/obm-tailscale.asc
echo 'Removed. Revoke the Pi in the tailnet admin console.'
echo 'Identity state in /var/lib/tailscale is preserved; see docs/remote-access.md.'

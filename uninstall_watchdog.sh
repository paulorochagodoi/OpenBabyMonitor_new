#!/bin/bash
# Remove only artifacts installed by install_watchdog.sh; retain configuration/history.
set -e
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
for ARGUMENT in "$@"; do
    case "$ARGUMENT" in
    -h|--help) echo 'Usage: ./uninstall_watchdog.sh'; exit 0 ;;
    *) echo "Unknown option: $ARGUMENT"; exit 1 ;;
    esac
done
source "$SCRIPT_DIR/config/setup_config.env"
[[ "$(whoami)" = "$BM_USER" ]] || { echo "Run as $BM_USER"; exit 1; }
source "$SCRIPT_DIR/env/envvar_exports"
[[ "$BM_DIR" = "$SCRIPT_DIR" ]] || { echo 'Installation path mismatch'; exit 1; }
sudo systemctl disable --now bm_watchdog.service
sudo rm -f /lib/systemd/system/bm_watchdog.service /etc/sudoers.d/bm_watchdog
sudo rm -f /etc/systemd/system.conf.d/bm-watchdog.conf
rm -f "$BM_DIR/control/services/bm_watchdog.service" "$BM_DIR/control/.comm/health.json"
sudo systemctl daemon-reload
echo 'Removed. If hardware watchdog was enabled, schedule a reboot to apply its removal.'

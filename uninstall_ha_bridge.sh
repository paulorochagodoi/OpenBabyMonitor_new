#!/bin/bash
# Preserves configuration, credentials and retained discovery in the broker.
set -e
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
if [[ $# -ne 0 ]]; then
    echo 'Usage: ./uninstall_ha_bridge.sh'; exit 1
fi
source "$SCRIPT_DIR/config/setup_config.env"
[[ "$(whoami)" == "$BM_USER" ]] || { echo "Run as $BM_USER"; exit 1; }
source "$SCRIPT_DIR/env/envvar_exports"
[[ "$BM_DIR" == "$SCRIPT_DIR" ]] || { echo 'Installed path differs'; exit 1; }
sudo systemctl disable --now bm_ha_bridge.service
sudo rm -f /lib/systemd/system/bm_ha_bridge.service
rm -f "$BM_DIR/control/services/bm_ha_bridge.service"
sudo systemctl daemon-reload
echo 'Bridge removed. External credentials and retained MQTT entities preserved.'

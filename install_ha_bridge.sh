#!/bin/bash
# Installs the opt-in stdlib MQTT bridge; no packages or database changes.
set -e
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
START=false
for ARGUMENT in "$@"; do
    case "$ARGUMENT" in
        --start) START=true ;;
        -h|--help) echo 'Usage: ./install_ha_bridge.sh [--start]'; exit 0 ;;
        *) echo "Unknown option: $ARGUMENT"; exit 1 ;;
    esac
done
source "$SCRIPT_DIR/config/setup_config.env"
[[ "$(whoami)" == "$BM_USER" ]] || { echo "Run as $BM_USER"; exit 1; }
source "$SCRIPT_DIR/env/envvar_exports"
[[ "$BM_DIR" == "$SCRIPT_DIR" ]] || { echo 'Installed path differs'; exit 1; }
mkdir -p "$BM_DIR/control/services" "$BM_DIR/control/.comm"
UNIT="$BM_DIR/control/services/bm_ha_bridge.service"
cat > "$UNIT" <<EOF
[Unit]
Description=Babymonitor Home Assistant MQTT bridge
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$BM_USER
Group=$BM_WEB_GROUP
EnvironmentFile=$BM_DIR/env/envvars
WorkingDirectory=$BM_DIR
ExecStart=/usr/bin/python3 $BM_DIR/control/ha_bridge.py
Restart=always
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
sudo ln -sfn "$UNIT" /lib/systemd/system/bm_ha_bridge.service
sudo systemctl daemon-reload
if [[ "$START" == true ]]; then
    sudo systemctl enable --now bm_ha_bridge.service
fi
echo 'Installed. Configure home_assistant and external mqtt.env before enabling.'

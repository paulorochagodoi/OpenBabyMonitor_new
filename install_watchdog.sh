#!/bin/bash
# Install the optional watchdog on an existing installation. No packages required.
set -e
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
HARDWARE=false
for ARGUMENT in "$@"; do
    case "$ARGUMENT" in
    --hardware-watchdog) HARDWARE=true ;;
    -h|--help) echo 'Usage: ./install_watchdog.sh [--hardware-watchdog]'; exit 0 ;;
    *) echo "Unknown option: $ARGUMENT"; exit 1 ;;
    esac
done
source "$SCRIPT_DIR/config/setup_config.env"
[[ "$(whoami)" = "$BM_USER" ]] || { echo "Run as $BM_USER"; exit 1; }
source "$SCRIPT_DIR/env/envvar_exports"
[[ "$BM_DIR" = "$SCRIPT_DIR" ]] || { echo 'Installation path mismatch'; exit 1; }
BM_ENV_PATH="$SCRIPT_DIR/env/envvars"
mkdir -p "$BM_DIR/control/services" "$BM_DIR/control/.comm"
SYSTEMCTL=$(command -v systemctl)
# Existing BM_MODES rules cover mode restarts. Only these two commands are new.
RULE=$(mktemp)
trap 'rm -f "$RULE"' EXIT
printf '%s ALL = (root) NOPASSWD: %s restart apache2, %s restart mariadb\n' "$BM_USER" "$SYSTEMCTL" "$SYSTEMCTL" > "$RULE"
sudo visudo -cf "$RULE"
sudo install -o root -g root -m 0440 "$RULE" /etc/sudoers.d/bm_watchdog
cat > "$BM_DIR/control/services/bm_watchdog.service" <<EOF
[Unit]
Description=Babymonitor optional health watchdog
After=apache2.service mariadb.service bm_startup.service
StartLimitIntervalSec=900
StartLimitBurst=5

[Service]
Type=notify
NotifyAccess=main
User=$BM_USER
Group=$BM_WEB_GROUP
EnvironmentFile=$BM_ENV_PATH
ExecStart=/usr/bin/python3 $BM_DIR/control/watchdog.py
Restart=always
RestartSec=15
WatchdogSec=120
TimeoutStartSec=30
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
sudo chown "$BM_USER:$BM_WEB_GROUP" "$BM_DIR/control/.comm"
sudo ln -sfn "$BM_DIR/control/services/bm_watchdog.service" /lib/systemd/system/bm_watchdog.service
if [[ "$HARDWARE" = true ]]; then
    # Deliberately separate from software recovery: PID 1 may reboot a wedged host.
    sudo mkdir -p /etc/systemd/system.conf.d
    printf '[Manager]\nRuntimeWatchdogSec=15\n' | sudo tee /etc/systemd/system.conf.d/bm-watchdog.conf >/dev/null
    echo 'Hardware watchdog configured; apply during a planned reboot.'
fi
sudo systemctl daemon-reload
sudo systemctl enable bm_watchdog.service
sudo systemctl restart bm_watchdog.service
echo 'Installed. Set watchdog.enabled=true in config/config.json and restart bm_watchdog to activate checks.'

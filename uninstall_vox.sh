#!/bin/bash
#
# Removes the VOX mode from a baby monitor where it was installed with
# install_vox.sh. The rest of the baby monitor is left untouched.
#
# Usage: ./uninstall_vox.sh [options]
#
#   --purge         Also delete the stored VOX settings from the database
#   --keep-config   Leave the vox entries in config/config.json (the mode will
#                   then still be shown in the web application, but not work)
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname $(readlink -f $0))

PURGE_DATABASE=false
UPDATE_CONFIG=true
RESTART_WEBSERVER=true

print_usage() {
    echo 'Usage: ./uninstall_vox.sh [options]'
    echo
    echo '  --purge         Also delete the stored VOX settings from the database'
    echo '  --keep-config   Leave the vox entries in config/config.json'
    echo '  --no-restart    Do not restart the web server when finished'
    echo '  -h, --help      Show this help text'
}

for ARGUMENT in "$@"; do
    case $ARGUMENT in
    --purge)
        PURGE_DATABASE=true
        ;;
    --keep-config)
        UPDATE_CONFIG=false
        ;;
    --no-restart)
        RESTART_WEBSERVER=false
        ;;
    -h | --help)
        print_usage
        exit 0
        ;;
    *)
        echo "Error: unknown option $ARGUMENT"
        print_usage
        exit 1
        ;;
    esac
done

source $SCRIPT_DIR/config/setup_config.env

if [[ "$(whoami)" != "$BM_USER" ]]; then
    echo "Error: this script must be run by user $BM_USER"
    exit 1
fi

BM_ENV_EXPORTS_PATH=$SCRIPT_DIR/env/envvar_exports

if [[ ! -f "$BM_ENV_EXPORTS_PATH" ]]; then
    echo "Error: $BM_ENV_EXPORTS_PATH not found, nothing to uninstall"
    exit 1
fi

# Defines BM_DIR and the other paths the installation uses
source $BM_ENV_EXPORTS_PATH

if [[ "$BM_DIR" != "$SCRIPT_DIR" ]]; then
    echo "Error: the installed baby monitor is in $BM_DIR, but this script is in $SCRIPT_DIR"
    exit 1
fi

CONFIG_FILE=$BM_DIR/config/config.json
BM_COMM_DIR=$BM_DIR/control/.comm

UNIT_DIR=/lib/systemd/system
LINKED_UNIT_DIR=$BM_DIR/control/services
SERVICE_FILENAME=bm_vox.service

echo
echo 'Removing the VOX mode'
echo

echo '==> Stopping the service'
if systemctl is-active --quiet bm_vox; then
    sudo systemctl stop bm_vox
    sudo systemctl start bm_standby
fi

if [[ "$PURGE_DATABASE" = true ]]; then
    echo '==> Deleting the VOX settings from the database'
    sudo php $BM_DIR/site/config/init/init_table.php vox_settings --drop
fi

if [[ "$UPDATE_CONFIG" = true ]]; then
    echo "==> Removing the vox entries from $CONFIG_FILE (a copy is kept as $CONFIG_FILE.bak)"
    cp $CONFIG_FILE $CONFIG_FILE.bak
    python3 - "$CONFIG_FILE" <<'PYTHON'
import collections
import json
import sys

config_file = sys.argv[1]

with open(config_file, 'r') as f:
    config = json.load(f, object_pairs_hook=collections.OrderedDict)

config['modes']['current']['values'].pop('vox', None)
config.pop('vox_settings', None)
config.pop('vox_groups', None)

with open(config_file, 'w') as f:
    json.dump(config, f, indent=4)
    f.write('\n')
PYTHON
fi

echo '==> Removing the systemd service'
sudo rm -f $UNIT_DIR/$SERVICE_FILENAME
rm -f $LINKED_UNIT_DIR/$SERVICE_FILENAME
sudo systemctl daemon-reload

echo '==> Updating the commands the web server is allowed to run'
BM_MODE_NAMES=$(python3 -c "import json; print(' '.join(json.load(open('$CONFIG_FILE'))['modes']['current']['values'].keys()))")
SYSTEMCTL=$(which systemctl)
VCGENCMD=$(which vcgencmd)
CMD_ALIAS="Cmnd_Alias BM_MODES = $VCGENCMD get_throttled, $VCGENCMD measure_temp,"
for SERVICE in $BM_MODE_NAMES; do
    SERVICE_ROOT_NAME=bm_$SERVICE
    CMD_ALIAS+=" $SYSTEMCTL stop $SERVICE_ROOT_NAME, $SYSTEMCTL start $SERVICE_ROOT_NAME, $SYSTEMCTL restart $SERVICE_ROOT_NAME,"
done
echo -e "${CMD_ALIAS%,}\n%$BM_WEB_GROUP ALL = NOPASSWD: BM_MODES" | (sudo su -c "EDITOR=\"tee\" visudo -f /etc/sudoers.d/$BM_WEB_GROUP")

echo '==> Removing the files used for communicating with the web application'
rm -f $BM_COMM_DIR/vox_state.json $BM_COMM_DIR/vox_level.dat
rm -f $BM_MODE_SIGNAL_FILE_STEM.vox

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The VOX mode has been removed.'
echo

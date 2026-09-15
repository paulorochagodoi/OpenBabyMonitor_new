#!/bin/bash
#
# Removes the rolling recording and the event timeline from a baby monitor where
# they were installed with install_recording.sh. The rest of the baby monitor is
# left untouched.
#
# Usage: ./uninstall_recording.sh [options]
#
#   --purge         Also delete the settings, the stored events and everything
#                   that has been recorded
#   --keep-config   Leave the entries in config/config.json
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
source "$SCRIPT_DIR/config/install_common.sh"

PURGE=false
UPDATE_CONFIG=true
RESTART_WEBSERVER=true

print_usage() {
    echo 'Usage: ./uninstall_recording.sh [options]'
    echo
    echo '  --purge         Also delete the settings, the events and the recordings'
    echo '  --keep-config   Leave the entries in config/config.json'
    echo '  --no-restart    Do not restart the web server when finished'
    echo '  -h, --help      Show this help text'
}

for ARGUMENT in "$@"; do
    case $ARGUMENT in
    --purge)
        PURGE=true
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

bm_load_environment

RECORDING_DIR=${BM_RECORDING_DIR:-$BM_DIR/recordings}
LINKED_RECORDING_DIR=$BM_DIR/site/public/recordings

echo
echo 'Removing the recording and the timeline'
echo

if [[ "$PURGE" = true ]]; then
    echo '==> Deleting the settings and the events from the database'
    sudo php $BM_DIR/site/config/init/init_table.php recording_settings --drop
    sudo php $BM_DIR/site/config/init/init_table.php events --drop

    echo "==> Deleting everything recorded in $RECORDING_DIR"
    sudo rm -f $RECORDING_DIR/video/*.ts $RECORDING_DIR/video/index.m3u8
    sudo rm -f $RECORDING_DIR/audio/*.ts $RECORDING_DIR/audio/index.m3u8
fi

echo '==> Removing the link to the recordings'
sudo rm -f $LINKED_RECORDING_DIR

echo '==> Removing the files used for announcing events'
rm -f $BM_COMM_DIR/event.json

if [[ "$UPDATE_CONFIG" = true ]]; then
    echo "==> Removing the entries from $BM_CONFIG_FILE (a copy is kept as $BM_CONFIG_FILE.bak)"
    bm_remove_config_entries recording_settings recording_groups events
fi

bm_unset_env_var BM_RECORDING_DIR

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The recording and the timeline have been removed.'
if [[ "$PURGE" != true ]]; then
    echo "What was recorded is still in $RECORDING_DIR. Run again with --purge to delete it."
fi
echo 'Switch the device to standby and back to stop a recording that is still running.'
echo

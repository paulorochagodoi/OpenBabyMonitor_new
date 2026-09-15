#!/bin/bash
#
# Removes the virtual fence from a baby monitor where it was installed with
# install_fence.sh. The rest of the baby monitor is left untouched.
#
# Usage: ./uninstall_fence.sh [options]
#
#   --purge         Also delete the fence settings, including the drawn fence
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
    echo 'Usage: ./uninstall_fence.sh [options]'
    echo
    echo '  --purge         Also delete the fence settings, including the drawn fence'
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

echo
echo 'Removing the virtual fence'
echo

if [[ "$PURGE" = true ]]; then
    echo '==> Deleting the fence settings from the database'
    sudo php $BM_DIR/site/config/init/init_table.php fence_settings --drop
fi

echo '==> Removing the files used for reporting what the fence sees'
rm -f $BM_COMM_DIR/fence.json $BM_COMM_DIR/snapshot.jpg

if [[ "$UPDATE_CONFIG" = true ]]; then
    echo "==> Removing the entries from $BM_CONFIG_FILE (a copy is kept as $BM_CONFIG_FILE.bak)"
    bm_remove_config_entries fence_settings fence_groups
fi

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The virtual fence has been removed.'
echo 'Switch the device to standby and back to stop a fence that is still watching.'
echo

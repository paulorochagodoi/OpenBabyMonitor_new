#!/bin/bash
#
# Removes the Android app support from a baby monitor where it was installed with
# install_app.sh. The rest of the baby monitor is left untouched.
#
# The table of paired phones is dropped by default, because leaving tokens behind
# that nothing checks any more would be the wrong kind of tidy. Every phone has
# to be paired again after reinstalling.
#
# Usage: ./uninstall_app.sh [options]
#
#   --keep-devices  Leave the paired phones in the database
#   --purge         Accepted and ignored; the phones are revoked either way
#   --keep-config   Leave the entries in config/config.json
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
source "$SCRIPT_DIR/config/install_common.sh"

DROP_DEVICES=true
UPDATE_CONFIG=true
RESTART_WEBSERVER=true

print_usage() {
    echo 'Usage: ./uninstall_app.sh [options]'
    echo
    echo '  --keep-devices  Leave the paired phones in the database'
    echo '  --purge         Accepted and ignored; the phones are revoked either way'
    echo '  --keep-config   Leave the entries in config/config.json'
    echo '  --no-restart    Do not restart the web server when finished'
    echo '  -h, --help      Show this help text'
}

for ARGUMENT in "$@"; do
    case $ARGUMENT in
    --keep-devices)
        DROP_DEVICES=false
        ;;
    --purge)
        # Revoking every phone is already what this does without being asked
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
echo 'Removing the phone app support'
echo

if [[ "$DROP_DEVICES" = true ]]; then
    echo '==> Revoking every paired phone'
    sudo php $BM_DIR/site/config/init/init_table.php app_tokens --drop
fi

echo '==> Removing the files the app endpoints used'
rm -f $BM_COMM_DIR/app_login_attempts.json

if [[ "$UPDATE_CONFIG" = true ]]; then
    echo "==> Removing the entries from $BM_CONFIG_FILE (a copy is kept as $BM_CONFIG_FILE.bak)"
    bm_remove_config_entries app_tokens
fi

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The phone app support has been removed.'
echo 'The app on the phone will report that it is no longer paired.'
echo

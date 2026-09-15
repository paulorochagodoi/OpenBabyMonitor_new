#!/bin/bash
#
# Removes every optional feature at once: the virtual fence, the rolling
# recording with its timeline, and the VOX mode. The rest of the baby monitor is
# left untouched.
#
# Usage: ./uninstall_all.sh [options]
#
#   --purge           Also delete the settings, the events and the recordings
#   --without <name>  Keep a feature. Repeatable, one of: vox, recording, fence
#   --keep-config     Leave the entries in config/config.json
#   --no-restart      Do not restart the web server when finished
#   -h, --help        Show this help text
#
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
source "$SCRIPT_DIR/config/install_common.sh"

# Removed in the opposite order to the installation, so the features that depend
# on the event log go first
ALL_FEATURES='fence recording vox'

PURGE=false
UPDATE_CONFIG=true
RESTART_WEBSERVER=true
EXCLUDED_FEATURES=

print_usage() {
    echo 'Usage: ./uninstall_all.sh [options]'
    echo
    echo '  --purge           Also delete the settings, the events and the recordings'
    echo '  --without <name>  Keep a feature. Repeatable, one of: vox, recording, fence'
    echo '  --keep-config     Leave the entries in config/config.json'
    echo '  --no-restart      Do not restart the web server when finished'
    echo '  -h, --help        Show this help text'
}

while [[ $# -gt 0 ]]; do
    case $1 in
    --purge)
        PURGE=true
        shift
        ;;
    --without)
        if [[ ! " $ALL_FEATURES " == *" $2 "* ]]; then
            echo "Error: --without takes one of: $ALL_FEATURES"
            exit 1
        fi
        EXCLUDED_FEATURES="$EXCLUDED_FEATURES $2"
        shift 2
        ;;
    --keep-config)
        UPDATE_CONFIG=false
        shift
        ;;
    --no-restart)
        RESTART_WEBSERVER=false
        shift
        ;;
    -h | --help)
        print_usage
        exit 0
        ;;
    *)
        echo "Error: unknown option $1"
        print_usage
        exit 1
        ;;
    esac
done

FEATURES=
for FEATURE in $ALL_FEATURES; do
    if [[ ! " $EXCLUDED_FEATURES " == *" $FEATURE "* ]]; then
        FEATURES="$FEATURES $FEATURE"
    fi
done

if [[ -z "$FEATURES" ]]; then
    echo 'Nothing to remove, every feature was kept'
    exit 0
fi

bm_load_environment

echo
echo "Removing the optional features from $BM_DIR"
echo "Features:$FEATURES"
echo

COMMON_OPTIONS='--no-restart'
if [[ "$PURGE" = true ]]; then
    COMMON_OPTIONS="$COMMON_OPTIONS --purge"
fi
if [[ "$UPDATE_CONFIG" != true ]]; then
    COMMON_OPTIONS="$COMMON_OPTIONS --keep-config"
fi

SUCCEEDED=
FAILED=

for FEATURE in $FEATURES; do
    UNINSTALLER="$SCRIPT_DIR/uninstall_$FEATURE.sh"

    if [[ ! -f "$UNINSTALLER" ]]; then
        echo "Error: $UNINSTALLER not found"
        FAILED="$FAILED $FEATURE"
        continue
    fi

    echo "==================== $FEATURE ===================="
    if bash "$UNINSTALLER" $COMMON_OPTIONS; then
        SUCCEEDED="$SUCCEEDED $FEATURE"
    else
        echo "Removing $FEATURE failed"
        FAILED="$FAILED $FEATURE"
    fi
done

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo '=================================================='
if [[ -n "$SUCCEEDED" ]]; then
    echo "Removed:$SUCCEEDED"
fi
if [[ -n "$FAILED" ]]; then
    echo "Failed:$FAILED"
    exit 1
fi
echo

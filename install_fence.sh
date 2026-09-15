#!/bin/bash
#
# Installs the virtual fence on a baby monitor that has already been set up with
# setup.sh. It is safe to run the script more than once.
#
# The fence watches the video the camera is already streaming, so it only does
# anything while the device is in the observe mode.
#
# Usage: ./install_fence.sh [options]
#
#   --no-packages   Do not install system packages (use when offline)
#   --no-database   Do not touch the database
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname $(readlink -f $0))
source $SCRIPT_DIR/config/install_common.sh

INSTALL_PACKAGES=true
INITIALIZE_DATABASE=true
RESTART_WEBSERVER=true

print_usage() {
    echo 'Usage: ./install_fence.sh [options]'
    echo
    echo '  --no-packages   Do not install system packages (use when offline)'
    echo '  --no-database   Do not touch the database'
    echo '  --no-restart    Do not restart the web server when finished'
    echo '  -h, --help      Show this help text'
}

for ARGUMENT in "$@"; do
    case $ARGUMENT in
    --no-packages)
        INSTALL_PACKAGES=false
        ;;
    --no-database)
        INITIALIZE_DATABASE=false
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
bm_require_config_keys fence_settings events

echo
echo "Installing the virtual fence in $BM_DIR"
echo

if [[ "$INSTALL_PACKAGES" = true ]]; then
    echo '==> Making sure the required packages are installed'
    sudo apt -y install ffmpeg
fi

echo '==> Checking that the frame analysis can run'
if ! python3 -c "import cv2, numpy" 2>/dev/null; then
    echo 'The Python packages the fence needs are missing, installing them'
    pip3 install --no-cache-dir -r $BM_DIR/requirements.txt
fi

if [[ ! -e "$BM_CONTROL_CAM_CONNECTED_FILE" ]] || [[ "$(cat $BM_CONTROL_CAM_CONNECTED_FILE)" != '1' ]]; then
    echo
    echo 'Warning: no camera seems to be connected. The fence will be installed, but'
    echo 'it will stay hidden in the web application until a camera is detected.'
    echo
fi

echo '==> Creating the files used for reporting what the fence sees'
mkdir -p $BM_COMM_DIR
touch $BM_COMM_DIR/fence.json
touch $BM_COMM_DIR/event.json

echo '==> Setting ownership and permissions'
bm_restore_permissions

if [[ "$INITIALIZE_DATABASE" = true ]]; then
    echo '==> Adding the fence settings and the event log to the database'
    sudo php $BM_DIR/site/config/init/init_table.php fence_settings
    sudo php $BM_DIR/site/config/init/init_table.php events
fi

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The virtual fence is installed.'
echo 'Start the observe mode, then open Settings -> Fence to draw the fence on the camera image.'
echo

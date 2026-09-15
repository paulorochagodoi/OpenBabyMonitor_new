#!/bin/bash
#
# Installs the rolling recording and the event timeline on a baby monitor that
# has already been set up with setup.sh. It is safe to run the script more than
# once.
#
# Usage: ./install_recording.sh [options]
#
#   --dir <path>    Where to keep the recordings (default: <project>/recordings).
#                   Point this at a USB drive to spare the memory card.
#   --no-packages   Do not install system packages (use when offline)
#   --no-database   Do not touch the database
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
source "$SCRIPT_DIR/config/install_common.sh"

INSTALL_PACKAGES=true
INITIALIZE_DATABASE=true
RESTART_WEBSERVER=true
RECORDING_DIR=

print_usage() {
    echo 'Usage: ./install_recording.sh [options]'
    echo
    echo '  --dir <path>    Where to keep the recordings (default: <project>/recordings)'
    echo '  --no-packages   Do not install system packages (use when offline)'
    echo '  --no-database   Do not touch the database'
    echo '  --no-restart    Do not restart the web server when finished'
    echo '  -h, --help      Show this help text'
}

while [[ $# -gt 0 ]]; do
    case $1 in
    --dir)
        RECORDING_DIR="$2"
        if [[ -z "$RECORDING_DIR" ]]; then
            echo 'Error: --dir needs a path'
            exit 1
        fi
        shift 2
        ;;
    --no-packages)
        INSTALL_PACKAGES=false
        shift
        ;;
    --no-database)
        INITIALIZE_DATABASE=false
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

bm_load_environment
bm_require_config_keys recording_settings events

if [[ -z "$RECORDING_DIR" ]]; then
    RECORDING_DIR=${BM_RECORDING_DIR:-$BM_DIR/recordings}
fi

LINKED_RECORDING_DIR=$BM_DIR/site/public/recordings

echo
echo "Installing the recording and the timeline in $BM_DIR"
echo "Recordings will be kept in $RECORDING_DIR"
echo

if [[ "$INSTALL_PACKAGES" = true ]]; then
    echo '==> Making sure the required packages are installed'
    sudo apt -y install ffmpeg
fi

echo '==> Creating the place the recordings are kept'
sudo install -d -o $BM_USER -g $BM_WEB_GROUP -m $BM_READ_PERMISSIONS $RECORDING_DIR
sudo install -d -o $BM_USER -g $BM_WEB_GROUP -m $BM_READ_PERMISSIONS $RECORDING_DIR/video $RECORDING_DIR/audio
sudo ln -sfn $RECORDING_DIR $LINKED_RECORDING_DIR

echo '==> Telling the baby monitor where the recordings are'
bm_set_env_var BM_RECORDING_DIR $RECORDING_DIR

echo '==> Creating the file used for announcing events'
mkdir -p $BM_COMM_DIR
touch $BM_COMM_DIR/event.json

echo '==> Setting ownership and permissions'
bm_restore_permissions

if [[ "$INITIALIZE_DATABASE" = true ]]; then
    echo '==> Adding the recording settings and the event log to the database'
    sudo php $BM_DIR/site/config/init/init_table.php recording_settings
    sudo php $BM_DIR/site/config/init/init_table.php events
fi

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The recording and the timeline are installed.'
echo 'Recording starts by itself the next time the device enters the listen, VOX or observe mode.'
echo 'Open Timeline in the navigation menu to see what has happened and play it back.'
echo

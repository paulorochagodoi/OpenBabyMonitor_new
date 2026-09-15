#!/bin/bash
#
# Installs the VOX mode on a baby monitor that has already been set up with
# setup.sh. It is safe to run the script more than once.
#
# Usage: ./install_vox.sh [options]
#
#   --no-packages   Do not install system packages (use when offline)
#   --no-database   Do not touch the database
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname $(readlink -f $0))

INSTALL_PACKAGES=true
INITIALIZE_DATABASE=true
RESTART_WEBSERVER=true

print_usage() {
    echo 'Usage: ./install_vox.sh [options]'
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

source $SCRIPT_DIR/config/setup_config.env

if [[ "$(whoami)" != "$BM_USER" ]]; then
    echo "Error: this script must be run by user $BM_USER"
    exit 1
fi

BM_ENV_EXPORTS_PATH=$SCRIPT_DIR/env/envvar_exports
BM_ENV_PATH=$SCRIPT_DIR/env/envvars

if [[ ! -f "$BM_ENV_EXPORTS_PATH" ]]; then
    echo "Error: $BM_ENV_EXPORTS_PATH not found"
    echo "The baby monitor must be installed with setup.sh before the VOX mode can be added"
    exit 1
fi

# Defines BM_DIR and the other paths and permissions the installation uses
source $BM_ENV_EXPORTS_PATH

if [[ "$BM_DIR" != "$SCRIPT_DIR" ]]; then
    echo "Error: the installed baby monitor is in $BM_DIR, but this script is in $SCRIPT_DIR"
    echo 'Run setup.sh again if the project has been moved'
    exit 1
fi

CONFIG_FILE=$BM_DIR/config/config.json

if ! python3 -c "import json, sys; sys.exit(0 if 'vox' in json.load(open('$CONFIG_FILE'))['modes']['current']['values'] else 1)"; then
    echo "Error: the vox mode is missing from $CONFIG_FILE"
    echo "Make sure the project files are up to date before running this script"
    exit 1
fi

BM_MODE_NAMES=$(python3 -c "import json; print(' '.join(json.load(open('$CONFIG_FILE'))['modes']['current']['values'].keys()))")

BM_COMM_DIR=$BM_DIR/control/.comm
BM_MODE_LOCK_DIR=$(dirname $BM_MODE_LOCK_FILE)
BM_CONTROL_MIC_DIR=$(dirname $BM_CONTROL_MIC_ID_FILE)
BM_CONTROL_CAM_DIR=$(dirname $BM_CONTROL_CAM_CONNECTED_FILE)

UNIT_DIR=/lib/systemd/system
LINKED_UNIT_DIR=$BM_DIR/control/services
SERVICE_FILENAME=bm_vox.service

echo
echo "Installing the VOX mode in $BM_DIR"
echo

if [[ "$INSTALL_PACKAGES" = true ]]; then
    echo '==> Making sure the required packages are installed'
    sudo apt -y install alsa-utils ffmpeg lame
fi

echo '==> Making sure the web server can prevent caching of the stream'
sudo a2enmod headers

echo '==> Creating the systemd service'
mkdir -p $LINKED_UNIT_DIR

echo "[Unit]
Description=Babymonitor vox service

[Service]
Type=simple
User=$BM_USER
Group=$BM_WEB_GROUP
EnvironmentFile=$BM_ENV_PATH
ExecStart=$BM_DIR/control/vox.sh
StandardError=append:$BM_SERVER_LOG_PATH" >$LINKED_UNIT_DIR/$SERVICE_FILENAME

sudo ln -sfn {$LINKED_UNIT_DIR,$UNIT_DIR}/$SERVICE_FILENAME
sudo systemctl daemon-reload

echo '==> Allowing the web server to control the mode services'
SYSTEMCTL=$(which systemctl)
VCGENCMD=$(which vcgencmd)
CMD_ALIAS="Cmnd_Alias BM_MODES = $VCGENCMD get_throttled, $VCGENCMD measure_temp,"
for SERVICE in $BM_MODE_NAMES; do
    SERVICE_ROOT_NAME=bm_$SERVICE
    CMD_ALIAS+=" $SYSTEMCTL stop $SERVICE_ROOT_NAME, $SYSTEMCTL start $SERVICE_ROOT_NAME, $SYSTEMCTL restart $SERVICE_ROOT_NAME,"
done
echo -e "${CMD_ALIAS%,}\n%$BM_WEB_GROUP ALL = NOPASSWD: BM_MODES" | (sudo su -c "EDITOR=\"tee\" visudo -f /etc/sudoers.d/$BM_WEB_GROUP")

echo '==> Creating the files used for communicating with the web application'
mkdir -p $BM_COMM_DIR
touch $BM_COMM_DIR/{vox_state.json,vox_level.dat}

# Make sure every mode has a signal file the web application can watch
for MODE in $BM_MODE_NAMES; do
    touch $BM_MODE_SIGNAL_FILE_STEM.$MODE
done

echo '==> Setting ownership and permissions'
sudo chown -R $BM_USER:$BM_WEB_GROUP $BM_DIR
sudo chmod -R $BM_READ_PERMISSIONS $BM_DIR

# Restore the write permissions needed by the web server
sudo chmod $BM_WRITE_PERMISSIONS $BM_SERVER_ACTION_DIR $BM_MODE_LOCK_DIR $BM_COMM_DIR $BM_CONTROL_MIC_DIR $BM_CONTROL_CAM_DIR
sudo chmod $BM_WRITE_PERMISSIONS $BM_PHPSYSINFO_CONFIG_FILE $(dirname $BM_PHPSYSINFO_CONFIG_FILE)
for MODE in $BM_MODE_NAMES; do
    sudo chmod $BM_WRITE_PERMISSIONS $BM_MODE_SIGNAL_FILE_STEM.$MODE
done

if [[ "$INITIALIZE_DATABASE" = true ]]; then
    echo '==> Adding the VOX settings to the database'
    $BM_DIR/site/config/init/init_vox.sh
fi

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

echo
echo 'The VOX mode is installed.'
echo 'Open the web application and select VOX in the row of mode buttons.'
echo 'Its behaviour can be adjusted under Settings -> VOX.'
echo

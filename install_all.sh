#!/bin/bash
#
# Installs every optional feature at once on a baby monitor that has already
# been set up with setup.sh: the VOX mode, the rolling recording with its
# timeline, the virtual fence, and the support the Android app needs.
#
# This is the same work the individual installers do, with the shared steps done
# once instead of three times. It is safe to run more than once, and features
# that are already installed are simply brought up to date.
#
# Usage: ./install_all.sh [options]
#
#   --dir <path>      Where to keep the recordings (default: <project>/recordings).
#                     Point this at a USB drive to spare the memory card.
#   --without <name>  Leave a feature out. Repeatable, one of: vox, recording, fence, app
#   --no-packages     Do not install system packages (use when offline)
#   --no-database     Do not touch the database
#   --no-restart      Do not restart the web server when finished
#   -h, --help        Show this help text
#
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
source "$SCRIPT_DIR/config/install_common.sh"

ALL_FEATURES='vox recording fence app'

INSTALL_PACKAGES=true
INITIALIZE_DATABASE=true
RESTART_WEBSERVER=true
RECORDING_DIR=
EXCLUDED_FEATURES=

print_usage() {
    echo 'Usage: ./install_all.sh [options]'
    echo
    echo '  --dir <path>      Where to keep the recordings (default: <project>/recordings)'
    echo '  --without <name>  Leave a feature out. Repeatable, one of: vox, recording, fence, app'
    echo '  --no-packages     Do not install system packages (use when offline)'
    echo '  --no-database     Do not touch the database'
    echo '  --no-restart      Do not restart the web server when finished'
    echo '  -h, --help        Show this help text'
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
    --without)
        if [[ ! " $ALL_FEATURES " == *" $2 "* ]]; then
            echo "Error: --without takes one of: $ALL_FEATURES"
            exit 1
        fi
        EXCLUDED_FEATURES="$EXCLUDED_FEATURES $2"
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

FEATURES=
for FEATURE in $ALL_FEATURES; do
    if [[ ! " $EXCLUDED_FEATURES " == *" $FEATURE "* ]]; then
        FEATURES="$FEATURES $FEATURE"
    fi
done

if [[ -z "$FEATURES" ]]; then
    echo 'Nothing to install, every feature was left out'
    exit 0
fi

# Fails early with one message rather than once per feature
bm_load_environment

echo
echo "Installing the optional features in $BM_DIR"
echo "Features:$FEATURES"
echo

if [[ "$INSTALL_PACKAGES" = true ]]; then
    echo '==> Installing the packages every feature needs'
    sudo apt -y install alsa-utils ffmpeg lame
    echo
fi

# The individual installers do the shared work themselves, so they are told to
# skip the parts this script has already done or will do at the end
COMMON_OPTIONS='--no-packages --no-restart'
if [[ "$INITIALIZE_DATABASE" != true ]]; then
    COMMON_OPTIONS="$COMMON_OPTIONS --no-database"
fi

SUCCEEDED=
FAILED=

for FEATURE in $FEATURES; do
    INSTALLER="$SCRIPT_DIR/install_$FEATURE.sh"

    if [[ ! -f "$INSTALLER" ]]; then
        echo "Error: $INSTALLER not found, are the project files up to date?"
        FAILED="$FAILED $FEATURE"
        continue
    fi

    OPTIONS=$COMMON_OPTIONS
    if [[ "$FEATURE" = 'recording' ]] && [[ -n "$RECORDING_DIR" ]]; then
        OPTIONS="$OPTIONS --dir $RECORDING_DIR"
    fi

    echo "==================== $FEATURE ===================="
    # A feature that fails should not stop the others from being installed
    if bash "$INSTALLER" $OPTIONS; then
        SUCCEEDED="$SUCCEEDED $FEATURE"
    else
        echo "Installing $FEATURE failed"
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
    echo "Installed:$SUCCEEDED"
fi
if [[ -n "$FAILED" ]]; then
    echo "Failed:$FAILED"
    echo 'Look above for what went wrong, then run the installer for that feature on its own.'
    exit 1
fi

echo
echo 'In the web application you now have:'
for FEATURE in $SUCCEEDED; do
    case $FEATURE in
    vox)
        echo '  VOX        a mode that starts streaming audio by itself when it hears something'
        ;;
    recording)
        echo '  Timeline   what happened, with playback of the recording'
        ;;
    fence)
        echo '  Fence      draw it under Settings -> Fence while the observe mode is running'
        ;;
    app)
        echo '  Phone app  pair it with the fingerprint printed above, under "app"'
        ;;
    esac
done
echo

#!/bin/bash
#
# Installs the support the Android app needs on a baby monitor that has already
# been set up with setup.sh. It is safe to run the script more than once.
#
# The app talks straight to this device over the local network. Nothing is sent
# to any outside service, and the phone is tied to the certificate of this
# device, whose fingerprint this script prints at the end. That fingerprint is
# what you compare against when pairing, so read it from the device itself and
# not from anywhere the network could have touched.
#
# Usage: ./install_app.sh [options]
#
#   --no-packages   Accepted and ignored; nothing here needs a package
#   --no-database   Do not touch the database
#   --no-restart    Do not restart the web server when finished
#   -h, --help      Show this help text
#
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
source "$SCRIPT_DIR/config/install_common.sh"

INITIALIZE_DATABASE=true
RESTART_WEBSERVER=true

print_usage() {
    echo 'Usage: ./install_app.sh [options]'
    echo
    echo '  --no-packages   Accepted and ignored; nothing here needs a package'
    echo '  --no-database   Do not touch the database'
    echo '  --no-restart    Do not restart the web server when finished'
    echo '  -h, --help      Show this help text'
}

for ARGUMENT in "$@"; do
    case $ARGUMENT in
    --no-packages)
        # Taken so that install_all.sh can pass the same options to every installer
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
bm_require_config_keys app_tokens events

echo
echo "Installing the phone app support in $BM_DIR"
echo

echo '==> Creating the files the app endpoints use'
mkdir -p $BM_COMM_DIR
touch $BM_COMM_DIR/event.json
touch $BM_COMM_DIR/app_login_attempts.json

echo '==> Setting ownership and permissions'
bm_restore_permissions

if [[ "$INITIALIZE_DATABASE" = true ]]; then
    echo '==> Adding the paired devices and the event log to the database'
    sudo php $BM_DIR/site/config/init/init_table.php app_tokens
    sudo php $BM_DIR/site/config/init/init_table.php events
fi

if [[ "$RESTART_WEBSERVER" = true ]]; then
    echo '==> Restarting the web server'
    sudo systemctl restart apache2
fi

source "$BM_SERVERCONTROL_DIR/ssl_cert_key_paths.env"

if [[ ! -f "$SSL_CERT_PATH" ]]; then
    echo
    echo "Error: no certificate at $SSL_CERT_PATH"
    echo 'The web server must be set up with setup.sh before the app can pair with it.'
    exit 1
fi

FINGERPRINT=$(sudo openssl x509 -in "$SSL_CERT_PATH" -noout -fingerprint -sha256 | cut -d= -f2)

echo
echo '======================================================================'
echo ' The phone app support is installed.'
echo
echo ' Pair the app with:'
echo
echo "   Address:  $BM_HOSTNAME.local"
echo '   Port:     443'
echo '   Password: the same one you use for the web interface'
echo
echo ' When the app shows a fingerprint, it must be exactly this one:'
echo
echo "   $FINGERPRINT"
echo
echo ' Write it down from this screen. If the app shows anything else, it is'
echo ' not talking to this device, and you should not accept it.'
echo '======================================================================'
echo
echo ' Revoke a paired phone later under Settings -> System in the web'
echo ' interface. Replacing the certificate means pairing every phone again.'
echo

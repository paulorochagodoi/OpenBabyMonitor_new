# Shared by the feature installers and uninstallers.
#
# Source this from a script that has set SCRIPT_DIR to its own directory, then
# call bm_load_environment before using any of the other functions.

bm_load_environment() {
    source $SCRIPT_DIR/config/setup_config.env

    if [[ "$(whoami)" != "$BM_USER" ]]; then
        echo "Error: this script must be run by user $BM_USER"
        exit 1
    fi

    BM_ENV_EXPORTS_PATH=$SCRIPT_DIR/env/envvar_exports
    BM_ENV_PATH=$SCRIPT_DIR/env/envvars

    if [[ ! -f "$BM_ENV_EXPORTS_PATH" ]]; then
        echo "Error: $BM_ENV_EXPORTS_PATH not found"
        echo 'The baby monitor must be installed with setup.sh first'
        exit 1
    fi

    # Defines BM_DIR and the other paths and permissions the installation uses
    source $BM_ENV_EXPORTS_PATH

    if [[ "$BM_DIR" != "$SCRIPT_DIR" ]]; then
        echo "Error: the installed baby monitor is in $BM_DIR, but this script is in $SCRIPT_DIR"
        echo 'Run setup.sh again if the project has been moved'
        exit 1
    fi

    BM_CONFIG_FILE=$BM_DIR/config/config.json
    BM_COMM_DIR=$BM_DIR/control/.comm
    BM_MODE_LOCK_DIR=$(dirname $BM_MODE_LOCK_FILE)
    BM_CONTROL_MIC_DIR=$(dirname $BM_CONTROL_MIC_ID_FILE)
    BM_CONTROL_CAM_DIR=$(dirname $BM_CONTROL_CAM_CONNECTED_FILE)
}

# Fails with a helpful message if the configuration file does not have the keys a
# feature needs, which means the project files are out of date
bm_require_config_keys() {
    local keys="$@"
    if ! python3 -c "import json, sys; config = json.load(open('$BM_CONFIG_FILE')); sys.exit(0 if all(key in config for key in '$keys'.split()) else 1)"; then
        echo "Error: $keys missing from $BM_CONFIG_FILE"
        echo 'Make sure the project files are up to date before running this script'
        exit 1
    fi
}

bm_get_mode_names() {
    python3 -c "import json; print(' '.join(json.load(open('$BM_CONFIG_FILE'))['modes']['current']['values'].keys()))"
}

# Adds a variable to the environment the services and the web application see,
# replacing it if it is already there
bm_set_env_var() {
    local name=$1
    local value=$2
    sed -i "\|^export $name=|d" $BM_ENV_EXPORTS_PATH
    echo "export $name=$value" >>$BM_ENV_EXPORTS_PATH
    local exports=$(cat $BM_ENV_EXPORTS_PATH)
    echo "${exports//'export '/}" >$BM_ENV_PATH
}

bm_unset_env_var() {
    local name=$1
    sed -i "\|^export $name=|d" $BM_ENV_EXPORTS_PATH
    local exports=$(cat $BM_ENV_EXPORTS_PATH)
    echo "${exports//'export '/}" >$BM_ENV_PATH
}

# Gives the project files back the ownership and permissions the web server needs,
# which new files fetched with git do not have
bm_restore_permissions() {
    sudo chown -R $BM_USER:$BM_WEB_GROUP $BM_DIR/control $BM_DIR/site $BM_DIR/config $BM_DIR/env
    sudo chmod -R $BM_READ_PERMISSIONS $BM_DIR/control $BM_DIR/site $BM_DIR/config $BM_DIR/env

    sudo chmod $BM_WRITE_PERMISSIONS $BM_COMM_DIR $BM_MODE_LOCK_DIR $BM_SERVER_ACTION_DIR
    sudo chmod $BM_WRITE_PERMISSIONS $BM_CONTROL_MIC_DIR $BM_CONTROL_CAM_DIR
    sudo chmod $BM_WRITE_PERMISSIONS $BM_PHPSYSINFO_CONFIG_FILE $(dirname $BM_PHPSYSINFO_CONFIG_FILE)

    for signal_file in $BM_MODE_SIGNAL_FILE_STEM.*; do
        if [[ -e "$signal_file" ]]; then
            sudo chmod $BM_WRITE_PERMISSIONS "$signal_file"
        fi
    done
    for comm_file in $BM_COMM_DIR/*; do
        if [[ -e "$comm_file" ]]; then
            sudo chmod $BM_WRITE_PERMISSIONS "$comm_file"
        fi
    done
}

# Removes the entries a feature added to the configuration file, keeping a copy
# of the original next to it
bm_remove_config_entries() {
    local keys="$@"
    cp $BM_CONFIG_FILE $BM_CONFIG_FILE.bak
    python3 - "$BM_CONFIG_FILE" $keys <<'PYTHON'
import collections
import json
import sys

config_file = sys.argv[1]
keys = sys.argv[2:]

with open(config_file, 'r') as f:
    config = json.load(f, object_pairs_hook=collections.OrderedDict)

for key in keys:
    if key.startswith('modes.'):
        config['modes']['current']['values'].pop(key.split('.', 1)[1], None)
    else:
        config.pop(key, None)

with open(config_file, 'w') as f:
    json.dump(config, f, indent=4)
    f.write('\n')
PYTHON
}

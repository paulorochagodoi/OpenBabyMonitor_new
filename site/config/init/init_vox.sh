#!/bin/bash
set -e

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")

sudo php $SCRIPT_DIR/init_table.php vox_settings "$@"
echo 'VOX settings initialized successfully'

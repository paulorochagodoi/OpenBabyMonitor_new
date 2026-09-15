#!/bin/bash
set -e

SCRIPT_DIR=$(dirname $(readlink -f $0))

sudo php $SCRIPT_DIR/init_vox.php
echo 'VOX settings initialized successfully'

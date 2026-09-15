#!/bin/bash

SCRIPT_DIR=$(dirname $(readlink -f $0))

# Guard against removing the wrong location if the environment is incomplete
[[ -n "$BM_AUDIO_STREAM_DIR" ]] && rm -rf "$BM_AUDIO_STREAM_DIR"
[[ -n "$BM_PICAM_STREAM_DIR" ]] && rm -rf "$BM_PICAM_STREAM_DIR"

$SCRIPT_DIR/standby.py

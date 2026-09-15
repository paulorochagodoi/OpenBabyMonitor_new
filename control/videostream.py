#!/usr/bin/env python3

import os
import sys
import time
import pathlib
import subprocess
import control
import mic
import recorder

MODE = 'videostream'
HORIZONTAL_RESOLUTIONS = {480: 640, 720: 1280, 1080: 1920}

# How long to wait for the camera to produce a stream before giving up on the
# helpers that consume it
STREAM_WAIT_TIMEOUT = 60.0  # [s]
STREAM_WAIT_INTERVAL = 0.5  # [s]


def stream_video():
    control.enter_mode(MODE, run_video_mode)


def run_video_mode(mode, config, database):
    settings = control.read_settings(mode, config, database)
    settings.update(
        control.read_setting('audiostream', 'gain', config, database))
    recording_settings = control.read_settings_if_available(
        'recording', config, database)
    fence_settings = control.read_settings_if_available(
        'fence', config, database)
    stream_video_with_settings(recording_settings=recording_settings,
                               fence_settings=fence_settings,
                               **settings)


def stream_video_with_settings(recording_settings=None,
                               fence_settings=None,
                               encrypted=True,
                               vertical_resolution=720,
                               use_variable_framerate=True,
                               framerate=30,
                               rotation=0,
                               flip_horizontally=False,
                               flip_vertically=False,
                               exposure_mode='auto',
                               metering='average',
                               exposure_value_compensation=0,
                               exposure_time=100,
                               iso=400,
                               white_balance_mode='greyworld',
                               red_gain=0.0,
                               blue_gain=0.0,
                               capture_audio=True,
                               show_time=True,
                               gain=100,
                               **kwargs):
    picam_dir = os.environ['BM_PICAM_DIR']
    output_dir = os.environ['BM_PICAM_STREAM_DIR']
    log_path = os.environ['BM_SERVER_LOG_PATH']
    mic_id = mic.get_mic_id()

    mic.update_current_mic_volume(gain)

    assert vertical_resolution in HORIZONTAL_RESOLUTIONS, \
        'Vertical resolution ({}) is not one of {}'.format(
        vertical_resolution, ', '.join(list(HORIZONTAL_RESOLUTIONS.keys())))
    resolution_args = [
        '--width',
        str(HORIZONTAL_RESOLUTIONS[vertical_resolution]), '--height',
        str(vertical_resolution)
    ]

    fps_args = ['--vfr'] if use_variable_framerate else [
        '--fps', str(framerate)
    ]

    orientation_args = ['--rotation', str(rotation)]
    if flip_horizontally:
        orientation_args += ['--hflip']
    if flip_vertically:
        orientation_args += ['--vflip']

    brightness_args = ['--metering', metering, '--ex', exposure_mode]
    if exposure_mode == 'off':
        brightness_args += [
            '--evcomp',
            str(exposure_value_compensation), '--shutter',
            str(exposure_time), '--iso',
            str(iso)
        ]

    color_args = ['--wb', white_balance_mode]
    if white_balance_mode == 'off':
        color_args += ['--wbred', str(red_gain), '--wbblue', str(blue_gain)]

    audio_args = ['--alsadev', mic_id] if capture_audio else ['--noaudio']

    time_args = ['--time', '--timeformat', r'%a %d.%m.%Y %T'
                 ] if show_time else []

    if encrypted:
        with open(os.path.join(output_dir, 'stream.hexkey')) as f:
            encryption_key = f.read()
        encryption_args = [
            '--hlsenc', '--hlsenckeyuri', 'stream.key', '--hlsenckey',
            encryption_key
        ]
    else:
        encryption_args = []

    output_args = ['--hlsdir', output_dir]

    control.signal_mode_started(MODE)

    with open(log_path, 'a') as log_file:
        picam_process = subprocess.Popen(
            [os.path.join(picam_dir, 'picam')] + output_args +
            encryption_args + resolution_args + fps_args + orientation_args +
            brightness_args + color_args + audio_args + time_args,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            cwd=output_dir)

        stream_recorder = None
        fence_process = None
        try:
            # The recording and the fence both read the stream the camera
            # produces, so they can only be started once it exists
            if wait_for_stream(os.environ['BM_PICAM_STREAM_FILE'],
                               picam_process):
                stream_recorder = start_recorder(recording_settings, log_path)
                fence_process = start_fence_monitor(fence_settings, log_file,
                                                    log_path)

            return_code = picam_process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, 'picam')
        finally:
            if stream_recorder is not None:
                stream_recorder.stop()
            stop_process(fence_process)
            stop_process(picam_process)


def start_recorder(recording_settings, log_path):
    stream_recorder = recorder.create_video_recorder(
        recording_settings,
        os.environ['BM_PICAM_STREAM_FILE'],
        log_path=log_path)
    if stream_recorder is None:
        return None
    try:
        stream_recorder.start()
    except Exception as exception:
        # Recording is secondary to showing the video, so a problem with it must
        # never take the mode down
        stream_recorder.log(f'Could not start the recording: {exception}')
        return None
    return stream_recorder


def start_fence_monitor(fence_settings, log_file, log_path=None):
    if not fence_settings or not fence_settings.get('enabled', False):
        return None
    fence_path = pathlib.Path(__file__).resolve().parent / 'fence.py'
    try:
        # Started through the interpreter so it does not depend on the file
        # keeping its executable bit
        return subprocess.Popen([sys.executable, str(fence_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=log_file)
    except OSError as exception:
        # Watching the fence is secondary too
        log_message(log_path, f'Could not start the fence: {exception}')
        return None


def log_message(log_path, message):
    message = f'videostream: {message}'
    if log_path is None:
        print(message, file=sys.stderr)
        return
    try:
        with open(log_path, 'a') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n')
    except OSError:
        pass


def wait_for_stream(stream_file, picam_process):
    path = pathlib.Path(stream_file)
    elapsed_time = 0.0
    while not path.exists():
        if picam_process.poll() is not None:
            return False
        time.sleep(STREAM_WAIT_INTERVAL)
        elapsed_time += STREAM_WAIT_INTERVAL
        if elapsed_time > STREAM_WAIT_TIMEOUT:
            return False
    return True


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


if __name__ == '__main__':
    stream_video()

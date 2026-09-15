#!/usr/bin/env python3

import os
import time
import pathlib
import subprocess
import control
import mic
import recorder

MODE = 'audiostream'

# How long to wait for the stream to appear before giving up on recording it
STREAM_WAIT_TIMEOUT = 30.0  # [s]
STREAM_WAIT_INTERVAL = 0.5  # [s]


def stream_audio():
    control.enter_mode(MODE, run_audiostream_mode)


def run_audiostream_mode(mode, config, database):
    stream_audio_with_settings(
        recording_settings=control.read_settings_if_available(
            'recording', config, database),
        **control.read_settings(mode, config, database))


def stream_audio_with_settings(recording_settings=None,
                               encrypted=True,
                               gain=100,
                               sampling_rate=8000,
                               mp3_bitrate=128,
                               hls_segment_time=1,
                               hls_list_size=3,
                               **kwargs):
    output_dir = os.environ['BM_AUDIO_STREAM_DIR']
    output_file = os.environ['BM_AUDIO_STREAM_FILE']
    log_path = os.environ['BM_SERVER_LOG_PATH']
    mic_id = mic.get_mic_id()

    mic.update_current_mic_volume(gain)

    input_args = [
        '-f', 'alsa', '-channels', '1', '-sample_rate',
        '{:d}'.format(sampling_rate), '-i', 'plug{}'.format(mic_id)
    ]
    codec_args = [
        '-vn',
        '-acodec',
        'libmp3lame',
        '-b:a',
        '{:d}k'.format(mp3_bitrate),
    ]
    stream_args = [
        '-f', 'hls', '-hls_time', '{}'.format(hls_segment_time),
        '-hls_list_size', '{}'.format(hls_list_size), '-hls_flags',
        'delete_segments', '-hls_allow_cache', '0'
    ]
    encryption_args = ['-hls_key_info_file', 'stream.keyinfo'
                       ] if encrypted else []

    control.signal_mode_started(MODE)

    with open(log_path, 'a') as log_file:
        stream_process = subprocess.Popen(
            ['ffmpeg', '-hide_banner', '-loglevel', 'fatal'] + input_args +
            codec_args + stream_args + encryption_args + [output_file],
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            cwd=output_dir)

        stream_recorder = None
        try:
            # The recording copies the stream that is already being produced
            if wait_for_stream(output_file, stream_process):
                stream_recorder = recorder.create_audio_stream_recorder(
                    recording_settings, output_file, log_path=log_path)
                if stream_recorder is not None:
                    try:
                        stream_recorder.start()
                    except Exception as exception:
                        # Recording is secondary to streaming the audio, so a
                        # problem with it must never take the mode down
                        stream_recorder.log(
                            f'Could not start the recording: {exception}')
                        stream_recorder = None

            return_code = stream_process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, 'ffmpeg')
        finally:
            if stream_recorder is not None:
                stream_recorder.stop()
            if stream_process.poll() is None:
                stream_process.terminate()
                try:
                    stream_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    stream_process.kill()
                    stream_process.wait()


def wait_for_stream(stream_file, stream_process):
    path = pathlib.Path(stream_file)
    elapsed_time = 0.0
    while not path.exists():
        if stream_process.poll() is not None:
            return False
        time.sleep(STREAM_WAIT_INTERVAL)
        elapsed_time += STREAM_WAIT_INTERVAL
        if elapsed_time > STREAM_WAIT_TIMEOUT:
            return False
    return True


if __name__ == '__main__':
    stream_audio()

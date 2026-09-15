#!/usr/bin/env python3
"""
VOX (voice operated exchange) mode.

The microphone is monitored continuously, and as soon as the sound level rises
sufficiently above the background level, an audio stream is started
automatically. The stream is kept alive as long as there is activity, and is
shut down again after a period of silence, leaving the device ready to transmit
the next time the child makes a sound.

A single capture process is used both for the sound level analysis and for the
stream, so the level can be monitored while transmitting and no audio is lost
when the transmission starts.
"""

import os
import sys
import json
import time
import signal
import queue
import pathlib
import threading
import collections
import subprocess

sys.path.append(os.path.join(os.environ['BM_DIR'], 'detection'))
import features
import control
import mic
import events
import recorder

MODE = 'vox'

STATE_CALIBRATING = 'calibrating'
STATE_ARMED = 'armed'
STATE_TRANSMITTING = 'transmitting'

# Duration of the audio blocks that the sound level is computed for
ANALYSIS_BLOCK_DURATION = 0.4  # [s]
# Minimum time between two sound level reports to the web application
LEVEL_REPORT_INTERVAL = 1.0  # [s]
# Amount of audio kept in memory and prepended to a new transmission, so the
# sound that triggered the transmission can also be heard
PRE_ROLL_DURATION = 1.5  # [s]
# Maximum number of audio blocks waiting to be written to the encoder
MAX_QUEUED_BLOCKS = 32
# Number of times in a row the encoder may fail before the mode gives up
MAX_ENCODER_FAILURES = 3

SAMPLE_FORMAT = 'S16_LE'
FFMPEG_INPUT_FORMAT = 's16le'


class VoxTrigger:
    """
    Decides when to start and stop transmitting, based on the sound level
    relative to the background level.

    Activation requires the sound to stay above `activation_threshold` for
    `activation_time`. Deactivation requires the sound to stay below
    `activation_threshold - release_margin` for `hang_time`. The two thresholds
    give a hysteresis that prevents the transmission from flickering on and off
    around the threshold.
    """
    def __init__(self,
                 activation_threshold=12.0,
                 activation_time=1.0,
                 release_margin=3.0,
                 hang_time=20.0,
                 min_transmission_time=10.0,
                 max_transmission_time=300.0):
        self.activation_threshold = activation_threshold
        self.activation_time = activation_time
        self.release_threshold = activation_threshold - release_margin
        self.hang_time = hang_time
        self.min_transmission_time = min_transmission_time
        self.max_transmission_time = max_transmission_time

        self.transmitting = False
        self.loud_duration = 0.0
        self.activation_time_stamp = None
        self.last_activity_time = None

    def update(self, sound_contrast, block_duration, now):
        """
        Registers a new sound level measurement, returning True if this changed
        whether the device should be transmitting.
        """
        if self.transmitting:
            if sound_contrast >= self.release_threshold:
                self.last_activity_time = now
            if self.should_deactivate(now):
                self.deactivate()
                return True
        else:
            if sound_contrast >= self.activation_threshold:
                self.loud_duration += block_duration
                if self.loud_duration >= self.activation_time:
                    self.activate(now)
                    return True
            else:
                self.loud_duration = 0.0
        return False

    def should_deactivate(self, now):
        transmission_duration = now - self.activation_time_stamp
        if self.max_transmission_time > 0 and transmission_duration >= self.max_transmission_time:
            return True
        return (transmission_duration >= self.min_transmission_time
                and now - self.last_activity_time >= self.hang_time)

    def activate(self, now):
        self.transmitting = True
        self.activation_time_stamp = now
        self.last_activity_time = now
        self.loud_duration = 0.0

    def deactivate(self):
        self.transmitting = False
        self.loud_duration = 0.0


class HLSAudioTransmitter:
    """
    Encodes raw audio blocks into an HLS stream, in the same location and format
    as the regular audio streaming mode, so the web application can play it
    without any changes.

    The audio is handed to the encoder by a separate thread, so a slow or stalled
    encoder can never block the sound level monitoring.
    """
    def __init__(self,
                 output_dir,
                 output_file,
                 sampling_rate,
                 mp3_bitrate=128,
                 encrypted=True,
                 hls_segment_time=1,
                 hls_list_size=3,
                 log_path=None):
        self.output_dir = output_dir
        self.log_path = log_path

        input_args = [
            '-f', FFMPEG_INPUT_FORMAT, '-ar', '{:d}'.format(sampling_rate),
            '-ac', '1', '-i', 'pipe:0'
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

        self.command = ['ffmpeg', '-hide_banner', '-loglevel', 'fatal'] \
            + input_args + codec_args + stream_args + encryption_args \
            + [output_file]

        self.process = None
        self.log_file = None
        self.queue = None
        self.writer_thread = None

    @property
    def is_running(self):
        return self.process is not None

    def has_failed(self):
        return self.process is not None and self.process.poll() is not None

    def start(self, initial_blocks=()):
        if self.is_running:
            return
        self.log_file = open(self.log_path,
                             'a') if self.log_path else subprocess.DEVNULL
        self.process = subprocess.Popen(self.command,
                                        stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL,
                                        stderr=self.log_file,
                                        cwd=self.output_dir)
        self.queue = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)
        self.writer_thread = threading.Thread(target=self.write_queued_blocks,
                                              args=(self.process, self.queue),
                                              daemon=True)
        self.writer_thread.start()

        for block in initial_blocks:
            self.write(block)

    def write(self, raw_block):
        if not self.is_running:
            return
        try:
            self.queue.put_nowait(raw_block)
        except queue.Full:
            # Dropping audio is preferable to stalling the monitoring loop
            pass

    def write_queued_blocks(self, process, block_queue):
        while True:
            block = block_queue.get()
            if block is None:
                break
            try:
                process.stdin.write(block)
                process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError):
                break
        try:
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def stop(self):
        if not self.is_running:
            return
        self.request_writer_stop()
        if self.writer_thread is not None:
            self.writer_thread.join(timeout=2)
        try:
            # Closing the input makes ffmpeg finalize the stream and exit
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None
        self.queue = None
        self.writer_thread = None
        if self.log_file is not None and self.log_file is not subprocess.DEVNULL:
            self.log_file.close()
        self.log_file = None

    def request_writer_stop(self):
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            # Make room for the sentinel by discarding the oldest block
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(None)
            except (queue.Empty, queue.Full):
                pass


def run_vox():
    control.enter_mode(MODE, run_vox_mode)


def run_vox_mode(mode, config, database):
    log_path = os.environ.get('BM_SERVER_LOG_PATH')
    recording_settings = control.read_settings_if_available(
        'recording', config, database)
    run_vox_with_settings(
        config,
        control.read_settings(mode, config, database),
        control.read_settings('audiostream', config, database),
        recording_settings=recording_settings,
        event_log=events.create_event_log(config,
                                          database,
                                          recording_settings,
                                          log_path=log_path))


def run_vox_with_settings(config,
                          vox_settings,
                          audiostream_settings,
                          recording_settings=None,
                          event_log=None):
    comm_dir = pathlib.Path(os.environ['BM_DIR']) / 'control' / '.comm'
    state_file = comm_dir / 'vox_state.json'
    level_file = comm_dir / 'vox_level.dat'
    log_path = os.environ.get('BM_SERVER_LOG_PATH')

    sampling_rate = int(audiostream_settings.get('sampling_rate', 8000))
    mp3_bitrate = int(audiostream_settings.get('mp3_bitrate', 128))
    encrypted = bool(audiostream_settings.get('encrypted', True))
    gain = audiostream_settings.get('gain', 100)

    activation_threshold = float(vox_settings.get('activation_threshold', 12))
    notify_on_activation = bool(vox_settings.get('notify_on_activation', True))
    min_notification_interval = float(
        vox_settings.get('min_notification_interval', 60))

    mic.update_current_mic_volume(gain)

    extractor = create_feature_extractor(config, sampling_rate)
    extractor.create_A_weights()

    block_samples = extractor.adjust_waveform_length_to_fit_windows(
        max(extractor.fft_length, int(ANALYSIS_BLOCK_DURATION *
                                      sampling_rate)))

    capture = features.ContinuousRecorder(mic.get_audio_device(),
                                          sampling_rate=sampling_rate,
                                          block_samples=block_samples,
                                          output_format=SAMPLE_FORMAT,
                                          log_path=log_path)
    block_duration = capture.block_duration

    analyzer = features.LoudnessAnalyzer(
        background_loudness_level_offset=float(
            vox_settings.get('background_loudness_level_offset', 0)))

    trigger = VoxTrigger(
        activation_threshold=activation_threshold,
        activation_time=float(vox_settings.get('activation_time', 1.0)),
        release_margin=float(vox_settings.get('release_margin', 3.0)),
        hang_time=float(vox_settings.get('hang_time', 20)),
        min_transmission_time=float(
            vox_settings.get('min_transmission_time', 10)),
        max_transmission_time=float(
            vox_settings.get('max_transmission_time', 300)))

    transmitter = HLSAudioTransmitter(os.environ['BM_AUDIO_STREAM_DIR'],
                                      os.environ['BM_AUDIO_STREAM_FILE'],
                                      sampling_rate,
                                      mp3_bitrate=mp3_bitrate,
                                      encrypted=encrypted,
                                      log_path=log_path)

    # The recording covers the whole time the mode is active, not just the
    # moments when something is being transmitted
    audio_recorder = recorder.create_audio_recorder(recording_settings,
                                                    sampling_rate=sampling_rate,
                                                    mp3_bitrate=mp3_bitrate,
                                                    log_path=log_path)

    pre_roll = collections.deque(
        maxlen=max(1, int(round(PRE_ROLL_DURATION / block_duration))))

    # The background level needs a few blocks before it is representative
    calibration_block_count = analyzer.background_averaging_count

    state = STATE_CALIBRATING
    block_count = 0
    last_level_report_time = 0.0
    last_notification_time = -float('inf')
    encoder_failures = 0

    register_termination_handler()

    try:
        if audio_recorder is not None:
            try:
                audio_recorder.start()
            except Exception as exception:
                # Recording is secondary to transmitting, so a problem with it
                # must never take the mode down
                audio_recorder.log(
                    f'Could not start the recording: {exception}')
                audio_recorder = None

        with capture:
            control.signal_mode_started(MODE)
            write_status(state_file, state, 0.0, 0.0, activation_threshold,
                         time.time())

            while True:
                block = capture.read_block()
                if block is None:
                    raise RuntimeError(
                        'Audio capture ended unexpectedly, is the microphone still connected?'
                    )
                raw_block, samples, record_time = block

                loudness = extractor.compute_loudness_of_waveform(
                    extractor.convert_waveform(samples))
                analyzer.add_loudness(loudness)
                background_level, sound_contrast = analyzer.get_loudness_levels(
                )

                if transmitter.is_running:
                    transmitter.write(raw_block)
                else:
                    pre_roll.append(raw_block)

                if audio_recorder is not None:
                    audio_recorder.write(raw_block)

                block_count += 1
                now = time.time()
                notify = False
                state_changed = False

                if block_count >= calibration_block_count:
                    if state == STATE_CALIBRATING:
                        state = STATE_ARMED
                        state_changed = True

                    if trigger.update(sound_contrast, block_duration, now):
                        if trigger.transmitting:
                            transmitter.start(list(pre_roll))
                            pre_roll.clear()
                            state = STATE_TRANSMITTING
                            notify = notify_on_activation and (
                                now - last_notification_time
                                >= min_notification_interval)
                            if notify:
                                last_notification_time = now
                            if event_log is not None:
                                event_log.add(events.TRANSMISSION,
                                              sound_contrast, now)
                        else:
                            transmitter.stop()
                            state = STATE_ARMED
                            encoder_failures = 0
                        state_changed = True

                if state == STATE_TRANSMITTING and transmitter.has_failed():
                    transmitter.stop()
                    trigger.deactivate()
                    state = STATE_ARMED
                    state_changed = True
                    encoder_failures += 1
                    if encoder_failures >= MAX_ENCODER_FAILURES:
                        raise RuntimeError(
                            'The audio encoder failed {:d} times in a row, see the log for details'
                            .format(encoder_failures))
                    log_message(
                        log_path,
                        'The audio encoder stopped unexpectedly, going back to listening'
                    )

                if state_changed:
                    write_status(state_file, state, background_level,
                                 sound_contrast, activation_threshold,
                                 record_time, notify)

                if now - last_level_report_time >= LEVEL_REPORT_INTERVAL:
                    write_status(level_file, state, background_level,
                                 sound_contrast, activation_threshold,
                                 record_time)
                    last_level_report_time = now
    finally:
        transmitter.stop()
        if audio_recorder is not None:
            audio_recorder.stop()


def create_feature_extractor(config, sampling_rate):
    n_mel_bands = config['inference']['input_shape'][0]
    return features.AudioFeatureExtractor(sampling_rate=sampling_rate,
                                          n_mel_bands=n_mel_bands,
                                          backend='python_speech_features',
                                          disable_io=True)


def register_termination_handler():
    # Makes sure the encoder and the recorder are shut down cleanly when the
    # service is stopped
    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))


def write_status(file_path,
                 state,
                 background_level,
                 sound_contrast,
                 activation_threshold,
                 record_time,
                 notify=False):
    with open(file_path, 'w') as f:
        json.dump(
            {
                'st': state,
                'bg': f'{background_level:.2f}',
                'ct': f'{sound_contrast:.2f}',
                'th': f'{activation_threshold:.1f}',
                't': f'{record_time:.3f}',
                'nt': 1 if notify else 0
            }, f)


def log_message(log_path, message):
    message = f'vox: {message}'
    if log_path is None:
        print(message, file=sys.stderr)
        return
    with open(log_path, 'a') as f:
        f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n')


if __name__ == '__main__':
    run_vox()

"""
Rolling recording of what the baby monitor is capturing.

The recording is an HLS playlist that keeps a fixed amount of time and deletes
its oldest segments as new ones are written, so it can be left running without
ever filling up the card. Every segment carries the wall clock time it was
recorded at, which is what lets the timeline jump to the moment an event
happened.

Video is recorded by remuxing the stream the camera is already producing, which
costs almost no CPU since nothing is re-encoded. Audio from the VOX mode is
encoded from the raw samples that mode already has in memory.
"""

import os
import re
import time
import queue
import shutil
import pathlib
import threading
import subprocess

SEGMENT_SECONDS = 10
SEGMENT_PATTERN = 'seg_%06d.ts'
SEGMENT_REGEX = re.compile(r'^seg_(\d+)\.ts$')
PLAYLIST_NAME = 'index.m3u8'

# How often the encoder and the free space on the card are checked
SUPERVISION_INTERVAL = 20.0  # [s]
# How many times the encoder may be restarted before the recording gives up
MAX_RESTARTS = 5
# Maximum number of audio blocks waiting to be written to the encoder
MAX_QUEUED_BLOCKS = 32

VIDEO_SUBDIR = 'video'
AUDIO_SUBDIR = 'audio'


def remove_file(path):
    """
    Deletes a file, ignoring it already being gone. Path.unlink has a missing_ok
    argument for this, but only from Python 3.8, and the device runs 3.7.
    """
    try:
        path.unlink()
    except OSError:
        pass


def get_recording_dir():
    return pathlib.Path(
        os.environ.get('BM_RECORDING_DIR',
                       os.path.join(os.environ['BM_DIR'], 'recordings')))


def get_archive_dir(kind):
    return get_recording_dir() / kind


class RollingRecorder:
    """
    Base class for the recorders. Subclasses provide the ffmpeg arguments that
    produce the stream to record.

    The encoder is watched while it runs: if it stops on its own, which can
    happen when the stream it reads is interrupted, it is started again, and if
    the card runs low on space the recording stops instead of filling it.
    """
    def __init__(self,
                 archive_dir,
                 retention_minutes=30,
                 min_free_space_mb=500,
                 log_path=None):
        self.archive_dir = pathlib.Path(archive_dir)
        self.segment_count = max(
            2, int(round(retention_minutes * 60 / SEGMENT_SECONDS)))
        self.min_free_space = min_free_space_mb * 1024 * 1024
        self.log_path = log_path

        self.process = None
        self.log_file = None
        self.supervisor = None
        self.stopping = threading.Event()
        self.restart_count = 0
        self.stopped_for_space = False

    @property
    def playlist_path(self):
        return self.archive_dir / PLAYLIST_NAME

    @property
    def is_running(self):
        return self.process is not None

    def get_input_args(self):
        raise NotImplementedError

    def get_codec_args(self):
        raise NotImplementedError

    def get_stdin(self):
        return subprocess.DEVNULL

    def after_process_started(self):
        pass

    def before_process_terminated(self):
        pass

    def start(self):
        if self.is_running:
            return

        self.archive_dir.mkdir(parents=True, exist_ok=True)

        if not self.has_free_space():
            self.log(
                'Not enough free space for recording, nothing will be recorded')
            self.stopped_for_space = True
            return

        self.start_process()

        self.stopping.clear()
        self.supervisor = threading.Thread(target=self.supervise, daemon=True)
        self.supervisor.start()

    def start_process(self):
        start_number = self.prepare_archive()

        output_args = [
            '-f',
            'hls',
            '-hls_time',
            str(SEGMENT_SECONDS),
            '-hls_list_size',
            str(self.segment_count),
            '-hls_flags',
            'delete_segments+append_list+discont_start+program_date_time',
            '-hls_segment_filename',
            str(self.archive_dir / SEGMENT_PATTERN),
            '-start_number',
            str(start_number),
        ]

        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error'] \
            + self.get_input_args() + self.get_codec_args() + output_args \
            + [str(self.playlist_path)]

        if self.log_file is None:
            self.log_file = open(self.log_path,
                                 'a') if self.log_path else subprocess.DEVNULL
        self.process = subprocess.Popen(command,
                                        stdin=self.get_stdin(),
                                        stdout=subprocess.DEVNULL,
                                        stderr=self.log_file)
        self.after_process_started()

    def prepare_archive(self):
        """
        Makes the existing archive safe to continue writing to, and returns the
        segment number to continue from.
        """
        segment_numbers = []
        for path in self.archive_dir.glob('seg_*.ts'):
            match = SEGMENT_REGEX.match(path.name)
            if match:
                segment_numbers.append(int(match.group(1)))

        next_segment_number = max(segment_numbers) + 1 if segment_numbers else 0

        if not self.playlist_path.exists():
            # Segments without a playlist can never be played back
            for path in self.archive_dir.glob('seg_*.ts'):
                remove_file(path)
            return 0

        try:
            with open(self.playlist_path, 'r') as f:
                lines = f.readlines()
        except OSError as exception:
            self.log(f'Could not read the existing playlist: {exception}')
            return next_segment_number

        # A playlist that was closed cannot be appended to
        listed_segments = set()
        kept_lines = []
        for line in lines:
            if line.startswith('#EXT-X-ENDLIST'):
                continue
            kept_lines.append(line)
            name = line.strip()
            if SEGMENT_REGEX.match(name):
                listed_segments.add(name)

        if len(kept_lines) != len(lines):
            try:
                with open(self.playlist_path, 'w') as f:
                    f.writelines(kept_lines)
            except OSError as exception:
                self.log(f'Could not reopen the playlist: {exception}')

        # Segments left behind by an interrupted recording are never played
        for path in self.archive_dir.glob('seg_*.ts'):
            if path.name not in listed_segments:
                remove_file(path)

        return next_segment_number

    def has_free_space(self):
        try:
            return shutil.disk_usage(
                self.archive_dir).free >= self.min_free_space
        except OSError:
            return True

    def supervise(self):
        while not self.stopping.wait(SUPERVISION_INTERVAL):
            if not self.has_free_space():
                self.log(
                    'Free space ran low, stopping the recording to protect the card'
                )
                self.stopped_for_space = True
                self.terminate_process()
                return

            process = self.process
            if process is None or process.poll() is None:
                continue

            if self.restart_count >= MAX_RESTARTS:
                self.log(
                    'The encoder keeps stopping, giving up on the recording')
                self.terminate_process()
                return

            self.restart_count += 1
            self.log('The encoder stopped, starting it again')
            self.clean_up_process()
            try:
                self.start_process()
            except OSError as exception:
                self.log(f'Could not start the encoder again: {exception}')
                return

    def stop(self):
        self.stopping.set()
        if self.supervisor is not None:
            self.supervisor.join(timeout=2)
            self.supervisor = None
        self.before_process_terminated()
        self.terminate_process()
        if self.log_file is not None and self.log_file is not subprocess.DEVNULL:
            self.log_file.close()
        self.log_file = None

    def clean_up_process(self):
        self.process = None

    def terminate_process(self):
        process = self.process
        self.clean_up_process()
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def log(self, message):
        message = f'recorder: {message}'
        if self.log_path is None:
            import sys
            print(message, file=sys.stderr)
            return
        try:
            with open(self.log_path, 'a') as f:
                f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n')
        except OSError:
            pass


class StreamRemuxRecorder(RollingRecorder):
    """
    Records a stream that is already being produced, by copying the encoded
    packets into the archive without touching the codecs.
    """
    def __init__(self, source_playlist, archive_dir, **kwargs):
        super().__init__(archive_dir, **kwargs)
        self.source_playlist = str(source_playlist)

    def get_input_args(self):
        return [
            '-live_start_index', '-1', '-allowed_extensions', 'ALL', '-i',
            self.source_playlist
        ]

    def get_codec_args(self):
        return ['-c', 'copy']


class PCMRecorder(RollingRecorder):
    """
    Records raw audio samples handed over by the mode that captured them. The
    samples are written by a separate thread, so a slow encoder can never block
    the capture loop.
    """
    def __init__(self,
                 archive_dir,
                 sampling_rate=8000,
                 mp3_bitrate=64,
                 input_format='s16le',
                 **kwargs):
        super().__init__(archive_dir, **kwargs)
        self.sampling_rate = sampling_rate
        self.mp3_bitrate = mp3_bitrate
        self.input_format = input_format

        self.queue = None
        self.writer_thread = None

    def get_input_args(self):
        return [
            '-f', self.input_format, '-ar',
            '{:d}'.format(self.sampling_rate), '-ac', '1', '-i', 'pipe:0'
        ]

    def get_codec_args(self):
        return [
            '-acodec', 'libmp3lame', '-b:a', '{:d}k'.format(self.mp3_bitrate)
        ]

    def get_stdin(self):
        return subprocess.PIPE

    def after_process_started(self):
        self.queue = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)
        self.writer_thread = threading.Thread(target=self.write_queued_blocks,
                                              args=(self.process, self.queue),
                                              daemon=True)
        self.writer_thread.start()

    def write(self, raw_block):
        block_queue = self.queue
        if not self.is_running or block_queue is None:
            return
        try:
            block_queue.put_nowait(raw_block)
        except queue.Full:
            # Dropping audio is preferable to stalling the capture loop
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

    def clean_up_process(self):
        self.stop_writer()
        super().clean_up_process()

    def before_process_terminated(self):
        self.stop_writer()
        # Closing the input lets ffmpeg finish the last segment by itself
        process = self.process
        if process is not None:
            try:
                process.wait(timeout=5)
                self.process = None
            except subprocess.TimeoutExpired:
                pass

    def stop_writer(self):
        block_queue = self.queue
        self.queue = None
        if block_queue is not None:
            try:
                block_queue.put_nowait(None)
            except queue.Full:
                try:
                    block_queue.get_nowait()
                    block_queue.put_nowait(None)
                except (queue.Empty, queue.Full):
                    pass
        if self.writer_thread is not None:
            self.writer_thread.join(timeout=2)
            self.writer_thread = None


def create_remux_recorder(recording_settings,
                          source_playlist,
                          kind,
                          setting_name,
                          log_path=None):
    """
    Creates a recorder that copies a stream that is already being produced, or
    None if recording is turned off or has not been installed.
    """
    if not recording_settings or not recording_settings.get('enabled', False):
        return None
    if not recording_settings.get(setting_name, True):
        return None
    return StreamRemuxRecorder(
        source_playlist,
        get_archive_dir(kind),
        retention_minutes=recording_settings.get('retention_minutes', 30),
        min_free_space_mb=recording_settings.get('min_free_space', 500),
        log_path=log_path)


def create_video_recorder(recording_settings, source_playlist, log_path=None):
    return create_remux_recorder(recording_settings,
                                 source_playlist,
                                 VIDEO_SUBDIR,
                                 'record_video',
                                 log_path=log_path)


def create_audio_stream_recorder(recording_settings,
                                 source_playlist,
                                 log_path=None):
    return create_remux_recorder(recording_settings,
                                 source_playlist,
                                 AUDIO_SUBDIR,
                                 'record_audio',
                                 log_path=log_path)


def create_audio_recorder(recording_settings,
                          sampling_rate=8000,
                          mp3_bitrate=64,
                          log_path=None):
    """
    Creates the recorder for raw audio, or None if recording is turned off or
    has not been installed.
    """
    if not recording_settings or not recording_settings.get('enabled', False):
        return None
    if not recording_settings.get('record_audio', True):
        return None
    return PCMRecorder(
        get_archive_dir(AUDIO_SUBDIR),
        sampling_rate=sampling_rate,
        mp3_bitrate=mp3_bitrate,
        retention_minutes=recording_settings.get('retention_minutes', 30),
        min_free_space_mb=recording_settings.get('min_free_space', 500),
        log_path=log_path)

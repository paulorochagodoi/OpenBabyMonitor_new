#!/usr/bin/env python3
"""
Virtual fence monitoring.

A fence is a polygon the user draws over the camera image, around the area the
child is supposed to stay in. This program watches the video the camera is
already streaming and reports what happens relative to that polygon: movement
inside it, movement outside it, and how long the area inside it has been still,
which is what the sleep detection is based on.

The video is taken from the live stream rather than from the camera directly,
so the camera stays available for the streaming and there is no second capture
to keep in sync. The frames are decoded at a low resolution and a low frame
rate, which is all that movement detection needs.

Note that this detects *movement*, not the child. A still child and an empty
crib look the same to it, so "asleep" means "nothing has moved in the fence for
a while" and nothing more than that.
"""

import os
import sys
import json
import time
import signal
import pathlib
import subprocess

import numpy as np
import cv2

import control
import events

MODE = 'fence'

# Resolution the frames are analyzed at. The fence is stored in relative
# coordinates, so this is independent of the resolution the camera streams at.
ANALYSIS_WIDTH = 320
ANALYSIS_HEIGHT = 240

# Minimum time between two status reports to the web application
STATUS_REPORT_INTERVAL = 1.0  # [s]
# How long to wait for the stream to appear before giving up
STREAM_WAIT_TIMEOUT = 60.0  # [s]
STREAM_WAIT_INTERVAL = 0.5  # [s]
# How many times the decoder may die before the fence gives up
MAX_DECODER_FAILURES = 5

STATE_UNKNOWN = 'unknown'
STATE_AWAKE = 'awake'
STATE_ASLEEP = 'asleep'


class FrameSource:
    """
    Decodes the live stream into small grayscale frames.
    """
    def __init__(self, source_playlist, framerate=4, log_path=None):
        self.source_playlist = str(source_playlist)
        self.framerate = framerate
        self.log_path = log_path

        self.frame_bytes = ANALYSIS_WIDTH * ANALYSIS_HEIGHT
        self.process = None
        self.log_file = None

        self.command = [
            'ffmpeg',
            '-hide_banner',
            '-loglevel',
            'error',
            '-live_start_index',
            '-1',
            '-allowed_extensions',
            'ALL',
            '-i',
            self.source_playlist,
            '-an',
            '-vf',
            'fps={:d},scale={:d}:{:d}'.format(framerate, ANALYSIS_WIDTH,
                                              ANALYSIS_HEIGHT),
            '-f',
            'rawvideo',
            '-pix_fmt',
            'gray',
            'pipe:1',
        ]

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        if self.process is not None:
            return
        self.log_file = open(self.log_path,
                             'a') if self.log_path else subprocess.DEVNULL
        self.process = subprocess.Popen(self.command,
                                        stdout=subprocess.PIPE,
                                        stderr=self.log_file)

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        if self.log_file is not None and self.log_file is not subprocess.DEVNULL:
            self.log_file.close()
        self.log_file = None

    def read_frame(self):
        """
        Returns the next frame, or None when the stream ended.
        """
        raw_frame = self.process.stdout.read(self.frame_bytes)
        if raw_frame is None or len(raw_frame) < self.frame_bytes:
            return None
        return np.frombuffer(raw_frame, dtype=np.uint8).reshape(
            ANALYSIS_HEIGHT, ANALYSIS_WIDTH)


class FenceMask:
    """
    The area inside and outside the fence, as masks over the analyzed frame.
    """
    def __init__(self, polygon):
        self.polygon = polygon
        inside = np.zeros((ANALYSIS_HEIGHT, ANALYSIS_WIDTH), dtype=np.uint8)

        if polygon is not None and len(polygon) >= 3:
            points = np.array(
                [[int(round(x * (ANALYSIS_WIDTH - 1))),
                  int(round(y * (ANALYSIS_HEIGHT - 1)))] for x, y in polygon],
                dtype=np.int32)
            cv2.fillPoly(inside, [points], 1)
            self.is_configured = True
        else:
            # Without a fence the whole image counts as inside it
            inside[:] = 1
            self.is_configured = False

        self.inside = inside.astype(bool)
        self.outside = ~self.inside
        self.inside_pixels = int(np.count_nonzero(self.inside))
        self.outside_pixels = int(np.count_nonzero(self.outside))

    def compute_motion_fractions(self, motion_mask):
        inside_fraction = (np.count_nonzero(motion_mask & self.inside) /
                           self.inside_pixels) if self.inside_pixels else 0.0
        outside_fraction = (np.count_nonzero(motion_mask & self.outside) /
                            self.outside_pixels) if self.outside_pixels else 0.0
        return 100 * inside_fraction, 100 * outside_fraction


class MotionDetector:
    """
    Finds the pixels that changed since the previous frame.
    """
    def __init__(self, sensitivity=50):
        # A high sensitivity means a small change is enough to count as movement
        self.pixel_threshold = max(3, int(round(3 + (100 - sensitivity) * 0.4)))
        self.previous_frame = None

    def reset(self):
        """
        Forgets the previous frame, so the first frame after an interruption is
        not compared against something from before it and read as movement.
        """
        self.previous_frame = None

    def __call__(self, frame):
        blurred_frame = cv2.GaussianBlur(frame, (5, 5), 0)
        if self.previous_frame is None:
            self.previous_frame = blurred_frame
            return None
        difference = cv2.absdiff(blurred_frame, self.previous_frame)
        self.previous_frame = blurred_frame
        return difference > self.pixel_threshold


class FenceMonitor:
    """
    Turns the stream of motion measurements into states and events.
    """
    def __init__(self,
                 event_log=None,
                 min_motion_area=1.0,
                 alert_on_motion=True,
                 alert_on_outside=True,
                 sleep_delay=120.0,
                 min_alert_interval=60.0):
        self.event_log = event_log
        self.min_motion_area = min_motion_area
        self.alert_on_motion = alert_on_motion
        self.alert_on_outside = alert_on_outside
        self.sleep_delay = sleep_delay
        self.min_alert_interval = min_alert_interval

        self.state = STATE_UNKNOWN
        self.last_inside_motion_time = None
        self.last_alert_times = {}

    def update(self, inside_fraction, outside_fraction, now):
        """
        Registers a new measurement, returning the name of the alert it should
        be announced with, if any.
        """
        moving_inside = inside_fraction >= self.min_motion_area
        moving_outside = outside_fraction >= self.min_motion_area

        alert = None

        if moving_inside:
            self.last_inside_motion_time = now
            if self.state != STATE_AWAKE:
                previous_state = self.state
                self.state = STATE_AWAKE
                if previous_state == STATE_ASLEEP:
                    self.log_event(events.AWAKE, inside_fraction)
                    alert = events.AWAKE
            if self.alert_on_motion and self.allow_alert(events.MOTION, now):
                self.log_event(events.MOTION, inside_fraction)
                alert = events.MOTION
        elif self.last_inside_motion_time is not None and \
                now - self.last_inside_motion_time >= self.sleep_delay and \
                self.state != STATE_ASLEEP:
            self.state = STATE_ASLEEP
            self.log_event(events.ASLEEP)
            alert = events.ASLEEP

        if moving_outside and self.alert_on_outside and self.allow_alert(
                events.OUTSIDE, now):
            self.log_event(events.OUTSIDE, outside_fraction)
            alert = events.OUTSIDE

        return alert

    def allow_alert(self, alert_type, now):
        last_time = self.last_alert_times.get(alert_type)
        if last_time is not None and now - last_time < self.min_alert_interval:
            return False
        self.last_alert_times[alert_type] = now
        return True

    def log_event(self, event_type, value=None):
        if self.event_log is not None:
            self.event_log.add(event_type, value)

    def start_timing(self, now):
        if self.last_inside_motion_time is None:
            self.last_inside_motion_time = now


def watch_fence():
    config = control.get_config()
    database = control.get_database(config)
    log_path = os.environ.get('BM_SERVER_LOG_PATH')

    fence_settings = control.read_settings_if_available('fence', config,
                                                        database)
    if not fence_settings:
        log_message(log_path,
                    'The fence settings are missing, not watching the fence')
        return
    if not fence_settings.get('enabled', False):
        return

    recording_settings = control.read_settings_if_available(
        'recording', config, database)
    event_log = events.create_event_log(config,
                                        database,
                                        recording_settings,
                                        log_path=log_path)

    status_file = events.get_comm_dir() / 'fence.json'
    source_playlist = os.environ['BM_PICAM_STREAM_FILE']

    if not wait_for_stream(source_playlist):
        log_message(log_path,
                    f'The stream {source_playlist} never appeared')
        return

    mask = FenceMask(parse_polygon(fence_settings.get('polygon'), log_path))
    detector = MotionDetector(
        sensitivity=int(fence_settings.get('sensitivity', 50)))
    monitor = FenceMonitor(
        event_log=event_log,
        min_motion_area=float(fence_settings.get('min_motion_area', 1.0)),
        alert_on_motion=bool(fence_settings.get('alert_on_motion', True)),
        alert_on_outside=bool(fence_settings.get('alert_on_outside', True)),
        sleep_delay=float(fence_settings.get('sleep_delay', 120)),
        min_alert_interval=float(fence_settings.get('min_alert_interval', 60)))

    framerate = int(fence_settings.get('analysis_framerate', 4))

    register_termination_handler()

    last_status_time = 0.0
    decoder_failures = 0

    while True:
        frame_count = 0
        detector.reset()
        with FrameSource(source_playlist, framerate=framerate,
                         log_path=log_path) as frames:
            monitor.start_timing(time.time())
            write_status(status_file, monitor.state, 0.0, 0.0,
                         mask.is_configured, time.time())

            while True:
                frame = frames.read_frame()
                if frame is None:
                    break
                frame_count += 1

                motion_mask = detector(frame)
                now = time.time()
                if motion_mask is None:
                    continue

                inside_fraction, outside_fraction = mask.compute_motion_fractions(
                    motion_mask)
                alert = monitor.update(inside_fraction, outside_fraction, now)

                if alert is not None or now - last_status_time >= STATUS_REPORT_INTERVAL:
                    write_status(status_file,
                                 monitor.state,
                                 inside_fraction,
                                 outside_fraction,
                                 mask.is_configured,
                                 now,
                                 alert=alert)
                    last_status_time = now

        # The stream ends when the video mode is stopped, but it can also be
        # interrupted for a moment while segments are rotated. Only give up if
        # the interruptions come one after another.
        if frame_count > 10 * framerate:
            decoder_failures = 0
        decoder_failures += 1
        if decoder_failures >= MAX_DECODER_FAILURES:
            log_message(
                log_path,
                'The video stream could not be read, giving up on the fence')
            return
        time.sleep(1.0)
        if not pathlib.Path(source_playlist).exists():
            return


def parse_polygon(polygon_text, log_path=None):
    if not polygon_text:
        return None
    try:
        polygon = json.loads(polygon_text)
    except (ValueError, TypeError) as exception:
        log_message(log_path, f'Could not read the fence: {exception}')
        return None
    if not isinstance(polygon, list) or len(polygon) < 3:
        return None
    try:
        return [(min(1.0, max(0.0, float(point[0]))),
                 min(1.0, max(0.0, float(point[1])))) for point in polygon]
    except (TypeError, ValueError, IndexError) as exception:
        log_message(log_path, f'Could not read the fence corners: {exception}')
        return None


def wait_for_stream(source_playlist):
    path = pathlib.Path(source_playlist)
    elapsed_time = 0.0
    while not path.exists():
        time.sleep(STREAM_WAIT_INTERVAL)
        elapsed_time += STREAM_WAIT_INTERVAL
        if elapsed_time > STREAM_WAIT_TIMEOUT:
            return False
    return True


def register_termination_handler():
    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))


def write_status(file_path,
                 state,
                 inside_fraction,
                 outside_fraction,
                 fence_is_configured,
                 timestamp,
                 alert=None):
    with open(file_path, 'w') as f:
        json.dump(
            {
                'st': state,
                'in': f'{inside_fraction:.2f}',
                'out': f'{outside_fraction:.2f}',
                'cfg': 1 if fence_is_configured else 0,
                't': f'{timestamp:.3f}',
                'alert': '' if alert is None else alert
            }, f)


def log_message(log_path, message):
    message = f'fence: {message}'
    if log_path is None:
        print(message, file=sys.stderr)
        return
    try:
        with open(log_path, 'a') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n')
    except OSError:
        pass


if __name__ == '__main__':
    watch_fence()

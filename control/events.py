"""
Logging of the events shown on the timeline.

Events are short markers in time (the child started crying, something moved
inside the fence, the child fell asleep) that the modes report while they run.
They are kept in the database so the timeline can show what happened while
nobody was watching, and the most recent one is also written to a file so the
web application can be notified about it without polling the database.
"""

import os
import json
import time
import pathlib

# Reported by the listen mode
CRYING = 'crying'
BABBLING = 'babbling'
SOUND = 'sound'
# Reported by the VOX mode
TRANSMISSION = 'transmission'
# Reported by the fence monitor
MOTION = 'motion'
OUTSIDE = 'outside'
ASLEEP = 'asleep'
AWAKE = 'awake'
# Reported by the recorder
RECORDING_STOPPED = 'rec_stopped'

TABLE_NAME = 'events'

# How often old events are removed
PRUNE_INTERVAL = 600.0  # [s]


def get_comm_dir():
    return pathlib.Path(os.environ['BM_DIR']) / 'control' / '.comm'


class EventLog:
    """
    Writes events to the database, removing events that have grown too old.

    A failure to log an event must never take down the mode that reported it,
    so database errors are swallowed after being written to the log.
    """
    def __init__(self, database, retention_hours=48, log_path=None):
        self.database = database
        self.retention = retention_hours * 3600.0
        self.log_path = log_path
        self.event_file = get_comm_dir() / 'event.json'
        self.last_prune_time = 0.0

    def add(self, event_type, value=None, timestamp=None):
        if timestamp is None:
            timestamp = time.time()

        record = {'time': timestamp, 'type': event_type, 'value': value}

        try:
            with self.database as open_database:
                open_database.insert_values_into_table(TABLE_NAME, record)
                self.prune(open_database, timestamp)
        except Exception as exception:
            self.log(f'Could not store {event_type} event: {exception}')
            return

        self.publish(record)

    def prune(self, open_database, now):
        if now - self.last_prune_time < PRUNE_INTERVAL:
            return
        self.last_prune_time = now
        open_database.delete_rows_from_table(TABLE_NAME, '`time` < %s',
                                             (now - self.retention, ))

    def publish(self, record):
        try:
            with open(self.event_file, 'w') as f:
                json.dump(
                    {
                        't': '{:.3f}'.format(record['time']),
                        'type': record['type'],
                        'value':
                        '' if record['value'] is None else '{:.2f}'.format(
                            record['value'])
                    }, f)
        except OSError as exception:
            self.log(f'Could not publish event: {exception}')

    def log(self, message):
        message = f'events: {message}'
        if self.log_path is None:
            import sys
            print(message, file=sys.stderr)
            return
        try:
            with open(self.log_path, 'a') as f:
                f.write(
                    f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n')
        except OSError:
            pass


def create_event_log_from_config(config, recording_settings=None,
                                 log_path=None):
    """
    Creates an event log with its own database handle. Use this from a process
    that did not open the database itself, such as the inference worker.
    """
    import control
    return create_event_log(config,
                            control.get_database(config),
                            recording_settings,
                            log_path=log_path)


def notification_to_event_type(notification):
    """
    Maps a notification from the listen mode to the event it is recorded as.
    """
    if notification == 'sound':
        return SOUND
    return CRYING if 'bad' in notification else BABBLING


def create_event_log(config, database, recording_settings=None,
                     log_path=None):
    """
    Creates an event log with the retention from the recording settings, or None
    if the events table has not been installed yet, in which case the modes
    simply do not report any events.
    """
    import control
    if not control.table_is_available(TABLE_NAME, config, database):
        return None
    retention_hours = 48 if recording_settings is None else recording_settings.get(
        'event_retention_hours', 48)
    return EventLog(database,
                    retention_hours=retention_hours,
                    log_path=log_path)

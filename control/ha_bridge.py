#!/usr/bin/env python3
"""Opt-in Home Assistant bridge. No imports from hardware/database modules."""
import datetime
import json
import logging
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time

from mqtt_client import MQTTClient, Backoff

MODES = {'standby': 'Espera', 'listen': 'Notify/Avisar',
         'audiostream': 'Áudio', 'videostream': 'Vídeo', 'vox': 'VOX'}
DEFAULTS = dict(enabled=False, host='', port=1883, tls=False, ca_file='',
                discovery_prefix='homeassistant', base_topic='babymonitor',
                device_id='baba', heartbeat_interval=30, event_timeout=30,
                snapshot_enabled=False, snapshot_interval=30,
                snapshot_max_bytes=262144, mode_command_enabled=False,
                secrets_file='/home/pi/.config/babymonitor/mqtt.env')


def load_config(path):
    raw = json.loads(Path(path).read_text())['home_assistant']
    config = DEFAULTS.copy()
    config.update({key: value.get('initial_value') if isinstance(value, dict)
                   else value for key, value in raw.items() if key in DEFAULTS})
    for key in ('enabled', 'tls', 'snapshot_enabled', 'mode_command_enabled'):
        if not isinstance(config[key], bool):
            raise ValueError('Invalid boolean: ' + key)
    for key in ('device_id', 'base_topic', 'discovery_prefix'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', config[key]):
            raise ValueError('Invalid topic/id: ' + key)
    if '/' in config['device_id']:
        raise ValueError('Invalid device id')
    for key, low, high in [('port', 1, 65535), ('heartbeat_interval', 5, 3600),
                           ('event_timeout', 1, 3600), ('snapshot_interval', 5, 3600),
                           ('snapshot_max_bytes', 1024, 1048576)]:
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError('Invalid numeric setting: ' + key)
    if config['enabled'] and not config['host'].strip():
        raise ValueError('MQTT host required')
    return config


def load_secrets(path, repo):
    path = Path(path).expanduser().resolve()
    root = Path(repo).resolve()
    if path == root or root in path.parents:
        raise ValueError('MQTT secrets must be outside repository')
    with path.open() as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('MQTT secrets require mode 600')
        values = {}
        for line in stream:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator or key not in ('MQTT_USERNAME', 'MQTT_PASSWORD'):
                raise ValueError('Invalid MQTT secret file')
            values[key] = value
    if not values.get('MQTT_USERNAME') or not values.get('MQTT_PASSWORD'):
        raise ValueError('MQTT credentials required')
    return values


def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def fresh(record, now, age):
    try:
        return 0 <= now - float(record.get('ts', record.get('t', 0))) <= age
    except (ValueError, TypeError):
        return False


def iso_time(timestamp):
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()


def mode_call(root, mode=None):
    if mode is not None and mode not in MODES:
        raise ValueError('Invalid mode')
    args = ['php', str(Path(root) / 'control/ha_mode.php')]
    if mode is not None:
        args.append(mode)
    return subprocess.check_output(args, timeout=45, stderr=subprocess.DEVNULL).decode().strip()


def health_state(comm, now, mode_reader, temp_path='/sys/class/thermal/thermal_zone0/temp'):
    health = read_json(Path(comm) / 'health.json')
    if not health:
        health = {'ts': now, 'ok': True, 'checks': {}}
        try:
            health['mode'] = mode_reader()
        except (OSError, subprocess.SubprocessError):
            health['mode'], health['ok'] = 'unknown', False
        try:
            health['cpu_temp_c'] = float(Path(temp_path).read_text()) / 1000
        except (OSError, ValueError):
            pass
    result = dict(health)
    result['mode'] = health.get('mode', 'unknown')
    result['mode_label'] = MODES.get(result['mode'], 'Desconhecido')
    result['problem'] = ('ON' if not health.get('ok', False) or
                         not fresh(health, now, 180) or health.get('undervoltage') or
                         float(health.get('cpu_temp_c') or 0) >= 80 else 'OFF')
    result['heartbeat'] = iso_time(now)
    return result


def discovery(config):
    device_id = config['device_id']
    base = config['base_topic'] + '/' + device_id
    device = {'identifiers': ['openbabymonitor_' + device_id],
              'name': 'Babá eletrônica', 'manufacturer': 'OpenBabyMonitor',
              'model': 'Raspberry Pi'}
    entities = [('sensor', 'mode', 'Modo', None),
                ('binary_sensor', 'cry', 'Choro', 'sound'),
                ('binary_sensor', 'vox', 'VOX', 'sound'),
                ('binary_sensor', 'fence', 'Cerca virtual', 'motion'),
                ('binary_sensor', 'problem', 'Saúde', 'problem'),
                ('sensor', 'cpu_temp_c', 'Temperatura CPU', 'temperature'),
                ('sensor', 'heartbeat', 'Último heartbeat', 'timestamp'),
                ('sensor', 'event', 'Último evento', None)]
    if config['snapshot_enabled']:
        entities.append(('camera', 'snapshot', 'Snapshot', None))
    if config['mode_command_enabled']:
        entities.append(('select', 'mode_select', 'Modo (comando)', None))
    result = {}
    for component, obj, name, device_class in entities:
        payload = {'name': name, 'unique_id': 'obm_' + device_id + '_' + obj,
                   'availability_topic': base + '/availability', 'device': device}
        if component == 'camera':
            payload['topic'] = base + '/snapshot'
        else:
            payload['state_topic'] = base + '/state'
            key = 'mode_label' if obj == 'mode' else 'mode' if obj == 'mode_select' else obj
            payload['value_template'] = '{{ value_json.' + key + ' }}'
        if obj == 'event':
            payload['state_topic'] = base + '/event'
            payload['value_template'] = '{{ value_json.type }}'
            payload['json_attributes_topic'] = base + '/event'
        if device_class:
            payload['device_class'] = device_class
        if obj == 'cpu_temp_c':
            payload['unit_of_measurement'] = '°C'
            payload['state_class'] = 'measurement'
        if component == 'select':
            payload['command_topic'] = base + '/mode/set'
            payload['options'] = list(MODES)
        result[config['discovery_prefix'] + '/' + component + '/' + device_id + '/' + obj + '/config'] = payload
    return result


class EventStates:
    """Alert pulses; fence asleep/awake are sleep states, not fence alarms."""
    MAPPING = {'crying': 'cry', 'transmission': 'vox', 'motion': 'fence', 'outside': 'fence'}

    def __init__(self, timeout=30):
        self.timeout = timeout
        self.until = dict(cry=0, vox=0, fence=0)
        self.seen = {}
        self.last_event = {}

    def consume(self, record, source, now):
        signature = json.dumps(record, sort_keys=True)
        if not record or self.seen.get(source) == signature:
            return None
        self.seen[source] = signature
        if not fresh(record, now, self.timeout):
            return None
        kind = record.get('type')
        timestamp = float(record['t'])
        if abs(timestamp - self.last_event.get(kind, -1000000000)) < 1:
            return None
        self.last_event[kind] = timestamp
        key = self.MAPPING.get(kind)
        if key:
            self.until[key] = now + self.timeout
        return {'type': kind, 'ts': iso_time(float(record['t'])),
                'details': {'value': record.get('value'), 'source': source}}

    def values(self, now, vox=None, mode=None):
        result = {key: 'ON' if now < expiry else 'OFF' for key, expiry in self.until.items()}
        if mode != 'vox':
            result['vox'] = 'OFF'
        elif vox and fresh(vox, now, self.timeout):
            result['vox'] = 'ON' if vox.get('st') == 'transmitting' else 'OFF'
        return result


class Bridge:
    def __init__(self, root, config, client, clock=time.time):
        self.root, self.config, self.client, self.clock = Path(root), config, client, clock
        self.comm = self.root / 'control/.comm'
        self.base = config['base_topic'] + '/' + config['device_id']
        self.events = EventStates(config['event_timeout'])
        self.last_health = self.last_snapshot = 0
        self.health = {}
        self.last_state = None
        self.running = True
        self.vox_transmitting = False
        self.client.on_message = self.command

    def command(self, topic, payload):
        if not self.config['mode_command_enabled'] or topic != self.base + '/mode/set':
            return
        try:
            mode = payload.decode('utf-8')
            if mode not in MODES:
                return
            mode_call(self.root, mode)
            self.last_health = 0
        except (UnicodeError, OSError, subprocess.SubprocessError):
            logging.warning('Mode command failed')

    def snapshot(self, now):
        if not self.config['snapshot_enabled'] or self.health.get('mode') != 'videostream':
            return
        if now - self.last_snapshot < self.config['snapshot_interval']:
            return
        self.last_snapshot = now
        try:
            if mode_call(self.root) != 'videostream':
                return
        except (OSError, subprocess.SubprocessError):
            return
        stream = os.environ.get('BM_PICAM_STREAM_FILE', '')
        if not stream or not Path(stream).is_file():
            return
        try:
            with tempfile.TemporaryDirectory(prefix='obm-snapshot-') as directory:
                target = Path(directory) / 'frame.jpg'
                subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                                '-live_start_index', '-1', '-allowed_extensions', 'ALL',
                                '-i', stream, '-frames:v', '1', '-vf', 'scale=640:-2',
                                '-q:v', '5', '-fs', str(self.config['snapshot_max_bytes']),
                                str(target)], timeout=8, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if 0 < target.stat().st_size <= self.config['snapshot_max_bytes']:
                    data = target.read_bytes()
                    if data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
                        self.client.publish(self.base + '/snapshot', data)
        except (OSError, subprocess.SubprocessError):
            logging.warning('Snapshot unavailable')

    def connected(self):
        self.client.connect(self.base + '/availability')
        for topic, payload in discovery(self.config).items():
            self.client.publish(topic, json.dumps(payload), retain=True, qos=1)
        # Clear optional entities left by an earlier enabled configuration.
        for component, obj, enabled in [('camera', 'snapshot', 'snapshot_enabled'),
                                         ('select', 'mode_select', 'mode_command_enabled')]:
            if not self.config[enabled]:
                topic = self.config['discovery_prefix'] + '/' + component + '/' + self.config['device_id'] + '/' + obj + '/config'
                self.client.publish(topic, '', retain=True, qos=1)
        if self.config['mode_command_enabled']:
            self.client.subscribe(self.base + '/mode/set')
        self.last_health, self.last_state = 0, None
        self.tick()
        self.client.publish(self.base + '/availability', 'online', retain=True, qos=1)

    def tick(self):
        now = self.clock()
        heartbeat = not self.health or now - self.last_health >= self.config['heartbeat_interval']
        if heartbeat:
            self.health = health_state(self.comm, now, lambda: mode_call(self.root))
            self.last_health = now
        records = [('events', read_json(self.comm / 'event.json'))]
        vox = read_json(self.comm / 'vox_state.json')
        transmitting = (self.health.get('mode') == 'vox' and
                        fresh(vox, now, self.config['event_timeout']) and
                        vox.get('st') == 'transmitting')
        if transmitting and not self.vox_transmitting:
            records.append(('vox', dict(t=vox['t'], type='transmission')))
        self.vox_transmitting = transmitting
        fence = read_json(self.comm / 'fence.json')
        if fence.get('cfg') and fence.get('alert') in ('motion', 'outside') and self.health.get('mode') == 'videostream':
            records.append(('fence', dict(t=fence.get('t'), type=fence['alert'])))
        for source, record in records:
            event = self.events.consume(record, source, now)
            if event:
                self.client.publish(self.base + '/event', json.dumps(event))
                if event['type'] in EventStates.MAPPING:
                    self.snapshot(now)
        state = dict(self.health)
        state.update(self.events.values(now, read_json(self.comm / 'vox_state.json'), self.health.get('mode')))
        payload = json.dumps(state, sort_keys=True)
        if heartbeat or payload != self.last_state:
            self.client.publish(self.base + '/state', payload, retain=True, qos=1)
            self.last_state = payload

    def run(self, sleep=time.sleep):
        backoff = Backoff()
        while self.running:
            started = self.clock()
            try:
                self.connected()
                while self.running:
                    self.client.poll()
                    self.tick()
                    if self.clock() - started >= 60:
                        backoff.reset()
            except (OSError, ValueError, subprocess.SubprocessError):
                logging.warning('MQTT bridge unavailable; reconnecting')
            finally:
                if not self.running and self.client.sock:
                    try:
                        self.client.publish(self.base + '/availability', 'offline', retain=True, qos=1)
                    except OSError:
                        pass
                self.client.close()
            if self.running:
                sleep(backoff.next())


def main():
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / 'config/config.json')
    if not config['enabled']:
        # Remain idle under Restart=always. Never open the broker while disabled.
        while True:
            time.sleep(60)
    secrets = load_secrets(config['secrets_file'], root)
    client = MQTTClient(config['host'], config['port'], 'obm_' + config['device_id'],
                        secrets['MQTT_USERNAME'], secrets['MQTT_PASSWORD'],
                        tls=config['tls'], ca_file=config['ca_file'])
    bridge = Bridge(root, config, client)
    def stop(*args):
        bridge.running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        bridge.run()
    finally:
        if client.sock:
            try:
                client.publish(bridge.base + '/availability', 'offline', retain=True, qos=1)
            finally:
                client.close()


if __name__ == '__main__':
    main()

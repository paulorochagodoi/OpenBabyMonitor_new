#!/usr/bin/env python3
"""Optional local supervisor. health.json's ts is the public heartbeat."""
import fcntl
import json
import logging
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.request

import config

VERSION = '1'
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HEALTH_PATH = os.path.join(ROOT, 'control', '.comm', 'health.json')
MODES = ('standby', 'listen', 'audiostream', 'videostream', 'vox')
SERVICES = ('apache2', 'mariadb') + tuple('bm_' + mode for mode in MODES)


def settings(document):
    result = document['watchdog'].copy()
    for key in ('interval_s', 'timeout_s', 'hls_max_age_s', 'failure_count',
                'restart_limit', 'restart_window_s', 'backoff_s'):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError('Invalid watchdog setting: ' + key)
    for key in ('failure_count', 'restart_limit'):
        if not isinstance(result[key], int):
            raise ValueError('Expected integer: ' + key)
    for key in ('cpu_temp_max_c', 'disk_max_pct', 'mem_max_pct'):
        if not 0 < result[key] <= 100:
            raise ValueError('Invalid threshold: ' + key)
    if not isinstance(result['enabled'], bool):
        raise ValueError('enabled must be boolean')
    if result['apache_url'] not in ('http://localhost', 'https://localhost'):
        raise ValueError('apache_url must be local')
    return result


def atomic_json(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.health-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sd_notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        return
    if address.startswith('@'):
        address = '\0' + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(message.encode('utf-8'), address)


def parse_throttled(output):
    value = int(output.strip().split('=')[-1], 16)
    return hex(value), bool(value & 1)


def stream_check(path, now, maximum):
    try:
        age = now - os.stat(path).st_mtime
        return check(0 <= age <= maximum, 'HLS age {:.1f}s'.format(age))
    except OSError:
        return check(False, 'HLS missing')


def check(ok, detail):
    return {'ok': bool(ok), 'detail': detail}


class RestartPolicy:
    """Count attempts (including failed commands); retain an hour across restarts."""
    def __init__(self, cfg, history=None):
        self.cfg = cfg
        self.failures = {}
        self.history = history or {}

    def observe(self, service, ok, now):
        self.history[service] = [t for t in self.history.get(service, [])
                                 if now - t < 3600]
        self.failures[service] = 0 if ok else self.failures.get(service, 0) + 1
        return self.failures[service] >= self.cfg['failure_count']

    def allowed(self, service, now):
        recent = [t for t in self.history.get(service, [])
                  if now - t < self.cfg['restart_window_s']]
        delay = self.cfg['backoff_s'] * 2 ** min(len(recent), 10)
        return (len(recent) < self.cfg['restart_limit'] and
                (not recent or now - recent[-1] >= delay))

    def record(self, service, now):
        self.history.setdefault(service, []).append(now)
        self.failures[service] = 0


class Probe:
    def __init__(self, document, cfg):
        self.document = document
        self.cfg = cfg

    def command(self, args):
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              universal_newlines=True, timeout=self.cfg['timeout_s'])

    def active(self, service):
        return self.command(['systemctl', 'is-active', '--quiet', service]).returncode == 0

    def mode(self):
        # Existing connector and credentials; no extra package or secret.
        from database import Database
        database = Database.from_config(self.document)
        database.extra_config['connection_timeout'] = max(1, int(self.cfg['timeout_s']))
        with database as opened:
            value = opened.read_values_from_table('modes', 'current')
        for mode in MODES:
            if self.document['modes']['current']['values'][mode]['value'] == value:
                return mode
        raise ValueError('Unknown mode')

    def apache(self):
        # Do not follow redirects to non-local hosts; redirects still mean HTTP responds.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        try:
            with opener.open(self.cfg['apache_url'], timeout=self.cfg['timeout_s']) as response:
                return response.status < 500
        except urllib.error.HTTPError as error:
            return error.code < 500

    def restart(self, service, mode):
        if service not in SERVICES:
            raise ValueError('Service not allowed')
        if service.startswith('bm_'):
            path = os.environ.get('BM_MODE_LOCK_FILE', os.path.join(ROOT, 'control/.lock/lock'))
            with open(path, 'r') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return None
                if self.mode() != mode:
                    return None
                return self.command(['sudo', '-n', 'systemctl', 'restart', service]).returncode
        return self.command(['sudo', '-n', 'systemctl', 'restart', service]).returncode

    def resources(self):
        with open('/proc/meminfo') as source:
            memory = dict((line.split(':')[0], int(line.split()[1])) for line in source)
        disk = shutil.disk_usage(ROOT)
        temp, throttled, undervoltage = None, None, None
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as source:
                temp = float(source.read()) / 1000
        except (OSError, ValueError):
            pass
        try:
            throttled, undervoltage = parse_throttled(self.command(['vcgencmd', 'get_throttled']).stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return dict(cpu_temp_c=temp, throttled=throttled, undervoltage=undervoltage,
                    disk_used_pct=100.0 * disk.used / disk.total,
                    mem_used_pct=100.0 * (1 - memory['MemAvailable'] / memory['MemTotal']))


class Watchdog:
    def __init__(self, cfg, probe, path=HEALTH_PATH, clock=time.time, monotonic=time.monotonic):
        self.cfg, self.probe, self.path = cfg, probe, path
        self.clock, self.monotonic = clock, monotonic
        self.started = monotonic()
        self.previous_checks = {}
        self.state_path = path + '.restarts'
        history = {}
        try:
            with open(self.state_path) as source:
                raw = json.load(source)
            history = {s: [t for t in values if isinstance(t, (int, float))]
                       for s, values in raw.items() if s in SERVICES and isinstance(values, list)}
        except FileNotFoundError:
            pass
        # Other state read errors are fatal: never silently erase the restart budget.
        self.policy = RestartPolicy(cfg, history)

    def safe(self, function):
        try:
            return bool(function())
        except Exception:
            return False

    def tick(self):
        now = self.clock()
        apache = self.safe(self.probe.apache)
        maria = self.safe(lambda: self.probe.active('mariadb'))
        mode = 'unknown'
        if maria:
            try:
                mode = self.probe.mode()
            except Exception:
                maria = False
        checks = {'apache': check(apache, 'HTTP responds' if apache else 'HTTP unavailable'),
                  'mariadb': check(maria, 'active; mode query succeeded' if maria else 'inactive or query failed')}
        # standby is intentionally a short-lived script, hence inactive (dead) is normal.
        mode_ok = mode == 'standby' or (mode in MODES and self.safe(lambda: self.probe.active('bm_' + mode)))
        checks['mode_service'] = check(mode_ok, 'standby completed' if mode == 'standby' else mode)
        checks['stream'] = (stream_check(os.environ.get('BM_PICAM_STREAM_FILE', '/run/shm/picam/index.m3u8'), now,
                                         self.cfg['hls_max_age_s']) if mode == 'videostream'
                            else check(True, 'not applicable'))
        resources = self.probe.resources()
        checks['resources'] = check(
            resources['disk_used_pct'] < self.cfg['disk_max_pct'] and
            resources['mem_used_pct'] < self.cfg['mem_max_pct'] and
            (resources['cpu_temp_c'] is None or resources['cpu_temp_c'] < self.cfg['cpu_temp_max_c']) and
            resources['undervoltage'] is not True and
            (resources['throttled'] is None or not int(resources['throttled'], 16) & 0xf),
            'resource thresholds; historical throttling bits are informational')
        for name, result in checks.items():
            if self.previous_checks.get(name) != result['ok']:
                logging.warning('watchdog check=%s ok=%s', name, result['ok'])
            self.previous_checks[name] = result['ok']
        targets = {'apache2': apache, 'mariadb': maria}
        if mode in MODES and mode != 'standby':
            targets['bm_' + mode] = mode_ok and checks['stream']['ok']
        # A mode change breaks a sequence of consecutive failures.
        for service in list(self.policy.failures):
            if service not in targets:
                self.policy.failures[service] = 0
        for service, ok in targets.items():
            if self.policy.observe(service, ok, now) and self.policy.allowed(service, now):
                # Reserve budget durably BEFORE executing, even if command times out or daemon dies.
                self.policy.record(service, now)
                atomic_json(self.state_path, self.policy.history)
                try:
                    result = self.probe.restart(service, mode)
                except Exception:
                    result = 'failed'
                logging.warning('watchdog restart service=%s result=%s', service, result)
        health = dict(ts=now, uptime_s=self.monotonic() - self.started, mode=mode,
                      ok=all(item['ok'] for item in checks.values()), checks=checks,
                      restarts={s: len([t for t in times if now - t < 3600])
                                for s, times in self.policy.history.items()}, version=VERSION,
                      interval_s=self.cfg['interval_s'], **resources)
        atomic_json(self.path, health)
        return health


def main():
    logging.basicConfig(level=logging.INFO)
    document = config.read_config()
    cfg = settings(document)
    sd_notify('READY=1')
    watchdog = Watchdog(cfg, Probe(document, cfg)) if cfg['enabled'] else None
    while True:
        if watchdog is not None:
            watchdog.tick()
        sd_notify('WATCHDOG=1')
        # Keep systemd's heartbeat independent of the configured check interval.
        deadline = time.monotonic() + cfg['interval_s']
        while time.monotonic() < deadline:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            sd_notify('WATCHDOG=1')


if __name__ == '__main__':
    main()

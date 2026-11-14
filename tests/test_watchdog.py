import json
import os
import socket

import pytest
from conftest import load_module, ROOT


@pytest.fixture
def wd(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'control'))
    return load_module('watchdog_under_test', 'control/watchdog.py')


@pytest.fixture
def cfg(wd):
    with open(str(ROOT / 'config/config.json')) as source:
        return wd.settings(json.load(source))


def test_defaults_and_invalid_settings(wd, cfg):
    assert cfg['enabled'] is False
    assert cfg['interval_s'] == 10
    for key in ('interval_s', 'failure_count', 'restart_limit', 'timeout_s'):
        broken = cfg.copy()
        broken[key] = 0
        with pytest.raises(ValueError):
            wd.settings({'watchdog': broken})


def test_failures_recovery_and_budget(wd, cfg):
    policy = wd.RestartPolicy(cfg)
    assert not policy.observe('apache2', False, 0)
    assert not policy.observe('apache2', False, 10)
    assert not policy.observe('apache2', True, 20)
    for now in (30, 40):
        assert not policy.observe('apache2', False, now)
    assert policy.observe('apache2', False, 50)
    assert policy.allowed('apache2', 50)
    policy.record('apache2', 50)
    assert not policy.allowed('apache2', 60)
    assert policy.allowed('apache2', 110)
    policy.record('apache2', 110)
    assert not policy.allowed('apache2', 229)
    assert policy.allowed('apache2', 230)
    policy.record('apache2', 230)
    assert not policy.allowed('apache2', 800)
    assert policy.allowed('mariadb', 800)
    assert policy.allowed('apache2', 1200)


@pytest.mark.parametrize('raw,expected', [('throttled=0x0', ('0x0', False)),
                                         ('throttled=0x50005', ('0x50005', True)),
                                         ('0x10000', ('0x10000', False))])
def test_throttled(wd, raw, expected):
    assert wd.parse_throttled(raw) == expected


def test_hls(wd, tmp_path):
    path = str(tmp_path / 'index.m3u8')
    assert not wd.stream_check(path, 100, 30)['ok']
    with open(path, 'w') as output:
        output.write('#EXTM3U')
    os.utime(path, (90, 90))
    assert wd.stream_check(path, 100, 30)['ok']
    assert not wd.stream_check(path, 121, 30)['ok']


def test_atomic_write_and_cleanup(wd, tmp_path, monkeypatch):
    path = str(tmp_path / 'health.json')
    wd.atomic_json(path, {'old': True})
    original = wd.os.replace
    calls = []

    def replace(source, destination):
        assert json.loads(open(destination).read()) == {'old': True}
        calls.append(json.loads(open(source).read()))
        original(source, destination)
    monkeypatch.setattr(wd.os, 'replace', replace)
    wd.atomic_json(path, {'new': True})
    assert calls == [{'new': True}]
    assert len(list(tmp_path.iterdir())) == 1
    with pytest.raises(ValueError):
        wd.atomic_json(path, {'bad': float('nan')})
    assert json.loads(open(path).read()) == {'new': True}
    assert len(list(tmp_path.iterdir())) == 1


def test_notify(wd, tmp_path, monkeypatch):
    path = str(tmp_path / 'notify')
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(path)
        server.settimeout(1)
        monkeypatch.setenv('NOTIFY_SOCKET', path)
        wd.sd_notify('READY=1')
        assert server.recv(100) == b'READY=1'
        wd.sd_notify('WATCHDOG=1')
        assert server.recv(100) == b'WATCHDOG=1'


class FakeProbe:
    def __init__(self):
        self.current = 'videostream'
        self.good = False
        self.calls = []

    def apache(self):
        return True

    def active(self, service):
        return service == 'mariadb' or self.good

    def mode(self):
        return self.current

    def resources(self):
        return dict(cpu_temp_c=40.0, throttled='0x0', undervoltage=False,
                    disk_used_pct=10.0, mem_used_pct=20.0)

    def restart(self, service, mode):
        self.calls.append((service, mode))
        return 0


def test_tick_schema_persistence_and_mode_change(wd, cfg, tmp_path, monkeypatch):
    path = str(tmp_path / 'health.json')
    monkeypatch.setenv('BM_PICAM_STREAM_FILE', str(tmp_path / 'missing'))
    now = [100]
    probe = FakeProbe()
    daemon = wd.Watchdog(cfg, probe, path, lambda: now[0], lambda: now[0])
    for n in range(3):
        health = daemon.tick()
        now[0] += 10
    assert probe.calls == [('bm_videostream', 'videostream')]
    assert not health['ok']
    assert health['restarts'] == {'apache2': 0, 'mariadb': 0, 'bm_videostream': 1}
    assert set(health) == set(('ts', 'uptime_s', 'mode', 'ok', 'checks', 'cpu_temp_c',
                              'throttled', 'undervoltage', 'disk_used_pct', 'mem_used_pct',
                              'restarts', 'version', 'interval_s'))
    assert json.loads(open(path).read()) == health
    restarted = wd.Watchdog(cfg, probe, path, lambda: now[0], lambda: now[0])
    assert not restarted.policy.allowed('bm_videostream', now[0])
    probe.current = 'listen'
    probe.good = True
    assert daemon.tick()['ok']
    assert daemon.policy.failures['bm_videostream'] == 0
    probe.current = 'standby'
    probe.good = False
    assert daemon.tick()['ok']


def test_database_failure_never_restarts_unknown_mode(wd, cfg, tmp_path):
    probe = FakeProbe()
    probe.active = lambda service: False
    daemon = wd.Watchdog(cfg, probe, str(tmp_path / 'health.json'), lambda: 100)
    for _ in range(6):
        health = daemon.tick()
    assert health['mode'] == 'unknown'
    assert not health['checks']['mariadb']['ok']
    assert probe.calls == [('mariadb', 'unknown')]


def test_resource_alarm_does_not_restart(wd, cfg, tmp_path):
    probe = FakeProbe()
    probe.current = 'standby'
    original = probe.resources

    def hot():
        result = original()
        result['cpu_temp_c'] = 85.0
        return result
    probe.resources = hot
    daemon = wd.Watchdog(cfg, probe, str(tmp_path / 'health.json'), lambda: 100)
    for _ in range(5):
        health = daemon.tick()
    assert not health['ok']
    assert not health['checks']['resources']['ok']
    assert probe.calls == []


def test_mode_restart_respects_lock_and_rechecks_mode(wd, cfg, tmp_path, monkeypatch):
    path = tmp_path / 'lock'
    path.write_text('')
    monkeypatch.setenv('BM_MODE_LOCK_FILE', str(path))
    probe = wd.Probe({}, cfg)
    calls = []
    probe.command = lambda args: calls.append(args) or type('Result', (), {'returncode': 0})()
    probe.mode = lambda: 'listen'
    assert probe.restart('bm_videostream', 'videostream') is None
    assert not calls
    assert probe.restart('bm_listen', 'listen') == 0
    assert calls == [['sudo', '-n', 'systemctl', 'restart', 'bm_listen']]
    calls[:] = []
    with open(str(path)) as lock:
        wd.fcntl.flock(lock, wd.fcntl.LOCK_EX | wd.fcntl.LOCK_NB)
        assert probe.restart('bm_listen', 'listen') is None
    assert not calls
    with pytest.raises(ValueError):
        probe.restart('arbitrary', 'listen')


def test_restart_timeout_consumes_persistent_budget(wd, cfg, tmp_path):
    probe = FakeProbe()
    path = str(tmp_path / 'health.json')

    def timeout(service, mode):
        # Reservation is already durable when the command begins.
        assert json.loads(open(path + '.restarts').read())['bm_videostream'] == [100]
        raise wd.subprocess.TimeoutExpired('fake', 3)
    probe.restart = timeout
    daemon = wd.Watchdog(cfg, probe, path, lambda: 100)
    for _ in range(3):
        daemon.tick()
    new_daemon = wd.Watchdog(cfg, probe, path, lambda: 100)
    assert not new_daemon.policy.allowed('bm_videostream', 110)


def test_apache_uses_local_opener_and_timeout(wd, cfg, monkeypatch):
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Opener:
        def open(self, url, timeout):
            calls.append((url, timeout))
            return Response()
    monkeypatch.setattr(wd.urllib.request, 'build_opener', lambda *handlers: Opener())
    assert wd.Probe({}, cfg).apache()
    assert calls == [('https://localhost', 3)]


def test_clock_rollback_keeps_budget(wd, cfg):
    policy = wd.RestartPolicy(cfg, {'apache2': [100, 200, 300]})
    policy.observe('apache2', False, 50)
    assert not policy.allowed('apache2', 50)
    assert policy.history['apache2'] == [100, 200, 300]

"""MQTT/HA contract tests: no network, hardware, sleeps or secrets."""
import json
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'control'))
import mqtt_client as mqtt
import ha_bridge as ha


class Socket:
    def __init__(self, data=b''):
        self.data = data
        self.sent = []
        self.closed = False

    def recv(self, count):
        if not self.data:
            raise socket.timeout()
        result, self.data = self.data[:count], self.data[count:]
        return result

    def sendall(self, data):
        self.sent.append(data)

    def settimeout(self, timeout):
        pass

    def close(self):
        self.closed = True


def client(data=b'', clock=lambda: 0):
    sock = Socket(data)
    obj = mqtt.MQTTClient('fake', socket_factory=lambda *a, **k: sock, clock=clock)
    obj.sock = sock
    return obj, sock


def test_connect_credentials_will():
    expected = (b'\x10\x2a\x00\x04MQTT\x04\xe6\x00\x1e'
                b'\x00\x02id\x00\x04a/av\x00\x07offline\x00\x01u\x00\x01p')
    # Remaining length is checked independently against the complete body.
    data = mqtt.connect_packet('id', 30, 'u', 'p', 'a/av')
    assert data[2:] == expected[2:]
    assert data[1] == len(data) - 2
    obj, sock = client(b'\x20\x02\x00\x00')
    obj.connect('av')
    assert sock.sent[0][0] == 0x10


def test_publish_qos_and_puback():
    obj, sock = client(b'\x40\x02\x00\x01')
    obj.publish('t', b'x', retain=True)
    assert sock.sent[-1] == b'\x31\x04\x00\x01tx'
    obj.publish('t', b'x', qos=1)
    assert sock.sent[-1] == b'\x32\x06\x00\x01t\x00\x01x'


@pytest.mark.parametrize('number,encoded', [(0,b'\x00'), (127,b'\x7f'),
    (128,b'\x80\x01'), (16384,b'\x80\x80\x01'), (268435455,b'\xff\xff\xff\x7f')])
def test_remaining_length(number, encoded):
    assert mqtt.remaining_length(number) == encoded


def test_decode_multibyte_and_malformed():
    obj, _ = client(mqtt.packet(0x30, b'x' * 200))
    assert obj.read_packet() == (0x30, b'x' * 200)
    obj, _ = client(b'\x30\x80\x80\x80\x80')
    with pytest.raises(mqtt.MQTTError):
        obj.read_packet()


def test_ping_and_timeout():
    now = [16]
    obj, sock = client(b'\xd0\x00', clock=lambda: now[0])
    obj.poll()
    assert sock.sent == [b'\xc0\x00']
    assert obj.ping_at is None
    now[0] = 32
    obj.poll()
    now[0] = 63
    with pytest.raises(mqtt.MQTTError):
        obj.poll()


def test_subscribe_command_and_retained_rejected():
    obj, sock = client(b'\x90\x03\x00\x01\x00')
    obj.subscribe('cmd')
    assert sock.sent[0] == b'\x82\x08\x00\x01\x00\x03cmd\x00'
    calls = []
    obj.on_message = lambda *args: calls.append(args)
    obj.handle(0x31, mqtt.field('cmd') + b'vox')
    assert not calls
    obj.handle(0x30, mqtt.field('cmd') + b'vox')
    assert calls == [('cmd', b'vox')]


def test_backoff():
    backoff = mqtt.Backoff()
    assert [backoff.next() for _ in range(8)] == [2,4,8,16,32,60,60,60]
    backoff.reset()
    assert backoff.next() == 2


def test_config_and_external_secret(tmp_path):
    config = ha.load_config(Path(__file__).resolve().parents[1] / 'config/config.json')
    assert not config['enabled'] and not config['snapshot_enabled']
    assert not config['mode_command_enabled']
    secret = tmp_path / 'mqtt.env'
    secret.write_text('MQTT_USERNAME=<USUARIO_MQTT>\nMQTT_PASSWORD=<SENHA_MQTT>\n')
    secret.chmod(0o600)
    assert ha.load_secrets(secret, tmp_path / 'repo')['MQTT_USERNAME'] == '<USUARIO_MQTT>'
    with pytest.raises(ValueError):
        ha.load_secrets(secret, tmp_path)
    secret.chmod(0o644)
    with pytest.raises(ValueError):
        ha.load_secrets(secret, tmp_path / 'repo')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'home_assistant': {'heartbeat_interval': 0}}))
    with pytest.raises(ValueError):
        ha.load_config(path)


def test_discovery():
    config = dict(ha.DEFAULTS)
    config.update(snapshot_enabled=True, mode_command_enabled=True)
    first = ha.discovery(config)
    assert len(first) == 10
    assert first == ha.discovery(config)
    for topic, payload in first.items():
        payload = json.loads(json.dumps(payload))
        assert topic.endswith('/config')
        assert payload['availability_topic'] == 'babymonitor/baba/availability'
        assert payload['unique_id'].startswith('obm_baba_')
        assert payload['device']['name'] == 'Babá eletrônica'


@pytest.mark.parametrize('event,key', [('crying','cry'),('transmission','vox'),
                                       ('motion','fence'),('outside','fence')])
def test_event_pulses(event, key):
    states = ha.EventStates(10)
    record = {'t': '100', 'type': event, 'value': '2'}
    assert states.consume(record, 'events', 100)['type'] == event
    assert states.consume(record, 'events', 101) is None
    assert states.values(105, mode='vox')[key] == 'ON'
    assert states.values(110, mode='vox')[key] == 'OFF'
    assert states.consume({'t': 1, 'type': event}, 'events', 100) is None


def test_vox_status_and_fence_sleep():
    states = ha.EventStates()
    states.consume({'t': 100, 'type': 'asleep'}, 'events', 100)
    assert states.values(100)['fence'] == 'OFF'
    assert states.values(100, {'t':100,'st':'transmitting'}, 'vox')['vox'] == 'ON'
    assert states.values(100, {'t':100,'st':'armed'}, 'vox')['vox'] == 'OFF'
    assert states.values(200, {'t':100,'st':'transmitting'}, 'vox')['vox'] == 'OFF'


def test_mode_validation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ha, 'mode_call', lambda *args: calls.append(args))
    obj, _ = client()
    config = dict(ha.DEFAULTS, mode_command_enabled=True)
    bridge = ha.Bridge(tmp_path, config, obj)
    for bad in (b'nope', b'vox; reboot', b'\xff', b'1'):
        bridge.command(bridge.base + '/mode/set', bad)
    assert not calls
    bridge.command(bridge.base + '/mode/set', b'listen')
    assert calls[-1][1] == 'listen'
    config['mode_command_enabled'] = False
    bridge.command(bridge.base + '/mode/set', b'vox')
    assert len(calls) == 1


def test_health_fallback_and_stale(tmp_path):
    temp = tmp_path / 'temp'
    temp.write_text('55000')
    state = ha.health_state(tmp_path, 1000, lambda: 'listen', temp)
    assert state['mode_label'] == 'Notify/Avisar'
    assert state['cpu_temp_c'] == 55
    assert state['problem'] == 'OFF'
    (tmp_path / 'health.json').write_text(json.dumps({'ts':1, 'ok':True, 'mode':'vox'}))
    assert ha.health_state(tmp_path, 1000, lambda: 'listen', temp)['problem'] == 'ON'


def test_run_reconnect_without_sleep(tmp_path):
    class Failing:
        sock = None
        def close(self):
            pass
    bridge = ha.Bridge(tmp_path, dict(ha.DEFAULTS), Failing(), clock=lambda: 100)
    attempts = []
    def fail():
        raise OSError('fake')
    bridge.connected = fail
    def sleep(delay):
        attempts.append(delay)
        if len(attempts) == 4:
            bridge.running = False
    bridge.run(sleep)
    assert attempts == [2,4,8,16]


class Publisher:
    sock = None
    def __init__(self):
        self.messages = []
    def connect(self, topic):
        self.will = topic
    def publish(self, topic, payload, **kwargs):
        self.messages.append((topic, payload, kwargs))
    def subscribe(self, topic):
        self.subscription = topic


def test_connect_republishes_and_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(ha, 'mode_call', lambda *args: 'standby')
    pub = Publisher()
    now = [1000]
    bridge = ha.Bridge(tmp_path, dict(ha.DEFAULTS), pub, clock=lambda: now[0])
    bridge.connected()
    assert pub.will.endswith('/availability')
    assert pub.messages[-1][1] == 'online'
    assert pub.messages[-1][2] == {'retain': True, 'qos': 1}
    state = [m for m in pub.messages if m[0].endswith('/state')][-1]
    assert json.loads(state[1])['cry'] == 'OFF'
    count = len(pub.messages)
    bridge.tick()
    assert len(pub.messages) == count
    now[0] += 30
    bridge.tick()
    assert len(pub.messages) == count + 1
    bridge.connected()
    assert len(pub.messages) > count + 8


def test_snapshot_gates_and_bounds(tmp_path, monkeypatch):
    pub = Publisher()
    config = dict(ha.DEFAULTS, snapshot_enabled=True, snapshot_max_bytes=1024)
    bridge = ha.Bridge(tmp_path, config, pub)
    bridge.health = {'mode': 'videostream'}
    stream = tmp_path / 'stream.m3u8'
    stream.touch()
    monkeypatch.setenv('BM_PICAM_STREAM_FILE', str(stream))
    monkeypatch.setattr(ha, 'mode_call', lambda *args: 'videostream')
    calls = []
    def ffmpeg(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b'\xff\xd8test\xff\xd9')
    monkeypatch.setattr(ha.subprocess, 'run', ffmpeg)
    bridge.snapshot(100)
    assert pub.messages[-1][0].endswith('/snapshot')
    assert not pub.messages[-1][2].get('retain', False)
    bridge.snapshot(101)
    assert len(calls) == 1
    bridge.health['mode'] = 'listen'
    bridge.snapshot(200)
    assert len(calls) == 1
    bridge.health['mode'] = 'videostream'
    monkeypatch.setattr(ha, 'mode_call', lambda *args: 'listen')
    bridge.snapshot(300)
    assert len(calls) == 1
    monkeypatch.setattr(ha, 'mode_call', lambda *args: 'videostream')
    def oversized(args, **kwargs):
        Path(args[-1]).write_bytes(b'x' * 1025)
    monkeypatch.setattr(ha.subprocess, 'run', oversized)
    bridge.snapshot(400)
    assert len(pub.messages) == 1

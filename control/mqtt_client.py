"""Small blocking MQTT 3.1.1 client; stdlib only, injectable socket and clock.

QoS 1 waits for PUBACK. Failed sessions are discarded (clean session); callers
republish retained state after reconnect. No unbounded offline message queue.
"""
import socket
import ssl
import struct
import time


class MQTTError(OSError):
    pass


def remaining_length(value):
    if not 0 <= value <= 268435455:
        raise ValueError('Invalid MQTT remaining length')
    result = bytearray()
    while True:
        digit = value % 128
        value //= 128
        result.append(digit | (128 if value else 0))
        if not value:
            return bytes(result)


def field(value):
    data = value.encode('utf-8') if isinstance(value, str) else value
    if len(data) > 65535:
        raise ValueError('MQTT field too long')
    return struct.pack('!H', len(data)) + data


def packet(header, body=b''):
    return bytes([header]) + remaining_length(len(body)) + body


def connect_packet(client_id, keepalive, username=None, password=None,
                   will_topic=None, will_payload=b'offline'):
    flags = 2  # clean session
    payload = field(client_id)
    if will_topic:
        flags |= 0x24  # QoS 0 retained will
        payload += field(will_topic) + field(will_payload)
    if username is not None:
        flags |= 0x80
        payload += field(username)
    if password is not None:
        if username is None:
            raise ValueError('Password requires username')
        flags |= 0x40
        payload += field(password)
    return packet(0x10, field('MQTT') + bytes([4, flags]) +
                  struct.pack('!H', keepalive) + payload)


class Backoff:
    def __init__(self):
        self.delay = 2

    def reset(self):
        self.delay = 2

    def next(self):
        delay = self.delay
        self.delay = min(60, delay * 2)
        return delay


class MQTTClient:
    def __init__(self, host, port=1883, client_id='babymonitor', username=None,
                 password=None, keepalive=30, tls=False, ca_file=None,
                 socket_factory=socket.create_connection, clock=time.monotonic):
        self.host, self.port = host, port
        self.client_id, self.username, self.password = client_id, username, password
        self.keepalive, self.tls, self.ca_file = keepalive, tls, ca_file
        self.socket_factory, self.clock = socket_factory, clock
        self.sock = None
        self.serial = 0
        self.on_message = None
        self.last_sent = 0
        self.ping_at = None

    def send(self, data):
        self.sock.settimeout(5)
        self.sock.sendall(data)
        self.last_sent = self.clock()

    def exact(self, count):
        result = b''
        while len(result) < count:
            chunk = self.sock.recv(count - len(result))
            if not chunk:
                raise MQTTError('Broker disconnected')
            result += chunk
        return result

    def read_packet(self):
        header = self.exact(1)[0]
        length, multiplier = 0, 1
        for _ in range(4):
            digit = self.exact(1)[0]
            length += (digit & 127) * multiplier
            if not digit & 128:
                if length > 1048576:
                    raise MQTTError('Incoming packet too large')
                return header, self.exact(length)
            multiplier *= 128
        raise MQTTError('Malformed remaining length')

    def connect(self, will_topic):
        self.sock = self.socket_factory((self.host, self.port), timeout=5)
        try:
            if self.tls:
                context = ssl.create_default_context(cafile=self.ca_file or None)
                self.sock = context.wrap_socket(self.sock, server_hostname=self.host)
            self.sock.settimeout(5)
            self.ping_at = None
            self.send(connect_packet(self.client_id, self.keepalive, self.username,
                                     self.password, will_topic))
            if self.read_packet() != (0x20, b'\x00\x00'):
                raise MQTTError('MQTT connection refused')
        except Exception:
            self.close()
            raise

    def next_id(self):
        self.serial = self.serial % 65535 + 1
        return struct.pack('!H', self.serial)

    def handle(self, header, body):
        kind = header >> 4
        if kind == 13 and body == b'':
            self.ping_at = None
        elif kind == 3:
            if len(body) < 2:
                raise MQTTError('Malformed PUBLISH')
            size = struct.unpack('!H', body[:2])[0]
            qos = (header >> 1) & 3
            end = 2 + size
            if qos > 1 or len(body) < end + (2 if qos else 0):
                raise MQTTError('Unsupported PUBLISH')
            topic = body[2:end].decode('utf-8')
            payload = body[end + (2 if qos else 0):]
            if qos:
                self.send(packet(0x40, body[end:end + 2]))
            # Retained commands are never executed on subscribe/reconnect.
            if self.on_message and not header & 1:
                self.on_message(topic, payload)

    def await_packet(self, expected, identifier):
        deadline = self.clock() + 10
        while self.clock() < deadline:
            header, body = self.read_packet()
            if header == expected and body[:2] == identifier:
                if expected == 0x90 and body[2:] != b'\x00':
                    raise MQTTError('Subscription refused')
                return
            self.handle(header, body)
        raise MQTTError('MQTT acknowledgement timeout')

    def publish(self, topic, payload, retain=False, qos=0):
        if qos not in (0, 1):
            raise ValueError('Only QoS 0 and 1 supported')
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        identifier = self.next_id() if qos else b''
        self.send(packet(0x30 | (qos << 1) | int(retain),
                         field(topic) + identifier + payload))
        if qos:
            self.await_packet(0x40, identifier)

    def subscribe(self, topic):
        identifier = self.next_id()
        self.send(packet(0x82, identifier + field(topic) + b'\x00'))
        self.await_packet(0x90, identifier)

    def poll(self, timeout=0.5):
        now = self.clock()
        if self.ping_at is not None and now - self.ping_at >= self.keepalive:
            raise MQTTError('PINGRESP timeout')
        if self.ping_at is None and now - self.last_sent >= self.keepalive / 2:
            self.send(packet(0xc0))
            self.ping_at = now
        self.sock.settimeout(timeout)
        try:
            # Only the first byte may time out harmlessly. Mid-packet timeout
            # invalidates the session, avoiding parser desynchronization.
            first = self.sock.recv(1)
        except socket.timeout:
            return
        if not first:
            raise MQTTError('Broker disconnected')
        self.sock.settimeout(5)
        # Reuse the parser with the first byte buffered.
        original = self.exact
        buffered = [first]
        def read(count):
            if buffered:
                return buffered.pop()
            return original(count)
        self.exact = read
        try:
            self.handle(*self.read_packet())
        finally:
            self.exact = original

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

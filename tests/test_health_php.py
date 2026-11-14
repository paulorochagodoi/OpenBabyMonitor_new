"""Stale detection in site/public/health.php (runs only where a php CLI exists)."""
import json
import os
import shutil
import subprocess
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHP = shutil.which('php')
pytestmark = pytest.mark.skipif(PHP is None, reason='php CLI not available')


def run_health(tmp_path, ts):
    public = tmp_path / 'site' / 'public'
    src = tmp_path / 'site' / 'src'
    comm = tmp_path / 'control' / '.comm'
    for directory in (public, src, comm):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy(os.path.join(ROOT, 'site', 'public', 'health.php'), str(public / 'health.php'))
    (src / 'session.php').write_text('<?php function isLoggedIn() { return false; }\n')
    (comm / 'health.json').write_text(json.dumps(
        {'ts': ts, 'ok': True, 'mode': 'standby', 'interval_s': 10}))
    env = dict(os.environ, REQUEST_METHOD='GET')
    output = subprocess.check_output([PHP, str(public / 'health.php')], env=env)
    return json.loads(output.decode())


def test_fresh_fractional_timestamp_is_not_stale(tmp_path):
    # Regression: a ts written in the current second was flagged as future.
    result = run_health(tmp_path, time.time() + 0.9)
    assert result['stale'] is False and result['ok'] is True


def test_old_heartbeat_is_stale(tmp_path):
    result = run_health(tmp_path, time.time() - 40)
    assert result['stale'] is True and result['ok'] is False


def test_far_future_heartbeat_is_stale(tmp_path):
    result = run_health(tmp_path, time.time() + 60)
    assert result['stale'] is True


def test_anonymous_response_has_only_public_fields(tmp_path):
    result = run_health(tmp_path, time.time())
    assert set(result) == {'ok', 'ts', 'mode', 'stale'}

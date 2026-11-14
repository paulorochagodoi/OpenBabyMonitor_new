"""Static safety checks only: never install packages or join a tailnet."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [ROOT / 'scripts' / name for name in (
    'install_tailscale.sh', 'uninstall_tailscale.sh')]


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.name)
def test_script_safety(script):
    text = script.read_text(encoding='utf-8')
    assert re.search(r'^set -euo pipefail$', text, re.MULTILINE)
    assert 'tskey-' not in text.lower()
    # Reject literal assignments, including quoted ones; variable references
    # and obvious placeholders are allowed. This is a guard, not a secret scanner.
    literal_secret = re.compile(
        r'\b(?:password|passwd|senha|token|auth_?key|api_?key)\s*=\s*'
        r'''["']?(?![\s$<"'])[a-z0-9_+/.-]+''', re.IGNORECASE)
    assert not literal_secret.search(text)


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda path: path.name)
def test_script_bash_syntax(script):
    bash = shutil.which('bash')
    if bash is None:
        pytest.skip('bash is not installed')
    subprocess.run([bash, '-n', str(script)], check=True)

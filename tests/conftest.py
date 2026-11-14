"""Load real source modules while isolating VOX's device/service imports."""
import importlib.util
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vox(monkeypatch):
    # Only import-time dependencies are replaced. VoxTrigger itself is loaded
    # unchanged from production; no audio, database or subprocess is started.
    monkeypatch.setenv('BM_DIR', str(ROOT))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    for name in ('features', 'control', 'mic', 'events', 'recorder'):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    return load_module('vox_under_test', 'control/vox.py')


@pytest.fixture
def config_module():
    return load_module('config_under_test', 'control/config.py')

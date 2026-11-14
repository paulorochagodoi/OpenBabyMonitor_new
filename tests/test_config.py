import json

import pytest


def test_read_config_preserves_json_types(config_module, tmp_path, monkeypatch):
    expected = {'vox': {'enabled': True, 'threshold': 12.5, 'hang_time': 20},
                'optional': None, 'languages': ['pt', 'en'], 'name': 'Babá'}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(expected), encoding='utf-8')
    monkeypatch.setattr(config_module, 'CONFIG_PATH', str(path))
    assert config_module.read_config() == expected


def test_invalid_json_is_reported(config_module, tmp_path, monkeypatch):
    path = tmp_path / 'invalid.json'
    path.write_text('{invalid', encoding='utf-8')
    monkeypatch.setattr(config_module, 'CONFIG_PATH', str(path))
    with pytest.raises(json.JSONDecodeError):
        config_module.read_config()


def test_missing_config_is_reported(config_module, tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, 'CONFIG_PATH', str(tmp_path / 'missing'))
    with pytest.raises(FileNotFoundError):
        config_module.read_config()


def test_repository_config_can_be_read_outside_project_directory(
        config_module, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = config_module.read_config()
    assert config['modes']['current']['values']['vox']['value'] == 4
    assert 'database' in config
    assert config['watchdog']['enabled'] is False
    assert config['watchdog']['failure_count'] == 3

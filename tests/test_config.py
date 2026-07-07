"""Tests for the Config class."""

from framelabs.core.config import Config


def test_defaults_used_when_no_file_exists(tmp_path):
    config_path = tmp_path / "config.json"
    cfg = Config(config_path=config_path)

    assert cfg.get("default_fps") == 12
    assert cfg.get("max_undo_history") == 100


def test_save_and_reload_persists_changes(tmp_path):
    config_path = tmp_path / "config.json"

    cfg = Config(config_path=config_path)
    cfg.set("default_fps", 24)
    cfg.save()

    reloaded = Config(config_path=config_path)
    assert reloaded.get("default_fps") == 24


def test_missing_keys_fall_back_to_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"default_fps": 30}')

    cfg = Config(config_path=config_path)

    assert cfg.get("default_fps") == 30
    assert cfg.get("max_undo_history") == 100


def test_corrupted_file_falls_back_to_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{not valid json")

    cfg = Config(config_path=config_path)

    assert cfg.get("default_fps") == 12

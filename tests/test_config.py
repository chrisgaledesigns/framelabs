"""Tests for the Config class."""

import json

from framelabs.core.config import Config, parse_shortcut


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


def test_old_config_missing_new_shortcut_keys_still_gets_defaults(tmp_path):
    """A config.json saved before "duplicate_frame"/"play_pause" existed
    should still get those two keys' defaults after loading, instead of
    losing them because the whole "keyboard_shortcuts" sub-dict got
    replaced wholesale by a shallow update().
    """
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "keyboard_shortcuts": {
                    "capture": "Space",
                    "save": "Ctrl+S",
                }
            }
        )
    )

    cfg = Config(config_path=config_path)
    shortcuts = cfg.get("keyboard_shortcuts")

    assert shortcuts["capture"] == "Space"
    assert shortcuts["duplicate_frame"] == "Ctrl+D"
    assert shortcuts["play_pause"] == "Return,Enter"


def test_saved_shortcut_override_is_preserved(tmp_path):
    """A user's deliberate override of an existing shortcut should survive
    the merge, not get reset back to the default.
    """
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"keyboard_shortcuts": {"capture": "Ctrl+Shift+C"}})
    )

    cfg = Config(config_path=config_path)

    assert cfg.get("keyboard_shortcuts")["capture"] == "Ctrl+Shift+C"
    assert cfg.get("keyboard_shortcuts")["save"] == "Ctrl+S"


def test_parse_shortcut_single_key():
    assert parse_shortcut("Ctrl+D") == ["Ctrl+D"]


def test_parse_shortcut_multiple_keys():
    assert parse_shortcut("Return,Enter") == ["Return", "Enter"]


def test_parse_shortcut_strips_whitespace_and_drops_empties():
    assert parse_shortcut(" Ctrl+D , , Ctrl+E ") == ["Ctrl+D", "Ctrl+E"]


def test_parse_shortcut_empty_string():
    assert parse_shortcut("") == []

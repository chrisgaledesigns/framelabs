"""Application configuration management.

Settings persist as JSON in the user's home directory, separate from the
project repository -- user preferences are not source code.
"""

import json
from pathlib import Path
from typing import Any

from framelabs.core.logger import get_logger

logger = get_logger("core.config")

CONFIG_DIR = Path.home() / ".framelabs"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_fps": 12,
    "autosave_interval_seconds": 30,
    "max_autosaves_kept": 20,
    "max_undo_history": 100,
    "keyboard_shortcuts": {
        "capture": "Space",
        "save": "Ctrl+S",
        "undo": "Ctrl+Z",
        "redo": "Ctrl+Shift+Z",
        "duplicate_frame": "Ctrl+D",
        "play_pause": "Return,Enter",
        "open_in_blender": "B",
        "toggle_onion_skin": "O",
        "previous_frame": "Left",
        "next_frame": "Right",
    },
}


class Config:
    """Loads, holds, and saves application settings.

    Falls back to DEFAULT_SETTINGS for any key missing from the saved file,
    so new settings can be added later without breaking existing users'
    config files (the handbook's "forward-compatible whenever possible" rule).
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or CONFIG_FILE
        self._settings: dict[str, Any] = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self) -> None:
        """Load settings from disk, if a config file exists."""
        if not self._config_path.exists():
            logger.info("No existing config found; using defaults")
            return

        try:
            with open(self._config_path, encoding="utf-8") as f:
                saved_settings = json.load(f)

            # "keyboard_shortcuts" is a nested dict, so a plain
            # dict.update() below would silently DROP any key that's in
            # DEFAULT_SETTINGS but missing from an older saved config.json
            # (e.g. every config saved before "duplicate_frame"/
            # "play_pause" existed) -- replacing the whole sub-dict rather
            # than filling in the gap. Per the Handbook's "forward-
            # compatible whenever possible" rule, merge it explicitly
            # instead of trusting a shallow update for this one nested key.
            saved_shortcuts = saved_settings.pop("keyboard_shortcuts", None)
            self._settings.update(saved_settings)
            if saved_shortcuts is not None:
                merged_shortcuts = DEFAULT_SETTINGS["keyboard_shortcuts"].copy()
                merged_shortcuts.update(saved_shortcuts)
                self._settings["keyboard_shortcuts"] = merged_shortcuts

            logger.info("Config loaded from %s", self._config_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load config, using defaults: %s", exc)

    def save(self) -> None:
        """Write current settings to disk."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
            logger.info("Config saved to %s", self._config_path)
        except OSError as exc:
            logger.error("Failed to save config: %s", exc)
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value by key."""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value by key. Does not save automatically."""
        self._settings[key] = value
        logger.info("Config setting changed: %s = %s", key, value)


def parse_shortcut(value: str) -> list[str]:
    """Split a keyboard_shortcuts config value into individual key strings.

    Most actions have a single key sequence ("Ctrl+D"); a few (e.g. Play,
    which accepts both Return and numpad Enter) need more than one
    physical key bound to the same action, expressed as a comma-separated
    string ("Return,Enter"). Kept Qt-free and pure -- per the Handbook's
    "Small Modules" principle -- so it's unit-testable with no GUI setup
    at all. The only caller that wraps each resulting string in a real
    QKeySequence is MainWindow._shortcuts().
    """
    return [part.strip() for part in value.split(",") if part.strip()]

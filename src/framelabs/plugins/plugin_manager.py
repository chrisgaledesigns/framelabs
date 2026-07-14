"""Discovers, loads, and isolates FrameLabs plugins.

Plugins live in ~/.framelabs/plugins/ -- outside the installed application
package, same separation Config and logs already use (see core/config.py's
CONFIG_DIR) -- so a distributable .exe still has a sensible place for
users to drop plugin files without touching the installed application.

Per the Developer Handbook's Plugin System rule, a single misbehaving
plugin must never crash the application: each plugin file is imported and
activated inside its own try/except Exception, deliberately broad --
unlike most exception handling in this codebase, catching the generic
Exception here is the correct, intentional choice, since a plugin can
fail in essentially any way (bad syntax, import error, a wrong number of
PluginBase subclasses, or an exception from activate() itself) and every
one of those must be isolated the same way: disable that plugin, log it,
keep going.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from framelabs.core.logger import get_logger
from framelabs.plugins.plugin_interface import PluginBase

logger = get_logger(__name__)

PLUGINS_DIR = Path.home() / ".framelabs" / "plugins"


class PluginManager:
    """Scans a directory for plugin files and activates each valid one.

    Runs synchronously on the main thread at application startup --
    plugin loading is one-time file I/O at launch, the same category as
    Config.load(), not a recurring or long-running operation, so no
    worker thread is needed here.
    """

    def __init__(self, plugins_dir: Path | None = None) -> None:
        """Set the directory to scan for plugins.

        Args:
            plugins_dir: Overrides the default ~/.framelabs/plugins/ --
                exists so tests can point at a tmp_path instead of the
                real user directory.
        """
        self._plugins_dir = plugins_dir or PLUGINS_DIR
        self.loaded_plugins: list[PluginBase] = []
        self.failed_plugin_files: list[str] = []

    def load_plugins(self) -> None:
        """Scan the plugins directory and activate every valid plugin.

        Missing plugins directory is not an error -- it just means no
        plugins are installed, which is the common case. Each *.py file
        found is attempted independently; one failing never stops the
        rest from loading.
        """
        if not self._plugins_dir.exists():
            logger.info(
                "No plugins directory found at %s; skipping plugin load",
                self._plugins_dir,
            )
            return

        plugin_files = sorted(self._plugins_dir.glob("*.py"))
        if not plugin_files:
            logger.info("No plugin files found in %s", self._plugins_dir)
            return

        for plugin_file in plugin_files:
            self._load_one_plugin(plugin_file)

    def _load_one_plugin(self, plugin_file: Path) -> None:
        """Import, instantiate, and activate a single plugin file.

        Any failure at any stage is caught, logged, and recorded in
        failed_plugin_files -- the loop in load_plugins() is never
        interrupted by a single bad plugin.
        """
        try:
            plugin_class = self._import_plugin_class(plugin_file)
            plugin_instance = plugin_class()
            plugin_instance.activate()
        except Exception as exc:
            logger.error("Plugin failed: %s: %s", plugin_file.name, exc)
            self.failed_plugin_files.append(plugin_file.name)
            return

        self.loaded_plugins.append(plugin_instance)
        logger.info("Plugin loaded: %s", plugin_instance.name)

    @staticmethod
    def _import_plugin_class(plugin_file: Path) -> type[PluginBase]:
        """Import a plugin file as a module and return its PluginBase
        subclass.

        Raises ValueError if the file defines zero or more than one
        PluginBase subclass -- a plugin file must define exactly one, so
        PluginManager always knows unambiguously what to instantiate.
        """
        module_name = f"framelabs_plugin_{plugin_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load spec for {plugin_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        found_classes = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type)
            and issubclass(obj, PluginBase)
            and obj is not PluginBase
        ]

        if len(found_classes) == 0:
            raise ValueError(f"{plugin_file.name} defines no PluginBase subclass")
        if len(found_classes) > 1:
            raise ValueError(
                f"{plugin_file.name} defines multiple PluginBase subclasses "
                f"({len(found_classes)}); expected exactly one"
            )

        return found_classes[0]

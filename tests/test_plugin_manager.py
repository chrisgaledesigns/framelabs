"""Tests for plugin discovery, loading, and isolation in plugin_manager.py.

Uses real plugin files written to tmp_path rather than mocked imports --
PluginManager's whole job is dynamic file-based importlib loading, so a
mock would test nothing real. No test here depends on ~/.framelabs/plugins/
or any real installed plugin, per the Developer Handbook's testing rule.
"""

from framelabs.plugins.plugin_manager import PluginManager

VALID_PLUGIN_SOURCE = """
from framelabs.plugins.plugin_interface import PluginBase


class SamplePlugin(PluginBase):
    name = "Sample Plugin"

    def activate(self):
        pass
"""

NO_PLUGINBASE_SOURCE = """
class NotAPlugin:
    pass
"""

TWO_PLUGINBASE_SOURCE = """
from framelabs.plugins.plugin_interface import PluginBase


class FirstPlugin(PluginBase):
    name = "First Plugin"

    def activate(self):
        pass


class SecondPlugin(PluginBase):
    name = "Second Plugin"

    def activate(self):
        pass
"""

ACTIVATE_RAISES_SOURCE = """
from framelabs.plugins.plugin_interface import PluginBase


class BrokenPlugin(PluginBase):
    name = "Broken Plugin"

    def activate(self):
        raise RuntimeError("activate() blew up")
"""

SYNTAX_ERROR_SOURCE = """
def this is not valid python(
"""


def test_load_plugins_with_missing_directory_is_noop(tmp_path):
    """No plugins directory at all should not raise -- it just means no
    plugins are installed, the common case."""
    missing_dir = tmp_path / "does_not_exist"
    manager = PluginManager(plugins_dir=missing_dir)

    manager.load_plugins()  # should not raise

    assert manager.loaded_plugins == []
    assert manager.failed_plugin_files == []


def test_load_plugins_with_empty_directory_is_noop(tmp_path):
    """An existing but empty plugins directory should not raise and should
    leave both lists empty."""
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()

    assert manager.loaded_plugins == []
    assert manager.failed_plugin_files == []


def test_load_plugins_loads_valid_plugin(tmp_path):
    """A plugin file defining exactly one PluginBase subclass should be
    imported, instantiated, and activated."""
    (tmp_path / "sample_plugin.py").write_text(VALID_PLUGIN_SOURCE)
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()

    assert len(manager.loaded_plugins) == 1
    assert manager.loaded_plugins[0].name == "Sample Plugin"
    assert manager.failed_plugin_files == []


def test_load_plugins_with_zero_pluginbase_subclass_fails(tmp_path):
    """A file with no PluginBase subclass should be caught and recorded as
    failed, not raised -- one bad plugin must never crash the app."""
    (tmp_path / "not_a_plugin.py").write_text(NO_PLUGINBASE_SOURCE)
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()  # should not raise

    assert manager.loaded_plugins == []
    assert manager.failed_plugin_files == ["not_a_plugin.py"]


def test_load_plugins_with_multiple_pluginbase_subclasses_fails(tmp_path):
    """A file defining more than one PluginBase subclass is ambiguous and
    should be caught and recorded as failed, not raised."""
    (tmp_path / "two_plugins.py").write_text(TWO_PLUGINBASE_SOURCE)
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()

    assert manager.loaded_plugins == []
    assert manager.failed_plugin_files == ["two_plugins.py"]


def test_load_plugins_activate_exception_is_caught_and_logged(tmp_path):
    """A plugin whose activate() raises should be caught and recorded as
    failed, not allowed to propagate and crash the app."""
    (tmp_path / "broken_plugin.py").write_text(ACTIVATE_RAISES_SOURCE)
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()

    assert manager.loaded_plugins == []
    assert manager.failed_plugin_files == ["broken_plugin.py"]


def test_load_plugins_with_syntax_error_fails(tmp_path):
    """A plugin file that isn't even valid Python should be caught and
    recorded as failed, not raised -- exec_module() surfaces a SyntaxError
    here, which the broad except Exception must still catch."""
    (tmp_path / "syntax_error.py").write_text(SYNTAX_ERROR_SOURCE)
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()

    assert manager.loaded_plugins == []
    assert manager.failed_plugin_files == ["syntax_error.py"]


def test_load_plugins_continues_after_one_failure(tmp_path):
    """One bad plugin file must not stop the rest of the directory from
    loading -- this is the core Plugin System guarantee from the Handbook."""
    (tmp_path / "a_broken.py").write_text(NO_PLUGINBASE_SOURCE)
    (tmp_path / "b_valid.py").write_text(VALID_PLUGIN_SOURCE)
    manager = PluginManager(plugins_dir=tmp_path)

    manager.load_plugins()

    assert len(manager.loaded_plugins) == 1
    assert manager.loaded_plugins[0].name == "Sample Plugin"
    assert manager.failed_plugin_files == ["a_broken.py"]


def test_plugin_manager_defaults_to_standard_plugins_dir():
    """With no plugins_dir override, PluginManager should point at the
    module-level default (~/.framelabs/plugins/), not None."""
    from framelabs.plugins.plugin_manager import PLUGINS_DIR

    manager = PluginManager()

    assert manager._plugins_dir == PLUGINS_DIR

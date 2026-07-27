"""Tests for blender/launcher.py."""

from unittest.mock import MagicMock, patch

import pytest

from framelabs.blender.launcher import (
    BlenderLauncher,
    BlenderLaunchError,
    auto_detect_executable,
)
from framelabs.core.config import Config


@pytest.fixture
def config(tmp_path):
    return Config(config_path=tmp_path / "config.json")


@pytest.fixture
def fake_blender(tmp_path):
    """A real file standing in for a Blender executable, so
    Path.is_file() checks succeed without touching a real install."""
    path = tmp_path / "blender.exe"
    path.write_text("fake")
    return path


class TestAutoDetectExecutable:
    def test_returns_none_when_nothing_found(self):
        with patch("framelabs.blender.launcher._search_paths", return_value=()):
            assert auto_detect_executable() is None

    def test_returns_first_existing_path(self, fake_blender):
        with patch(
            "framelabs.blender.launcher._search_paths",
            return_value=("/nonexistent/blender", str(fake_blender)),
        ):
            assert auto_detect_executable() == fake_blender


class TestResolveExecutable:
    def test_uses_remembered_path_if_it_exists(self, config, fake_blender):
        config.set("blender_executable_path", str(fake_blender))
        launcher = BlenderLauncher(config)
        assert launcher.resolve_executable() == fake_blender

    def test_falls_back_to_auto_detect_if_remembered_path_missing(
        self, config, fake_blender
    ):
        config.set("blender_executable_path", "/does/not/exist/blender")
        launcher = BlenderLauncher(config)
        with patch(
            "framelabs.blender.launcher.auto_detect_executable",
            return_value=fake_blender,
        ):
            assert launcher.resolve_executable() == fake_blender

    def test_falls_back_to_auto_detect_if_nothing_remembered(
        self, config, fake_blender
    ):
        launcher = BlenderLauncher(config)
        with patch(
            "framelabs.blender.launcher.auto_detect_executable",
            return_value=fake_blender,
        ):
            assert launcher.resolve_executable() == fake_blender

    def test_raises_when_nothing_found_anywhere(self, config):
        launcher = BlenderLauncher(config)
        with patch(
            "framelabs.blender.launcher.auto_detect_executable", return_value=None
        ):
            with pytest.raises(BlenderLaunchError):
                launcher.resolve_executable()


class TestRememberExecutable:
    def test_saves_to_config(self, config, fake_blender):
        launcher = BlenderLauncher(config)
        launcher.remember_executable(fake_blender)
        assert config.get("blender_executable_path") == str(fake_blender)

    def test_persists_across_config_reload(self, config, fake_blender, tmp_path):
        launcher = BlenderLauncher(config)
        launcher.remember_executable(fake_blender)

        reloaded = Config(config_path=tmp_path / "config.json")
        assert reloaded.get("blender_executable_path") == str(fake_blender)

    def test_raises_for_nonexistent_path(self, config, tmp_path):
        launcher = BlenderLauncher(config)
        with pytest.raises(BlenderLaunchError):
            launcher.remember_executable(tmp_path / "nope.exe")


class TestHasRunningInstance:
    def test_false_before_any_launch(self, config):
        launcher = BlenderLauncher(config)
        assert launcher.has_running_instance() is False

    def test_true_while_launched_process_alive(self, config, fake_blender):
        config.set("blender_executable_path", str(fake_blender))
        launcher = BlenderLauncher(config)
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        with patch("subprocess.Popen", return_value=fake_process):
            launcher.launch(fake_blender)
        assert launcher.has_running_instance() is True

    def test_false_once_launched_process_exits(self, config, fake_blender):
        config.set("blender_executable_path", str(fake_blender))
        launcher = BlenderLauncher(config)
        fake_process = MagicMock()
        fake_process.poll.return_value = 0
        with patch("subprocess.Popen", return_value=fake_process):
            launcher.launch(fake_blender)
        assert launcher.has_running_instance() is False


class TestLaunch:
    def test_calls_popen_with_python_flag(self, config, fake_blender, tmp_path):
        config.set("blender_executable_path", str(fake_blender))
        launcher = BlenderLauncher(config)
        script_path = tmp_path / "generate_scene.py"

        fake_process = MagicMock(pid=1234)
        fake_process.poll.return_value = None
        with patch("subprocess.Popen", return_value=fake_process) as mock_popen:
            launcher.launch(script_path)

        mock_popen.assert_called_once_with(
            [str(fake_blender), "--python", str(script_path)]
        )

    def test_raises_if_executable_cannot_be_resolved(self, config, tmp_path):
        launcher = BlenderLauncher(config)
        with patch(
            "framelabs.blender.launcher.auto_detect_executable", return_value=None
        ):
            with pytest.raises(BlenderLaunchError):
                launcher.launch(tmp_path / "generate_scene.py")

    def test_raises_if_popen_fails(self, config, fake_blender, tmp_path):
        config.set("blender_executable_path", str(fake_blender))
        launcher = BlenderLauncher(config)
        with patch("subprocess.Popen", side_effect=OSError("no exec permission")):
            with pytest.raises(BlenderLaunchError):
                launcher.launch(tmp_path / "generate_scene.py")

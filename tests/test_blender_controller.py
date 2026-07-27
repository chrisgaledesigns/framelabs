"""Tests for ui/blender_controller.py."""

from unittest.mock import MagicMock, patch

import pytest

from framelabs.blender.launcher import (
    BlenderExecutableNotFoundError,
    BlenderLaunchError,
)
from framelabs.core.config import Config
from framelabs.project.project import Frame, Project
from framelabs.ui.blender_controller import BlenderBridgeController


@pytest.fixture
def config(tmp_path):
    return Config(config_path=tmp_path / "config.json")


@pytest.fixture
def project(tmp_path):
    project_path = tmp_path / "TestProject"
    project_path.mkdir()
    (project_path / "images").mkdir()
    (project_path / "images" / "000001.png").write_bytes(b"fake png")
    return Project(
        version=1,
        name="Test Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[Frame(number=1, file="images/000001.png")],
        project_path=project_path,
    )


class TestBridgeRequestedHappyPath:
    def test_launches_and_emits_succeeded(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher, "launch", return_value=MagicMock()
        ) as mock_launch:
            with qtbot.waitSignal(controller.bridge_succeeded, timeout=1000) as blocker:
                controller.bridge_requested.emit(project)

        assert blocker.args[0].endswith("Test Project.blend")
        mock_launch.assert_called_once()
        # The script path passed to launch() should be the one actually
        # written to disk under cache/blender/.
        script_path = mock_launch.call_args[0][0]
        assert script_path.exists()
        assert script_path.name == "generate_scene.py"

    def test_writes_manifest_json_alongside_script(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(controller._launcher, "launch", return_value=MagicMock()):
            with qtbot.waitSignal(controller.bridge_succeeded, timeout=1000):
                controller.bridge_requested.emit(project)

        manifest_path = (
            project.project_path / "cache" / "blender" / "blender_manifest.json"
        )
        assert manifest_path.exists()


class TestBridgeRequestedFailurePaths:
    def test_no_frames_emits_bridge_failed(self, qtbot, config, tmp_path):
        empty_project = Project(
            version=1,
            name="Empty",
            fps=12,
            resolution=(1920, 1080),
            camera_model=None,
            camera_lens=None,
            frames=[],
            project_path=tmp_path,
        )
        controller = BlenderBridgeController(config)
        with qtbot.waitSignal(controller.bridge_failed, timeout=1000):
            controller.bridge_requested.emit(empty_project)

    def test_executable_not_found_emits_dedicated_signal_not_bridge_failed(
        self, qtbot, config, project
    ):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher,
            "launch",
            side_effect=BlenderExecutableNotFoundError("not found"),
        ):
            with qtbot.waitSignal(controller.executable_not_found, timeout=1000):
                controller.bridge_requested.emit(project)

    def test_other_launch_error_emits_bridge_failed(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher,
            "launch",
            side_effect=BlenderLaunchError("popen exploded"),
        ):
            with qtbot.waitSignal(controller.bridge_failed, timeout=1000) as blocker:
                controller.bridge_requested.emit(project)
        assert "popen exploded" in blocker.args[0]

    def test_unexpected_exception_still_emits_bridge_failed(
        self, qtbot, config, project
    ):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher, "launch", side_effect=RuntimeError("boom")
        ):
            with qtbot.waitSignal(controller.bridge_failed, timeout=1000) as blocker:
                controller.bridge_requested.emit(project)
        assert "boom" in blocker.args[0]


class TestLocateExecutableRequested:
    def test_remembers_valid_path(self, qtbot, config, tmp_path):
        fake_blender = tmp_path / "blender.exe"
        fake_blender.write_text("fake")
        controller = BlenderBridgeController(config)

        controller.locate_executable_requested.emit(str(fake_blender))
        qtbot.wait(50)

        assert config.get("blender_executable_path") == str(fake_blender)

    def test_invalid_path_emits_bridge_failed(self, qtbot, config, tmp_path):
        controller = BlenderBridgeController(config)
        with qtbot.waitSignal(controller.bridge_failed, timeout=1000):
            controller.locate_executable_requested.emit(str(tmp_path / "nope.exe"))

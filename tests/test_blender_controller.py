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


class TestAlreadyRunning:
    def test_running_instance_emits_already_running_not_bridge(
        self, qtbot, config, project
    ):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher, "has_running_instance", return_value=True
        ):
            with patch.object(controller._launcher, "launch") as mock_launch:
                with qtbot.waitSignal(controller.already_running, timeout=1000):
                    controller.bridge_requested.emit(project)
                mock_launch.assert_not_called()

    def test_no_running_instance_launches_normally(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher, "has_running_instance", return_value=False
        ):
            with patch.object(controller._launcher, "launch", return_value=MagicMock()):
                with qtbot.waitSignal(controller.bridge_succeeded, timeout=1000):
                    controller.bridge_requested.emit(project)

    def test_force_new_instance_bypasses_running_check(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher, "has_running_instance", return_value=True
        ):
            with patch.object(
                controller._launcher, "launch", return_value=MagicMock()
            ) as mock_launch:
                with qtbot.waitSignal(controller.bridge_succeeded, timeout=1000):
                    controller.force_new_instance_requested.emit(project)
                mock_launch.assert_called_once()


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


class TestExportBlendRequestedHappyPath:
    """ "Export .blend" -- the headless equivalent of "Open in Blender",
    driven by export_blend_requested rather than bridge_requested."""

    def test_runs_in_background_and_emits_succeeded(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(
            controller._launcher, "launch_background", return_value=fake_result
        ) as mock_launch_background:
            with qtbot.waitSignal(
                controller.blend_export_succeeded, timeout=1000
            ) as blocker:
                controller.export_blend_requested.emit(project)

        assert blocker.args[0].endswith("Test Project.blend")
        mock_launch_background.assert_called_once()
        script_path = mock_launch_background.call_args[0][0]
        assert script_path.exists()
        assert script_path.name == "generate_scene.py"

    def test_does_not_check_has_running_instance(self, qtbot, config, project):
        """Unlike bridge_requested, a background export should never be
        blocked by an interactive Blender window still being open --
        it's an independent, short-lived process."""
        controller = BlenderBridgeController(config)
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(
            controller._launcher, "has_running_instance", return_value=True
        ):
            with patch.object(
                controller._launcher, "launch_background", return_value=fake_result
            ) as mock_launch_background:
                with qtbot.waitSignal(controller.blend_export_succeeded, timeout=1000):
                    controller.export_blend_requested.emit(project)
                mock_launch_background.assert_called_once()


class TestExportBlendRequestedFailurePaths:
    def test_no_frames_emits_blend_export_failed(self, qtbot, config, tmp_path):
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
        with qtbot.waitSignal(controller.blend_export_failed, timeout=1000):
            controller.export_blend_requested.emit(empty_project)

    def test_executable_not_found_emits_dedicated_signal(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher,
            "launch_background",
            side_effect=BlenderExecutableNotFoundError("not found"),
        ):
            with qtbot.waitSignal(
                controller.blend_export_executable_not_found, timeout=1000
            ):
                controller.export_blend_requested.emit(project)

    def test_nonzero_exit_code_emits_blend_export_failed(self, qtbot, config, project):
        """A script that raised inside Blender (non-zero exit, no
        exception raised from launch_background itself) should still be
        reported as a failure, not silently treated as success."""
        controller = BlenderBridgeController(config)
        fake_result = MagicMock(
            returncode=1, stdout="", stderr="AttributeError: 'SequenceEditor'..."
        )
        with patch.object(
            controller._launcher, "launch_background", return_value=fake_result
        ):
            with qtbot.waitSignal(
                controller.blend_export_failed, timeout=1000
            ) as blocker:
                controller.export_blend_requested.emit(project)
        assert "code 1" in blocker.args[0]

    def test_launch_error_emits_blend_export_failed(self, qtbot, config, project):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher,
            "launch_background",
            side_effect=BlenderLaunchError("popen exploded"),
        ):
            with qtbot.waitSignal(
                controller.blend_export_failed, timeout=1000
            ) as blocker:
                controller.export_blend_requested.emit(project)
        assert "popen exploded" in blocker.args[0]

    def test_unexpected_exception_still_emits_blend_export_failed(
        self, qtbot, config, project
    ):
        controller = BlenderBridgeController(config)
        with patch.object(
            controller._launcher, "launch_background", side_effect=RuntimeError("boom")
        ):
            with qtbot.waitSignal(
                controller.blend_export_failed, timeout=1000
            ) as blocker:
                controller.export_blend_requested.emit(project)
        assert "boom" in blocker.args[0]

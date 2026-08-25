"""Tests for ui/blender_sync_controller.py.

No real Blender listener anywhere -- discover_port() and
BlenderSyncClient.connect()/send() are patched at the module boundary,
same "no real hardware/process" testing philosophy as
test_blender_controller.py uses for BlenderLauncher.
"""

from unittest.mock import MagicMock, patch

import pytest

from framelabs.blender.sync_client import BlenderSyncError
from framelabs.blender.sync_protocol import SyncMessage
from framelabs.project.project import Frame, Project
from framelabs.ui.blender_sync_controller import BlenderSyncController


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
        camera_model=None,
        camera_lens=None,
        frames=[Frame(number=1, file="images/000001.png")],
        project_path=project_path,
    )


class TestConnectRequested:
    def test_happy_path_emits_sync_connected(self, qtbot, project):
        controller = BlenderSyncController()
        with patch(
            "framelabs.ui.blender_sync_controller.discover_port", return_value=6000
        ):
            with patch(
                "framelabs.ui.blender_sync_controller.BlenderSyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.connect.return_value = None
                with qtbot.waitSignal(controller.sync_connected, timeout=1000):
                    controller.connect_requested.emit(project)

        assert controller._client is mock_client_cls.return_value

    def test_no_project_path_emits_connect_failed(self, qtbot, tmp_path):
        controller = BlenderSyncController()
        empty = Project(
            version=1,
            name="Empty",
            fps=12,
            resolution=(1920, 1080),
            camera_model=None,
            camera_lens=None,
            frames=[],
            project_path=None,
        )
        with qtbot.waitSignal(controller.sync_connect_failed, timeout=1000):
            controller.connect_requested.emit(empty)

    def test_discover_port_failure_emits_connect_failed(self, qtbot, project):
        controller = BlenderSyncController()
        with patch(
            "framelabs.ui.blender_sync_controller.discover_port",
            side_effect=BlenderSyncError("timed out"),
        ):
            with qtbot.waitSignal(controller.sync_connect_failed, timeout=1000):
                controller.connect_requested.emit(project)
        assert controller._client is None

    def test_connect_failure_emits_connect_failed(self, qtbot, project):
        controller = BlenderSyncController()
        with patch(
            "framelabs.ui.blender_sync_controller.discover_port", return_value=6000
        ):
            with patch(
                "framelabs.ui.blender_sync_controller.BlenderSyncClient"
            ) as mock_client_cls:
                mock_client_cls.return_value.connect.side_effect = BlenderSyncError(
                    "refused"
                )
                with qtbot.waitSignal(controller.sync_connect_failed, timeout=1000):
                    controller.connect_requested.emit(project)
        assert controller._client is None

    def test_reconnecting_closes_the_previous_client(self, qtbot, project):
        controller = BlenderSyncController()
        old_client = MagicMock()
        controller._client = old_client

        with patch(
            "framelabs.ui.blender_sync_controller.discover_port", return_value=6000
        ):
            with patch("framelabs.ui.blender_sync_controller.BlenderSyncClient"):
                with qtbot.waitSignal(controller.sync_connected, timeout=1000):
                    controller.connect_requested.emit(project)

        old_client.close.assert_called_once()


class TestFrameSyncRequested:
    def test_noop_when_not_connected(self, qtbot, project):
        controller = BlenderSyncController()
        controller.frame_sync_requested.emit(project, 1)
        # No client, nothing to assert on a mock -- this test's job is
        # simply confirming no exception and no signal fires.
        with qtbot.assertNotEmitted(controller.sync_disconnected, wait=200):
            pass

    def test_sends_expected_message_when_connected(self, qtbot, project):
        controller = BlenderSyncController()
        mock_client = MagicMock()
        controller._client = mock_client

        controller.frame_sync_requested.emit(project, 1)

        mock_client.send.assert_called_once()
        sent_message = mock_client.send.call_args[0][0]
        assert sent_message == SyncMessage(
            frame_number=1,
            frame_path=str(project.project_path / "images/000001.png"),
            fps=12,
            frame_count=1,
        )

    def test_unknown_frame_number_does_not_disconnect(self, qtbot, project):
        controller = BlenderSyncController()
        mock_client = MagicMock()
        controller._client = mock_client

        controller.frame_sync_requested.emit(project, 99)

        mock_client.send.assert_not_called()
        assert controller._client is mock_client

    def test_send_failure_emits_disconnected_and_drops_client(self, qtbot, project):
        controller = BlenderSyncController()
        mock_client = MagicMock()
        mock_client.send.side_effect = BlenderSyncError("broken pipe")
        controller._client = mock_client

        with qtbot.waitSignal(controller.sync_disconnected, timeout=1000):
            controller.frame_sync_requested.emit(project, 1)

        assert controller._client is None


class TestDisconnectRequested:
    def test_closes_client_and_emits_disconnected(self, qtbot):
        controller = BlenderSyncController()
        mock_client = MagicMock()
        controller._client = mock_client

        with qtbot.waitSignal(controller.sync_disconnected, timeout=1000):
            controller.disconnect_requested.emit()

        mock_client.close.assert_called_once()
        assert controller._client is None

    def test_noop_when_not_connected(self, qtbot):
        controller = BlenderSyncController()
        with qtbot.assertNotEmitted(controller.sync_disconnected, wait=200):
            controller.disconnect_requested.emit()

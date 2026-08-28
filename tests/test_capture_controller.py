"""Tests for CaptureController in ui/capture_controller.py.

Like test_camera_controller.py, capture_frame() and ReplaceFrameCommand
are entirely mocked here -- their own behavior is covered elsewhere (see
test_capture_service.py and test_asset_commands.py-style command tests).
These tests are purely about the decisions CaptureController makes given
those mocked results: which signal it emits, and with what payload.

No real QThread is spun up. The controller's *_requested signals really
are connected in __init__ (that's the point -- they're what
moveToThread() cross-thread delivery relies on), so a couple of tests
verify that wiring directly; every other test calls the private
_handle_* methods synchronously, which is exactly what Qt would do on
the worker thread once these signals fire for real.
"""

from unittest.mock import MagicMock, patch

from framelabs.capture.capture_service import (
    CameraLostServiceError,
    CaptureServiceError,
    DiskFullServiceError,
)
from framelabs.ui.capture_controller import CaptureController


def _make_controller():
    """Build a CaptureController with a mocked EventBus and CameraManager.

    Not a test itself -- shared setup. Returns
    (controller, mock_camera_manager, mock_event_bus).
    """
    mock_event_bus = MagicMock()
    mock_camera_manager = MagicMock()
    controller = CaptureController(mock_event_bus, mock_camera_manager)
    return controller, mock_camera_manager, mock_event_bus


def test_init_connects_capture_and_replace_requested_signals():
    """On construction, both *_requested signals should be wired to their
    handlers -- this is the queued-connection plumbing moveToThread()
    relies on for real cross-thread delivery."""
    controller, _, _ = _make_controller()

    # Signal.connect() doesn't expose an inspectable list of receivers
    # via a public API, so verify the wiring behaviorally: emitting each
    # signal should reach its handler.
    with patch.object(controller, "_handle_capture_requested") as mock_handle:
        controller.capture_requested.emit(MagicMock())
        mock_handle.assert_called_once()

    with patch.object(controller, "_handle_replace_requested") as mock_handle:
        controller.replace_requested.emit(MagicMock())
        mock_handle.assert_called_once()


@patch("framelabs.ui.capture_controller.capture_frame")
def test_handle_capture_requested_success_emits_capture_succeeded(mock_capture_frame):
    """A successful capture should emit capture_succeeded with the new
    frame's number."""
    controller, mock_manager, mock_event_bus = _make_controller()
    mock_frame = MagicMock()
    mock_frame.number = 7
    mock_capture_frame.return_value = mock_frame

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    disk_full_slot = MagicMock()
    controller.capture_succeeded.connect(succeeded_slot)
    controller.capture_failed.connect(failed_slot)
    controller.disk_full.connect(disk_full_slot)

    mock_project = MagicMock()
    controller._handle_capture_requested(mock_project)

    mock_capture_frame.assert_called_once_with(
        mock_project, mock_manager, mock_event_bus
    )
    succeeded_slot.assert_called_once_with(7)
    failed_slot.assert_not_called()
    disk_full_slot.assert_not_called()


@patch("framelabs.ui.capture_controller.capture_frame")
def test_handle_capture_requested_disk_full_emits_disk_full_not_capture_failed(
    mock_capture_frame,
):
    """DiskFullServiceError is a CaptureServiceError subclass -- it must
    be caught first, so disk-full errors surface via disk_full, never the
    generic capture_failed."""
    controller, _, _ = _make_controller()
    mock_capture_frame.side_effect = DiskFullServiceError("Disk full")

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    disk_full_slot = MagicMock()
    controller.capture_succeeded.connect(succeeded_slot)
    controller.capture_failed.connect(failed_slot)
    controller.disk_full.connect(disk_full_slot)

    controller._handle_capture_requested(MagicMock())  # should not raise

    disk_full_slot.assert_called_once_with("Disk full")
    failed_slot.assert_not_called()
    succeeded_slot.assert_not_called()


@patch("framelabs.ui.capture_controller.capture_frame")
def test_handle_capture_requested_camera_lost_emits_camera_lost_not_capture_failed(
    mock_capture_frame,
):
    """CameraLostServiceError is a CaptureServiceError subclass -- it
    must be caught first, so Feature 2's "Camera Lost" case surfaces via
    camera_lost, never the generic capture_failed."""
    controller, _, _ = _make_controller()
    mock_capture_frame.side_effect = CameraLostServiceError("Camera disconnected")

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    camera_lost_slot = MagicMock()
    controller.capture_succeeded.connect(succeeded_slot)
    controller.capture_failed.connect(failed_slot)
    controller.camera_lost.connect(camera_lost_slot)

    controller._handle_capture_requested(MagicMock())  # should not raise

    camera_lost_slot.assert_called_once_with("Camera disconnected")
    failed_slot.assert_not_called()
    succeeded_slot.assert_not_called()


@patch("framelabs.ui.capture_controller.capture_frame")
def test_handle_capture_requested_generic_service_error_emits_capture_failed(
    mock_capture_frame,
):
    """Any other CaptureServiceError should emit capture_failed with the
    error message."""
    controller, _, _ = _make_controller()
    mock_capture_frame.side_effect = CaptureServiceError("Camera trigger failed")

    failed_slot = MagicMock()
    controller.capture_failed.connect(failed_slot)

    controller._handle_capture_requested(MagicMock())  # should not raise

    failed_slot.assert_called_once_with("Camera trigger failed")


@patch("framelabs.ui.capture_controller.capture_frame")
def test_handle_capture_requested_value_error_emits_capture_failed(mock_capture_frame):
    """A ValueError (e.g. project.project_path is None) should also be
    treated as a capture failure rather than crashing the worker thread."""
    controller, _, _ = _make_controller()
    mock_capture_frame.side_effect = ValueError("project_path is None")

    failed_slot = MagicMock()
    controller.capture_failed.connect(failed_slot)

    controller._handle_capture_requested(MagicMock())  # should not raise

    failed_slot.assert_called_once_with("project_path is None")


def test_handle_replace_requested_success_emits_replace_succeeded_with_command():
    """A successful replace should call do() on the command and emit it
    back unchanged, so MainWindow can record it via
    execute_already_done() without re-running do()."""
    controller, _, _ = _make_controller()
    mock_command = MagicMock()
    mock_command.description = "Replace frame 3"

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.replace_succeeded.connect(succeeded_slot)
    controller.replace_failed.connect(failed_slot)

    controller._handle_replace_requested(mock_command)

    mock_command.do.assert_called_once()
    succeeded_slot.assert_called_once_with(mock_command)
    failed_slot.assert_not_called()


def test_handle_replace_requested_disk_full_emits_disk_full():
    """Same disk-full precedence as capture: a DiskFullServiceError from
    command.do() must surface via disk_full, not replace_failed."""
    controller, _, _ = _make_controller()
    mock_command = MagicMock()
    mock_command.do.side_effect = DiskFullServiceError("Disk full")

    disk_full_slot = MagicMock()
    replace_failed_slot = MagicMock()
    controller.disk_full.connect(disk_full_slot)
    controller.replace_failed.connect(replace_failed_slot)

    controller._handle_replace_requested(mock_command)  # should not raise

    disk_full_slot.assert_called_once_with("Disk full")
    replace_failed_slot.assert_not_called()


def test_handle_replace_requested_camera_lost_emits_replace_camera_lost():
    """Same camera-lost precedence as capture: a CameraLostServiceError
    from command.do() must surface via replace_camera_lost (with the
    command's frame_number), not replace_failed."""
    controller, _, _ = _make_controller()
    mock_command = MagicMock()
    mock_command.do.side_effect = CameraLostServiceError("Camera disconnected")
    mock_command.frame_number = 12

    replace_failed_slot = MagicMock()
    replace_camera_lost_slot = MagicMock()
    controller.replace_failed.connect(replace_failed_slot)
    controller.replace_camera_lost.connect(replace_camera_lost_slot)

    controller._handle_replace_requested(mock_command)  # should not raise

    replace_camera_lost_slot.assert_called_once_with("Camera disconnected", 12)
    replace_failed_slot.assert_not_called()


def test_handle_replace_requested_generic_service_error_emits_replace_failed():
    """Any other CaptureServiceError from do() should emit replace_failed
    with the error message."""
    controller, _, _ = _make_controller()
    mock_command = MagicMock()
    mock_command.do.side_effect = CaptureServiceError("Camera trigger failed")

    replace_failed_slot = MagicMock()
    controller.replace_failed.connect(replace_failed_slot)

    controller._handle_replace_requested(mock_command)  # should not raise

    replace_failed_slot.assert_called_once_with("Camera trigger failed")


def test_handle_replace_requested_value_error_emits_replace_failed():
    """A ValueError from do() (no active project) should also emit
    replace_failed rather than crash the worker thread."""
    controller, _, _ = _make_controller()
    mock_command = MagicMock()
    mock_command.do.side_effect = ValueError("project_path is None")

    replace_failed_slot = MagicMock()
    controller.replace_failed.connect(replace_failed_slot)

    controller._handle_replace_requested(mock_command)  # should not raise

    replace_failed_slot.assert_called_once_with("project_path is None")

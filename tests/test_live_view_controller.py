"""Tests for LiveViewController in ui/live_view_controller.py.

CameraManager is entirely mocked here, same approach as
test_camera_controller.py -- these tests are about the decisions
LiveViewController makes, not about CameraManager itself. No real QThread
or QTimer event loop is spun up; the timer class is mocked and signal
emissions are verified via a MagicMock slot.

Note: _on_camera_connected_event/_on_camera_disconnected_event only emit
internal _start_timer_requested/_stop_timer_requested signals (see the
module's threading docstring) -- they call the actual _start_timer/
_stop_timer slots directly here (bypassing the signal/queued-connection
machinery), since a plain unit test has no real cross-thread delivery to
exercise; that part is verified manually, per the established pattern for
this codebase's threading code.
"""

from unittest.mock import MagicMock, patch

from framelabs.camera.camera_interface import CameraError
from framelabs.ui.live_view_controller import PREVIEW_INTERVAL_MS, LiveViewController


def _make_controller(mock_manager=None):
    """Build a LiveViewController with a mocked CameraManager and EventBus."""
    mock_manager = mock_manager or MagicMock()
    mock_event_bus = MagicMock()
    controller = LiveViewController(mock_event_bus, mock_manager)
    return controller, mock_manager, mock_event_bus


def test_init_subscribes_to_camera_connected_and_disconnected_events():
    """On construction, LiveViewController should subscribe to both camera
    lifecycle events, so preview polling starts/stops automatically."""
    controller, _, mock_event_bus = _make_controller()

    mock_event_bus.subscribe.assert_any_call(
        "CAMERA_CONNECTED", controller._on_camera_connected_event
    )
    mock_event_bus.subscribe.assert_any_call(
        "CAMERA_DISCONNECTED", controller._on_camera_disconnected_event
    )


@patch("framelabs.ui.live_view_controller.QTimer")
def test_start_configures_timer_but_does_not_start_it(mock_timer_class):
    """start() should build the QTimer at the target preview interval and
    wire it to _read_frame, but must NOT start it yet -- polling should
    only begin once a camera is actually connected."""
    mock_timer = MagicMock()
    mock_timer_class.return_value = mock_timer
    controller, _, _ = _make_controller()

    controller.start()

    mock_timer_class.assert_called_once_with(controller)
    mock_timer.setInterval.assert_called_once_with(PREVIEW_INTERVAL_MS)
    mock_timer.timeout.connect.assert_called_once_with(controller._read_frame)
    mock_timer.start.assert_not_called()


def test_on_camera_connected_starts_live_view_and_requests_timer_start():
    """CAMERA_CONNECTED should start live view on the backend (via
    CameraManager) and emit _start_timer_requested -- not call the timer
    directly, since this handler may run on a different thread than the
    one that owns the timer (see module docstring)."""
    controller, mock_manager, _ = _make_controller()

    start_requested_slot = MagicMock()
    controller._start_timer_requested.connect(start_requested_slot)

    controller._on_camera_connected_event({"camera_id": 0})

    mock_manager.start_live_view.assert_called_once()
    start_requested_slot.assert_called_once()


def test_on_camera_connected_start_live_view_failure_does_not_request_timer():
    """If start_live_view() fails, _start_timer_requested should not be
    emitted -- there's nothing to poll yet."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.start_live_view.side_effect = CameraError("No active camera.")

    start_requested_slot = MagicMock()
    controller._start_timer_requested.connect(start_requested_slot)

    controller._on_camera_connected_event({"camera_id": 0})  # should not raise

    start_requested_slot.assert_not_called()


def test_on_camera_disconnected_requests_timer_stop():
    """CAMERA_DISCONNECTED should emit _stop_timer_requested."""
    controller, _, _ = _make_controller()

    stop_requested_slot = MagicMock()
    controller._stop_timer_requested.connect(stop_requested_slot)

    controller._on_camera_disconnected_event({"camera_id": 0})

    stop_requested_slot.assert_called_once()


def test_start_timer_starts_the_real_timer():
    """_start_timer() (the actual slot, run on this controller's own
    thread via the queued connection) should start the timer."""
    controller, _, _ = _make_controller()
    controller._timer = MagicMock()

    controller._start_timer()

    controller._timer.start.assert_called_once()


def test_stop_timer_stops_the_real_timer():
    """_stop_timer() (the actual slot) should stop the timer."""
    controller, _, _ = _make_controller()
    controller._timer = MagicMock()

    controller._stop_timer()

    controller._timer.stop.assert_called_once()


def test_read_frame_emits_bytes_on_success():
    """A successful grab should emit frame_ready with the backend's bytes."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.capture_in_progress = False
    mock_manager.read_preview_frame.return_value = b"fake-jpeg-bytes"

    frame_slot = MagicMock()
    controller.frame_ready.connect(frame_slot)

    controller._read_frame()

    frame_slot.assert_called_once_with(b"fake-jpeg-bytes")


def test_read_frame_skips_when_capture_in_progress():
    """While a still capture is in flight, _read_frame() should not touch
    the camera at all, and should not emit."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.capture_in_progress = True

    frame_slot = MagicMock()
    controller.frame_ready.connect(frame_slot)

    controller._read_frame()

    mock_manager.read_preview_frame.assert_not_called()
    frame_slot.assert_not_called()


def test_read_frame_swallows_camera_error_and_does_not_emit():
    """A failed grab should be logged and skipped, not raised or emitted."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.capture_in_progress = False
    mock_manager.read_preview_frame.side_effect = CameraError("Failed to read frame")

    frame_slot = MagicMock()
    controller.frame_ready.connect(frame_slot)

    controller._read_frame()  # should not raise

    frame_slot.assert_not_called()

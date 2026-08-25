"""Tests for CameraController in ui/camera_controller.py.

CameraManager is entirely mocked here -- its own behavior is already
covered by test_camera_manager.py. These tests are purely about the
decisions CameraController makes given a CameraManager's responses (mock
signal emissions, connect/rescan calls), not about CameraManager itself.

These tests never spin up a real QThread or QTimer event loop -- methods
are called directly, and Qt signal emissions are verified by connecting a
MagicMock to each signal before triggering behavior, then asserting on
that mock. This keeps the suite fast and deterministic; the actual
threading behavior (moveToThread, cross-thread signal delivery, clean
shutdown) is verified manually by running the real app, per the hand-off.
"""

from unittest.mock import MagicMock, patch

from framelabs.camera.camera_interface import CameraError, CameraMetadata
from framelabs.ui.camera_controller import SCAN_INTERVAL_MS, CameraController


@patch("framelabs.ui.camera_controller.CameraManager")
def _make_controller(mock_camera_manager_class, mock_manager=None):
    """Build a CameraController with CameraManager fully mocked out.

    Not a test itself -- a shared helper, since every test below needs
    the same setup. Returns (controller, mock_manager, mock_event_bus).
    """
    mock_manager = mock_manager or MagicMock()
    mock_camera_manager_class.return_value = mock_manager
    mock_event_bus = MagicMock()
    controller = CameraController(mock_event_bus)
    return controller, mock_manager, mock_event_bus


def test_init_subscribes_to_camera_connected_and_disconnected_events():
    """On construction, CameraController should subscribe to both camera
    lifecycle events on the shared EventBus, so it stays in sync even if
    some other module triggers the connect/disconnect."""
    controller, _, mock_event_bus = _make_controller()

    mock_event_bus.subscribe.assert_any_call(
        "CAMERA_CONNECTED", controller._on_camera_connected_event
    )
    mock_event_bus.subscribe.assert_any_call(
        "CAMERA_DISCONNECTED", controller._on_camera_disconnected_event
    )


@patch("framelabs.ui.camera_controller.QTimer")
def test_start_scanning_configures_and_starts_timer(mock_timer_class):
    """start_scanning() should build a QTimer at the configured interval,
    wire it to _scan, start it, and also run one scan immediately rather
    than waiting for the first timeout."""
    mock_timer = MagicMock()
    mock_timer_class.return_value = mock_timer
    controller, mock_manager, _ = _make_controller()
    mock_manager.rescan_once.return_value = []

    controller.start_scanning()

    mock_timer_class.assert_called_once_with(controller)
    mock_timer.setInterval.assert_called_once_with(SCAN_INTERVAL_MS)
    mock_timer.timeout.connect.assert_called_once_with(controller._scan)
    mock_timer.start.assert_called_once()
    mock_manager.rescan_once.assert_called_once()  # the immediate scan


def test_scan_with_nothing_connected_and_none_available_emits_no_camera_found():
    """If rescan_once() finds no cameras, _scan() should emit
    camera_connecting first (so the UI can show "Scanning..."), then
    no_camera_found -- and should never attempt to connect()."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.rescan_once.return_value = []

    connecting_slot = MagicMock()
    no_camera_slot = MagicMock()
    controller.camera_connecting.connect(connecting_slot)
    controller.no_camera_found.connect(no_camera_slot)

    controller._scan()

    connecting_slot.assert_called_once()
    no_camera_slot.assert_called_once()
    mock_manager.connect.assert_not_called()


def test_scan_with_nothing_connected_and_camera_available_connects_to_first():
    """If rescan_once() finds available cameras, _scan() should connect to
    the first one in the list."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.rescan_once.return_value = [0, 1]

    controller._scan()

    mock_manager.connect.assert_called_once_with(0)


def test_scan_connect_failure_emits_no_camera_found():
    """If CameraManager.connect() raises CameraError (e.g. the device
    vanished between discovery and connect), _scan() should treat this the
    same as finding nothing -- emit no_camera_found rather than crashing
    or leaving the UI stuck on 'Scanning...'."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.rescan_once.return_value = [0]
    mock_manager.connect.side_effect = CameraError("Could not open webcam at index 0")

    no_camera_slot = MagicMock()
    controller.no_camera_found.connect(no_camera_slot)

    controller._scan()  # should not raise

    no_camera_slot.assert_called_once()


def test_scan_while_already_connected_only_polls_quietly():
    """Once a camera is connected, _scan() should still call rescan_once()
    (to detect other cameras hot-plugging), but must not touch the UI --
    no camera_connecting, no further connect() calls."""
    controller, mock_manager, _ = _make_controller()
    controller._connected_camera_id = 0

    connecting_slot = MagicMock()
    controller.camera_connecting.connect(connecting_slot)

    controller._scan()

    mock_manager.rescan_once.assert_called_once()
    mock_manager.connect.assert_not_called()
    connecting_slot.assert_not_called()


@patch.object(CameraController, "_scan")
def test_handle_rescan_requested_calls_scan(mock_scan):
    """A manual rescan request should trigger exactly one scan pass."""
    controller, _, _ = _make_controller()

    controller._handle_rescan_requested()

    mock_scan.assert_called_once()


def test_on_camera_connected_event_emits_camera_connected_with_display_name():
    """When CAMERA_CONNECTED fires, the controller should store the
    camera_id, look up real metadata, and emit camera_connected with the
    backend's actual display_name -- not a hardcoded or guessed string."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.get_active_camera_metadata.return_value = CameraMetadata(
        camera_id="webcam-0", display_name="Webcam (device 0)", backend_type="webcam"
    )

    connected_slot = MagicMock()
    controller.camera_connected.connect(connected_slot)

    controller._on_camera_connected_event({"camera_id": 0})

    assert controller._connected_camera_id == 0
    connected_slot.assert_called_once_with("Webcam (device 0)")


def test_on_camera_connected_event_metadata_failure_does_not_emit():
    """If metadata can't be read right after connecting (edge case: camera
    dropped instantly), the controller should not emit camera_connected
    with bad or missing data -- better to stay silent than show something
    false in the UI."""
    controller, mock_manager, _ = _make_controller()
    mock_manager.get_active_camera_metadata.side_effect = CameraError(
        "No active camera. Call connect() first."
    )

    connected_slot = MagicMock()
    controller.camera_connected.connect(connected_slot)

    controller._on_camera_connected_event({"camera_id": 0})  # should not raise

    connected_slot.assert_not_called()


def test_on_camera_disconnected_event_clears_state_and_emits():
    """When CAMERA_DISCONNECTED fires, the controller should clear its
    tracked camera_id (so the next _scan() knows to look for a new camera
    again) and emit camera_disconnected for the UI."""
    controller, _, _ = _make_controller()
    controller._connected_camera_id = 0

    disconnected_slot = MagicMock()
    controller.camera_disconnected.connect(disconnected_slot)

    controller._on_camera_disconnected_event({"camera_id": 0})

    assert controller._connected_camera_id is None
    disconnected_slot.assert_called_once()

"""Tests for camera discovery in camera_manager.py.

Uses mocks for cv2.VideoCapture so these tests never depend on real
hardware being connected, per the Developer Handbook's testing rule.
"""

from unittest.mock import MagicMock, patch

from framelabs.camera.camera_interface import CameraDisconnectedError, CameraError
from framelabs.camera.camera_manager import CameraManager, discover_webcams


@patch("framelabs.camera.camera_manager.cv2.VideoCapture")
def test_discover_webcams_finds_open_indices(mock_video_capture):
    """Only indices where isOpened() is True should be returned."""

    def fake_capture(index):
        cap = MagicMock()
        # Pretend only index 0 has a real camera.
        cap.isOpened.return_value = index == 0
        return cap

    mock_video_capture.side_effect = fake_capture

    result = discover_webcams()

    assert result == [0]


@patch("framelabs.camera.camera_manager.cv2.VideoCapture")
def test_discover_webcams_returns_empty_when_none_found(mock_video_capture):
    """No open indices means no cameras -- should return an empty list."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    mock_video_capture.return_value = mock_cap

    result = discover_webcams()

    assert result == []


@patch("framelabs.camera.camera_manager.cv2.VideoCapture")
def test_discover_webcams_releases_every_capture(mock_video_capture):
    """Every VideoCapture object opened during probing must be released,
    whether or not it turned out to be a real camera."""
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_video_capture.return_value = mock_cap

    discover_webcams()

    assert mock_cap.release.call_count == 5  # MAX_WEBCAM_INDEX


@patch("framelabs.camera.camera_manager.WebcamBackend")
def test_connect_success(mock_webcam_backend_class):
    """A successful connect() should store the backend and camera_id."""
    mock_backend = MagicMock()
    mock_webcam_backend_class.return_value = mock_backend

    manager = CameraManager()
    manager.connect(0)

    mock_webcam_backend_class.assert_called_once_with(0)
    mock_backend.connect.assert_called_once()
    assert manager._active_backend is mock_backend
    assert manager._active_camera_id == 0


@patch("framelabs.camera.camera_manager.WebcamBackend")
def test_connect_failure_logs_and_reraises(mock_webcam_backend_class):
    """If the backend fails to connect, CameraManager should re-raise
    CameraError and leave its state unchanged."""
    mock_backend = MagicMock()
    mock_backend.connect.side_effect = CameraError("Could not open webcam at index 0")
    mock_webcam_backend_class.return_value = mock_backend

    manager = CameraManager()

    try:
        manager.connect(0)
        assert False, "Expected CameraError to be raised"
    except CameraError:
        pass

    assert manager._active_backend is None
    assert manager._active_camera_id is None


@patch("framelabs.camera.camera_manager.WebcamBackend")
def test_disconnect_after_connect(mock_webcam_backend_class):
    """disconnect() should call the backend's disconnect() and clear state."""
    mock_backend = MagicMock()
    mock_webcam_backend_class.return_value = mock_backend

    manager = CameraManager()
    manager.connect(0)
    manager.disconnect()

    mock_backend.disconnect.assert_called_once()
    assert manager._active_backend is None
    assert manager._active_camera_id is None


def test_disconnect_when_not_connected_is_noop():
    """disconnect() with nothing connected should not raise, and state
    should remain None."""
    manager = CameraManager()

    manager.disconnect()  # should not raise

    assert manager._active_backend is None
    assert manager._active_camera_id is None


@patch("framelabs.camera.camera_manager.WebcamBackend")
def test_capture_success(mock_webcam_backend_class):
    """A successful capture() should return the backend's bytes unchanged."""
    mock_backend = MagicMock()
    mock_backend.capture.return_value = b"fake-png-bytes"
    mock_webcam_backend_class.return_value = mock_backend

    manager = CameraManager()
    manager.connect(0)
    result = manager.capture()

    assert result == b"fake-png-bytes"
    mock_backend.capture.assert_called_once()


def test_capture_with_no_active_camera_raises_camera_error():
    """capture() with nothing connected should raise CameraError, not
    CameraDisconnectedError -- there's no camera to have disconnected."""
    manager = CameraManager()

    try:
        manager.capture()
        assert False, "Expected CameraError to be raised"
    except CameraDisconnectedError:
        assert False, "Should not raise CameraDisconnectedError with no active camera"
    except CameraError:
        pass


@patch("framelabs.camera.camera_manager.WebcamBackend")
def test_capture_transient_failure_reraises_camera_error(mock_webcam_backend_class):
    """If capture() fails but is_connected() still reports True, this is a
    transient failure -- the original CameraError should be re-raised, and
    the camera should remain the active camera (not cleared)."""
    mock_backend = MagicMock()
    mock_backend.capture.side_effect = CameraError(
        "Failed to capture frame from webcam"
    )
    mock_backend.is_connected.return_value = True
    mock_webcam_backend_class.return_value = mock_backend

    manager = CameraManager()
    manager.connect(0)

    try:
        manager.capture()
        assert False, "Expected CameraError to be raised"
    except CameraDisconnectedError:
        assert False, "Should not raise CameraDisconnectedError for a transient failure"
    except CameraError:
        pass

    assert manager._active_backend is mock_backend
    assert manager._active_camera_id == 0


@patch("framelabs.camera.camera_manager.WebcamBackend")
def test_capture_real_disconnect_raises_and_publishes_event(mock_webcam_backend_class):
    """If capture() fails and is_connected() reports False, CameraManager
    should raise CameraDisconnectedError, clear its active camera state,
    and publish CAMERA_DISCONNECTED on the event bus."""
    mock_backend = MagicMock()
    mock_backend.capture.side_effect = CameraError(
        "Failed to capture frame from webcam"
    )
    mock_backend.is_connected.return_value = False
    mock_webcam_backend_class.return_value = mock_backend

    mock_event_bus = MagicMock()

    manager = CameraManager(event_bus=mock_event_bus)
    manager.connect(0)

    try:
        manager.capture()
        assert False, "Expected CameraDisconnectedError to be raised"
    except CameraDisconnectedError:
        pass

    assert manager._active_backend is None
    assert manager._active_camera_id is None
    mock_event_bus.publish.assert_called_once_with(
        "CAMERA_DISCONNECTED", {"camera_id": 0}
    )

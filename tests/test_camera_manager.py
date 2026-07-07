"""Tests for camera discovery in camera_manager.py.

Uses mocks for cv2.VideoCapture so these tests never depend on real
hardware being connected, per the Developer Handbook's testing rule.
"""

from unittest.mock import MagicMock, patch

from framelabs.camera.camera_interface import CameraError
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

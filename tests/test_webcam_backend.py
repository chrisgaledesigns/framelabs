"""Tests for WebcamBackend. Uses mocks -- never touches real hardware."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from framelabs.camera.camera_interface import CameraError
from framelabs.camera.webcam_backend import WebcamBackend


def _fake_frame():
    """A tiny fake image, standing in for a real camera frame."""
    return np.zeros((2, 2, 3), dtype=np.uint8)


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_connect_success(mock_video_capture):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend(device_index=0)
    cam.connect()

    mock_video_capture.assert_called_once_with(0)


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_connect_failure_raises_camera_error(mock_video_capture):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = False
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend(device_index=0)

    with pytest.raises(CameraError):
        cam.connect()


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_capture_without_connect_raises_camera_error(mock_video_capture):
    cam = WebcamBackend()

    with pytest.raises(CameraError):
        cam.capture()


@patch("framelabs.camera.webcam_backend.cv2.imencode")
@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_capture_success_returns_bytes(mock_video_capture, mock_imencode):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, _fake_frame())
    mock_video_capture.return_value = mock_capture

    mock_imencode.return_value = (True, np.array([1, 2, 3], dtype=np.uint8))

    cam = WebcamBackend()
    cam.connect()
    result = cam.capture()

    assert isinstance(result, bytes)
    assert result == bytes([1, 2, 3])


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_capture_read_failure_raises_camera_error(mock_video_capture):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (False, None)
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend()
    cam.connect()

    with pytest.raises(CameraError):
        cam.capture()


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_disconnect_releases_capture(mock_video_capture):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend()
    cam.connect()
    cam.disconnect()

    mock_capture.release.assert_called_once()


def test_set_iso_shutter_aperture_do_not_raise():
    cam = WebcamBackend()
    cam.set_iso(100)
    cam.set_shutter("1/60")
    cam.set_aperture("f/2.8")


def test_get_metadata_returns_expected_values():
    cam = WebcamBackend(device_index=2)
    metadata = cam.get_metadata()

    assert metadata.camera_id == "webcam-2"
    assert metadata.backend_type == "webcam"


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_read_preview_frame_without_live_view_raises_camera_error(mock_video_capture):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend()
    cam.connect()

    with pytest.raises(CameraError):
        cam.read_preview_frame()


@patch("framelabs.camera.webcam_backend.cv2.imencode")
@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_read_preview_frame_success_returns_bytes(mock_video_capture, mock_imencode):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, _fake_frame())
    mock_video_capture.return_value = mock_capture

    mock_imencode.return_value = (True, np.array([4, 5, 6], dtype=np.uint8))

    cam = WebcamBackend()
    cam.connect()
    cam.start_live_view()
    result = cam.read_preview_frame()

    assert isinstance(result, bytes)
    assert result == bytes([4, 5, 6])


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_read_preview_frame_read_failure_raises_camera_error(mock_video_capture):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (False, None)
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend()
    cam.connect()
    cam.start_live_view()

    with pytest.raises(CameraError):
        cam.read_preview_frame()


@patch("framelabs.camera.webcam_backend.cv2.VideoCapture")
def test_read_preview_frame_after_stop_live_view_raises_camera_error(
    mock_video_capture,
):
    mock_capture = MagicMock()
    mock_capture.isOpened.return_value = True
    mock_video_capture.return_value = mock_capture

    cam = WebcamBackend()
    cam.connect()
    cam.start_live_view()
    cam.stop_live_view()

    with pytest.raises(CameraError):
        cam.read_preview_frame()

"""Tests for framelabs.capture.capture_service."""

import cv2
import numpy as np
import pytest

from framelabs.camera.camera_interface import CameraMetadata
from framelabs.capture.capture_service import CaptureServiceError, capture_frame
from framelabs.capture.frame_writer import CaptureWriteError
from framelabs.capture.metadata import MetadataWriteError
from framelabs.capture.metadata import write_metadata as real_write_metadata
from framelabs.core.event_bus import EventBus
from framelabs.project.creator import create_new_project
from framelabs.project.project import Project


def _real_png_bytes() -> bytes:
    """Build genuine encoded PNG bytes, matching test_frame_writer.py's approach."""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


class FakeCameraManager:
    """Minimal stand-in for CameraManager exposing only what capture_service.py uses.

    capture_should_fail / metadata_call_count let individual tests control
    failure behavior without touching real hardware.
    """

    def __init__(self, capture_should_fail: bool = False):
        self.capture_should_fail = capture_should_fail
        self.capture_call_count = 0

    def capture(self) -> bytes:
        self.capture_call_count += 1
        if self.capture_should_fail:
            raise RuntimeError("simulated camera trigger failure")
        return _real_png_bytes()

    def get_active_camera_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id="0",
            display_name="Fake Camera",
            backend_type="webcam",
        )


def _make_project(tmp_path):
    """Build a real Project via create_new_project, so all subfolders exist."""
    return create_new_project(
        name="Test Project",
        parent_dir=tmp_path,
        fps=12,
        resolution=(1920, 1080),
    )


def _make_event_bus():
    event_bus = EventBus()
    received = []
    event_bus.subscribe("FRAME_CAPTURED", lambda payload: received.append(payload))
    return event_bus, received


def test_capture_frame_happy_path(tmp_path):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager()
    event_bus, received = _make_event_bus()

    frame = capture_frame(project, camera_manager, event_bus)

    assert frame.number == 1
    assert frame.file == "images/000001.png"
    assert frame in project.frames

    assert (project.project_path / "images" / "000001.png").exists()
    assert (project.project_path / "thumbnails" / "000001.jpg").exists()
    assert (project.project_path / "metadata" / "000001.json").exists()
    assert (project.project_path / "project.ffproj").exists()

    assert received == [{"frame_number": 1}]


def test_capture_frame_camera_trigger_failure_raises_and_writes_nothing(tmp_path):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager(capture_should_fail=True)
    event_bus, received = _make_event_bus()

    with pytest.raises(CaptureServiceError):
        capture_frame(project, camera_manager, event_bus)

    assert project.frames == []
    assert list((project.project_path / "images").iterdir()) == []
    assert received == []


def test_capture_frame_write_failure_raises_and_does_not_update_timeline(
    tmp_path, monkeypatch
):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager()
    event_bus, received = _make_event_bus()

    def _boom(*args, **kwargs):
        raise CaptureWriteError("simulated write failure")

    monkeypatch.setattr("framelabs.capture.capture_service.write_frame", _boom)

    with pytest.raises(CaptureServiceError):
        capture_frame(project, camera_manager, event_bus)

    assert project.frames == []
    assert received == []


def test_capture_frame_thumbnail_failure_still_succeeds(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager()
    event_bus, received = _make_event_bus()

    def _boom(*args, **kwargs):
        raise CaptureWriteError("simulated thumbnail failure")

    monkeypatch.setattr("framelabs.capture.capture_service.generate_thumbnail", _boom)

    frame = capture_frame(project, camera_manager, event_bus)

    # Frame still captured despite thumbnail failure -- image is real,
    # thumbnail is just missing.
    assert frame.number == 1
    assert frame in project.frames
    assert (project.project_path / "images" / "000001.png").exists()
    assert not (project.project_path / "thumbnails" / "000001.jpg").exists()
    assert received == [{"frame_number": 1}]


def test_capture_frame_metadata_failure_retries_once_then_succeeds(
    tmp_path, monkeypatch
):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager()
    event_bus, received = _make_event_bus()

    call_count = {"n": 0}

    def _fail_once_then_succeed(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise MetadataWriteError("simulated first failure")
        return real_write_metadata(*args, **kwargs)

    monkeypatch.setattr(
        "framelabs.capture.capture_service.write_metadata", _fail_once_then_succeed
    )

    frame = capture_frame(project, camera_manager, event_bus)

    assert call_count["n"] == 2
    assert frame.number == 1
    assert (project.project_path / "metadata" / "000001.json").exists()
    assert received == [{"frame_number": 1}]


def test_capture_frame_metadata_failure_persists_frame_still_kept(
    tmp_path, monkeypatch
):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager()
    event_bus, received = _make_event_bus()

    def _always_fail(*args, **kwargs):
        raise MetadataWriteError("simulated persistent failure")

    monkeypatch.setattr(
        "framelabs.capture.capture_service.write_metadata", _always_fail
    )

    frame = capture_frame(project, camera_manager, event_bus)

    # Metadata never wrote, but the image/thumbnail are real and the frame
    # is still kept -- never lose already-captured data over a metadata
    # problem.
    assert frame.number == 1
    assert frame in project.frames
    assert (project.project_path / "images" / "000001.png").exists()
    assert (project.project_path / "thumbnails" / "000001.jpg").exists()
    assert not (project.project_path / "metadata" / "000001.json").exists()
    assert received == [{"frame_number": 1}]


def test_capture_frame_missing_project_path_raises_value_error():
    project = Project(
        version=1,
        name="No Path",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        project_path=None,
    )
    camera_manager = FakeCameraManager()
    event_bus, _ = _make_event_bus()

    with pytest.raises(ValueError):
        capture_frame(project, camera_manager, event_bus)


def test_capture_frame_numbering_increments_across_captures(tmp_path):
    project = _make_project(tmp_path)
    camera_manager = FakeCameraManager()
    event_bus, received = _make_event_bus()

    frame1 = capture_frame(project, camera_manager, event_bus)
    frame2 = capture_frame(project, camera_manager, event_bus)

    assert frame1.number == 1
    assert frame2.number == 2
    assert [f.number for f in project.frames] == [1, 2]
    assert received == [{"frame_number": 1}, {"frame_number": 2}]

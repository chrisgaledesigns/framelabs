"""Tests for framelabs.capture.commands."""

import cv2
import numpy as np
import pytest

from framelabs.camera.camera_interface import CameraMetadata
from framelabs.capture.capture_service import capture_frame
from framelabs.capture.commands import DuplicateFrameCommand
from framelabs.core.event_bus import EventBus
from framelabs.core.undo_manager import UndoManager
from framelabs.project.creator import create_new_project


def _real_png_bytes() -> bytes:
    """Build genuine encoded PNG bytes, matching test_capture_service.py's approach."""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


class FakeCameraManager:
    """Minimal stand-in for CameraManager, matching test_capture_service.py's."""

    def capture(self) -> bytes:
        return _real_png_bytes()

    def get_active_camera_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id="0", display_name="Fake Camera", backend_type="webcam"
        )


def _make_project(tmp_path):
    return create_new_project(
        name="Test Project", parent_dir=tmp_path, fps=12, resolution=(1920, 1080)
    )


def test_duplicate_frame_command_do_creates_new_frame(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    frame = capture_frame(project, FakeCameraManager(), event_bus)

    command = DuplicateFrameCommand(project, event_bus, frame.number)
    command.do()

    assert [f.number for f in project.frames] == [1, 2]
    assert (project.project_path / "images" / "000002.png").exists()


def test_duplicate_frame_command_undo_removes_created_frame(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    frame = capture_frame(project, FakeCameraManager(), event_bus)

    command = DuplicateFrameCommand(project, event_bus, frame.number)
    command.do()
    command.undo()

    assert [f.number for f in project.frames] == [1]
    assert not (project.project_path / "images" / "000002.png").exists()


def test_duplicate_frame_command_redo_recreates_frame(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    frame = capture_frame(project, FakeCameraManager(), event_bus)

    command = DuplicateFrameCommand(project, event_bus, frame.number)
    command.do()
    command.undo()
    command.do()

    assert [f.number for f in project.frames] == [1, 2]
    assert (project.project_path / "images" / "000002.png").exists()


def test_duplicate_frame_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    command = DuplicateFrameCommand(project, event_bus, 1)

    with pytest.raises(RuntimeError):
        command.undo()


def test_duplicate_frame_command_description_includes_source_frame_number(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    command = DuplicateFrameCommand(project, event_bus, 7)

    assert command.description == "Duplicate Frame 7"


def test_duplicate_frame_command_via_undo_manager_full_cycle(tmp_path):
    """Exercise the command through the real UndoManager, not called directly."""
    project = _make_project(tmp_path)
    event_bus = EventBus()
    frame = capture_frame(project, FakeCameraManager(), event_bus)
    manager = UndoManager()

    manager.execute(DuplicateFrameCommand(project, event_bus, frame.number))
    assert [f.number for f in project.frames] == [1, 2]
    assert manager.can_undo() is True
    assert manager.can_redo() is False

    manager.undo()
    assert [f.number for f in project.frames] == [1]
    assert manager.can_undo() is False
    assert manager.can_redo() is True

    manager.redo()
    assert [f.number for f in project.frames] == [1, 2]

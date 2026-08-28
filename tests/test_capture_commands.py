"""Tests for capture/commands.py's Command subclasses.

Follows test_capture_service.py's convention: a real Project (via
create_new_project) and real files on disk in tmp_path, plus a
FakeCameraManager standing in for real hardware -- these commands' whole
job is orchestrating real file backup/restore around capture_service's
already-tested functions, so mocking those out would test nothing real.
"""

from unittest.mock import patch

import cv2
import numpy as np
import pytest

from framelabs.camera.camera_interface import CameraError, CameraMetadata
from framelabs.capture.capture_service import (
    CaptureServiceError,
    FrameNotFoundError,
    capture_frame,
)
from framelabs.capture.commands import (
    DeleteFrameCommand,
    DuplicateFrameCommand,
    ReorderFramesCommand,
    ReplaceFrameCommand,
    SetFrameNotesCommand,
    ToggleFrameMarkerCommand,
    _backup_frame_files,
)
from framelabs.core.event_bus import EventBus
from framelabs.project.creator import create_new_project
from framelabs.project.serializer import ProjectSerializer


def _real_png_bytes(fill_value: int = 0) -> bytes:
    """Build genuine encoded PNG bytes, matching test_capture_service.py.

    fill_value lets tests distinguish an "original" capture from a
    "replacement" one -- FakeCameraManager's default (matching
    test_capture_service.py) always returns identical all-black frames,
    which would make an undo/restore assertion trivially pass even if
    nothing was actually restored.
    """
    image = np.full((100, 100, 3), fill_value, dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


class FakeCameraManager:
    """Minimal stand-in for CameraManager, matching test_capture_service.py."""

    def __init__(self, capture_should_fail: bool = False, fill_value: int = 0):
        self.capture_should_fail = capture_should_fail
        self.fill_value = fill_value
        self.capture_call_count = 0

    def capture(self) -> bytes:
        self.capture_call_count += 1
        if self.capture_should_fail:
            raise CameraError("simulated camera trigger failure")
        return _real_png_bytes(self.fill_value)

    def get_active_camera_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id="0", display_name="Fake Camera", backend_type="webcam"
        )


def _make_project(tmp_path):
    return create_new_project(
        name="Test Project", parent_dir=tmp_path, fps=12, resolution=(1920, 1080)
    )


def _make_event_bus():
    return EventBus()


def _capture_one_frame(project, event_bus, camera_manager=None):
    """Capture a real frame via capture_frame(), returning it."""
    return capture_frame(project, camera_manager or FakeCameraManager(), event_bus)


# --- _backup_frame_files --------------------------------------------------


def test_backup_frame_files_image_copy_failure_raises_capture_service_error(tmp_path):
    """The image copy is mandatory -- a failure copying it should raise,
    not be silently swallowed like thumbnail/metadata failures are."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)

    with patch("framelabs.capture.commands.shutil.copy2", side_effect=OSError("boom")):
        with pytest.raises(CaptureServiceError):
            _backup_frame_files(project, frame.number)


def test_backup_frame_files_thumbnail_failure_is_logged_and_skipped(tmp_path):
    """A thumbnail copy failure should not abort the backup -- it's
    logged and skipped, matching the rest of the codebase's treatment of
    thumbnails as optional."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    real_copy2 = __import__("shutil").copy2

    def fake_copy2(src, dst):
        if str(dst).endswith("thumbnail.jpg"):
            raise OSError("boom")
        return real_copy2(src, dst)

    with patch("framelabs.capture.commands.shutil.copy2", side_effect=fake_copy2):
        backup_dir = _backup_frame_files(project, frame.number)  # should not raise

    assert (backup_dir / "image.png").exists()
    assert not (backup_dir / "thumbnail.jpg").exists()


def test_backup_frame_files_metadata_failure_is_logged_and_skipped(tmp_path):
    """Same as the thumbnail case, for metadata.json."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    real_copy2 = __import__("shutil").copy2

    def fake_copy2(src, dst):
        if str(dst).endswith("metadata.json"):
            raise OSError("boom")
        return real_copy2(src, dst)

    with patch("framelabs.capture.commands.shutil.copy2", side_effect=fake_copy2):
        backup_dir = _backup_frame_files(project, frame.number)  # should not raise

    assert (backup_dir / "image.png").exists()
    assert not (backup_dir / "metadata.json").exists()


# --- DuplicateFrameCommand --------------------------------------------


def test_duplicate_frame_command_do_appends_a_copy(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DuplicateFrameCommand(project, event_bus, frame.number)

    command.do()

    assert len(project.frames) == 2
    assert command.description == f"Duplicate Frame {frame.number}"


def test_duplicate_frame_command_undo_removes_the_duplicate(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DuplicateFrameCommand(project, event_bus, frame.number)
    command.do()

    command.undo()

    assert len(project.frames) == 1
    assert project.frames[0].number == frame.number


def test_duplicate_frame_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DuplicateFrameCommand(project, event_bus, frame.number)

    with pytest.raises(RuntimeError):
        command.undo()


def test_duplicate_frame_command_redo_can_land_on_a_new_number(tmp_path):
    """Per the class docstring, a redo re-runs duplicate_frame() from
    scratch, so a redo after other frames changed can land on a
    different number than the original duplicate."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DuplicateFrameCommand(project, event_bus, frame.number)
    command.do()
    first_duplicate_number = command._duplicate_frame_number
    command.undo()

    # Add another frame before redoing.
    _capture_one_frame(project, event_bus)
    command.do()  # redo

    assert command._duplicate_frame_number != first_duplicate_number


# --- DeleteFrameCommand -------------------------------------------------


def test_delete_frame_command_do_removes_frame_and_files(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    image_path = project.project_path / "images" / f"{frame.number:06d}.png"
    command = DeleteFrameCommand(project, event_bus, frame.number)

    command.do()

    assert project.frames == []
    assert not image_path.exists()
    assert command.description == f"Delete Frame {frame.number}"


def test_delete_frame_command_undo_restores_files_notes_and_marker(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    frame.notes = "Arm raised"
    frame.marker = True
    ProjectSerializer.save(project)
    image_path = project.project_path / "images" / f"{frame.number:06d}.png"
    original_bytes = image_path.read_bytes()

    command = DeleteFrameCommand(project, event_bus, frame.number)
    command.do()

    command.undo()

    assert len(project.frames) == 1
    restored = project.frames[0]
    assert restored.number == frame.number
    assert restored.notes == "Arm raised"
    assert restored.marker is True
    assert image_path.read_bytes() == original_bytes


def test_delete_frame_command_undo_reinserts_in_number_order(tmp_path):
    """A frame deleted from the middle of the sequence must come back in
    the same position, not appended at the end."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    first = _capture_one_frame(project, event_bus)
    middle = _capture_one_frame(project, event_bus)
    last = _capture_one_frame(project, event_bus)

    command = DeleteFrameCommand(project, event_bus, middle.number)
    command.do()
    command.undo()

    numbers = [f.number for f in project.frames]
    assert numbers == [first.number, middle.number, last.number]


def test_delete_frame_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DeleteFrameCommand(project, event_bus, frame.number)

    with pytest.raises(RuntimeError):
        command.undo()


def test_delete_frame_command_redo_reuses_same_backup(tmp_path):
    """A redo after undo should reuse the same backup dir rather than
    re-backing-up (the frame's files are already gone by the time
    redo's do() runs a second time)."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DeleteFrameCommand(project, event_bus, frame.number)

    command.do()
    backup_dir_after_first_do = command._backup_dir
    command.undo()
    command.do()  # redo

    assert command._backup_dir == backup_dir_after_first_do
    assert project.frames == []


def test_delete_frame_command_discard_removes_backup_dir(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = DeleteFrameCommand(project, event_bus, frame.number)
    command.do()
    backup_dir = command._backup_dir
    assert backup_dir.exists()

    command.discard()

    assert not backup_dir.exists()
    assert command._backup_dir is None


# --- ReplaceFrameCommand -------------------------------------------------


def test_replace_frame_command_do_triggers_real_capture_on_first_call(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    camera_manager = FakeCameraManager()
    command = ReplaceFrameCommand(project, camera_manager, event_bus, frame.number)

    command.do()

    assert camera_manager.capture_call_count == 1
    assert command.description == f"Replace Frame {frame.number}"
    assert command.frame_number == frame.number


def test_replace_frame_command_undo_restores_old_file(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    image_path = project.project_path / "images" / f"{frame.number:06d}.png"
    original_bytes = image_path.read_bytes()

    # A distinct fill_value from the original capture's default (0), so
    # the replacement is genuinely different bytes -- otherwise this
    # assertion would trivially pass even if nothing were restored.
    camera_manager = FakeCameraManager(fill_value=200)
    command = ReplaceFrameCommand(project, camera_manager, event_bus, frame.number)
    command.do()
    assert image_path.read_bytes() != original_bytes  # replaced, from FakeCameraManager

    command.undo()

    assert image_path.read_bytes() == original_bytes


def test_replace_frame_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    camera_manager = FakeCameraManager()
    command = ReplaceFrameCommand(project, camera_manager, event_bus, frame.number)

    with pytest.raises(RuntimeError):
        command.undo()


def test_replace_frame_command_redo_reapplies_new_backup_without_recapturing(tmp_path):
    """Per the class docstring, every redo after the first do() must
    reapply the already-captured 'new' backup rather than triggering the
    camera again."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    camera_manager = FakeCameraManager()
    command = ReplaceFrameCommand(project, camera_manager, event_bus, frame.number)
    image_path = project.project_path / "images" / f"{frame.number:06d}.png"

    command.do()  # first do(): real capture
    replaced_bytes = image_path.read_bytes()
    command.undo()
    command.do()  # redo: should reapply, not recapture

    assert camera_manager.capture_call_count == 1  # still just the one real capture
    assert image_path.read_bytes() == replaced_bytes


def test_replace_frame_command_discard_removes_both_backups(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    camera_manager = FakeCameraManager()
    command = ReplaceFrameCommand(project, camera_manager, event_bus, frame.number)
    command.do()
    old_backup, new_backup = command._old_backup_dir, command._new_backup_dir
    assert old_backup.exists()
    assert new_backup.exists()

    command.discard()

    assert not old_backup.exists()
    assert not new_backup.exists()
    assert command._old_backup_dir is None
    assert command._new_backup_dir is None


# --- ToggleFrameMarkerCommand ---------------------------------------------


def test_toggle_frame_marker_command_do_flips_marker_on(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    assert frame.marker is False
    command = ToggleFrameMarkerCommand(project, event_bus, frame.number)

    command.do()

    assert frame.marker is True
    assert command.description == f"Toggle Marker on Frame {frame.number}"


def test_toggle_frame_marker_command_undo_flips_it_back(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = ToggleFrameMarkerCommand(project, event_bus, frame.number)
    command.do()

    command.undo()

    assert frame.marker is False


# --- SetFrameNotesCommand -------------------------------------------------


def test_set_frame_notes_command_init_captures_previous_notes(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    frame.notes = "Original notes"

    command = SetFrameNotesCommand(project, event_bus, frame.number, "New notes")

    assert command._previous_notes == "Original notes"
    assert command.description == f"Set Notes on Frame {frame.number}"


def test_set_frame_notes_command_init_missing_frame_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()

    with pytest.raises(FrameNotFoundError):
        SetFrameNotesCommand(project, event_bus, 999, "New notes")


def test_set_frame_notes_command_do_applies_new_notes(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    command = SetFrameNotesCommand(project, event_bus, frame.number, "New notes")

    command.do()

    assert frame.notes == "New notes"


def test_set_frame_notes_command_undo_restores_previous_notes(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frame = _capture_one_frame(project, event_bus)
    frame.notes = "Original notes"
    command = SetFrameNotesCommand(project, event_bus, frame.number, "New notes")
    command.do()

    command.undo()

    assert frame.notes == "Original notes"


# --- ReorderFramesCommand -------------------------------------------------


def _capture_frames(project, event_bus, count):
    return [_capture_one_frame(project, event_bus) for _ in range(count)]


def test_reorder_frames_command_do_renumbers_frames(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frames = _capture_frames(project, event_bus, 4)  # numbers 1..4
    for i, frame in enumerate(frames):
        frame.notes = f"f{i}"
    command = ReorderFramesCommand(project, event_bus, [1], insert_before=4)

    command.do()

    ordered = sorted(project.frames, key=lambda f: f.number)
    assert [f.notes for f in ordered] == ["f1", "f2", "f0", "f3"]
    assert command.description == "Reorder 1 Frame(s)"


def test_reorder_frames_command_undo_restores_original_numbers(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frames = _capture_frames(project, event_bus, 4)  # numbers 1..4
    for i, frame in enumerate(frames):
        frame.notes = f"f{i}"
    command = ReorderFramesCommand(project, event_bus, [1], insert_before=4)
    command.do()

    command.undo()

    ordered = sorted(project.frames, key=lambda f: f.number)
    assert [f.notes for f in ordered] == ["f0", "f1", "f2", "f3"]
    assert [f.number for f in ordered] == [1, 2, 3, 4]
    for number in (1, 2, 3, 4):
        assert (project.project_path / "images" / f"{number:06d}.png").exists()
        assert (project.project_path / "thumbnails" / f"{number:06d}.jpg").exists()
        assert (project.project_path / "metadata" / f"{number:06d}.json").exists()


def test_reorder_frames_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    _capture_frames(project, event_bus, 2)
    command = ReorderFramesCommand(project, event_bus, [1], insert_before=None)

    with pytest.raises(RuntimeError):
        command.undo()


def test_reorder_frames_command_redo_reproduces_same_move(tmp_path):
    """do() re-derives the mapping from frame_numbers/insert_before on
    every call rather than replaying a stored one -- since undo() always
    restores the exact pre-move state, redoing should reproduce the exact
    same result."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frames = _capture_frames(project, event_bus, 4)
    for i, frame in enumerate(frames):
        frame.notes = f"f{i}"
    command = ReorderFramesCommand(project, event_bus, [1], insert_before=4)
    command.do()
    after_first_do = [f.notes for f in sorted(project.frames, key=lambda f: f.number)]

    command.undo()
    command.do()  # redo
    after_redo = [f.notes for f in sorted(project.frames, key=lambda f: f.number)]

    assert after_redo == after_first_do


def test_reorder_frames_command_undo_is_no_op_for_a_no_op_move(tmp_path):
    """A drop that doesn't actually move anything (do()'s mapping is
    empty) must have an undo() that's equally harmless."""
    project = _make_project(tmp_path)
    event_bus = _make_event_bus()
    frames = _capture_frames(project, event_bus, 3)  # numbers 1..3
    for i, frame in enumerate(frames):
        frame.notes = f"f{i}"
    command = ReorderFramesCommand(project, event_bus, [1], insert_before=2)
    command.do()  # frame 1 is already right before frame 2 -- a no-op

    command.undo()

    ordered = sorted(project.frames, key=lambda f: f.number)
    assert [f.notes for f in ordered] == ["f0", "f1", "f2"]

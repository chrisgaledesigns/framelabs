"""Tests for ExportController in ui/export_controller.py.

export_all()/export_video()/export_image_sequence()/export_gif() are
already covered by test_export_service.py -- these tests are purely about
the decisions ExportController makes given real calls to it (signal
emissions, error handling), following the same style as
test_autosave_controller.py. export_all() does real file I/O against
tmp_path rather than being mocked, since it's cheap and pure (no
camera/hardware involved).
"""

from unittest.mock import MagicMock

import cv2
import numpy as np

from framelabs.core.event_bus import EventBus
from framelabs.export.export_service import ExportServiceError
from framelabs.project.creator import create_new_project
from framelabs.project.project import Frame
from framelabs.ui.export_controller import ExportController


def _make_project(tmp_path, frame_count=1):
    project = create_new_project(
        name="Robot Walk Cycle", parent_dir=tmp_path, fps=12, resolution=(64, 48)
    )
    width, height = project.resolution
    for number in range(1, frame_count + 1):
        image = np.full((height, width, 3), number % 255, dtype=np.uint8)
        filename = f"images/{number:06d}.png"
        cv2.imwrite(str(project.project_path / filename), image)
        project.frames.append(Frame(number=number, file=filename))
    return project


def test_export_requested_signal_is_wired_to_handler(tmp_path):
    """On construction, export_requested should already be wired to
    _handle_export_requested, so MainWindow only ever needs to emit the
    public signal, never call the handler directly."""
    controller = ExportController(EventBus())
    project = _make_project(tmp_path)

    succeeded_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)

    controller.export_requested.emit(project)

    succeeded_slot.assert_called_once()


def test_handle_export_requested_success_emits_succeeded(tmp_path):
    """A project with real frames should emit export_succeeded with an
    ExportResult reporting all three formats as succeeded."""
    controller = ExportController(EventBus())
    project = _make_project(tmp_path, frame_count=2)

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(project)

    succeeded_slot.assert_called_once()
    failed_slot.assert_not_called()
    result = succeeded_slot.call_args.args[0]
    assert set(result.succeeded) == {"video", "image_sequence", "gif"}
    assert not result.failed


def test_handle_export_requested_no_frames_emits_failed(tmp_path):
    """A project with no frames (ExportServiceError raised before any
    output is created) should emit export_failed rather than raising and
    crashing the worker thread."""
    controller = ExportController(EventBus())
    project = _make_project(tmp_path, frame_count=0)

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(project)  # should not raise

    failed_slot.assert_called_once()
    succeeded_slot.assert_not_called()


def test_handle_export_requested_partial_failure_still_emits_succeeded(
    tmp_path, monkeypatch
):
    """One format failing (e.g. no usable video codec) should still
    report the other two as succeeded, via export_succeeded with a
    non-empty ExportResult.failed -- not export_failed, since that's
    reserved for "nothing at all could be exported"."""
    controller = ExportController(EventBus())
    project = _make_project(tmp_path)

    def _raise(*args, **kwargs):
        raise ExportServiceError("simulated codec failure")

    monkeypatch.setattr("framelabs.export.export_service.export_video", _raise)

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(project)

    failed_slot.assert_not_called()
    succeeded_slot.assert_called_once()
    result = succeeded_slot.call_args.args[0]
    assert result.failed == {"video": "simulated codec failure"}
    assert set(result.succeeded) == {"image_sequence", "gif"}

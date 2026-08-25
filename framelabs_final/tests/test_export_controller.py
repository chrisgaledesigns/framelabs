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
from framelabs.export.export_service import (
    ExportProgress,
    ExportRequest,
    ExportServiceError,
)
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


def _make_request(project, **kwargs):
    """An ExportRequest with all three formats checked by default, so
    existing tests written before the Export dialog still exercise the
    same "all three" behavior unless a test overrides specific flags."""
    kwargs.setdefault("want_video", True)
    kwargs.setdefault("want_image_sequence", True)
    kwargs.setdefault("want_gif", True)
    return ExportRequest(project=project, **kwargs)


def test_export_requested_signal_is_wired_to_handler(tmp_path):
    """On construction, export_requested should already be wired to
    _handle_export_requested, so MainWindow only ever needs to emit the
    public signal, never call the handler directly."""
    controller = ExportController(EventBus())
    request = _make_request(_make_project(tmp_path))

    succeeded_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)

    controller.export_requested.emit(request)

    succeeded_slot.assert_called_once()


def test_handle_export_requested_success_emits_succeeded(tmp_path):
    """A request with real frames and all three formats checked should
    emit export_succeeded with an ExportResult reporting all three
    formats as succeeded."""
    controller = ExportController(EventBus())
    request = _make_request(_make_project(tmp_path, frame_count=2))

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(request)

    succeeded_slot.assert_called_once()
    failed_slot.assert_not_called()
    result = succeeded_slot.call_args.args[0]
    assert set(result.succeeded) == {"video", "image_sequence", "gif"}
    assert not result.failed


def test_handle_export_requested_only_checked_formats_run(tmp_path):
    """A request checking only GIF should only report GIF as succeeded
    -- the controller-level equivalent of the Export dialog letting the
    user pick specific formats rather than always exporting all three."""
    controller = ExportController(EventBus())
    request = _make_request(
        _make_project(tmp_path, frame_count=1),
        want_video=False,
        want_image_sequence=False,
        want_gif=True,
    )

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(request)

    succeeded_slot.assert_called_once()
    failed_slot.assert_not_called()
    result = succeeded_slot.call_args.args[0]
    assert set(result.succeeded) == {"gif"}


def test_handle_export_requested_no_frames_emits_failed(tmp_path):
    """A project with no frames (ExportServiceError raised before any
    output is created) should emit export_failed rather than raising and
    crashing the worker thread."""
    controller = ExportController(EventBus())
    request = _make_request(_make_project(tmp_path, frame_count=0))

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(request)  # should not raise

    failed_slot.assert_called_once()
    succeeded_slot.assert_not_called()


def test_handle_export_requested_unexpected_error_still_emits_failed(
    tmp_path, monkeypatch
):
    """An exception that ISN'T ExportServiceError (i.e. something
    export_service failed to wrap) must still emit export_failed rather
    than escaping _handle_export_requested silently. Previously this
    would leave neither signal firing -- exactly the observed bug where
    the Export menu item stayed disabled forever with no dialog, because
    MainWindow had no way to learn the export had ended."""
    controller = ExportController(EventBus())
    request = _make_request(_make_project(tmp_path))

    def _raise(*args, **kwargs):
        raise ValueError("simulated unwrapped error")

    monkeypatch.setattr("framelabs.export.export_service.export_video", _raise)

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(request)  # should not raise

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
    request = _make_request(_make_project(tmp_path))

    def _raise(*args, **kwargs):
        raise ExportServiceError("simulated codec failure")

    monkeypatch.setattr("framelabs.export.export_service.export_video", _raise)

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.export_succeeded.connect(succeeded_slot)
    controller.export_failed.connect(failed_slot)

    controller._handle_export_requested(request)

    failed_slot.assert_not_called()
    succeeded_slot.assert_called_once()
    result = succeeded_slot.call_args.args[0]
    assert result.failed == {"video": "simulated codec failure"}
    assert set(result.succeeded) == {"image_sequence", "gif"}


def test_handle_export_requested_emits_progress_updates(tmp_path):
    """export_all()'s on_progress callback should be re-emitted as the
    export_progress signal -- MainWindow's progress dialog has no other
    way to hear about mid-export frame counts."""
    controller = ExportController(EventBus())
    request = _make_request(
        _make_project(tmp_path, frame_count=3),
        want_video=False,
        want_image_sequence=True,
        want_gif=False,
    )

    progress_slot = MagicMock()
    controller.export_progress.connect(progress_slot)

    controller._handle_export_requested(request)

    assert progress_slot.call_count == 3
    updates = [call.args[0] for call in progress_slot.call_args_list]
    assert [u.current for u in updates] == [1, 2, 3]
    assert all(isinstance(u, ExportProgress) for u in updates)
    assert all(u.format_key == "image_sequence" for u in updates)

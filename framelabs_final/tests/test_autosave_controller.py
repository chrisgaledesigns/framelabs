"""Tests for AutosaveController in ui/autosave_controller.py.

write_autosave() itself is already covered by test_autosave.py -- these
tests are purely about the decisions AutosaveController makes given real
calls to it (signal emissions, error handling), following the same
"call methods directly, verify signal emissions with a MagicMock" style
as test_camera_controller.py. write_autosave() does real file I/O
against tmp_path rather than being mocked, since it's cheap and pure
(no camera/hardware involved), matching test_autosave.py's own approach.
"""

from unittest.mock import MagicMock

from framelabs.project.project import Frame, Project
from framelabs.project.serializer import CURRENT_VERSION
from framelabs.ui.autosave_controller import AutosaveController


def _make_project(project_path, frame_count=1):
    return Project(
        version=CURRENT_VERSION,
        name="Robot Walk Cycle",
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[
            Frame(number=n, file=f"images/{n:06d}.png")
            for n in range(1, frame_count + 1)
        ],
        project_path=project_path,
    )


def test_autosave_requested_signal_is_wired_to_handler(tmp_path):
    """On construction, autosave_requested should already be wired to
    _handle_autosave_requested, so MainWindow only ever needs to emit the
    public signal, never call the handler directly. Verified by emitting
    the signal itself (not calling the handler directly, unlike every
    other test below) and confirming a real snapshot gets written."""
    controller = AutosaveController()
    project = _make_project(tmp_path)

    succeeded_slot = MagicMock()
    controller.autosave_succeeded.connect(succeeded_slot)

    controller.autosave_requested.emit(project)

    succeeded_slot.assert_called_once()
    assert (tmp_path / ".autosave").is_dir()


def test_handle_autosave_requested_writes_snapshot_and_emits_succeeded(tmp_path):
    """A successful write should emit autosave_succeeded with the real
    written path, and create the .autosave/ folder on disk."""
    controller = AutosaveController()
    project = _make_project(tmp_path)

    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.autosave_succeeded.connect(succeeded_slot)
    controller.autosave_failed.connect(failed_slot)

    controller._handle_autosave_requested(project)

    succeeded_slot.assert_called_once()
    failed_slot.assert_not_called()
    written_path = succeeded_slot.call_args.args[0]
    assert written_path.startswith(str(tmp_path))
    assert (tmp_path / ".autosave").is_dir()


def test_handle_autosave_requested_no_project_path_emits_failed():
    """A Project with no project_path set (shouldn't be reachable in
    practice, per the handler's own docstring) should emit
    autosave_failed rather than raising and crashing the worker thread."""
    controller = AutosaveController()
    project = _make_project(project_path=None)

    failed_slot = MagicMock()
    succeeded_slot = MagicMock()
    controller.autosave_failed.connect(failed_slot)
    controller.autosave_succeeded.connect(succeeded_slot)

    controller._handle_autosave_requested(project)  # should not raise

    failed_slot.assert_called_once()
    succeeded_slot.assert_not_called()


def test_handle_autosave_requested_oserror_emits_failed(tmp_path, monkeypatch):
    """A filesystem failure while writing the snapshot (disk full,
    permission denied, etc.) should emit autosave_failed, not raise."""
    controller = AutosaveController()
    project = _make_project(tmp_path)

    def _raise_oserror(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(
        "framelabs.ui.autosave_controller.write_autosave", _raise_oserror
    )

    failed_slot = MagicMock()
    succeeded_slot = MagicMock()
    controller.autosave_failed.connect(failed_slot)
    controller.autosave_succeeded.connect(succeeded_slot)

    controller._handle_autosave_requested(project)  # should not raise

    failed_slot.assert_called_once()
    succeeded_slot.assert_not_called()

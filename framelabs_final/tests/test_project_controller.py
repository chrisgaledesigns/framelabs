"""Tests for ProjectController in ui/project_controller.py.

NOTE: this is the first test file ProjectController has ever had -- its
pre-existing save/load behavior (_handle_save_requested,
_handle_load_requested) was previously uncovered by any direct unit test.
That gap is flagged, not silently backfilled here; these tests are scoped
to the genuinely new behavior this session adds -- the Feature 8 autosave
-restore path (_handle_restore_requested) and the _find_missing_files
helper both save/load and restore now share. Follows the same
"call methods directly, verify signal emissions with a MagicMock, real
file I/O against tmp_path rather than mocking ProjectSerializer" style as
test_autosave_controller.py.
"""

from unittest.mock import MagicMock

from framelabs.project.autosave import write_autosave
from framelabs.project.project import Frame, Project
from framelabs.project.serializer import CURRENT_VERSION
from framelabs.ui.project_controller import ProjectController


def _make_project(project_path, name="Robot Walk Cycle", frame_count=1):
    return Project(
        version=CURRENT_VERSION,
        name=name,
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


def _make_controller():
    return ProjectController(MagicMock())


def test_restore_requested_signal_is_wired_to_handler(tmp_path):
    """restore_requested should already be wired on construction, same as
    save_requested/load_requested -- MainWindow only ever needs to emit
    the public signal. Verified by emitting the signal itself (not
    calling the handler directly, unlike every other test below) against
    a real autosave snapshot."""
    project = _make_project(tmp_path)
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "000001.png").write_bytes(b"fake")
    write_autosave(project)

    controller = _make_controller()
    succeeded_slot = MagicMock()
    controller.load_succeeded.connect(succeeded_slot)

    controller.restore_requested.emit(tmp_path)

    succeeded_slot.assert_called_once()


def test_handle_restore_requested_success_emits_load_succeeded(tmp_path):
    """Restoring from a real autosave snapshot should emit load_succeeded
    with the reconstructed Project and an empty missing_files list when
    every frame image is present on disk -- the same shape a normal
    successful load emits, per the class docstring's "reuses
    load_succeeded/load_failed" design."""
    project = _make_project(tmp_path)
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "000001.png").write_bytes(b"fake-png-bytes")
    write_autosave(project)  # no project.ffproj written -- simulates a crash

    controller = _make_controller()
    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.load_succeeded.connect(succeeded_slot)
    controller.load_failed.connect(failed_slot)

    controller._handle_restore_requested(tmp_path)

    failed_slot.assert_not_called()
    succeeded_slot.assert_called_once()
    restored_project, missing_files = succeeded_slot.call_args.args
    assert restored_project.name == "Robot Walk Cycle"
    assert missing_files == []


def test_handle_restore_requested_reports_missing_frame_files(tmp_path):
    """Same missing-frames check Feature 1's normal load path already
    does -- restoring from an autosave whose referenced frame image is
    gone from disk should still succeed, but report it as missing rather
    than silently dropping it or failing outright."""
    project = _make_project(tmp_path)
    # Deliberately don't create images/000001.png.
    write_autosave(project)

    controller = _make_controller()
    succeeded_slot = MagicMock()
    controller.load_succeeded.connect(succeeded_slot)

    controller._handle_restore_requested(tmp_path)

    succeeded_slot.assert_called_once()
    _, missing_files = succeeded_slot.call_args.args
    assert missing_files == ["images/000001.png"]


def test_handle_restore_requested_no_autosave_emits_load_failed(tmp_path):
    """If no autosave exists for the given project_path at all
    (restore_autosave() raises FileNotFoundError), the controller should
    emit load_failed rather than raising and crashing the worker
    thread."""
    controller = _make_controller()
    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.load_succeeded.connect(succeeded_slot)
    controller.load_failed.connect(failed_slot)

    controller._handle_restore_requested(tmp_path)  # empty tmp_path, no .autosave/

    succeeded_slot.assert_not_called()
    failed_slot.assert_called_once()


def test_handle_restore_requested_corrupt_autosave_emits_load_failed(tmp_path):
    """If the newest autosave snapshot itself is malformed
    (restore_autosave() raises ProjectLoadError), the controller should
    emit load_failed -- per autosave.py's own docstring, deliberately not
    falling back further to an older snapshot."""
    autosave_dir = tmp_path / ".autosave"
    autosave_dir.mkdir()
    (autosave_dir / "autosave_20260101T000000000000.ffproj").write_text(
        "not valid json"
    )

    controller = _make_controller()
    succeeded_slot = MagicMock()
    failed_slot = MagicMock()
    controller.load_succeeded.connect(succeeded_slot)
    controller.load_failed.connect(failed_slot)

    controller._handle_restore_requested(tmp_path)

    succeeded_slot.assert_not_called()
    failed_slot.assert_called_once()


def test_find_missing_files_shared_helper(tmp_path):
    """_find_missing_files() is the shared helper both the normal load
    path and the restore path now call -- test it directly since it's
    exercised only indirectly by the tests above otherwise."""
    project = _make_project(tmp_path, frame_count=2)
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "000001.png").write_bytes(b"fake")
    # 000002.png deliberately not created.

    missing = ProjectController._find_missing_files(project, tmp_path)

    assert missing == ["images/000002.png"]

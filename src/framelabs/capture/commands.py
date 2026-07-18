"""Concrete Command subclasses wrapping capture_service's per-frame actions.

Per core/command.py's own module docstring, concrete commands live
alongside the service they wrap, not in core/ itself.

DeleteFrameCommand and ReplaceFrameCommand both need to reverse an action
that touches real files on disk (delete_frame unlinks them; replace_frame
overwrites them via a real camera capture), so both back up whatever
files they're about to destroy/overwrite into a private directory under
project_path/cache/undo_backups/<uuid>/ before their first do() ever
runs, and restore from that backup on undo(). ReplaceFrameCommand backs
up twice (the "old" files before capturing, and the "new" files right
after) specifically because its do() triggers real camera hardware --
unlike a file copy, a second real capture on redo would produce a
genuinely different image, not a replay of the first, so redo reapplies
the already-captured "new" backup instead of firing the camera again.

ToggleFrameMarkerCommand and SetFrameNotesCommand touch no files at all
(see toggle_frame_marker's and set_frame_notes' own docstrings in
capture_service.py), so neither needs any on-disk backup -- just the
prior in-memory value for SetFrameNotesCommand, and nothing at all for
ToggleFrameMarkerCommand, since toggling is its own exact inverse.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from framelabs.camera.camera_manager import CameraManager
from framelabs.capture.capture_service import (
    CaptureServiceError,
    FrameNotFoundError,
    delete_frame,
    duplicate_frame,
    replace_frame,
    set_frame_notes,
    toggle_frame_marker,
)
from framelabs.core.command import Command
from framelabs.core.event_bus import EventBus
from framelabs.project.project import Frame, Project
from framelabs.project.serializer import ProjectSerializer

logger = logging.getLogger(__name__)


def _frame_paths(project: Project, frame_number: int) -> tuple[Path, Path, Path]:
    """Return (image, thumbnail, metadata) paths for a frame number.

    Shared by every Command in this module that needs to back up or
    restore a frame's real on-disk files, mirroring the same three-file
    layout capture_service.py's own _copy_frame_files/_delete_frame_files
    already assume.
    """
    return (
        project.project_path / "images" / f"{frame_number:06d}.png",
        project.project_path / "thumbnails" / f"{frame_number:06d}.jpg",
        project.project_path / "metadata" / f"{frame_number:06d}.json",
    )


def _backup_frame_files(project: Project, frame_number: int) -> Path:
    """Copy a frame's current image/thumbnail/metadata into a fresh backup
    dir under project_path/cache/undo_backups/<uuid>/, returning that dir.

    The image copy is mandatory (raises CaptureServiceError on failure,
    matching capture_service._copy_frame_files' own treatment of the
    image as the one file a frame cannot meaningfully exist without).
    Thumbnail/metadata are optional -- logged and skipped if missing or
    uncopyable, same as everywhere else in this codebase.
    """
    image_path, thumb_path, meta_path = _frame_paths(project, frame_number)

    backup_dir = project.project_path / "cache" / "undo_backups" / uuid.uuid4().hex
    backup_dir.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(image_path, backup_dir / "image.png")
    except OSError as exc:
        raise CaptureServiceError(
            f"Failed to back up frame {frame_number}'s image for undo: {exc}"
        ) from exc

    if thumb_path.exists():
        try:
            shutil.copy2(thumb_path, backup_dir / "thumbnail.jpg")
        except OSError as exc:
            logger.warning(
                "Failed to back up thumbnail for frame %d: %s", frame_number, exc
            )
    if meta_path.exists():
        try:
            shutil.copy2(meta_path, backup_dir / "metadata.json")
        except OSError as exc:
            logger.warning(
                "Failed to back up metadata for frame %d: %s", frame_number, exc
            )

    return backup_dir


def _restore_frame_files(project: Project, frame_number: int, backup_dir: Path) -> None:
    """Copy a previously-made backup dir's files back to their real location."""
    image_path, thumb_path, meta_path = _frame_paths(project, frame_number)

    shutil.copy2(backup_dir / "image.png", image_path)

    backup_thumb = backup_dir / "thumbnail.jpg"
    if backup_thumb.exists():
        shutil.copy2(backup_thumb, thumb_path)

    backup_meta = backup_dir / "metadata.json"
    if backup_meta.exists():
        shutil.copy2(backup_meta, meta_path)


def _discard_backup(backup_dir: Path | None) -> None:
    """Remove a backup dir if it exists, tolerating it already being gone."""
    if backup_dir is not None and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)


def _get_frame(project: Project, frame_number: int) -> Frame:
    """Return the Frame with the given number, or raise FrameNotFoundError.

    A local equivalent of capture_service._find_frame() -- deliberately
    not imported from there, since that helper is private (underscore-
    prefixed) to that module.
    """
    for frame in project.frames:
        if frame.number == frame_number:
            return frame
    raise FrameNotFoundError(f"No frame numbered {frame_number} in project.")


class DuplicateFrameCommand(Command):
    """Duplicate a frame; undoable by deleting the frame it created.

    Undo needs no backup data of its own (discard() stays the default
    no-op inherited from Command) -- undoing a duplicate is just removing
    a frame that's otherwise indistinguishable from any other frame in the
    project, and delete_frame() already does that safely.

    Redo re-runs duplicate_frame() from scratch rather than replaying
    stored file bytes. This means a redo occurring after other frames have
    since been added or removed can land on a different frame number than
    the original duplicate did -- that's correct, not a bug:
    capture_service's "no duplicate frame numbers" rule always takes
    priority over reproducing the exact prior number.
    """

    def __init__(
        self, project: Project, event_bus: EventBus, frame_number: int
    ) -> None:
        """Prepare to duplicate `frame_number`. Does not execute anything yet.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus duplicate_frame()/delete_frame() will
                publish on.
            frame_number: The existing frame to duplicate.
        """
        self._project = project
        self._event_bus = event_bus
        self._source_frame_number = frame_number
        # Set by do() on every call (initial execution AND every redo) --
        # see the class docstring for why a redo is not guaranteed to
        # reproduce the same number as the original duplicate.
        self._duplicate_frame_number: int | None = None

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Duplicate Frame 12"."""
        return f"Duplicate Frame {self._source_frame_number}"

    def do(self) -> None:
        """Duplicate the source frame, appended as a new frame at the end."""
        new_frame = duplicate_frame(
            self._project, self._event_bus, self._source_frame_number
        )
        self._duplicate_frame_number = new_frame.number

    def undo(self) -> None:
        """Delete the frame this command's most recent do() created.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._duplicate_frame_number is None:
            raise RuntimeError(
                "DuplicateFrameCommand.undo() called before do() -- "
                "nothing to undo yet."
            )
        delete_frame(self._project, self._event_bus, self._duplicate_frame_number)


class DeleteFrameCommand(Command):
    """Delete a frame; undoable by restoring its files and re-inserting it.

    Per Command's own docstring, all data needed to reverse this action
    must be captured before do() first runs. delete_frame() unlinks the
    frame's files from disk and drops it from project.frames entirely, so
    this command backs up its image/thumbnail/metadata files (via
    _backup_frame_files) and its notes/marker values the first time do()
    runs, then reuses that same backup on every subsequent redo --
    unlike DuplicateFrameCommand, a delete's undo must reproduce the
    EXACT original frame (same number, same files, same notes/marker),
    not a freshly-derived one. discard() releases the backup once this
    command permanently falls out of undo/redo history.
    """

    def __init__(
        self, project: Project, event_bus: EventBus, frame_number: int
    ) -> None:
        """Prepare to delete `frame_number`. Does not execute anything yet.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus delete_frame() will publish on.
            frame_number: The existing frame to delete.
        """
        self._project = project
        self._event_bus = event_bus
        self._frame_number = frame_number
        self._backup_dir: Path | None = None
        self._notes: str = ""
        self._marker: bool = False

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Delete Frame 152"."""
        return f"Delete Frame {self._frame_number}"

    def do(self) -> None:
        """Back up the frame's files/fields (first call only), then delete it."""
        if self._backup_dir is None:
            frame = _get_frame(self._project, self._frame_number)
            self._notes = frame.notes
            self._marker = frame.marker
            self._backup_dir = _backup_frame_files(self._project, self._frame_number)
        delete_frame(self._project, self._event_bus, self._frame_number)

    def undo(self) -> None:
        """Restore the frame's files and re-insert it into project.frames.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._backup_dir is None:
            raise RuntimeError(
                "DeleteFrameCommand.undo() called before do() -- nothing to "
                "undo yet."
            )
        _restore_frame_files(self._project, self._frame_number, self._backup_dir)

        restored = Frame(
            number=self._frame_number,
            file=f"images/{self._frame_number:06d}.png",
            notes=self._notes,
            marker=self._marker,
        )
        # Re-insert in number order -- a frame deleted from the middle of
        # the sequence must come back in the same position, not at the end.
        insert_at = len(self._project.frames)
        for index, existing in enumerate(self._project.frames):
            if existing.number > self._frame_number:
                insert_at = index
                break
        self._project.frames.insert(insert_at, restored)

        ProjectSerializer.save(self._project)
        self._event_bus.publish("FRAME_RESTORED", {"frame_number": self._frame_number})
        logger.info("Restored frame %d via undo", self._frame_number)

    def discard(self) -> None:
        """Release this command's backup files once it falls out of history."""
        _discard_backup(self._backup_dir)
        self._backup_dir = None


class ReplaceFrameCommand(Command):
    """Replace a frame's captured image; undoable by restoring the old files.

    Replace's do() triggers a real camera capture, which -- unlike
    Duplicate's file copy or Delete's file removal -- can't be
    deterministically reproduced on redo (a second real capture would be
    a genuinely different image, not a replay of the first). So this
    command backs up BOTH the frame's files before the first do() (the
    "old" version, restored by undo()) AND the files that result right
    after that first do() succeeds (the "new" version) -- every redo
    after the first simply reapplies the "new" backup instead of
    triggering the camera again. discard() releases both backups once
    this command permanently falls out of undo/redo history.
    """

    def __init__(
        self,
        project: Project,
        camera_manager: CameraManager,
        event_bus: EventBus,
        frame_number: int,
    ) -> None:
        """Prepare to replace `frame_number`. Does not execute anything yet.

        Args:
            project: The active project. Must have a non-None project_path.
            camera_manager: The CameraManager whose active camera will be
                triggered on the first do() only (see class docstring).
            event_bus: The event bus FRAME_REPLACED will be published on.
            frame_number: The existing frame to replace.
        """
        self._project = project
        self._camera_manager = camera_manager
        self._event_bus = event_bus
        self._frame_number = frame_number
        self._old_backup_dir: Path | None = None
        self._new_backup_dir: Path | None = None

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Replace Frame 12"."""
        return f"Replace Frame {self._frame_number}"

    def do(self) -> None:
        """Trigger a real capture the first time; reapply it on every redo.

        Raises:
            CaptureServiceError: If the first do()'s camera trigger fails,
                or if the pre-capture backup of the existing files fails.
            DiskFullServiceError: If the first do()'s write fails because
                the disk is full. A subclass of CaptureServiceError.
        """
        if self._old_backup_dir is None:
            self._old_backup_dir = _backup_frame_files(
                self._project, self._frame_number
            )
            replace_frame(
                self._project,
                self._camera_manager,
                self._event_bus,
                self._frame_number,
            )
            self._new_backup_dir = _backup_frame_files(
                self._project, self._frame_number
            )
        else:
            # Redo: reapply the already-captured "new" files rather than
            # triggering another real camera capture -- see class
            # docstring for why.
            _restore_frame_files(
                self._project, self._frame_number, self._new_backup_dir
            )
            ProjectSerializer.save(self._project)
            self._event_bus.publish(
                "FRAME_REPLACED", {"frame_number": self._frame_number}
            )
            logger.info("Reapplied replaced frame %d via redo", self._frame_number)

    def undo(self) -> None:
        """Restore the frame's pre-replace files.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._old_backup_dir is None:
            raise RuntimeError(
                "ReplaceFrameCommand.undo() called before do() -- nothing to "
                "undo yet."
            )
        _restore_frame_files(self._project, self._frame_number, self._old_backup_dir)
        ProjectSerializer.save(self._project)
        self._event_bus.publish("FRAME_REPLACED", {"frame_number": self._frame_number})
        logger.info("Reverted replace on frame %d via undo", self._frame_number)

    def discard(self) -> None:
        """Release both backups once this command falls out of history."""
        _discard_backup(self._old_backup_dir)
        _discard_backup(self._new_backup_dir)
        self._old_backup_dir = None
        self._new_backup_dir = None


class ToggleFrameMarkerCommand(Command):
    """Toggle a frame's marker; undoable by toggling it again.

    Toggling is its own exact inverse (see toggle_frame_marker's own
    docstring), so undo() and do() both just call toggle_frame_marker()
    -- no backup data of any kind is needed, discard() stays the default
    no-op inherited from Command.
    """

    def __init__(
        self, project: Project, event_bus: EventBus, frame_number: int
    ) -> None:
        """Prepare to toggle the marker on `frame_number`.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus toggle_frame_marker() will publish on.
            frame_number: The frame whose marker is being toggled.
        """
        self._project = project
        self._event_bus = event_bus
        self._frame_number = frame_number

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Toggle Marker on Frame 12"."""
        return f"Toggle Marker on Frame {self._frame_number}"

    def do(self) -> None:
        """Flip the marker."""
        toggle_frame_marker(self._project, self._event_bus, self._frame_number)

    def undo(self) -> None:
        """Flip the marker back -- toggling is its own inverse."""
        toggle_frame_marker(self._project, self._event_bus, self._frame_number)


class SetFrameNotesCommand(Command):
    """Set a frame's notes; undoable by restoring the previous notes.

    The previous notes are captured in __init__, before do() ever runs --
    unlike Delete/Replace, this needs no on-disk backup (set_frame_notes
    touches no files), just the one prior string value.
    """

    def __init__(
        self,
        project: Project,
        event_bus: EventBus,
        frame_number: int,
        new_notes: str,
    ) -> None:
        """Prepare to set `frame_number`'s notes to `new_notes`.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus set_frame_notes() will publish on.
            frame_number: The frame whose notes are being set.
            new_notes: The notes text to apply.

        Raises:
            FrameNotFoundError: If no frame with frame_number exists.
        """
        self._project = project
        self._event_bus = event_bus
        self._frame_number = frame_number
        self._new_notes = new_notes
        self._previous_notes = _get_frame(project, frame_number).notes

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Set Notes on Frame 12"."""
        return f"Set Notes on Frame {self._frame_number}"

    def do(self) -> None:
        """Apply the new notes."""
        set_frame_notes(
            self._project, self._event_bus, self._frame_number, self._new_notes
        )

    def undo(self) -> None:
        """Restore the previous notes."""
        set_frame_notes(
            self._project, self._event_bus, self._frame_number, self._previous_notes
        )

"""Concrete Command subclasses wrapping asset_service's add/remove actions.

Per core/command.py's own module docstring, concrete commands live
alongside the service they wrap, not in core/ itself.

AddAssetCommand's undo just deletes the copy it made -- the original
source file the user picked lives outside the project and is never
touched, so nothing needs backing up for that direction (no discard()
override needed; the default no-op is correct).

RemoveAssetCommand's undo needs the real file back, so it backs it up
under project_path/cache/undo_backups/<uuid>/ before its first do() runs,
mirroring capture/commands.py's DeleteFrameCommand pattern for frame
images.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from framelabs.core.command import Command
from framelabs.core.event_bus import EventBus
from framelabs.project.asset_service import add_asset, remove_asset
from framelabs.project.project import Project
from framelabs.project.serializer import ProjectSerializer

logger = logging.getLogger(__name__)


def _discard_backup(backup_dir: Path | None) -> None:
    """Remove a backup dir if it exists, tolerating it already being gone."""
    if backup_dir is not None and backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)


class AddAssetCommand(Command):
    """Add an asset (copy a file into the project); undoable by deleting
    the copy that was made.

    No on-disk backup is needed for undo -- the original source file the
    user picked lives outside the project and is never touched, so
    deleting the copy this command made is enough (discard() stays the
    default no-op inherited from Command).
    """

    def __init__(
        self,
        project: Project,
        event_bus: EventBus,
        kind: str,
        source_path: Path,
    ) -> None:
        """Prepare to add `source_path` as a `kind` asset. Does not execute
        anything yet.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus add_asset()/remove_asset() will
                publish on.
            kind: One of "audio", "references", "overlays".
            source_path: Path to the real file to copy in, anywhere on disk.
        """
        self._project = project
        self._event_bus = event_bus
        self._kind = kind
        self._source_path = source_path
        # Set by do() on every call (initial execution AND every redo) --
        # a redo re-copies from the original source path, so a fresh
        # collision-safe destination name is picked each time, same as
        # DuplicateFrameCommand's redo in capture/commands.py.
        self._relative_path: str | None = None

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Add Audio scratch_track.wav"."""
        return f"Add {self._kind.capitalize()} {self._source_path.name}"

    def do(self) -> None:
        """Copy the source file into the project as a new `kind` asset."""
        self._relative_path = add_asset(
            self._project, self._event_bus, self._kind, self._source_path
        )

    def undo(self) -> None:
        """Remove the asset this command's most recent do() added.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._relative_path is None:
            raise RuntimeError(
                "AddAssetCommand.undo() called before do() -- nothing to " "undo yet."
            )
        remove_asset(self._project, self._event_bus, self._kind, self._relative_path)


class RemoveAssetCommand(Command):
    """Remove an asset (delete its file, untrack it); undoable by
    restoring the real file and re-tracking it.

    Per Command's own docstring, all data needed to reverse this action
    must be captured before do() first runs -- this command backs up the
    asset's real file (via a private copy under
    project_path/cache/undo_backups/<uuid>/) the first time do() runs,
    then reuses that same backup on every subsequent redo, mirroring
    DeleteFrameCommand's treatment of frame images in
    capture/commands.py. discard() releases the backup once this command
    permanently falls out of undo/redo history.
    """

    def __init__(
        self,
        project: Project,
        event_bus: EventBus,
        kind: str,
        relative_path: str,
    ) -> None:
        """Prepare to remove `relative_path`. Does not execute anything yet.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus add_asset()/remove_asset() will
                publish on.
            kind: One of "audio", "references", "overlays".
            relative_path: The project-relative path to remove, e.g.
                "audio/scratch_track.wav".
        """
        self._project = project
        self._event_bus = event_bus
        self._kind = kind
        self._relative_path = relative_path
        self._backup_dir: Path | None = None
        self._backup_filename: str | None = None

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Remove Audio scratch_track.wav"."""
        return f"Remove {self._kind.capitalize()} {Path(self._relative_path).name}"

    def do(self) -> None:
        """Back up the asset's file (first call only), then remove it."""
        if self._backup_dir is None:
            real_path = self._project.project_path / self._relative_path
            self._backup_dir = (
                self._project.project_path / "cache" / "undo_backups" / uuid.uuid4().hex
            )
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            self._backup_filename = real_path.name
            shutil.copy2(real_path, self._backup_dir / self._backup_filename)

        remove_asset(self._project, self._event_bus, self._kind, self._relative_path)

    def undo(self) -> None:
        """Restore the asset's file and re-track it at its original path.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._backup_dir is None:
            raise RuntimeError(
                "RemoveAssetCommand.undo() called before do() -- nothing to "
                "undo yet."
            )
        real_path = self._project.project_path / self._relative_path
        real_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._backup_dir / self._backup_filename, real_path)

        getattr(self._project, self._kind).append(self._relative_path)
        ProjectSerializer.save(self._project)

        added_event = {
            "audio": "AUDIO_ADDED",
            "references": "REFERENCE_ADDED",
            "overlays": "OVERLAY_ADDED",
        }[self._kind]
        self._event_bus.publish(added_event, {"path": self._relative_path})
        logger.info("Restored %s asset via undo: %s", self._kind, self._relative_path)

    def discard(self) -> None:
        """Release this command's backup file once it falls out of history."""
        _discard_backup(self._backup_dir)
        self._backup_dir = None

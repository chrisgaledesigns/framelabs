"""Project save/load controller for the UI layer.

Runs ProjectSerializer.save() and ProjectSerializer.load() off the main
thread, per the Developer Handbook's "UI Never Blocks" rule -- file I/O,
even though usually fast, must never run on the UI thread by policy.

Also drives Feature 8's crash-recovery restore path
(restore_autosave()) -- reusing load_succeeded/load_failed rather than a
separate signal pair, since from MainWindow's perspective a project
restored from an autosave snapshot adopts exactly the same way a
normally-loaded one does, including Feature 1's missing-frames check.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from both the camera and capture
threads -- Save/Open can be triggered at any time, including when no
capture or camera scan is in progress, and there's no reason to make it
contend with either of them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from framelabs.core.event_bus import EventBus
from framelabs.project.autosave import restore_autosave
from framelabs.project.project import Project
from framelabs.project.serializer import ProjectLoadError, ProjectSerializer

logger = logging.getLogger(__name__)


class ProjectController(QObject):
    """Drives Save Project, Open Project, and autosave restore on a worker
    thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    save_succeeded = Signal()
    save_failed = Signal(str)

    # Project, missing_frame_files -- missing_frame_files is a list of the
    # relative file paths (as stored in project.ffproj) for any frame whose
    # image file could not be found on disk, so Feature 1's "N frames are
    # missing" dialog can report the exact count.
    load_succeeded = Signal(object, list)
    load_failed = Signal(str)

    save_requested = Signal(object)
    load_requested = Signal(object)

    # project_path -- restore always operates on a project folder, not an
    # in-memory Project, since restoring is what CONSTRUCTS the Project in
    # the first place (from the newest .autosave/ snapshot rather than
    # project.ffproj). Reuses load_succeeded/load_failed; see class
    # docstring.
    restore_requested = Signal(object)

    def __init__(self, event_bus: EventBus) -> None:
        """Build the controller against the app's shared EventBus.

        Args:
            event_bus: The same EventBus instance used elsewhere in the
                app.
        """
        super().__init__()
        self._event_bus = event_bus

        self.save_requested.connect(self._handle_save_requested)
        self.load_requested.connect(self._handle_load_requested)
        self.restore_requested.connect(self._handle_restore_requested)

    def _handle_save_requested(self, project: Project) -> None:
        """Save a project. Always runs on the worker thread."""
        try:
            ProjectSerializer.save(project)
        except ValueError as exc:
            # project.project_path is None -- shouldn't be reachable in
            # practice since the UI only allows Save with an active
            # project, but handled explicitly per the Handbook's "never
            # silently ignore exceptions" rule.
            logger.error("Save failed, no active project: %s", exc)
            self.save_failed.emit(str(exc))
        except OSError as exc:
            # Covers disk-full, permission, and other filesystem failures
            # writing project.ffproj.
            logger.error("Save failed: %s", exc)
            self.save_failed.emit(str(exc))
        else:
            logger.info("Project saved: %s", project.name)
            self.save_succeeded.emit()

    def _handle_load_requested(self, project_path: Path) -> None:
        """Load a project and check for missing frame files.

        Always runs on the worker thread. Per Feature 1's edge case,
        missing images don't prevent loading -- they're reported to the
        UI so it can offer Continue / Locate Missing Files / Cancel.
        """
        try:
            project = ProjectSerializer.load(project_path)
        except ProjectLoadError as exc:
            logger.error("Load failed: %s", exc)
            self.load_failed.emit(str(exc))
            return

        missing_files = self._find_missing_files(project, project_path)
        if missing_files:
            logger.warning(
                "Project loaded with %d missing frame(s): %s",
                len(missing_files),
                project.name,
            )
        else:
            logger.info("Project loaded: %s", project.name)

        self.load_succeeded.emit(project, missing_files)

    def _handle_restore_requested(self, project_path: Path) -> None:
        """Restore a project from its most recent autosave snapshot.

        Always runs on the worker thread. MainWindow only emits this
        signal after has_recoverable_autosave() has already confirmed a
        genuinely-recoverable snapshot exists, but both failure modes are
        still handled explicitly here (not assumed unreachable) per the
        Handbook's "never silently ignore exceptions" rule -- a snapshot
        can vanish or turn out corrupt between that check and this call
        actually running.
        """
        try:
            project = restore_autosave(project_path)
        except FileNotFoundError as exc:
            logger.error("Restore failed, no autosave found: %s", exc)
            self.load_failed.emit(str(exc))
            return
        except ProjectLoadError as exc:
            logger.error("Restore failed, autosave is corrupt: %s", exc)
            self.load_failed.emit(str(exc))
            return

        missing_files = self._find_missing_files(project, project_path)
        if missing_files:
            logger.warning(
                "Project restored from autosave with %d missing frame(s): %s",
                len(missing_files),
                project.name,
            )
        else:
            logger.info("Project restored from autosave: %s", project.name)

        self.load_succeeded.emit(project, missing_files)

    @staticmethod
    def _find_missing_files(project: Project, project_path: Path) -> list:
        """Return the relative file paths of any frame image missing on
        disk. Shared by both the normal load path and the autosave
        restore path, which both need Feature 1's identical check.
        """
        return [
            frame.file
            for frame in project.frames
            if not (project_path / frame.file).exists()
        ]

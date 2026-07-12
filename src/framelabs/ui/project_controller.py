"""Project save/load controller for the UI layer.

Runs ProjectSerializer.save() and ProjectSerializer.load() off the main
thread, per the Developer Handbook's "UI Never Blocks" rule -- file I/O,
even though usually fast, must never run on the UI thread by policy.

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
from framelabs.project.project import Project
from framelabs.project.serializer import ProjectLoadError, ProjectSerializer

logger = logging.getLogger(__name__)


class ProjectController(QObject):
    """Drives Save Project and Open Project on a worker thread for the UI.

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

        missing_files = [
            frame.file
            for frame in project.frames
            if not (project_path / frame.file).exists()
        ]
        if missing_files:
            logger.warning(
                "Project loaded with %d missing frame(s): %s",
                len(missing_files),
                project.name,
            )
        else:
            logger.info("Project loaded: %s", project.name)

        self.load_succeeded.emit(project, missing_files)

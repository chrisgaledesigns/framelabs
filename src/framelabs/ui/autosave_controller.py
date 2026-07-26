"""Autosave worker controller for the UI layer.

Drives project/autosave.py's write_autosave() off the main thread, per the
Developer Handbook's "UI Never Blocks" rule. Feature 8 requires a snapshot
every 30 seconds AND after every capture. Neither trigger originates on
this controller's own worker thread, so both are delivered the same way
CaptureController.capture_requested already carries its Project on the
signal itself (see that module's docstring): MainWindow emits
autosave_requested with whichever Project is actually active at the
moment of the trigger, rather than this controller tracking a separately
-synced "current project" reference that could drift stale.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from every other worker thread -- an
autosave write should never contend with an in-progress capture, camera
scan, live preview, onion skin refresh, playback tick, or a Save/Open
Project request.

Note: the 30-second periodic timer itself does NOT live here -- see
MainWindow._start_autosave_controller()'s docstring for why it lives on
the main thread instead, unlike CameraController's scanning timer.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from framelabs.project.autosave import write_autosave
from framelabs.project.project import Project

logger = logging.getLogger(__name__)


class AutosaveController(QObject):
    """Drives Feature 8's autosave snapshots on a worker thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    autosave_succeeded = Signal(str)
    autosave_failed = Signal(str)

    # Emitted from the main thread with the currently active Project as
    # its payload; connected to _handle_autosave_requested below, which --
    # because this object lives on the worker thread once moved -- Qt
    # automatically delivers via a queued connection.
    autosave_requested = Signal(object)

    def __init__(self) -> None:
        """Build the controller. Takes no dependencies -- write_autosave()
        is a pure function of the Project it's given, so unlike most other
        controllers there's no shared manager/service instance to wire up.
        """
        super().__init__()
        self.autosave_requested.connect(self._handle_autosave_requested)

    def _handle_autosave_requested(self, project: Project) -> None:
        """Write one autosave snapshot. Always runs on the worker thread."""
        try:
            autosave_path = write_autosave(project)
        except ValueError as exc:
            # project.project_path is None -- shouldn't be reachable in
            # practice since MainWindow only ever emits this signal with
            # an active project, but handled explicitly rather than left
            # to crash the worker thread, per the Handbook's "never
            # silently ignore exceptions" rule.
            logger.error("Autosave failed, no active project: %s", exc)
            self.autosave_failed.emit(str(exc))
        except OSError as exc:
            # Disk-full/permission/etc. writing the .autosave/ snapshot.
            logger.error("Autosave failed: %s", exc)
            self.autosave_failed.emit(str(exc))
        else:
            logger.info("Autosave written: %s", autosave_path)
            self.autosave_succeeded.emit(str(autosave_path))

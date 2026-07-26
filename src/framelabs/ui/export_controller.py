"""Export worker controller for the UI layer.

Drives export_service.export_all() off the main thread, per the
Developer Handbook's "UI Never Blocks" rule -- rendering a full project to
video/GIF, or copying every frame into an image sequence, can take real
time on a long project and must never freeze the window.

Same "carry the Project on the signal itself" pattern
autosave_controller.py and capture_controller.py already use, rather than
this controller tracking its own separately-synced "current project"
reference.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from every other worker thread -- an
export in progress should never contend with an in-progress capture,
camera scan, live preview, onion skin refresh, playback tick, project
save/load, or autosave write.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from framelabs.core.event_bus import EventBus
from framelabs.export.export_service import ExportResult, ExportServiceError, export_all
from framelabs.project.project import Project

logger = logging.getLogger(__name__)


class ExportController(QObject):
    """Drives the "Export Video, Sequence & GIF" action on a worker
    thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    export_succeeded = Signal(object)  # ExportResult
    export_failed = Signal(str)

    # Emitted from the main thread with the currently active Project as
    # its payload; connected to _handle_export_requested below, which --
    # because this object lives on the worker thread once moved -- Qt
    # automatically delivers via a queued connection.
    export_requested = Signal(object)

    def __init__(self, event_bus: EventBus) -> None:
        """Build the controller against the app's shared EventBus, so
        each successful format's *_EXPORTED event is published on the
        same bus every other service publishes to.
        """
        super().__init__()
        self.event_bus = event_bus
        self.export_requested.connect(self._handle_export_requested)

    def _handle_export_requested(self, project: Project) -> None:
        """Run all three exports. Always runs on the worker thread."""
        try:
            result: ExportResult = export_all(project, self.event_bus)
        except ExportServiceError as exc:
            logger.error("Export failed: %s", exc)
            self.export_failed.emit(str(exc))
        else:
            logger.info(
                "Export finished: %d succeeded, %d failed",
                len(result.succeeded),
                len(result.failed),
            )
            self.export_succeeded.emit(result)

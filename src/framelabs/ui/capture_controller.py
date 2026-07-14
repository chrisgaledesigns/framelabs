"""Capture controller for the UI layer.

Owns no CameraManager of its own -- it's handed the SAME CameraManager
instance CameraController already created and connected, so capture
triggers the actual connected camera rather than a second, unconnected
one. Drives capture_service.capture_frame() entirely off the main thread,
per the Developer Handbook's "UI Never Blocks" rule -- capture_frame()
writes a PNG, extracts metadata, generates a thumbnail, and autosaves the
project, all of which are too slow to run on the UI thread without
freezing it.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from the camera-scanning thread.
CameraManager.capture() and .rescan_once() both guard against overlapping
via _capture_in_progress specifically because a capture and a background
scan can now genuinely happen concurrently -- keeping them on separate
threads is what makes that guard meaningful rather than redundant.

Unlike CameraController, there is no periodic timer here -- a capture
only happens when explicitly requested (Space key or the Capture menu
action), so this controller's worker thread sits idle between requests.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from framelabs.camera.camera_manager import CameraManager
from framelabs.capture.capture_service import (
    CaptureServiceError,
    DiskFullServiceError,
    capture_frame,
)
from framelabs.core.event_bus import EventBus
from framelabs.project.project import Project

logger = logging.getLogger(__name__)


class CaptureController(QObject):
    """Drives frame capture on a worker thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    capture_succeeded = Signal(int)
    capture_failed = Signal(str)
    disk_full = Signal(str)

    # Emitted from the main thread with the current Project as its
    # payload; connected to _handle_capture_requested below, which --
    # because this object lives on the worker thread once moved -- Qt
    # automatically delivers via a queued connection. Carrying the
    # Project on the signal itself (rather than reading a stored
    # self.project set earlier) means every capture always operates on
    # whichever project was actually active at the moment Space was
    # pressed, with no risk of acting on a stale reference.
    capture_requested = Signal(object)

    def __init__(self, event_bus: EventBus, camera_manager: CameraManager) -> None:
        """Build the controller against an already-existing, already-
        connected CameraManager and the app's shared EventBus.

        Args:
            event_bus: The same EventBus instance used elsewhere in the
                app (the same one CameraController was built with).
            camera_manager: The SAME CameraManager instance
                CameraController already owns. This is deliberately not
                a new CameraManager() -- capture must trigger the camera
                that's actually connected, not an independent, unconnected
                instance.
        """
        super().__init__()
        self._event_bus = event_bus
        self._camera_manager = camera_manager

        self.capture_requested.connect(self._handle_capture_requested)

    def _handle_capture_requested(self, project: Project) -> None:
        """Run one capture. Always runs on the worker thread.

        Catches DiskFullServiceError before the broader CaptureServiceError
        it's a subclass of, so Feature 4's distinct "Disk Full" case is
        never mistaken for the generic "Capture Failed" case.
        """
        try:
            logger.info("Capture started")
            frame = capture_frame(project, self._camera_manager, self._event_bus)
        except DiskFullServiceError as exc:
            logger.error("Capture aborted, disk full: %s", exc)
            self.disk_full.emit(str(exc))
        except CaptureServiceError as exc:
            logger.error("Capture failed: %s", exc)
            self.capture_failed.emit(str(exc))
        except ValueError as exc:
            # project.project_path is None -- shouldn't be reachable in
            # practice since the UI only allows capture with an active
            # project, but handled explicitly rather than left to crash
            # the worker thread, per the Handbook's "never silently
            # ignore exceptions" rule.
            logger.error("Capture failed, no active project: %s", exc)
            self.capture_failed.emit(str(exc))
        else:
            logger.info("Capture succeeded: frame %d", frame.number)
            self.capture_succeeded.emit(frame.number)

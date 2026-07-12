"""Live camera preview controller for the UI layer.

Owns no camera state itself -- shares the same CameraManager instance
CameraController already owns, per the Developer Handbook's guidance that
the rest of the application should only ever talk to one CameraManager.
Polls read_preview_frame() on a QTimer at a target preview rate and emits
the encoded bytes for display, entirely off the main thread so decoding
never blocks the UI.

Instances of this class are meant to be moved to a dedicated QThread via
moveToThread(), same threading contract as CameraController and
CaptureController -- see camera_controller.py's module docstring for the
full explanation of why this pattern is used throughout the UI layer.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from framelabs.camera.camera_interface import CameraError
from framelabs.camera.camera_manager import CameraManager
from framelabs.core.event_bus import EventBus
from framelabs.core.logger import get_logger

logger = get_logger(__name__)

# Feature Spec Feature 3's target: "30+ FPS preview".
PREVIEW_INTERVAL_MS = 33


class LiveViewController(QObject):
    """Drives the live camera preview feed on a worker thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started.
    """

    frame_ready = Signal(bytes)

    def __init__(self, event_bus: EventBus, camera_manager: CameraManager) -> None:
        """Build the controller against a shared EventBus and CameraManager.

        camera_manager must be the SAME instance CameraController owns, so
        this controller reacts to whatever camera is actually connected,
        rather than managing a second, redundant connection.
        """
        super().__init__()
        self._event_bus = event_bus
        self.camera_manager = camera_manager
        self._timer: QTimer | None = None

        event_bus.subscribe("CAMERA_CONNECTED", self._on_camera_connected_event)
        event_bus.subscribe("CAMERA_DISCONNECTED", self._on_camera_disconnected_event)

    def start(self) -> None:
        """Create the polling timer. Connect this to QThread.started.

        The QTimer is created here rather than in __init__ so it's actually
        created on the worker thread -- see CameraController.start_scanning's
        docstring for the full reasoning; the same threading concern applies
        here. The timer is created but left stopped until a camera is
        actually connected.
        """
        self._timer = QTimer(self)
        self._timer.setInterval(PREVIEW_INTERVAL_MS)
        self._timer.timeout.connect(self._read_frame)

    def _on_camera_connected_event(self, payload: dict[str, Any]) -> None:
        """Start live view and begin polling once a camera is connected."""
        try:
            self.camera_manager.start_live_view()
        except CameraError as exc:
            logger.error("Failed to start live view: %s", exc)
            return
        if self._timer is not None:
            self._timer.start()
        logger.info("Live view polling started")

    def _on_camera_disconnected_event(self, payload: dict[str, Any]) -> None:
        """Stop polling when the camera disconnects.

        No need to call camera_manager.stop_live_view() here -- the backend
        is already gone by the time CAMERA_DISCONNECTED is published (see
        CameraManager.disconnect()/capture()'s cleanup), so there's nothing
        left to stop it on. Just stop our own timer.
        """
        if self._timer is not None:
            self._timer.stop()
        logger.info("Live view polling stopped")

    def _read_frame(self) -> None:
        """Grab and emit one preview frame. Runs on the worker thread.

        A failed grab is logged and skipped rather than raised -- a single
        dropped frame during live preview is not worth surfacing to the
        user, and a genuine disconnect will be caught by CameraController's
        own polling, which publishes CAMERA_DISCONNECTED and stops this
        timer via _on_camera_disconnected_event above.
        """
        if self.camera_manager.capture_in_progress:
            # A still capture is in flight -- skip this tick rather than
            # risk two threads calling the same backend's read() at once.
            return

        try:
            frame_bytes = self.camera_manager.read_preview_frame()
        except CameraError as exc:
            logger.warning("Preview frame grab failed, skipping: %s", exc)
            return
        self.frame_ready.emit(frame_bytes)

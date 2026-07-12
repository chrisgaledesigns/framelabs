"""Camera connection controller for the UI layer.

Owns a CameraManager and drives it entirely off the main thread, per the
Developer Handbook's "UI Never Blocks" rule -- webcam discovery
(discover_webcams(), called by CameraManager.rescan_once()) opens and
closes real OpenCV VideoCapture handles, which is slow enough to freeze
the UI if run on the main thread.

Instances of this class are meant to be moved to a dedicated QThread via
moveToThread(). All of its slots (start_scanning, _scan, the slot behind
rescan_requested) then run on that worker thread. The Qt signals it emits
(camera_connecting, camera_connected, camera_disconnected, no_camera_found)
are automatically queued back to whichever thread the connected receiver
lives on -- this is standard Qt cross-thread signal/slot behavior and
requires no manual locking.

CameraManager state changes are also announced on the shared EventBus
(CAMERA_CONNECTED, CAMERA_DISCONNECTED) so that any future module -- not
just this controller -- can react to camera state changes without needing
a direct reference to this class.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from framelabs.camera.camera_interface import CameraError
from framelabs.camera.camera_manager import CameraManager
from framelabs.core.event_bus import EventBus
from framelabs.core.logger import get_logger

logger = get_logger(__name__)

# How often to poll for newly-appeared webcams while none is connected.
# Frequent enough to feel responsive to hot-plugging, infrequent enough
# not to hammer OpenCV with repeated device probes.
SCAN_INTERVAL_MS = 3000


class CameraController(QObject):
    """Drives camera discovery/connection on a worker thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    camera_connecting = Signal()
    camera_connected = Signal(str)
    camera_disconnected = Signal()
    no_camera_found = Signal()

    # Emitted from any thread; connected to _handle_rescan_requested below,
    # which -- because this object lives on the worker thread once moved --
    # Qt automatically delivers via a queued connection. This is the
    # correct way to ask the worker thread to do something from the UI
    # thread without calling a CameraManager method directly from there.
    rescan_requested = Signal()

    def __init__(self, event_bus: EventBus) -> None:
        """Build the controller against a shared, already-existing EventBus.

        The EventBus must be the same instance used elsewhere in the app
        (e.g. eventually passed to CaptureService) so that camera state
        changes triggered by other modules are also reflected here.
        """
        super().__init__()
        self._event_bus = event_bus
        self.camera_manager = CameraManager(event_bus=event_bus)
        self._timer: QTimer | None = None
        self._connected_camera_id: int | None = None

        event_bus.subscribe("CAMERA_CONNECTED", self._on_camera_connected_event)
        event_bus.subscribe("CAMERA_DISCONNECTED", self._on_camera_disconnected_event)

        self.rescan_requested.connect(self._handle_rescan_requested)

    def start_scanning(self) -> None:
        """Begin periodic scanning. Connect this to QThread.started.

        The QTimer is created here, rather than in __init__, so it's
        actually created on the worker thread -- a QTimer's callbacks fire
        on whichever thread it was created on, so creating it too early
        (before moveToThread()) would make it fire on the main thread
        instead.

        Parented to self (self is already on the worker thread by the time
        this runs) so Qt owns and destroys it on the correct thread when
        this controller is cleaned up -- an unparented QTimer left for
        Python's garbage collector to reap can get destroyed from whatever
        thread happens to drop the last reference, which is where the
        "Timers cannot be stopped from another thread" warning came from.
        """
        self._timer = QTimer(self)
        self._timer.setInterval(SCAN_INTERVAL_MS)
        self._timer.timeout.connect(self._scan)
        self._timer.start()
        self._scan()

    def _handle_rescan_requested(self) -> None:
        """Slot for a manual, out-of-schedule scan request from the UI.

        Logs explicitly (unlike the periodic timer-driven scan) so a
        manual Rescan click always leaves visible proof it actually ran,
        even on the common case where nothing about the camera list has
        changed and there is otherwise nothing to report.
        """
        logger.info("Manual rescan requested")
        self._scan()

    def _scan(self) -> None:
        """Run one scan pass. Always runs on the worker thread."""
        if self._connected_camera_id is not None:
            # Already connected -- just a light poll for other cameras
            # appearing/disappearing, no UI status change needed.
            self.camera_manager.rescan_once()
            return

        self.camera_connecting.emit()
        available = self.camera_manager.rescan_once()
        if not available:
            self.no_camera_found.emit()
            return

        try:
            self.camera_manager.connect(available[0])
        except CameraError as exc:
            logger.warning("Auto-connect to camera %s failed: %s", available[0], exc)
            self.no_camera_found.emit()

    def _on_camera_connected_event(self, payload: dict[str, Any]) -> None:
        """React to CAMERA_CONNECTED, however it was triggered."""
        self._connected_camera_id = payload.get("camera_id")
        try:
            metadata = self.camera_manager.get_active_camera_metadata()
        except CameraError as exc:
            logger.error("Could not read metadata for newly connected camera: %s", exc)
            return
        self.camera_connected.emit(metadata.display_name)

    def _on_camera_disconnected_event(self, payload: dict[str, Any]) -> None:
        """React to CAMERA_DISCONNECTED, however it was triggered."""
        self._connected_camera_id = None
        self.camera_disconnected.emit()

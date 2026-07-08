"""Camera discovery and lifecycle management.

Detects available cameras and hands out the correct CameraInterface
backend to the rest of the application, so no other module needs to
know or care which camera hardware is actually connected.
"""

from __future__ import annotations

import cv2

from framelabs.camera.camera_interface import CameraDisconnectedError, CameraError
from framelabs.camera.webcam_backend import WebcamBackend
from framelabs.core.event_bus import EventBus
from framelabs.core.logger import get_logger

logger = get_logger(__name__)

# How many device indices to probe when looking for webcams. OpenCV
# doesn't expose a "list all cameras" API on every platform, so we
# open-and-close a range of indices to see which ones are real.
MAX_WEBCAM_INDEX = 5


def discover_webcams() -> list[int]:
    """Probe for available webcam device indices.

    Actually opens each candidate index with OpenCV to confirm it's a
    real, usable camera, then immediately releases it. Returns only the
    indices that succeeded.
    """
    found: list[int] = []
    for index in range(MAX_WEBCAM_INDEX):
        cap = cv2.VideoCapture(index)
        try:
            if cap.isOpened():
                found.append(index)
                logger.info("Webcam found at index %d", index)
        finally:
            cap.release()
    return found


class CameraManager:
    """Detects available cameras and manages the active camera backend.

    The rest of the application should only ever talk to CameraManager,
    never to a specific backend (e.g. WebcamBackend) directly. This is
    what lets DSLR and libcamera backends be added later without any
    other module needing to change.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._active_backend = None
        self._active_camera_id: int | None = None
        self._event_bus = event_bus if event_bus is not None else EventBus()

    def connect(self, camera_id: int) -> None:
        """Connect to the camera at the given ID and make it active.

        For now every camera_id refers to a webcam device index, since
        WebcamBackend is the only backend implemented. When DSLR/libcamera
        backends exist, this method will decide which backend class to
        use based on how the camera was discovered -- callers won't need
        to change.
        """
        backend = WebcamBackend(camera_id)
        try:
            backend.connect()
        except CameraError as exc:
            logger.error(
                "CameraManager failed to connect to camera %d: %s", camera_id, exc
            )
            raise
        self._active_backend = backend
        self._active_camera_id = camera_id
        logger.info("CameraManager connected to camera %d", camera_id)
        self._event_bus.publish("CAMERA_CONNECTED", {"camera_id": camera_id})

    def disconnect(self) -> None:
        """Disconnect the currently active camera, if any.

        Safe to call even when nothing is connected -- this is a no-op in
        that case rather than an error, so callers can disconnect
        defensively without checking state first.
        """
        if self._active_backend is None:
            logger.info("CameraManager.disconnect() called with no active camera")
            return

        camera_id = self._active_camera_id
        try:
            self._active_backend.disconnect()
        except CameraError as exc:
            logger.error("Error while disconnecting camera %s: %s", camera_id, exc)
        finally:
            self._active_backend = None
            self._active_camera_id = None
            logger.info("CameraManager disconnected camera %s", camera_id)
            self._event_bus.publish("CAMERA_DISCONNECTED", {"camera_id": camera_id})

    def capture(self) -> bytes:
        """Capture a still frame from the currently active camera.

        Raises:
            CameraError: if there is no active camera, or if the capture
                failed but the camera is still connected (a transient
                failure -- safe to retry).
            CameraDisconnectedError: if the capture failed because the
                camera has actually disconnected. Clears the active camera
                state and publishes CAMERA_DISCONNECTED.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")

        try:
            return self._active_backend.capture()
        except CameraError as exc:
            if self._active_backend.is_connected():
                logger.warning("Transient capture failure: %s", exc)
                raise

            camera_id = self._active_camera_id
            logger.error("Camera %s disconnected during capture: %s", camera_id, exc)
            self._active_backend = None
            self._active_camera_id = None
            self._event_bus.publish("CAMERA_DISCONNECTED", {"camera_id": camera_id})
            raise CameraDisconnectedError(
                f"Camera {camera_id} disconnected during capture"
            ) from exc

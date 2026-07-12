"""Webcam camera backend, using OpenCV.

This is the simplest backend to test with, since it needs no special SDK
or hardware beyond a standard USB or built-in webcam.
"""

import cv2

from framelabs.camera.camera_interface import (
    CameraError,
    CameraInterface,
    CameraMetadata,
)
from framelabs.core.logger import get_logger

logger = get_logger(__name__)


class WebcamBackend(CameraInterface):
    """Camera backend for standard USB/built-in webcams via OpenCV.

    Webcams do not support manual ISO/shutter/aperture control, so those
    methods are implemented as no-ops that log a warning rather than raising
    an error -- calling them should never crash the app.
    """

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index
        self._capture: cv2.VideoCapture | None = None
        self._is_live_view_active = False

    def connect(self) -> None:
        logger.info("Connecting to webcam at index %d", self._device_index)
        self._capture = cv2.VideoCapture(self._device_index)

        if not self._capture.isOpened():
            logger.error("Failed to open webcam at index %d", self._device_index)
            raise CameraError(f"Could not open webcam at index {self._device_index}")

        logger.info("Webcam connected")

    def disconnect(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            logger.info("Webcam disconnected")

    def is_connected(self) -> bool:
        if self._capture is None:
            return False
        return self._capture.isOpened()

    def start_live_view(self) -> None:
        self._require_connection()
        self._is_live_view_active = True
        logger.info("Live view started")

    def stop_live_view(self) -> None:
        self._is_live_view_active = False
        logger.info("Live view stopped")

    def read_preview_frame(self) -> bytes:
        self._require_connection()
        if not self._is_live_view_active:
            raise CameraError("Live view is not active. Call start_live_view() first.")

        success, frame = self._capture.read()
        if not success:
            logger.error("Failed to read preview frame from webcam")
            raise CameraError("Failed to read preview frame from webcam")

        # JPEG, not PNG: preview frames are read many times per second and
        # discarded immediately, so encode speed matters far more than
        # lossless quality here (unlike capture(), which keeps its output).
        encode_success, encoded = cv2.imencode(".jpg", frame)
        if not encode_success:
            logger.error("Failed to encode preview frame as JPEG")
            raise CameraError("Failed to encode preview frame")

        return encoded.tobytes()

    def capture(self) -> bytes:
        self._require_connection()

        success, frame = self._capture.read()
        if not success:
            logger.error("Failed to read frame from webcam")
            raise CameraError("Failed to capture frame from webcam")

        encode_success, encoded = cv2.imencode(".png", frame)
        if not encode_success:
            logger.error("Failed to encode captured frame as PNG")
            raise CameraError("Failed to encode captured frame")

        logger.info("Frame captured successfully")
        return encoded.tobytes()

    def set_iso(self, value: int) -> None:
        logger.warning("Webcam backend does not support ISO control; ignoring")

    def set_shutter(self, value: str) -> None:
        logger.warning("Webcam backend does not support shutter control; ignoring")

    def set_aperture(self, value: str) -> None:
        logger.warning("Webcam backend does not support aperture control; ignoring")

    def get_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id=f"webcam-{self._device_index}",
            display_name=f"Webcam (device {self._device_index})",
            backend_type="webcam",
        )

    def _require_connection(self) -> None:
        if self._capture is None:
            raise CameraError("Camera is not connected. Call connect() first.")

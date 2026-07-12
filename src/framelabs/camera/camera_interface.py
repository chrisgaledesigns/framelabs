"""Defines the contract every camera backend must implement.

Per the FrameLabs Developer Handbook: "Every camera backend implements the
same interface... No backend-specific logic should leak into other modules."
The rest of the application only ever talks to this interface, never to a
specific backend directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CameraMetadata:
    """Metadata describing a connected camera."""

    camera_id: str
    display_name: str
    backend_type: str  # "webcam", "gphoto", "libcamera"


class CameraError(Exception):
    """Raised when a camera operation fails."""


class CameraDisconnectedError(CameraError):
    """Raised when a capture fails because the camera has actually disconnected.

    This is distinct from a plain CameraError, which may represent a
    transient failure. CameraManager only raises this specific type after
    confirming (via is_connected()) that the camera is truly gone.
    """


class CameraInterface(ABC):
    """Abstract base class that all camera backends must implement.

    Concrete backends (WebcamBackend, GphotoBackend, LibcameraBackend, ...)
    inherit from this and provide real implementations for each method.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish a connection to the camera.

        Raises:
            CameraError: if the connection cannot be established.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Cleanly release the camera connection."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Check whether the camera connection is still alive.

        This performs a real, backend-specific check (not just returning a
        cached flag) so that CameraManager can distinguish a transient
        capture failure from an actual disconnection.

        Returns:
            True if the camera is currently connected and responsive.
        """

    @abstractmethod
    def start_live_view(self) -> None:
        """Begin streaming a live preview feed."""

    @abstractmethod
    def stop_live_view(self) -> None:
        """Stop the live preview feed."""

    @abstractmethod
    def read_preview_frame(self) -> bytes:
        """Grab a single live preview frame, for display only.

        Deliberately separate from capture(): this does not write a PNG,
        write metadata, or update the timeline -- it only grabs whatever
        the camera currently sees, encoded for fast display. Encoding
        format is backend-defined (e.g. JPEG, chosen for speed over
        capture()'s lossless PNG) since preview quality doesn't need to
        match a final captured frame.

        Raises:
            CameraError: if start_live_view() has not been called, or if
                the grab fails.
        """

    @abstractmethod
    def capture(self) -> bytes:
        """Capture a single still frame.

        Returns:
            The captured image as raw encoded bytes (e.g. PNG/JPEG data).

        Raises:
            CameraError: if the capture fails.
        """

    @abstractmethod
    def set_iso(self, value: int) -> None:
        """Set the ISO value, if supported by this backend."""

    @abstractmethod
    def set_shutter(self, value: str) -> None:
        """Set the shutter speed, if supported by this backend."""

    @abstractmethod
    def set_aperture(self, value: str) -> None:
        """Set the aperture value, if supported by this backend."""

    @abstractmethod
    def get_metadata(self) -> CameraMetadata:
        """Return metadata describing this camera."""

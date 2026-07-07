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
    def start_live_view(self) -> None:
        """Begin streaming a live preview feed."""

    @abstractmethod
    def stop_live_view(self) -> None:
        """Stop the live preview feed."""

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

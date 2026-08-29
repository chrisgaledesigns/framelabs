"""Camera discovery and lifecycle management.

Detects available cameras and hands out the correct CameraInterface
backend to the rest of the application, so no other module needs to
know or care which camera hardware is actually connected.
"""

from __future__ import annotations

import cv2

from framelabs.camera.camera_interface import (
    CameraDisconnectedError,
    CameraError,
    CameraMetadata,
)
from framelabs.camera.canon_backend import discover_canon_cameras
from framelabs.camera.nikon_backend import discover_nikon_cameras
from framelabs.camera.sony_backend import discover_sony_cameras
from framelabs.camera.webcam_backend import WebcamBackend
from framelabs.core.event_bus import EventBus
from framelabs.core.logger import get_logger

logger = get_logger(__name__)

# gphoto2 (DSLR support) wraps the libgphoto2 system library, which not
# every install has -- it's an optional "dslr" extra, not a hard
# dependency, so a plain webcam-only install of FrameLabs must keep
# working even when it's absent. Only this discovery helper needs the
# import; GphotoBackend itself is imported lazily in connect(), when an
# actual DSLR camera_id is being connected to.
#
# gphoto2/libgphoto2 has no supported Windows build, so on Windows this
# is always unavailable -- CanonBackend/NikonBackend/SonyBackend (see
# their respective modules) are the Windows path for DSLR support
# instead. On Linux/macOS, where libgphoto2 *is* available, this stays
# the primary DSLR backend.
try:
    import gphoto2 as gp

    _GPHOTO_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    gp = None
    _GPHOTO_AVAILABLE = False

# Vendor-SDK camera_ids are disambiguated from a gphoto2 port address
# (e.g. "usb:001,004") by a "<vendor>:" prefix -- gphoto2 port
# addresses never start with these, so there's no collision. See
# _create_backend() for where this is parsed back apart.
_CANON_ID_PREFIX = "canon:"
_NIKON_ID_PREFIX = "nikon:"
_SONY_ID_PREFIX = "sony:"

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


def discover_gphoto_cameras() -> list[tuple[str, str]]:
    """Probe for available DSLR/mirrorless cameras via libgphoto2.

    Returns a list of (model_name, port_address) tuples, one per detected
    camera -- e.g. [("Nikon DSC D850", "usb:001,004")]. port_address is
    what actually identifies a specific camera and is used as its
    camera_id elsewhere in CameraManager; model_name is for display only.

    Returns an empty list, rather than raising, both when the optional
    gphoto2 package isn't installed and when it is installed but the
    autodetect call itself fails -- either way, it just means "no DSLRs
    available right now", which callers already handle for webcams.
    """
    if not _GPHOTO_AVAILABLE:
        return []

    try:
        return list(gp.Camera.autodetect())
    except gp.GPhoto2Error as exc:
        logger.warning("DSLR autodetect failed: %s", exc)
        return []


class CameraManager:
    """Detects available cameras and manages the active camera backend.

    The rest of the application should only ever talk to CameraManager,
    never to a specific backend (e.g. WebcamBackend) directly. This is
    what lets DSLR and libcamera backends be added later without any
    other module needing to change.

    camera_id disambiguates backend type: an int is a webcam device
    index (WebcamBackend); a str is either a gphoto2 port address like
    "usb:001,004" (GphotoBackend, Linux/macOS) or a vendor-prefixed ID
    like "canon:0001" / "nikon:0001" / "sony:0001" (CanonBackend /
    NikonBackend / SonyBackend, Windows). Callers never choose the
    backend directly -- they just pass back whatever camera_id
    rescan_once() reported as available.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._active_backend = None
        self._active_camera_id: int | str | None = None
        self._event_bus = event_bus if event_bus is not None else EventBus()
        self._capture_in_progress = False
        self._known_available_cameras: list[int | str] = []
        # Maps gphoto2 port address -> model name, refreshed on every
        # rescan_once(). Lets connect() pass GphotoBackend a display name
        # (and use it to target the right driver) even though the
        # camera_id it receives is just the port address.
        self._known_gphoto_models: dict[str, str] = {}
        # Same idea as _known_gphoto_models, one dict per vendor backend,
        # keyed by that vendor's prefixed camera_id (e.g. "canon:0001").
        self._known_canon_models: dict[str, str] = {}
        self._known_nikon_models: dict[str, str] = {}
        self._known_sony_models: dict[str, str] = {}

    def connect(self, camera_id: int | str) -> None:
        """Connect to the camera at the given ID and make it active.

        An int camera_id connects via WebcamBackend. A str camera_id
        connects via whichever DSLR backend its prefix (or lack of one,
        for gphoto2) indicates -- see this class's docstring. Callers
        don't choose the backend themselves -- they pass back a camera_id
        exactly as reported by rescan_once(), and it routes itself to
        the right backend.
        """
        backend = self._create_backend(camera_id)
        try:
            backend.connect()
        except CameraError as exc:
            logger.error(
                "CameraManager failed to connect to camera %s: %s", camera_id, exc
            )
            raise
        self._active_backend = backend
        self._active_camera_id = camera_id
        logger.info("CameraManager connected to camera %s", camera_id)
        self._event_bus.publish("CAMERA_CONNECTED", {"camera_id": camera_id})

    def _create_backend(self, camera_id: int | str):
        """Instantiate the right backend class for camera_id, unconnected.

        Kept separate from connect() so the type-dispatch logic -- the
        one place backend selection happens -- is easy to find and to
        unit test independent of a real connect() call.
        """
        if isinstance(camera_id, str):
            if camera_id.startswith(_CANON_ID_PREFIX):
                from framelabs.camera.canon_backend import CanonBackend

                raw_id = camera_id[len(_CANON_ID_PREFIX) :]
                model_name = self._known_canon_models.get(camera_id, "")
                return CanonBackend(raw_id, model_name)

            if camera_id.startswith(_NIKON_ID_PREFIX):
                from framelabs.camera.nikon_backend import NikonBackend

                raw_id = camera_id[len(_NIKON_ID_PREFIX) :]
                model_name = self._known_nikon_models.get(camera_id, "")
                return NikonBackend(raw_id, model_name)

            if camera_id.startswith(_SONY_ID_PREFIX):
                from framelabs.camera.sony_backend import SonyBackend

                raw_id = camera_id[len(_SONY_ID_PREFIX) :]
                model_name = self._known_sony_models.get(camera_id, "")
                return SonyBackend(raw_id, model_name)

            try:
                from framelabs.camera.gphoto_backend import GphotoBackend
            except ImportError as exc:
                raise CameraError(
                    "DSLR support requires the optional 'gphoto2' package "
                    "(and libgphoto2). Install FrameLabs with the 'dslr' "
                    "extra to enable it."
                ) from exc
            model_name = self._known_gphoto_models.get(camera_id, "")
            return GphotoBackend(camera_id, model_name)
        return WebcamBackend(camera_id)

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

        self._capture_in_progress = True
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
        finally:
            self._capture_in_progress = False

    def set_iso(self, value: int) -> None:
        """Set the ISO value on the currently active camera.

        A genuine config write on GphotoBackend (DSLR); a no-op warning on
        WebcamBackend, per CameraInterface's contract -- CameraManager
        doesn't need to know which.

        Raises:
            CameraError: if there is no active camera.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")
        self._active_backend.set_iso(value)

    def set_shutter(self, value: str) -> None:
        """Set the shutter speed on the currently active camera.

        Raises:
            CameraError: if there is no active camera.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")
        self._active_backend.set_shutter(value)

    def set_aperture(self, value: str) -> None:
        """Set the aperture value on the currently active camera.

        Raises:
            CameraError: if there is no active camera.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")
        self._active_backend.set_aperture(value)

    def start_live_view(self) -> None:
        """Start the active camera's live preview feed.

        Raises:
            CameraError: if there is no active camera.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")
        self._active_backend.start_live_view()

    def stop_live_view(self) -> None:
        """Stop the active camera's live preview feed.

        Safe to call even with no active camera -- a no-op in that case,
        matching disconnect()'s defensive style, since stopping a preview
        that was never running (e.g. after a disconnect already cleared
        the backend) shouldn't be an error.
        """
        if self._active_backend is None:
            return
        self._active_backend.stop_live_view()

    @property
    def capture_in_progress(self) -> bool:
        """Whether a still capture is currently in flight.

        Exposed so other worker-thread consumers of the same backend (e.g.
        LiveViewController) can skip touching the camera handle while a
        capture is happening, avoiding two threads calling the backend's
        read() concurrently on the same hardware handle.
        """
        return self._capture_in_progress

    def read_preview_frame(self) -> bytes:
        """Grab a single live preview frame from the active camera.

        Raises:
            CameraError: if there is no active camera, live view hasn't
                been started, or the grab fails.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")
        return self._active_backend.read_preview_frame()

    def get_active_camera_metadata(self) -> CameraMetadata:
        """Return metadata for the currently active camera.

        Raises:
            CameraError: if there is no active camera.
        """
        if self._active_backend is None:
            raise CameraError("No active camera. Call connect() first.")
        return self._active_backend.get_metadata()

    def rescan_once(self) -> list[int | str]:
        """Check for unconnected cameras (webcam or DSLR) appearing or
        disappearing.

        Synchronous and side-effect-light by design (per Option B from
        this session's design discussion) -- CameraManager does not run
        its own background thread. Whatever needs periodic scanning
        (eventually the UI layer, via a QTimer) is responsible for
        calling this repeatedly on its own schedule.

        Skips the actual scan if a capture is currently in progress, to
        avoid any chance of contending with the active camera's driver.
        In that case, simply returns the last-known list unchanged.

        Publishes AVAILABLE_CAMERAS_CHANGED only when the available
        camera list has actually changed since the last call, so callers
        aren't spammed with an event on every poll.
        """
        if self._capture_in_progress:
            return self._known_available_cameras

        webcams = discover_webcams()
        gphoto_cameras = discover_gphoto_cameras()
        self._known_gphoto_models = {
            port_address: model_name for model_name, port_address in gphoto_cameras
        }

        # Vendor-SDK backends (Windows DSLR path). Each discover_*()
        # currently always returns [] until its backend is actually
        # implemented -- see canon_backend.py / nikon_backend.py /
        # sony_backend.py -- so this is a no-op today but wired up so
        # nothing else needs to change once they aren't stubs anymore.
        canon_cameras = discover_canon_cameras()
        self._known_canon_models = {
            f"{_CANON_ID_PREFIX}{camera_id}": model_name
            for model_name, camera_id in canon_cameras
        }
        nikon_cameras = discover_nikon_cameras()
        self._known_nikon_models = {
            f"{_NIKON_ID_PREFIX}{camera_id}": model_name
            for model_name, camera_id in nikon_cameras
        }
        sony_cameras = discover_sony_cameras()
        self._known_sony_models = {
            f"{_SONY_ID_PREFIX}{camera_id}": model_name
            for model_name, camera_id in sony_cameras
        }

        current: list[int | str] = [
            *webcams,
            *(port_address for _, port_address in gphoto_cameras),
            *self._known_canon_models.keys(),
            *self._known_nikon_models.keys(),
            *self._known_sony_models.keys(),
        ]

        if set(current) != set(self._known_available_cameras):
            self._known_available_cameras = current
            logger.info("Available cameras changed: %s", current)
            self._event_bus.publish(
                "AVAILABLE_CAMERAS_CHANGED", {"available_cameras": current}
            )
        return self._known_available_cameras

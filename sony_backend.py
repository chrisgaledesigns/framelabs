"""Sony DSLR/mirrorless backend, using Sony's Camera Remote SDK.

STATUS: SCAFFOLD ONLY. Same situation as canon_backend.py -- correct
shape, no working implementation yet. Read that file's module docstring
first; this one only calls out what's different for Sony.

Getting access to Sony's Camera Remote SDK:
Publicly downloadable (no approval/waitlist as of Canon/Nikon-style
registration) after accepting Sony's SDK license agreement, via Sony's
developer site (search "Sony Camera Remote SDK"). Of the three vendors,
this is the easiest to actually obtain -- which is why it was suggested
as the natural "build one all the way through first" candidate.

The main technical wrinkle, different from Canon's EDSDK:
Sony's Camera Remote SDK is a C++ API (class-based, e.g. an `ICrCameraObject`
interface), not a flat C API like EDSDK. That means it is NOT directly
callable from Python via plain `ctypes` the way EDSDK is -- ctypes can
call C functions, but not C++ virtual methods/classes directly. Finishing
this backend for real needs one of:
  (a) A small C wrapper DLL (write a handful of `extern "C"` functions in
      C++ that internally call the SDK's C++ classes, compile that
      wrapper to its own DLL, then ctypes-load the wrapper instead of
      the SDK directly), or
  (b) `pybind11` or `cffi` with a C++-aware build step, generating actual
      Python bindings against the SDK's headers.
(a) is usually less work for a handful of methods like this backend
needs (connect/capture/live-view/three property setters); (b) pays off
more if far more of the SDK's surface will eventually be used. Whoever
picks this up should decide based on how much Sony-specific control
FrameLabs ends up wanting long-term.

Once bindings exist (however they're built), the shape mirrors Canon:
- connect(): enumerate cameras (Sony's SDK enumerates via USB), open a
  connection to the target camera.
- capture(): send a capture command, then handle the SDK's completion
  callback/notification to know when the file is ready, then download it.
- start_live_view()/read_preview_frame(): Sony's SDK streams live view
  frames via a callback registered on the camera object; read_preview_frame()
  will need to pull the most recent frame from wherever that callback
  stashes it (e.g. a small internal buffer/queue owned by this backend),
  since CameraInterface's contract is a pull-based read_preview_frame(),
  not a push callback.
- set_iso/set_shutter/set_aperture(): Sony exposes these as device
  properties (`CrDeviceProperty`) settable through the SDK; as with
  Canon, values are Sony-defined codes, not raw numbers/strings --
  confirm the ISO/shutter/aperture code tables against a real body.

None of the above has been tested against real Sony hardware.
"""

from __future__ import annotations

import sys

from framelabs.camera.camera_interface import (
    CameraError,
    CameraInterface,
    CameraMetadata,
)
from framelabs.core.logger import get_logger

logger = get_logger(__name__)


def sony_sdk_available() -> bool:
    """Whether the Sony Camera Remote SDK (or its C wrapper) can
    plausibly be present on this system.

    Cheap platform check only, matching the other backends' contract --
    does not attempt to load any actual SDK library.
    """
    return sys.platform == "win32"


def discover_sony_cameras() -> list[tuple[str, str]]:
    """Probe for available Sony cameras via the Camera Remote SDK.

    STUB: always returns []. See this module's docstring -- Sony is the
    best candidate to implement first (SDK is freely downloadable), but
    needs a C wrapper (or pybind11/cffi bindings) before any real calls
    can be made from Python at all.
    """
    if not sony_sdk_available():
        return []
    logger.debug("Sony SDK backend is a scaffold; reporting no cameras found")
    return []


class SonyBackend(CameraInterface):
    """Camera backend for Sony cameras tethered via Camera Remote SDK.

    SCAFFOLD: conforms to CameraInterface; no method is functionally
    implemented. See this module's docstring for the C++/ctypes wrinkle
    that needs solving before implementation can start.
    """

    def __init__(self, camera_id: str, model_name: str = "") -> None:
        """
        Args:
            camera_id: Backend-specific identifier for this camera, as
                returned by discover_sony_cameras(). Exact format is
                TODO, pending the C wrapper/bindings work described in
                this module's docstring.
            model_name: Human-readable model name, for display/logging.
        """
        self._camera_id = camera_id
        self._model_name = model_name
        self._is_connected = False
        self._is_live_view_active = False

    def connect(self) -> None:
        # TODO: enumerate + open connection via the SDK's C wrapper
        # (see module docstring for why a wrapper is needed at all).
        raise CameraError(
            "Sony Camera Remote SDK backend is not yet implemented. "
            "See sony_backend.py's module docstring for what's needed "
            "to finish it, including the C++ wrapper this backend "
            "requires."
        )

    def disconnect(self) -> None:
        # TODO: release the SDK connection/camera object.
        self._is_connected = False
        logger.info("Sony backend disconnect() called (scaffold, no-op)")

    def is_connected(self) -> bool:
        return self._is_connected

    def start_live_view(self) -> None:
        self._require_connection()
        raise CameraError("Sony live view is not yet implemented.")

    def stop_live_view(self) -> None:
        self._is_live_view_active = False

    def read_preview_frame(self) -> bytes:
        self._require_connection()
        # TODO: pull the most recent frame out of wherever the SDK's
        # live-view callback stashes it -- see module docstring on the
        # push/pull mismatch this backend needs to bridge.
        raise CameraError("Sony live view preview is not yet implemented.")

    def capture(self) -> bytes:
        self._require_connection()
        raise CameraError("Sony capture is not yet implemented.")

    def set_iso(self, value: int) -> None:
        self._require_connection()
        logger.warning("Sony set_iso is not yet implemented; ignoring")

    def set_shutter(self, value: str) -> None:
        self._require_connection()
        logger.warning("Sony set_shutter is not yet implemented; ignoring")

    def set_aperture(self, value: str) -> None:
        self._require_connection()
        logger.warning("Sony set_aperture is not yet implemented; ignoring")

    def get_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id=self._camera_id,
            display_name=self._model_name or f"Sony ({self._camera_id})",
            backend_type="sony",
        )

    def _require_connection(self) -> None:
        if not self._is_connected:
            raise CameraError("Camera is not connected. Call connect() first.")

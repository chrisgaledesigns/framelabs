"""Canon DSLR/mirrorless backend, using Canon's EDSDK (EOS Digital SDK).

STATUS: SCAFFOLD ONLY. This file defines the correct shape (methods,
signatures, error handling conventions) for a Canon backend so it plugs
into CameraManager exactly like WebcamBackend and GphotoBackend do, but
the actual EDSDK calls are not wired up yet -- every method below raises
CameraError("Not yet implemented...") until someone with a Canon body
finishes and tests it. See the "Finishing this backend" section below.

Why EDSDK instead of libgphoto2:
libgphoto2 (see gphoto_backend.py) has no supported Windows build.
EDSDK is Canon's own Windows/macOS SDK for exactly this: tethered
control of EOS-series cameras (live view, capture, and reading/writing
camera settings including ISO/shutter/aperture).

Getting access to EDSDK (must be done by a human, not this scaffold):
1. Register at the Canon Developer Community / EDSDK download page.
   As of this writing that's reached via https://developercommunity.usa.canon.com/
   (registration + accepting Canon's SDK license agreement required).
2. Download the EDSDK for Windows. It ships as a set of DLLs
   (EDSDK.dll and friends) plus C header files (EDSDK.h, EDSDKTypes.h,
   EDSDKErrors.h) describing the C API.
3. EDSDK is a C API, so it's callable from Python via `ctypes` without
   needing a compiled extension -- no Visual Studio required, just the
   DLL + headers to know the function signatures and struct layouts.

Finishing this backend:
- Load the DLL with `ctypes.WinDLL("EDSDK.dll")` (Windows-only call --
  guard the import so this module doesn't explode on Linux/macOS dev
  machines; see the `_load_edsdk()` stub below).
- Call EdsInitializeSDK() once per process (and EdsTerminateSDK() at
  shutdown) -- this is process-level SDK state, not per-camera, so it
  likely belongs in main.py's startup/shutdown rather than here. Left
  as a TODO for whoever wires this up, since CameraManager currently
  has no app-lifecycle hook for it.
- connect(): EdsGetCameraList() -> EdsGetChildAtIndex() -> EdsOpenSession()
- capture(): EdsSendCommand(kEdsCameraCommand_TakePicture), then handle
  the kEdsObjectEvent_DirItemCreated callback to download the file via
  EdsDownload()/EdsDownloadComplete().
- start_live_view()/read_preview_frame(): set kEdsPropID_Evf_OutputDevice
  to enable the EVF (live view) stream, then EdsGetPointer()/
  EdsGetLength() on an EdsStreamRef via EdsDownloadEvfImage() for each
  frame.
- set_iso/set_shutter/set_aperture(): EdsSetPropertyData() with
  kEdsPropID_ISOSpeed / kEdsPropID_Tv / kEdsPropID_Av. Values are
  Canon-defined enum codes (not raw numbers/strings) -- the mapping
  from e.g. "1/125" or "f/2.8" to EDSDK's codes has to be built from
  EDSDKTypes.h and confirmed against a real body, since Canon's enum
  values are not obviously derivable from the display value alone.
- Every EDSDK call returns an EdsError code (0 = EDS_ERR_OK); wrap
  each call and raise CameraError with the code on failure, mirroring
  GphotoBackend's try/except gp.GPhoto2Error pattern.

None of the above has been tested against real Canon hardware. Treat
every detail here as "best available guidance from EDSDK's public
documentation," not as verified behavior.
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


def edsdk_available() -> bool:
    """Whether the EDSDK DLL can plausibly be loaded on this system.

    Cheap platform check only -- does NOT attempt to actually load
    EDSDK.dll or verify it's on the path. CameraManager's discovery
    helper is expected to do the real load-and-probe and treat any
    failure as "no Canon cameras available," the same way
    discover_gphoto_cameras() already does for a missing gphoto2.
    """
    return sys.platform == "win32"


def discover_canon_cameras() -> list[tuple[str, str]]:
    """Probe for available Canon cameras via EDSDK.

    Returns a list of (model_name, camera_id) tuples, matching the shape
    of discover_gphoto_cameras() in camera_manager.py.

    STUB: always returns [] until EDSDK is actually wired in (see this
    module's docstring). Not raising here is intentional -- an
    unimplemented backend should behave like "no cameras of this type
    found," exactly like a missing gphoto2 does, so CameraManager's
    rescan_once() doesn't need special-case handling per backend.
    """
    if not edsdk_available():
        return []
    logger.debug("Canon EDSDK backend is a scaffold; reporting no cameras found")
    return []


class CanonBackend(CameraInterface):
    """Camera backend for Canon EOS cameras tethered via EDSDK.

    SCAFFOLD: conforms to CameraInterface so CameraManager can dispatch
    to it exactly like any other backend, but no method is functionally
    implemented yet. Every method raises CameraError until real EDSDK
    calls replace the TODOs -- see this module's docstring for the
    concrete EDSDK functions each method needs.
    """

    def __init__(self, camera_id: str, model_name: str = "") -> None:
        """
        Args:
            camera_id: Backend-specific identifier for this camera, as
                returned by discover_canon_cameras(). Exact format is
                still TODO -- likely needs to come from whatever EDSDK
                exposes per-camera (e.g. a serial number or EdsCameraRef
                index), decided when discovery is actually implemented.
            model_name: Human-readable model name, for display/logging.
        """
        self._camera_id = camera_id
        self._model_name = model_name
        self._is_connected = False
        self._is_live_view_active = False

    def connect(self) -> None:
        # TODO: EdsGetCameraList() -> EdsGetChildAtIndex() -> EdsOpenSession()
        raise CameraError(
            "Canon EDSDK backend is not yet implemented. See "
            "canon_backend.py's module docstring for what's needed to "
            "finish it."
        )

    def disconnect(self) -> None:
        # TODO: EdsCloseSession(), EdsRelease() on the camera reference.
        self._is_connected = False
        logger.info("Canon backend disconnect() called (scaffold, no-op)")

    def is_connected(self) -> bool:
        return self._is_connected

    def start_live_view(self) -> None:
        self._require_connection()
        # TODO: set kEdsPropID_Evf_OutputDevice via EdsSetPropertyData().
        raise CameraError("Canon live view is not yet implemented.")

    def stop_live_view(self) -> None:
        self._is_live_view_active = False

    def read_preview_frame(self) -> bytes:
        self._require_connection()
        # TODO: EdsCreateMemoryStream() + EdsDownloadEvfImage(), then
        # read the JPEG bytes out via EdsGetPointer()/EdsGetLength().
        raise CameraError("Canon live view preview is not yet implemented.")

    def capture(self) -> bytes:
        self._require_connection()
        # TODO: EdsSendCommand(kEdsCameraCommand_TakePicture), handle
        # the resulting kEdsObjectEvent_DirItemCreated callback, then
        # EdsDownload()/EdsDownloadComplete() to get the file bytes.
        raise CameraError("Canon capture is not yet implemented.")

    def set_iso(self, value: int) -> None:
        self._require_connection()
        # TODO: map `value` (e.g. 400) to EDSDK's kEdsPropID_ISOSpeed
        # enum code (Canon does not use raw ISO numbers here -- the
        # mapping table lives in EDSDKTypes.h and needs confirming
        # against a real body), then EdsSetPropertyData().
        logger.warning("Canon set_iso is not yet implemented; ignoring")

    def set_shutter(self, value: str) -> None:
        self._require_connection()
        # TODO: map `value` (e.g. "1/125") to kEdsPropID_Tv's enum code.
        logger.warning("Canon set_shutter is not yet implemented; ignoring")

    def set_aperture(self, value: str) -> None:
        self._require_connection()
        # TODO: map `value` (e.g. "f/2.8") to kEdsPropID_Av's enum code.
        logger.warning("Canon set_aperture is not yet implemented; ignoring")

    def get_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id=self._camera_id,
            display_name=self._model_name or f"Canon ({self._camera_id})",
            backend_type="canon",
        )

    def _require_connection(self) -> None:
        if not self._is_connected:
            raise CameraError("Camera is not connected. Call connect() first.")

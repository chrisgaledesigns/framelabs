"""Nikon DSLR/mirrorless backend, using Nikon's SDK (MAID3 / Type09).

STATUS: SCAFFOLD ONLY. Same situation as canon_backend.py -- correct
shape, no working implementation yet. Read that file's module docstring
first; this one only calls out what's different for Nikon.

Getting access to Nikon's SDK -- the hard part:
Unlike Canon (EDSDK) and Sony (Camera Remote SDK), Nikon has
historically NOT offered simple self-service developer registration.
Access has often required contacting Nikon directly (sometimes framed
as a business/licensing inquiry rather than an open developer program),
and terms have changed over time. Concretely, before any of this
backend can be finished:
1. Someone needs to actually obtain Nikon's SDK (search "Nikon SDK
   MAID3" or check Nikon's regional developer/business-partner
   contacts -- there is no single stable public download URL to point
   to here, which is itself the main blocker).
2. Confirm what's actually granted: some historical Nikon SDK access
   only covered image transfer/PTP-level control, not full live view +
   ISO/shutter/aperture control on every body. Full parity with the
   Canon/Sony backends depends on what that access actually includes.

If Nikon's SDK genuinely cannot be obtained in reasonable time, the
fallback is Windows Image Acquisition (WIA) or plain PTP (many Nikon
bodies are PTP-compliant) for capture-only support -- no live view, no
manual ISO/shutter/aperture. That would need a different, simpler
backend than this one; flagging it here since it may end up being the
practical outcome for Nikon specifically, unlike Canon/Sony.

Once real SDK access exists, the shape mirrors Canon/Sony: a C/C++ API
(callable via ctypes if it exposes a flat C interface, or via a small
compiled wrapper if it's C++-only -- confirm which once the SDK is in
hand), with SDK init, camera enumeration/session-open, capture,
live-view streaming, and property get/set (ISO/shutter/aperture) as the
five capability groups every method below maps onto.
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


def nikon_sdk_available() -> bool:
    """Whether the Nikon SDK can plausibly be present on this system.

    Cheap platform check only, matching canon_backend.edsdk_available()'s
    contract -- does not attempt to load any actual SDK library.
    """
    return sys.platform == "win32"


def discover_nikon_cameras() -> list[tuple[str, str]]:
    """Probe for available Nikon cameras via Nikon's SDK.

    STUB: always returns [] -- see this module's docstring for why
    Nikon is the least far along of the three backends (SDK access
    itself, not just implementation, is the current blocker).
    """
    if not nikon_sdk_available():
        return []
    logger.debug("Nikon SDK backend is a scaffold; reporting no cameras found")
    return []


class NikonBackend(CameraInterface):
    """Camera backend for Nikon cameras tethered via Nikon's SDK.

    SCAFFOLD: conforms to CameraInterface; no method is functionally
    implemented. See this module's docstring -- Nikon additionally
    blocks on obtaining SDK access at all, before implementation work
    can even start.
    """

    def __init__(self, camera_id: str, model_name: str = "") -> None:
        """
        Args:
            camera_id: Backend-specific identifier for this camera, as
                returned by discover_nikon_cameras(). Exact format is
                TODO, pending real SDK access (see module docstring).
            model_name: Human-readable model name, for display/logging.
        """
        self._camera_id = camera_id
        self._model_name = model_name
        self._is_connected = False
        self._is_live_view_active = False

    def connect(self) -> None:
        # TODO: SDK init + device enumeration + session open. Exact
        # calls depend on which Nikon SDK generation access is granted
        # for -- see module docstring.
        raise CameraError(
            "Nikon SDK backend is not yet implemented. See "
            "nikon_backend.py's module docstring -- Nikon SDK access "
            "itself needs to be obtained before this can be finished."
        )

    def disconnect(self) -> None:
        # TODO: close session, release SDK handles.
        self._is_connected = False
        logger.info("Nikon backend disconnect() called (scaffold, no-op)")

    def is_connected(self) -> bool:
        return self._is_connected

    def start_live_view(self) -> None:
        self._require_connection()
        raise CameraError("Nikon live view is not yet implemented.")

    def stop_live_view(self) -> None:
        self._is_live_view_active = False

    def read_preview_frame(self) -> bytes:
        self._require_connection()
        raise CameraError("Nikon live view preview is not yet implemented.")

    def capture(self) -> bytes:
        self._require_connection()
        raise CameraError("Nikon capture is not yet implemented.")

    def set_iso(self, value: int) -> None:
        self._require_connection()
        logger.warning("Nikon set_iso is not yet implemented; ignoring")

    def set_shutter(self, value: str) -> None:
        self._require_connection()
        logger.warning("Nikon set_shutter is not yet implemented; ignoring")

    def set_aperture(self, value: str) -> None:
        self._require_connection()
        logger.warning("Nikon set_aperture is not yet implemented; ignoring")

    def get_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id=self._camera_id,
            display_name=self._model_name or f"Nikon ({self._camera_id})",
            backend_type="nikon",
        )

    def _require_connection(self) -> None:
        if not self._is_connected:
            raise CameraError("Camera is not connected. Call connect() first.")

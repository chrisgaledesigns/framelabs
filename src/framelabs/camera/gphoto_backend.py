"""DSLR/mirrorless camera backend, using libgphoto2 via python-gphoto2.

Tethers a real camera over USB. This is the backend InspectorPanel's
ISO/Shutter/Aperture fields are waiting for (see its module docstring) --
unlike WebcamBackend, those three setters are genuine config writes, not
no-ops.

Requires the optional "gphoto2" package (and the libgphoto2 system
library it wraps) to be installed. CameraManager is responsible for
importing this module lazily and turning a missing-dependency ImportError
into a friendly CameraError, so that a plain webcam-only install of
FrameLabs never needs libgphoto2 at all.
"""

from __future__ import annotations

import gphoto2 as gp

from framelabs.camera.camera_interface import (
    CameraError,
    CameraInterface,
    CameraMetadata,
)
from framelabs.core.logger import get_logger

logger = get_logger(__name__)

# Config widget names as exposed by libgphoto2's config tree. Naming
# varies a little by driver, but these three are the field names
# virtually every gphoto2-supported DSLR/mirrorless body uses for the
# settings FrameLabs cares about.
_ISO_CONFIG_NAME = "iso"
_SHUTTER_CONFIG_NAME = "shutterspeed"
_APERTURE_CONFIG_NAME = "aperture"


class GphotoBackend(CameraInterface):
    """Camera backend for DSLR/mirrorless cameras tethered via libgphoto2.

    Live view and full capture are genuinely different pipelines here
    (capture_preview() vs capture()), unlike WebcamBackend where both read
    from the same video stream -- capture_preview() returns a low-res JPEG
    the camera generates for framing, while capture() takes and downloads
    a full still.
    """

    def __init__(self, port_address: str, model_name: str = "") -> None:
        """
        Args:
            port_address: The libgphoto2 port address (e.g.
                "usb:001,004"), as returned by
                camera_manager.discover_gphoto_cameras(). This -- not the
                model name -- is what disambiguates between two connected
                cameras of the same model, so it's what's used as this
                backend's camera_id throughout CameraManager.
            model_name: The human-readable model name reported alongside
                the port address by autodetect (e.g. "Nikon DSC D850").
                Used only for display/logging; connecting does not
                require it, but supplying it lets connect() target the
                exact driver for that model rather than relying on
                gphoto2 to guess it from the port alone.
        """
        self._port_address = port_address
        self._model_name = model_name
        self._camera: gp.Camera | None = None
        self._is_live_view_active = False

    def connect(self) -> None:
        logger.info(
            "Connecting to DSLR %s at %s",
            self._model_name or "camera",
            self._port_address,
        )
        camera = gp.Camera()
        try:
            port_info_list = gp.PortInfoList()
            port_info_list.load()
            port_index = port_info_list.lookup_path(self._port_address)
            camera.set_port_info(port_info_list[port_index])

            if self._model_name:
                # Optional, but pins gphoto2 to the exact driver for this
                # model rather than letting it guess from the port alone
                # -- matters most when two different camera models are
                # tethered at once.
                abilities_list = gp.CameraAbilitiesList()
                abilities_list.load()
                abilities_index = abilities_list.lookup_model(self._model_name)
                camera.set_abilities(abilities_list[abilities_index])

            camera.init()
        except gp.GPhoto2Error as exc:
            logger.error("Failed to connect to DSLR at %s: %s", self._port_address, exc)
            raise CameraError(
                f"Could not open DSLR at {self._port_address}: {exc}"
            ) from exc

        self._camera = camera
        logger.info("DSLR connected")

    def disconnect(self) -> None:
        if self._camera is not None:
            try:
                self._camera.exit()
            except gp.GPhoto2Error as exc:
                # Mirrors WebcamBackend.disconnect()'s "never raise on the
                # way out" behavior -- a camera that's already physically
                # gone (e.g. unplugged) shouldn't block cleanup.
                logger.warning("Error while releasing DSLR handle: %s", exc)
            finally:
                self._camera = None
                logger.info("DSLR disconnected")

    def is_connected(self) -> bool:
        if self._camera is None:
            return False
        try:
            # A cheap, side-effect-free round trip to the camera. If it's
            # actually been unplugged this raises rather than returning
            # stale data, which is what lets CameraManager tell a
            # transient capture failure apart from a real disconnect.
            self._camera.get_summary()
            return True
        except gp.GPhoto2Error:
            return False

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

        try:
            camera_file = self._camera.capture_preview()
        except gp.GPhoto2Error as exc:
            logger.error("Failed to read preview frame from DSLR: %s", exc)
            raise CameraError(f"Failed to read preview frame from DSLR: {exc}") from exc

        # libgphoto2 hands preview frames back already encoded (JPEG, on
        # every driver FrameLabs targets) -- unlike WebcamBackend, which
        # has to encode a raw OpenCV frame itself, there's no encode step
        # needed here.
        return bytes(camera_file.get_data_and_size())

    def capture(self) -> bytes:
        self._require_connection()

        try:
            file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE)
            camera_file = self._camera.file_get(
                file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL
            )
        except gp.GPhoto2Error as exc:
            logger.error("Failed to capture frame from DSLR: %s", exc)
            raise CameraError(f"Failed to capture frame from DSLR: {exc}") from exc

        logger.info("Frame captured successfully")
        return bytes(camera_file.get_data_and_size())

    def set_iso(self, value: int) -> None:
        self._set_config_value(_ISO_CONFIG_NAME, str(value))

    def set_shutter(self, value: str) -> None:
        self._set_config_value(_SHUTTER_CONFIG_NAME, value)

    def set_aperture(self, value: str) -> None:
        self._set_config_value(_APERTURE_CONFIG_NAME, value)

    def get_metadata(self) -> CameraMetadata:
        return CameraMetadata(
            camera_id=self._port_address,
            display_name=self._model_name or f"DSLR ({self._port_address})",
            backend_type="gphoto",
        )

    def _set_config_value(self, config_name: str, value: str) -> None:
        self._require_connection()
        try:
            config = self._camera.get_config()
            widget = config.get_child_by_name(config_name)
            widget.set_value(value)
            self._camera.set_config(config)
        except gp.GPhoto2Error as exc:
            # Not every gphoto2-supported body exposes every one of these
            # three widgets (older/cheaper bodies especially do not).
            # Matches WebcamBackend's "never raise, just warn" contract
            # for a setting this piece of hardware can't actually honor.
            logger.warning("Could not set %s to %r: %s", config_name, value, exc)

    def _require_connection(self) -> None:
        if self._camera is None:
            raise CameraError("Camera is not connected. Call connect() first.")

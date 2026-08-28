"""Inspector panel widget — displays camera and capture settings.

Camera/Lens/Capture Format/Resolution are active fields, genuinely settable
regardless of backend. ISO/Shutter/Aperture are genuine, settable controls
too, but only once a DSLR is connected via GphotoBackend (see the "dslr"
extra and gphoto_backend.py) -- MainWindow calls
set_dslr_controls_enabled() from CameraController.camera_connected's
backend_type, and InspectorPanel itself has no idea what a "backend" is,
consistent with the rest of this widget's dumb-display design.

White Balance/Focus stay disabled: no backend (webcam or DSLR) currently
implements getters/setters for either, so they exist in the UI as a
preview of a planned feature, grayed out rather than faked or hidden.

The Camera field also doubles as the live connection-status display
("Scanning...", "{device} Connected", or blank/placeholder when nothing
is connected) — driven by CameraController via MainWindow, not by this
widget itself, since InspectorPanel should not know anything about
threads or camera hardware.

The Histogram strip at the bottom is likewise a dumb display widget --
MainWindow connects LiveViewController.histogram_ready directly to
self.histogram_widget.update_histogram(), same direct-connection pattern
already used for frame_ready -> live_view_widget.show_frame.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QWidget

from framelabs.ui.histogram_widget import HistogramWidget

# Preset values offered in the ISO/Shutter/Aperture dropdowns once a DSLR
# is connected. These cover the common range virtually every
# gphoto2-supported body supports; GphotoBackend/libgphoto2 itself is
# tolerant of a value a particular body rejects (see its
# _set_config_value's "not every body exposes every widget" comment), so
# there's no need to query the camera's own supported-value list just to
# populate this UI.
ISO_VALUES = ["100", "200", "400", "800", "1600", "3200", "6400"]
SHUTTER_VALUES = [
    "1/2000",
    "1/1000",
    "1/500",
    "1/250",
    "1/125",
    "1/60",
    "1/30",
    "1/15",
    "1/8",
    "1/4",
    "1/2",
    "1",
]
APERTURE_VALUES = ["f/1.4", "f/2", "f/2.8", "f/4", "f/5.6", "f/8", "f/11", "f/16"]

_DISABLED_TOOLTIP = "Unavailable until a DSLR is connected"


class InspectorPanel(QWidget):
    """Displays camera identity and capture settings for the active project."""

    # Emitted only from user interaction (QComboBox.activated), never from
    # a programmatic change like set_dslr_controls_enabled() repopulating
    # the combo -- so MainWindow can wire these straight through to
    # CameraController's *_change_requested signals without any risk of a
    # feedback loop.
    iso_changed = Signal(int)
    shutter_changed = Signal(str)
    aperture_changed = Signal(str)

    def __init__(self) -> None:
        """Build the Inspector's form layout."""
        super().__init__()
        self.setObjectName("inspectorPanel")

        layout = QFormLayout(self)

        self.camera_field = QLineEdit()
        self.camera_field.setReadOnly(True)
        self.camera_field.setPlaceholderText("No camera connected")
        layout.addRow("Camera", self.camera_field)

        self.lens_field = QLineEdit()
        self.lens_field.setReadOnly(True)
        self.lens_field.setPlaceholderText("N/A")
        layout.addRow("Lens", self.lens_field)

        self.iso_field = self._make_dslr_combo(ISO_VALUES)
        layout.addRow("ISO", self.iso_field)

        self.shutter_field = self._make_dslr_combo(SHUTTER_VALUES)
        layout.addRow("Shutter", self.shutter_field)

        self.aperture_field = self._make_dslr_combo(APERTURE_VALUES)
        layout.addRow("Aperture", self.aperture_field)

        self.white_balance_field = self._make_disabled_field()
        layout.addRow("White Balance", self.white_balance_field)

        self.focus_field = self._make_disabled_field()
        layout.addRow("Focus", self.focus_field)

        self.capture_format_combo = QComboBox()
        self.capture_format_combo.addItems(["PNG"])
        layout.addRow("Capture Format", self.capture_format_combo)

        self.resolution_field = QLineEdit()
        self.resolution_field.setPlaceholderText("e.g. 1920x1080")
        layout.addRow("Resolution", self.resolution_field)

        self.histogram_widget = HistogramWidget()
        layout.addRow("Histogram", self.histogram_widget)

        self.iso_field.activated.connect(self._on_iso_activated)
        self.shutter_field.activated.connect(self._on_shutter_activated)
        self.aperture_field.activated.connect(self._on_aperture_activated)

    def set_camera_status(self, text: str) -> None:
        """Update the Camera field to reflect current connection status."""
        self.camera_field.setText(text)

    def clear_camera_status(self) -> None:
        """Clear the Camera field, falling back to its placeholder text."""
        self.camera_field.clear()

    def set_dslr_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the ISO/Shutter/Aperture controls.

        Called by MainWindow whenever the active camera changes -- with
        True when CameraController.camera_connected reports a "gphoto"
        backend_type, and with False on every webcam connection,
        disconnect, or failed scan, so these controls never sit enabled
        with no real DSLR behind them.
        """
        for field in (self.iso_field, self.shutter_field, self.aperture_field):
            field.setEnabled(enabled)
            field.setToolTip("" if enabled else _DISABLED_TOOLTIP)

    def _on_iso_activated(self, _index: int) -> None:
        """Re-emit the ISO combo's user-selected value as an int."""
        self.iso_changed.emit(int(self.iso_field.currentText()))

    def _on_shutter_activated(self, _index: int) -> None:
        """Re-emit the Shutter combo's user-selected value."""
        self.shutter_changed.emit(self.shutter_field.currentText())

    def _on_aperture_activated(self, _index: int) -> None:
        """Re-emit the Aperture combo's user-selected value."""
        self.aperture_changed.emit(self.aperture_field.currentText())

    @staticmethod
    def _make_dslr_combo(values: list[str]) -> QComboBox:
        """Build a preset-values combo for a DSLR-only setting.

        Populated up front and disabled by default (no camera connected
        yet), matching the "real feature, not faked" intent of the module
        docstring: the values shown are genuine options, not placeholder
        text, but not interactive until set_dslr_controls_enabled(True)
        confirms a DSLR is actually live.
        """
        combo = QComboBox()
        combo.addItems(values)
        combo.setEnabled(False)
        combo.setToolTip(_DISABLED_TOOLTIP)
        return combo

    @staticmethod
    def _make_disabled_field() -> QLineEdit:
        """Build a disabled field for a setting no backend can report or
        control yet (White Balance / Focus).
        """
        field = QLineEdit()
        field.setEnabled(False)
        field.setPlaceholderText("Unavailable")
        return field

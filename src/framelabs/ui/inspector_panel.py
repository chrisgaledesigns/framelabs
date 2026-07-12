"""Inspector panel widget — displays camera and capture settings.

Camera/Lens/Capture Format/Resolution are active fields, genuinely settable
for the current webcam-only alpha. ISO/Shutter/Aperture/White Balance/Focus
are disabled: the webcam backend has no real getters or setters for these
(see Developer Handbook's camera rules and the hand-off's "Full exposure
metadata" decision) — they exist in the UI now because they're real,
planned features once the DSLR backend lands, but are grayed out rather
than faked or hidden.
"""

from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QWidget


class InspectorPanel(QWidget):
    """Displays camera identity and capture settings for the active project."""

    def __init__(self) -> None:
        """Build the Inspector's form layout."""
        super().__init__()

        layout = QFormLayout(self)

        self.camera_field = QLineEdit()
        self.camera_field.setReadOnly(True)
        self.camera_field.setPlaceholderText("No camera connected")
        layout.addRow("Camera", self.camera_field)

        self.lens_field = QLineEdit()
        self.lens_field.setReadOnly(True)
        self.lens_field.setPlaceholderText("N/A")
        layout.addRow("Lens", self.lens_field)

        self.iso_field = self._make_disabled_field()
        layout.addRow("ISO", self.iso_field)

        self.shutter_field = self._make_disabled_field()
        layout.addRow("Shutter", self.shutter_field)

        self.aperture_field = self._make_disabled_field()
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

    @staticmethod
    def _make_disabled_field() -> QLineEdit:
        """Build a disabled field for a setting the current backend can't
        genuinely report or control (webcam-only alpha).
        """
        field = QLineEdit()
        field.setEnabled(False)
        field.setPlaceholderText("Unavailable (webcam)")
        return field

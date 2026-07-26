"""Export dialog for FrameLabs.

Opens directly from the Export menu action -- no dropdown/submenu, per
Chris's explicit choice. Lets the user choose which of Video / Image
Sequence / GIF to export, plus per-format settings (video codec, GIF
frame rate), instead of the previous one-click "always all three"
behavior.

Nothing is checked by default (Chris's explicit choice -- force a real
decision every time). The dialog's own Export button stays disabled
until at least one format is checked, so an empty submission can't reach
ExportController at all.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from framelabs.export.export_service import ExportRequest
from framelabs.project.project import Project

# Maps this dialog's video-codec dropdown labels to the "auto"/FourCC
# value export_service.export_video() expects. Order here is the order
# shown in the dropdown, "auto" first as the recommended default.
_VIDEO_CODEC_CHOICES = (
    ("Auto (try H.264, fall back to MPEG-4)", "auto"),
    ("H.264 (avc1) — not supported on every system", "avc1"),
    ("MPEG-4 (mp4v) — always available", "mp4v"),
)


class ExportDialog(QDialog):
    """Dialog for choosing export formats and their settings.

    Call export_request() after exec() returns QDialog.Accepted (or,
    equivalently, a truthy return from exec()) to get the ExportRequest
    to hand to ExportController.
    """

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        """Build the dialog's form against the project whose fps seeds
        the GIF frame-rate field's default value."""
        super().__init__(parent)
        self.setWindowTitle("Export")
        self._project = project
        self._build_form()

    def _build_form(self) -> None:
        """Build the dialog: one checkbox per format, each format's own
        settings grouped underneath it, and an Export/Cancel button row
        with Export disabled until something is checked.
        """
        self.video_check = QCheckBox("Video (.mp4)")
        self.video_check.toggled.connect(self._update_enabled_state)

        self.codec_combo = QComboBox()
        for label, _value in _VIDEO_CODEC_CHOICES:
            self.codec_combo.addItem(label)

        video_group = QGroupBox()
        video_layout = QFormLayout(video_group)
        video_layout.addRow(self.video_check)
        video_layout.addRow("Codec:", self.codec_combo)

        self.sequence_check = QCheckBox("Image Sequence")
        self.sequence_check.toggled.connect(self._update_enabled_state)

        self.gif_check = QCheckBox("GIF")
        self.gif_check.toggled.connect(self._update_enabled_state)

        self.gif_fps_spin = QDoubleSpinBox()
        self.gif_fps_spin.setRange(1.0, 120.0)
        self.gif_fps_spin.setDecimals(2)
        self.gif_fps_spin.setValue(float(self._project.fps))

        gif_group = QGroupBox()
        gif_layout = QFormLayout(gif_group)
        gif_layout.addRow(self.gif_check)
        gif_layout.addRow("Frame Rate (FPS):", self.gif_fps_spin)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(video_group)
        layout.addWidget(self.sequence_check)
        layout.addWidget(gif_group)
        layout.addWidget(self.buttons)

        self._update_enabled_state()

    def _update_enabled_state(self) -> None:
        """Enable each format's own settings only while that format's
        own checkbox is checked, and enable Export only once at least
        one format is checked.

        Also called once up front from _build_form(), so with nothing
        checked by default, Export correctly starts disabled and every
        settings field correctly starts disabled too.
        """
        self.codec_combo.setEnabled(self.video_check.isChecked())
        self.gif_fps_spin.setEnabled(self.gif_check.isChecked())

        any_checked = (
            self.video_check.isChecked()
            or self.sequence_check.isChecked()
            or self.gif_check.isChecked()
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(any_checked)

    def export_request(self) -> ExportRequest:
        """Build the ExportRequest for whichever formats are checked and
        their current settings. Only meaningful after exec() returns
        Accepted -- at least one format is guaranteed checked at that
        point, since Export is disabled otherwise.
        """
        _, video_codec = _VIDEO_CODEC_CHOICES[self.codec_combo.currentIndex()]
        return ExportRequest(
            project=self._project,
            want_video=self.video_check.isChecked(),
            want_image_sequence=self.sequence_check.isChecked(),
            want_gif=self.gif_check.isChecked(),
            video_codec=video_codec,
            gif_fps=self.gif_fps_spin.value(),
        )

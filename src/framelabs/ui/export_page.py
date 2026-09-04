"""Export page for FrameLabs.

Replaces the old ExportDialog popup with a full page reached via the
Export button in the bottom-right corner of Playback Controls (or the
Export menu action) -- per Chris's explicit choice, exporting should feel
like a real destination in the app, with a preview of what's about to be
exported sitting right next to the format settings, not a small modal
floating over the editor.

"Open in Blender" lives here too rather than only in the Export menu,
since it is, in spirit, just another export format alongside Video/Image
Sequence/GIF -- this page is the one place all of them come together.

Holds no Project of its own beyond what's needed to render the preview
and seed field defaults -- MainWindow calls set_project() every time the
page is shown, and connects to this widget's signals to actually do
anything. Same "dumb widget, MainWindow owns behavior" split as
PlaybackControls and FrameActionBar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from framelabs.export.export_service import ExportRequest
from framelabs.project.project import Project

# Maps this page's video-codec dropdown labels to the "auto"/FourCC value
# export_service.export_video() expects. Order here is the order shown in
# the dropdown, "auto" first as the recommended default. Kept identical to
# the values the old ExportDialog used, since export_service itself is
# unchanged.
_VIDEO_CODEC_CHOICES = (
    ("Auto (try H.264, fall back to MPEG-4)", "auto"),
    ("H.264 (avc1) — not supported on every system", "avc1"),
    ("MPEG-4 (mp4v) — always available", "mp4v"),
)

# Preview box's minimum size -- large enough to actually judge framing/
# exposure, without letting an empty/placeholder state dominate the page.
_PREVIEW_MIN_WIDTH = 480
_PREVIEW_MIN_HEIGHT = 320


class ExportPage(QWidget):
    """Full-page export screen: a preview of the project's last captured
    frame on the left, format settings and export/Blender actions on the
    right, and a Back link to return to the editor.
    """

    back_requested = Signal()
    export_requested = Signal(object)  # ExportRequest
    open_in_blender_requested = Signal()

    def __init__(self) -> None:
        """Build the page. Starts against no project -- MainWindow calls
        set_project() immediately after construction and again every
        time the page is shown."""
        super().__init__()
        self.setObjectName("exportPage")
        self._project: Project | None = None
        self._build_ui()
        self.set_project(None)

    def _build_ui(self) -> None:
        """Build the page's layout: a header with Back + title, then a
        preview pane on the left and a settings/actions column on the
        right."""
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(16)

        header = QHBoxLayout()
        self.back_button = QPushButton("←  Back")
        self.back_button.setFlat(True)
        self.back_button.clicked.connect(self.back_requested)
        title_label = QLabel("EXPORT")
        title_label.setObjectName("panelTitle")
        header.addWidget(self.back_button)
        header.addStretch(1)
        header.addWidget(title_label)
        header.addStretch(1)
        # Balances the Back button's width on the other side so the
        # title reads visually centered on the header row instead of
        # drifting left.
        balance = QLabel()
        balance.setFixedWidth(self.back_button.sizeHint().width())
        header.addWidget(balance)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(24)
        body.addLayout(self._build_preview_column(), 3)
        body.addLayout(self._build_settings_column(), 2)
        root.addLayout(body, 1)

    def _build_preview_column(self) -> QVBoxLayout:
        """Build the left-hand preview pane: a box showing the last
        captured frame (export_service always renders frames in
        timeline order, so the last frame is the most representative
        single-image preview available without decoding a real video),
        plus a one-line project summary underneath it."""
        column = QVBoxLayout()
        column.setSpacing(10)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("exportPreview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(_PREVIEW_MIN_WIDTH, _PREVIEW_MIN_HEIGHT)
        self.preview_label.setFrameShape(QFrame.Shape.Box)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        column.addWidget(self.preview_label, 1)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("exportSummary")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.summary_label)

        return column

    def _build_settings_column(self) -> QVBoxLayout:
        """Build the right-hand column: one settings group per render
        format (identical fields to the old ExportDialog), then the
        Open in Blender and Export actions beneath them."""
        column = QVBoxLayout()
        column.setSpacing(14)

        self.video_check = QCheckBox("Video (.mp4)")
        self.video_check.toggled.connect(self._update_enabled_state)
        self.codec_combo = QComboBox()
        for label, _value in _VIDEO_CODEC_CHOICES:
            self.codec_combo.addItem(label)
        video_group = QGroupBox()
        video_layout = QFormLayout(video_group)
        video_layout.addRow(self.video_check)
        video_layout.addRow("Codec:", self.codec_combo)
        column.addWidget(video_group)

        self.sequence_check = QCheckBox("Image Sequence")
        self.sequence_check.toggled.connect(self._update_enabled_state)
        column.addWidget(self.sequence_check)

        self.gif_check = QCheckBox("GIF")
        self.gif_check.toggled.connect(self._update_enabled_state)
        self.gif_fps_spin = QDoubleSpinBox()
        self.gif_fps_spin.setRange(1.0, 120.0)
        self.gif_fps_spin.setDecimals(2)
        gif_group = QGroupBox()
        gif_layout = QFormLayout(gif_group)
        gif_layout.addRow(self.gif_check)
        gif_layout.addRow("Frame Rate (FPS):", self.gif_fps_spin)
        column.addWidget(gif_group)

        column.addStretch(1)

        # "Open in Blender" is visually separated from the render
        # formats above -- it isn't gated by any checkbox above it,
        # it launches Blender directly whenever clicked.
        self.blender_button = QPushButton("Open in Blender")
        self.blender_button.clicked.connect(self.open_in_blender_requested)
        column.addWidget(self.blender_button)

        self.export_button = QPushButton("Export")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self._on_export_clicked)
        column.addWidget(self.export_button)

        return column

    def _update_enabled_state(self) -> None:
        """Enable each format's own settings only while that format's
        own checkbox is checked, and enable Export only once at least
        one format is checked AND a project is open. Mirrors
        ExportDialog._update_enabled_state()'s rules exactly, just
        without a dialog button box to drive."""
        self.codec_combo.setEnabled(self.video_check.isChecked())
        self.gif_fps_spin.setEnabled(self.gif_check.isChecked())
        self.export_button.setEnabled(
            self._project is not None and self._any_format_checked()
        )

    def _any_format_checked(self) -> bool:
        return (
            self.video_check.isChecked()
            or self.sequence_check.isChecked()
            or self.gif_check.isChecked()
        )

    def set_project(self, project: Project | None) -> None:
        """Refresh the page against `project`. Called once at
        construction and again every time MainWindow switches to this
        page, so the preview/summary and the GIF fps default always
        reflect whichever project is currently open -- including a
        project switch that happened while this page wasn't visible.
        """
        self._project = project

        if project is None:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("No project open")
            self.summary_label.setText("")
            self.blender_button.setEnabled(False)
            self._update_enabled_state()
            return

        self.gif_fps_spin.setValue(float(project.fps))
        self.blender_button.setEnabled(True)
        self._refresh_preview(project)
        self._update_enabled_state()

    def _refresh_preview(self, project: Project) -> None:
        """Load the last captured frame's thumbnail into the preview
        box, using the same thumbnails/{number:06d}.jpg convention
        ProjectBrowserWidget's Frames grid reads from -- see that
        widget's _fill_frames_grid() docstring for the source of truth
        on this path."""
        thumbnail_path = (
            project.project_path / "thumbnails" / f"{project.frames[-1].number:06d}.jpg"
            if project.frames and project.project_path is not None
            else None
        )
        pixmap = (
            QPixmap(str(thumbnail_path)) if thumbnail_path is not None else QPixmap()
        )

        if pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(
                "No frames captured yet"
                if not project.frames
                else "Preview unavailable"
            )
        else:
            self.preview_label.setText("")
            self.preview_label.setPixmap(
                pixmap.scaled(
                    self.preview_label.width() or _PREVIEW_MIN_WIDTH,
                    self.preview_label.height() or _PREVIEW_MIN_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        width, height = project.resolution
        self.summary_label.setText(
            f"{project.name}  •  {len(project.frames)} frames  •  "
            f"{project.fps} fps  •  {width}\u00d7{height}"
        )

    def export_request(self) -> ExportRequest:
        """Build the ExportRequest for whichever formats are checked
        and their current settings. Only meaningful with a project
        set -- MainWindow's export_requested handler is only ever
        connected once a project is open, same guard export_button's
        own enabled state already provides."""
        _, video_codec = _VIDEO_CODEC_CHOICES[self.codec_combo.currentIndex()]
        return ExportRequest(
            project=self._project,
            want_video=self.video_check.isChecked(),
            want_image_sequence=self.sequence_check.isChecked(),
            want_gif=self.gif_check.isChecked(),
            video_codec=video_codec,
            gif_fps=self.gif_fps_spin.value(),
        )

    def _on_export_clicked(self) -> None:
        if self._project is None:
            return
        self.export_requested.emit(self.export_request())

    def set_export_in_progress(self, in_progress: bool) -> None:
        """Disable Export while a render is running, and re-enable it
        afterward -- mirrors export_render_action's old
        setEnabled(False)/(True) pattern around _on_export_render().
        Does not touch Open in Blender, which runs independently on
        its own controller/thread and re-enables itself via
        set_blender_action_in_progress()."""
        self.export_button.setEnabled(
            not in_progress and self._project is not None and self._any_format_checked()
        )

    def set_blender_action_in_progress(self, in_progress: bool) -> None:
        """Disable Open in Blender for the duration of a bridge launch,
        mirroring blender_action's old setEnabled(False)/(True)
        pattern."""
        self.blender_button.setEnabled(not in_progress and self._project is not None)

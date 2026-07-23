"""Theater View dialog -- movable/resizable frame preview for the Project
Browser.

Implements Chris's session-15 follow-up on the Project Browser panel
(backlog item #3): double-clicking a frame tile in the Frames grid opens a
large preview of that frame's real image, in a normal, movable, resizable
window (not full-screen -- Chris asked for this explicitly after the
initial full-screen version). This is deliberately
DIFFERENT from every other double-click/click path already in this app
(the Timeline strip, and the Project Browser's own Notes list), which
moves the Timeline's playhead. Per Chris's explicit choice, opening this
dialog must NOT move the playhead or change the Timeline/frame-action-bar
selection -- it's a pure, read-only preview, the same "never modifies the
project" guarantee Feature 7 (Playback) already gives its own frame
stepping.

This dialog owns its own local browsing position entirely separately from
Timeline.current_index -- arrow-key Left/Right here steps through frames
for browsing only. Closing the dialog (Escape or the Close button) leaves
the Timeline's real playhead exactly where it was before the dialog
opened, since nothing here ever touches Project/Timeline state.

Reads the frame's real, full-resolution image at
project_path/frame.file (e.g. images/000001.png) -- NOT the small
thumbnail ProjectBrowserWidget/TimelineWidget read from thumbnails/ --
since the point of a "theater view" is to see the real captured frame at
full size, scaled to fit the screen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from framelabs.project.project import Frame

# A deliberately near-black (not pure #000) backdrop, so a fully black
# source frame still reads as distinct from the surrounding dialog --
# matches LiveViewWidget's own dark letterbox background.
_BACKGROUND_STYLE = "background-color: #141414;"
_POSITION_LABEL_STYLE = "color: white; font-size: 14px;"
_PLACEHOLDER_LABEL_STYLE = "color: white;"

# Default size is generous enough to read a frame clearly on a typical
# monitor without opening full-screen; minimum keeps the position label
# and Close button usable if Chris shrinks the window a lot.
_DEFAULT_WIDTH = 1100
_DEFAULT_HEIGHT = 750
_MINIMUM_WIDTH = 400
_MINIMUM_HEIGHT = 300


class TheaterViewDialog(QDialog):
    """Movable, resizable, read-only preview of a project's frames.

    Construct with the project's full ordered frame list (Timeline.frames
    -- already sorted by frame number, the same list every raw frame
    index elsewhere in the app indexes into) plus the index to start on.
    Opening this dialog never touches Timeline, Project, or any other app
    state -- it only reads image files from disk.
    """

    def __init__(
        self,
        project_path: Path,
        frames: list[Frame],
        start_index: int,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and show `frames[start_index]` first.

        `start_index` is clamped into range (matching Timeline.go_to_index's
        own clamping convention) rather than raising, so a stale/edge-case
        index can't crash the preview.
        """
        super().__init__(parent)
        self._project_path = project_path
        self._frames = frames
        self._index = max(0, min(start_index, len(frames) - 1)) if frames else 0
        self._current_pixmap: QPixmap | None = None

        self.setWindowTitle("Theater View")
        self.setStyleSheet(_BACKGROUND_STYLE)
        # Normal, movable, resizable window -- not full-screen. QDialog is
        # resizable by default (no fixed size policy is set below), and
        # keeping the native title bar is what makes it draggable.
        self.setSizeGripEnabled(True)
        self.resize(_DEFAULT_WIDTH, _DEFAULT_HEIGHT)
        self.setMinimumSize(_MINIMUM_WIDTH, _MINIMUM_HEIGHT)

        self._build_ui()
        self._load_current_frame()

    def _build_ui(self) -> None:
        """Build the image label, frame-position label, and Close button."""
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._position_label = QLabel()
        self._position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._position_label.setStyleSheet(_POSITION_LABEL_STYLE)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(8, 8, 8, 0)
        top_bar_layout.addWidget(self._position_label, 1)
        top_bar_layout.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(top_bar)
        layout.addWidget(self._image_label, 1)

    def _load_current_frame(self) -> None:
        """Read the current frame's real image from disk and repaint.

        Falls back to a plain "No Image" label for an unreadable/missing
        file -- the same non-crashing fallback pattern
        ProjectBrowserWidget/FrameThumbnail already use for a missing
        thumbnail -- rather than a broken image or an exception.
        """
        if not self._frames:
            self._current_pixmap = None
            self._image_label.setStyleSheet(_PLACEHOLDER_LABEL_STYLE)
            self._image_label.setText("No frames to preview")
            self._position_label.setText("")
            self._rescale_current_pixmap()
            return

        frame = self._frames[self._index]
        pixmap = QPixmap(str(self._project_path / frame.file))

        if pixmap.isNull():
            self._current_pixmap = None
            self._image_label.setStyleSheet(_PLACEHOLDER_LABEL_STYLE)
            self._image_label.setText("No Image")
        else:
            self._current_pixmap = pixmap
            self._image_label.setStyleSheet("")

        self._position_label.setText(
            f"Frame {frame.number}  ({self._index + 1} of {len(self._frames)})"
        )
        self._rescale_current_pixmap()

    def _rescale_current_pixmap(self) -> None:
        """Re-scale the currently loaded pixmap to fit the image label.

        Rescales the already-loaded pixmap rather than re-reading the
        file from disk, so window resizes stay cheap. Deliberately does
        NOT call setPixmap() at all when there's no pixmap to show --
        QLabel treats pixmap/text as mutually exclusive, so even a null
        QPixmap would wipe out whatever placeholder text
        _load_current_frame() just set.
        """
        if self._current_pixmap is None:
            return
        scaled = self._current_pixmap.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def go_to_index(self, index: int) -> None:
        """Move the preview to `index` if in range; otherwise no-op.

        Public (not `_go_to`) so tests can drive navigation directly,
        matching how Timeline.go_to_index is itself tested directly.
        Deliberately does not wrap or clamp past the ends -- stepping
        past the first/last frame simply does nothing, same as
        Timeline.next_frame/previous_frame's own boundary behavior.
        """
        if not self._frames:
            return
        if 0 <= index < len(self._frames):
            self._index = index
            self._load_current_frame()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Left/Right steps through frames for browsing; Escape closes."""
        if event.key() == Qt.Key.Key_Left:
            self.go_to_index(self._index - 1)
        elif event.key() == Qt.Key.Key_Right:
            self.go_to_index(self._index + 1)
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the preview scaled to fit whenever the dialog resizes."""
        super().resizeEvent(event)
        self._rescale_current_pixmap()

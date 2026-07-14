"""Timeline and playback control widgets for the main window.

TimelineWidget is the real Feature 5 frame-thumbnail strip: it renders one
FrameThumbnail per Frame in a Timeline, supports click-to-select, and shows
marker/selection state as independent, stackable colored borders. It holds
no Timeline of its own -- MainWindow calls refresh() whenever the active
Timeline's contents or playhead change (new project, opened project,
capture succeeded), consistent with how the rest of the UI layer stays
"dumb" per the Developer Handbook.

PlaybackControls is unchanged from the Phase 5 skeleton -- still real,
wired widgets for Feature 7 (Play/Pause, Loop, speed), driven externally by
MainWindow.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from framelabs.project.project import Frame
from framelabs.timeline.playback import PLAYBACK_SPEEDS

# Comfortable thumbnail size, per Chris's explicit choice over the compact
# alternative -- fixed height, width follows each thumbnail's own aspect
# ratio so non-4:3 projects still display correctly.
THUMBNAIL_DISPLAY_HEIGHT = 100

# Border widths/colors for marker and selection state. Chris chose "colored
# border around the whole thumbnail" for both marker and selection
# separately, which means the two need to be visually distinguishable and
# able to stack (a frame can be marked AND selected at once) -- solved by
# nesting two QFrames, each owning one border, rather than trying to draw
# two colors on a single edge.
MARKER_BORDER_WIDTH = 3
MARKER_BORDER_COLOR = "#f59e0b"  # amber
SELECTION_BORDER_WIDTH = 3
SELECTION_BORDER_COLOR = "#3b82f6"  # accent blue


class FrameThumbnail(QFrame):
    """A single clickable frame thumbnail in the Timeline strip.

    Two nested frames provide the marker border (outer) and selection
    border (inner) independently, so both can render at once without
    fighting over the same edge.
    """

    clicked = Signal(int)

    def __init__(
        self,
        frame: Frame,
        thumbnails_dir: Path,
        index: int,
        selected: bool,
    ) -> None:
        """Build one thumbnail for `frame` at `index` in the timeline.

        Args:
            frame: The Frame this thumbnail represents.
            thumbnails_dir: The project's thumbnails/ folder.
            index: This frame's position in Timeline.frames -- carried on
                the `clicked` signal so MainWindow can call
                Timeline.go_to_index(index) without the widget needing to
                know anything about Timeline itself.
            selected: Whether this is the currently-selected frame.
        """
        super().__init__()
        self._index = index

        marker_width = MARKER_BORDER_WIDTH if frame.marker else 0
        self.setStyleSheet(
            f"QFrame {{ border: {marker_width}px solid {MARKER_BORDER_COLOR}; }}"
        )

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(2, 2, 2, 2)

        selection_frame = QFrame()
        selection_width = SELECTION_BORDER_WIDTH if selected else 0
        selection_frame.setStyleSheet(
            f"QFrame {{ border: {selection_width}px solid {SELECTION_BORDER_COLOR}; }}"
        )
        selection_layout = QVBoxLayout(selection_frame)
        selection_layout.setContentsMargins(2, 2, 2, 2)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail_path = thumbnails_dir / f"{frame.number:06d}.jpg"
        pixmap = QPixmap(str(thumbnail_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaledToHeight(
                THUMBNAIL_DISPLAY_HEIGHT, Qt.TransformationMode.SmoothTransformation
            )
            image_label.setPixmap(pixmap)
        else:
            # Thumbnail missing/unreadable -- show the frame number alone
            # rather than a broken image, so a missing-thumbnail frame is
            # still selectable and identifiable.
            image_label.setFixedHeight(THUMBNAIL_DISPLAY_HEIGHT)
            image_label.setText("No\nThumbnail")

        number_label = QLabel(str(frame.number))
        number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        selection_layout.addWidget(image_label)
        selection_layout.addWidget(number_label)
        outer_layout.addWidget(selection_frame)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Emit `clicked` with this thumbnail's timeline index."""
        self.clicked.emit(self._index)
        super().mousePressEvent(event)


class TimelineWidget(QScrollArea):
    """The real Feature 5 frame-thumbnail timeline strip.

    Horizontally scrollable. Holds no Timeline/Project of its own --
    MainWindow calls refresh() with the current frames, thumbnails
    folder, and playhead index whenever any of those change.
    """

    frame_selected = Signal(int)

    def __init__(self) -> None:
        """Build an empty timeline strip."""
        super().__init__()
        self.setFixedHeight(THUMBNAIL_DISPLAY_HEIGHT + 60)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._strip = QWidget()
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self._strip)

    def refresh(
        self,
        frames: list[Frame],
        thumbnails_dir: Path,
        current_index: int,
    ) -> None:
        """Rebuild the strip to match the given frames and playhead.

        Args:
            frames: Frames in sequence order (Timeline.frames).
            thumbnails_dir: The active project's thumbnails/ folder.
            current_index: The index of the currently-selected/current
                frame, per Timeline.current_index. Ignored (no frame is
                drawn selected) if out of range for an empty timeline.
        """
        while self._strip_layout.count():
            item = self._strip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, frame in enumerate(frames):
            thumbnail = FrameThumbnail(
                frame,
                thumbnails_dir,
                index,
                selected=(index == current_index),
            )
            thumbnail.clicked.connect(self.frame_selected.emit)
            self._strip_layout.addWidget(thumbnail)


class PlaybackControls(QWidget):
    """Playback control bar for Feature 7: Play/Pause, Loop, speed.

    This widget only exposes raw controls -- it holds no PlaybackSettings
    or PlaybackController of its own. MainWindow reads and writes
    self.play_button, self.loop_button, and self.speed_combo directly and
    owns all the real playback wiring, consistent with how the rest of the
    UI layer stays "dumb" per the Developer Handbook (UI calls
    services/controllers, never owns application behavior itself).
    """

    def __init__(self) -> None:
        """Build the playback controls bar."""
        super().__init__()
        self.setFixedHeight(50)
        self.setStyleSheet("border: 1px solid gray;")

        layout = QHBoxLayout(self)

        self.play_button = QPushButton("Play")
        self.loop_button = QPushButton("Loop")
        self.loop_button.setCheckable(True)

        self.speed_combo = QComboBox()
        for speed in PLAYBACK_SPEEDS:
            self.speed_combo.addItem(f"{speed}%", userData=speed)
        # PLAYBACK_SPEEDS is (25, 50, 100, 200) -- default to 100%.
        self.speed_combo.setCurrentIndex(PLAYBACK_SPEEDS.index(100))

        layout.addWidget(self.play_button)
        layout.addWidget(self.loop_button)
        layout.addWidget(self.speed_combo)
        layout.addStretch()

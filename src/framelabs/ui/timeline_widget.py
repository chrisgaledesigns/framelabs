"""Timeline and playback control widgets for the main window.

TimelineWidget is the real Feature 5 frame-thumbnail strip: it renders one
FrameThumbnail per Frame in a Timeline, supports click-to-select, and shows
marker/selection state as independent, stackable colored borders. It holds
no Timeline of its own -- MainWindow calls refresh() whenever the active
Timeline's frame list changes (new project, opened project, capture
succeeded), and calls the cheaper set_current_index() whenever only the
playhead moves (arrow keys, playback ticks, thumbnail clicks) so that
moving the playhead never rebuilds every thumbnail from disk, consistent
with the Developer Handbook's "UI Never Blocks" principle.

Also emits frame_context_menu_requested (right-click on a thumbnail), for
Feature 5's context menu -- MainWindow owns the actual QMenu and the
frame actions on it (Delete/Replace/Duplicate/Notes/Marker); this widget
only reports where and on which frame the right-click happened, same
"dumb widget, MainWindow owns behavior" split as frame_selected already
follows for left-clicks.

PlaybackControls is unchanged from the Phase 5 skeleton -- still real,
wired widgets for Feature 7 (Play/Pause, Loop, speed), driven externally by
MainWindow.

FrameActionBar is the "selection action bar" referenced as not-yet-built
in main_window.py's _create_actions() (Duplicate Frame's temporary
Edit-menu home) and in capture/commands.py's module docstring
(DeleteFrameCommand/ReplaceFrameCommand deferred until this UI exists).
It exposes Delete/Replace/Duplicate/Marker/Notes controls for whichever
frame is currently selected, following the exact same "dumb widget,
MainWindow owns behavior" split as PlaybackControls above.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

# Backlog item #1: click-and-drag scrolling on the timeline strip,
# iPad-style. A press that never moves more than this many pixels (global,
# horizontal-only -- vertical wobble shouldn't cancel a click) is still a
# plain click-to-select; only once it crosses this threshold does it turn
# into a drag-to-scroll gesture. Small and fixed rather than
# QApplication.startDragDistance(), since that constant is tuned for
# drag-and-drop initiation, not click-vs-scroll disambiguation, and this
# needs to feel immediate on a strip that's clicked constantly.
DRAG_THRESHOLD_PX = 6


class FrameThumbnail(QFrame):
    """A single clickable frame thumbnail in the Timeline strip.

    Two nested frames provide the marker border (outer) and selection
    border (inner) independently, so both can render at once without
    fighting over the same edge.
    """

    clicked = Signal(int)
    context_menu_requested = Signal(int, QPoint)
    drag_scrolled = Signal(int)

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
        # Drag-vs-click state (backlog item #1). None means no press is in
        # progress. Tracked in global screen coordinates so the delta is
        # correct even as the mouse crosses from one thumbnail onto the
        # next mid-drag.
        self._press_global_x: float | None = None
        self._last_global_x: float | None = None
        self._dragging = False

        marker_width = MARKER_BORDER_WIDTH if frame.marker else 0
        self.setStyleSheet(
            f"QFrame {{ border: {marker_width}px solid {MARKER_BORDER_COLOR}; }}"
        )

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(2, 2, 2, 2)

        self._selection_frame = QFrame()
        selection_width = SELECTION_BORDER_WIDTH if selected else 0
        self._selection_frame.setStyleSheet(
            f"QFrame {{ border: {selection_width}px solid {SELECTION_BORDER_COLOR}; }}"
        )
        selection_layout = QVBoxLayout(self._selection_frame)
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
        outer_layout.addWidget(self._selection_frame)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Begin tracking a possible click or drag-to-scroll gesture.

        `clicked` is no longer emitted here -- it's decided on release,
        once we know whether the gesture stayed within DRAG_THRESHOLD_PX
        (a click) or moved past it (a drag-to-scroll, backlog item #1).
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global_x = event.globalPosition().x()
            self._last_global_x = self._press_global_x
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Turn a held left-button drag into iPad-style scroll deltas.

        Emits `drag_scrolled` with the horizontal pixel delta since the
        last move event once the total displacement from the press point
        exceeds DRAG_THRESHOLD_PX -- TimelineWidget applies these deltas to
        its horizontal scrollbar. Before that threshold, this is still
        just a click in progress and nothing is emitted, so a tiny
        press-time wobble can't turn an intended click into a scroll.
        """
        if (
            self._press_global_x is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            current_x = event.globalPosition().x()
            if (
                not self._dragging
                and abs(current_x - self._press_global_x) > DRAG_THRESHOLD_PX
            ):
                self._dragging = True
            if self._dragging:
                self.drag_scrolled.emit(int(current_x - self._last_global_x))
            self._last_global_x = current_x
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Emit `clicked` only if this gesture ended as a click, not a drag."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._press_global_x is not None and not self._dragging:
                self.clicked.emit(self._index)
            self._press_global_x = None
            self._last_global_x = None
            self._dragging = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Emit `context_menu_requested` with this thumbnail's index and
        the event's global position, per Feature 5's right-click menu.

        The global position is included (rather than just the index) so
        the QMenu that MainWindow builds in response can be shown exactly
        where the user right-clicked, the same way any native context
        menu behaves.
        """
        self.context_menu_requested.emit(self._index, event.globalPos())
        super().contextMenuEvent(event)

    def set_selected(self, selected: bool) -> None:
        """Toggle the selection border without rebuilding the thumbnail.

        Used by TimelineWidget.set_current_index() so that a playhead-only
        move (arrow keys, playback ticks, a thumbnail click) never tears
        down and recreates thumbnails or re-reads any image off disk --
        only the border style changes.
        """
        width = SELECTION_BORDER_WIDTH if selected else 0
        self._selection_frame.setStyleSheet(
            f"QFrame {{ border: {width}px solid {SELECTION_BORDER_COLOR}; }}"
        )


class TimelineWidget(QScrollArea):
    """The real Feature 5 frame-thumbnail timeline strip.

    Horizontally scrollable. Holds no Timeline/Project of its own --
    MainWindow calls refresh() with the current frames, thumbnails
    folder, and playhead index whenever the frame list itself changes, and
    calls set_current_index() whenever only the playhead moves.
    """

    frame_selected = Signal(int)
    frame_context_menu_requested = Signal(int, QPoint)

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

        Tears down and recreates every thumbnail, including a disk read
        and QPixmap scale per frame -- only call this when the frame list
        itself has changed (new project, opened project, capture
        succeeded). For a playhead-only move, call set_current_index()
        instead, which is much cheaper and does no disk I/O.

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
            thumbnail.context_menu_requested.connect(
                self.frame_context_menu_requested.emit
            )
            thumbnail.drag_scrolled.connect(self._on_drag_scrolled)
            self._strip_layout.addWidget(thumbnail)

    def set_current_index(self, current_index: int) -> None:
        """Move the selection border to match a playhead-only change.

        Cheap alternative to refresh() for arrow-key steps, playback
        ticks, and thumbnail clicks -- none of these change the frame
        list, only which thumbnail is selected, so no thumbnail needs to
        be recreated or re-read from disk. Per the Developer Handbook's
        "UI Never Blocks" principle, this matters most during playback,
        where the playhead can move many times per second.
        """
        for thumbnail in self._strip.findChildren(FrameThumbnail):
            thumbnail.set_selected(thumbnail._index == current_index)

    def _on_drag_scrolled(self, delta_x: int) -> None:
        """Scroll the strip by `delta_x` screen pixels (backlog item #1).

        Connected to every FrameThumbnail's drag_scrolled signal in
        refresh(). Uses the "content follows the finger" convention
        (dragging right reveals frames to the left, i.e. the scrollbar
        value goes down) to match iPad/touch-scroll behavior rather than
        a traditional scrollbar-handle drag, which would move the other
        way.
        """
        scrollbar = self.horizontalScrollBar()
        scrollbar.setValue(scrollbar.value() - delta_x)


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


class FrameActionBar(QWidget):
    """Fixed action bar for Feature 5's remaining per-frame actions.

    A single, non-scrolling row of controls -- Delete, Replace, Duplicate,
    Marker, and Notes -- that always acts on whichever frame is currently
    selected, regardless of how long the Timeline strip above it is. This
    is the "selection action bar" referenced as not-yet-built in
    main_window.py's _create_actions() (Duplicate Frame's temporary
    Edit-menu home) and in capture/commands.py's module docstring
    (DeleteFrameCommand/ReplaceFrameCommand deferred until it exists).

    Holds no Project/Timeline/Frame of its own -- MainWindow calls
    set_current_frame() whenever the selected frame changes (thumbnail
    click, arrow keys, capture, undo/redo, delete) and reads/writes
    self.delete_button, self.replace_button, self.duplicate_button,
    self.marker_button, and self.notes_edit directly, owning all actual
    command execution. Same "dumb widget, MainWindow owns behavior" split
    PlaybackControls and TimelineWidget already follow.
    """

    def __init__(self) -> None:
        """Build the bar, disabled until a frame is selected."""
        super().__init__()
        self.setFixedHeight(50)
        self.setStyleSheet("border: 1px solid gray;")

        layout = QHBoxLayout(self)

        self.delete_button = QPushButton("Delete")
        self.replace_button = QPushButton("Replace")
        self.duplicate_button = QPushButton("Duplicate")

        self.marker_button = QPushButton("Marker")
        self.marker_button.setCheckable(True)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Notes...")

        layout.addWidget(self.delete_button)
        layout.addWidget(self.replace_button)
        layout.addWidget(self.duplicate_button)
        layout.addWidget(self.marker_button)
        layout.addWidget(self.notes_edit, 1)

        # Grouped only so __init__ and set_current_frame() can enable/
        # disable all four buttons in one loop -- notes_edit is handled
        # separately since it isn't a QPushButton.
        self._buttons = (
            self.delete_button,
            self.replace_button,
            self.duplicate_button,
            self.marker_button,
        )
        self.set_current_frame(None)

    def set_current_frame(self, frame: Frame | None) -> None:
        """Reflect `frame` as the bar's current frame.

        Args:
            frame: The newly selected frame, or None if no project is
                open or the timeline is empty -- every control is
                disabled and cleared in that case, since there is
                nothing left for Delete/Replace/Duplicate/Marker/Notes
                to act on.

        Uses setText()/setChecked() rather than any signal-emitting call,
        so refreshing the bar to match a new selection never itself
        fires notes_edit.editingFinished or marker_button.clicked back
        out to MainWindow -- only real user interaction with these
        widgets does that, the same guarantee FrameThumbnail.set_selected
        already gives set_current_index() one layer up.
        """
        has_frame = frame is not None
        for button in self._buttons:
            button.setEnabled(has_frame)
        self.notes_edit.setEnabled(has_frame)

        self.notes_edit.setText(frame.notes if frame is not None else "")
        self.marker_button.setChecked(frame.marker if frame is not None else False)

    def set_bar_visible(self, visible: bool) -> None:
        """Show or hide the bar's own controls, without changing its fixed
        50px slot in MainWindow's central layout.

        MainWindow's central layout gives this widget's setFixedHeight(50)
        row a permanent slot directly above the splitter (Live View
        included); toggling QWidget.setVisible() on the whole bar removes/
        reinserts that slot, which visibly shifted Live View's size every
        time the bar appeared or disappeared -- confirmed in practice by
        Chris, see hand-off. Hiding only the border and the individual
        child controls instead, while the outer widget's fixed height
        never changes, keeps that 50px slot permanently reserved, so
        nothing above it ever moves.
        """
        self.setStyleSheet("border: 1px solid gray;" if visible else "")
        for button in self._buttons:
            button.setVisible(visible)
        self.notes_edit.setVisible(visible)

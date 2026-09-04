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

import bisect
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
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
SELECTION_BORDER_COLOR = "#00bc90"  # accent teal-green, matches theme.ACCENT

# Backlog item #2: Shift/Ctrl+click multi-select plus drag-to-reorder the
# selection. Multi-select gets its own visual treatment (a translucent
# fill on the outer QFrame) deliberately distinct from SELECTION_BORDER_
# COLOR above, which continues to mark only Timeline.current_index -- a
# frame is very often both at once (the playhead frame is usually part of
# whatever the user just shift-selected), so the two need to be able to
# stack without being confused for each other.
MULTI_SELECT_BACKGROUND = "rgba(0, 188, 144, 45)"
DROP_INDICATOR_WIDTH = 3
DROP_INDICATOR_COLOR = SELECTION_BORDER_COLOR

# Backlog item #1: click-and-drag scrolling on the timeline strip,
# iPad-style. A press that never moves more than this many pixels (global,
# horizontal-only -- vertical wobble shouldn't cancel a click) is still a
# plain click-to-select; only once it crosses this threshold does it turn
# into a drag-to-scroll gesture. Small and fixed rather than
# QApplication.startDragDistance(), since that constant is tuned for
# drag-and-drop initiation, not click-vs-scroll disambiguation, and this
# needs to feel immediate on a strip that's clicked constantly.
DRAG_THRESHOLD_PX = 6

# Reorder-vs-scroll disambiguation (backlog item #2 follow-up, superseding
# the earlier long-press-to-arm approach). A plain press on a thumbnail
# selects it immediately -- not deferred to release -- specifically so a
# single continuous press-and-drag on that same thumbnail can be recognized
# as a reorder-drag (see FrameThumbnail.mousePressEvent/mouseMoveEvent)
# without a separate prior click or a hold-still delay. The one exception is
# a press that lands on a thumbnail already part of a 2+-frame multi-
# selection: that stays deferred to release exactly as before, so pressing
# any one member of an existing multi-selection and dragging moves the
# whole group instead of collapsing it down to just the one pressed.

# Reorder-drag "picked-up card" ghost (backlog item #2 polish). The floating
# clone renders smaller than the thumbnail it's copying (half size, so it
# reads as a compact "card" rather than a full duplicate) and tilted a few
# degrees, echoing a solitaire card lifted off the table into your hand
# rather than a flat duplicate sliding around on top of the strip.
GHOST_SCALE = 0.54
GHOST_TILT_DEGREES = -5
GHOST_MAX_OPACITY = 0.92
GHOST_FADE_IN_MS = 90
GHOST_FADE_OUT_MS = 140
# Teal outline around the floating ghost so the lifted card reads clearly
# against whatever's underneath it -- same accent teal used for
# SELECTION_BORDER_COLOR above.
GHOST_BORDER_WIDTH = 3
GHOST_BORDER_COLOR = SELECTION_BORDER_COLOR
# Cursor lands near the ghost's top-left corner rather than its center --
# the same "pinched near the edge, card hangs below/right of your fingers"
# grip you'd use to actually lift a playing card.
GHOST_CURSOR_OFFSET = QPoint(-14, -18)
# Dim the source thumbnail(s) while their ghost is airborne, standing in for
# the empty slot a lifted card leaves behind on the table.
LIFTED_SOURCE_OPACITY = 0.35


class _DragGhost(QLabel):
    """Floating thumbnail clone that hovers with the cursor mid reorder-
    drag, picked-up-like-a-solitaire-card (backlog item #2 polish).

    A frameless, always-on-top top-level widget rather than a child of
    the strip or the scroll area's viewport, so it can float freely over
    the whole window -- including past TimelineWidget's own edges --
    without being clipped. Purely decorative: TimelineWidget still owns
    every bit of real reorder-drag state (selection, drop position); this
    widget only ever mirrors the cursor position it's given.
    """

    def __init__(self, pixmap: QPixmap, extra_count: int) -> None:
        """Build the ghost from `pixmap` (the dragged thumbnail's own
        image), tagged with a "+N" badge if `extra_count` other frames
        are riding along in the same reorder-drag.
        """
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        lifted = pixmap.scaled(
            int(pixmap.width() * GHOST_SCALE),
            int(pixmap.height() * GHOST_SCALE),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        lifted = lifted.transformed(
            QTransform().rotate(GHOST_TILT_DEGREES),
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(lifted)
        # Border is drawn outside the pixmap (via stylesheet) rather than
        # painted into it, so it stays a crisp, un-rotated rectangle around
        # the tilted image rather than getting tilted along with it.
        self.setStyleSheet(
            f"border: {GHOST_BORDER_WIDTH}px solid {GHOST_BORDER_COLOR}; "
            "background: transparent;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.resize(
            lifted.width() + 2 * GHOST_BORDER_WIDTH,
            lifted.height() + 2 * GHOST_BORDER_WIDTH,
        )

        # The shadow lives on this widget (a drop shadow), so the fade
        # in/out below has to animate windowOpacity rather than a second
        # QGraphicsOpacityEffect -- a QWidget can only carry one graphics
        # effect at a time.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(shadow)

        if extra_count > 0:
            badge = QLabel(f"+{extra_count}", self)
            badge.setStyleSheet(
                "background-color: #00bc90; color: white; border-radius: 9px; "
                "font-weight: bold; font-size: 11px; padding: 1px 6px;"
            )
            badge.adjustSize()
            badge.move(self.width() - badge.width() - 2, 2)

        self.setWindowOpacity(0.0)
        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(GHOST_FADE_IN_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(GHOST_MAX_OPACITY)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

    def lift_at(self, global_pos: QPoint) -> None:
        """Show the ghost at `global_pos` (the initial grab point) and
        fade it in -- called once, when a reorder-drag first crosses the
        drag threshold.
        """
        self.move(global_pos + GHOST_CURSOR_OFFSET)
        self.show()
        self._fade_in.start()

    def follow(self, global_pos: QPoint) -> None:
        """Reposition the ghost to track the cursor at `global_pos`,
        called on every subsequent mouse-move of the drag.
        """
        self.move(global_pos + GHOST_CURSOR_OFFSET)

    def drop(self) -> None:
        """Fade the ghost out and delete it once the drag ends (drop or
        an aborted release), matching a lifted card settling back down.
        """
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(GHOST_FADE_OUT_MS)
        fade_out.setStartValue(self.windowOpacity())
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        fade_out.finished.connect(self.deleteLater)
        # Parented to self so it isn't garbage-collected before it runs,
        # and torn down alongside the ghost itself.
        self._fade_out = fade_out
        fade_out.start()


class FrameThumbnail(QFrame):
    """A single clickable frame thumbnail in the Timeline strip.

    Two nested frames provide the marker border (outer) and selection
    border (inner) independently, so both can render at once without
    fighting over the same edge.
    """

    clicked = Signal(int, int)
    context_menu_requested = Signal(int, QPoint)
    drag_scrolled = Signal(int)
    # (dragged_index, global_x, global_y) -- both axes, so the pick-up
    # ghost (backlog item #2 polish) can follow the cursor freely instead
    # of sliding along a single horizontal line.
    reorder_dragged = Signal(int, int, int)
    reorder_dropped = Signal(int)

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
        # Backlog item #2: whether a press-and-drag on THIS thumbnail
        # should be interpreted as dragging the current Timeline selection
        # to a new position, rather than the existing drag-to-scroll
        # gesture above. Set by TimelineWidget via set_drag_eligible()
        # whenever its selection changes -- true exactly when this
        # thumbnail is part of that selection. Never touched by anything
        # this widget does on its own.
        self._drag_eligible = False
        self._reordering = False
        # Whether this press already resolved its selection immediately
        # (see mousePressEvent) -- if so, mouseReleaseEvent must not also
        # emit `clicked` for the same press, which would needlessly
        # re-run the same selection update a second time.
        self._press_resolved = False

        self._marker = frame.marker
        self._multi_selected = False
        self._apply_outer_style()

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
        # Kept even after scaledToHeight() below overwrites the local
        # `pixmap` name, so the reorder-drag ghost (backlog item #2
        # polish) has a real image to clone -- None for a missing/
        # unreadable thumbnail, in which case the ghost falls back to a
        # plain rectangle rather than trying to render a broken image.
        self._thumbnail_pixmap: QPixmap | None = None
        if not pixmap.isNull():
            pixmap = pixmap.scaledToHeight(
                THUMBNAIL_DISPLAY_HEIGHT, Qt.TransformationMode.SmoothTransformation
            )
            image_label.setPixmap(pixmap)
            self._thumbnail_pixmap = pixmap
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
        """Begin tracking a possible click or drag-to-scroll gesture, and
        -- for a plain press that isn't part of an existing multi-
        selection -- resolve selection immediately (backlog item #2
        follow-up) rather than waiting for release.

        Resolving on press (instead of deferring to release, the
        original backlog item #1 behavior) is what lets a single
        continuous press-and-drag reorder a not-yet-selected thumbnail:
        selecting it here makes it drag-eligible before mouseMoveEvent's
        threshold check ever runs, so that same gesture's first move past
        DRAG_THRESHOLD_PX already reads as a reorder-drag rather than a
        scroll.

        Deliberately skipped for two cases, both left to resolve on
        release exactly as before:
        - A press with Shift/Ctrl/Cmd held -- these are range-select/
          toggle actions, not reorder attempts, and resolving them
          immediately would fire the modifier logic before the user's
          gesture is actually known to be a plain click.
        - A press on a thumbnail that's already part of a 2+-frame
          multi-selection (`_multi_selected`) -- collapsing that
          selection down to just this thumbnail here, before a drag can
          start, would make it impossible to press-and-drag any one
          member of a multi-selection to move the whole group.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global_x = event.globalPosition().x()
            self._last_global_x = self._press_global_x
            self._dragging = False
            self._reordering = False
            modifiers = event.modifiers()
            has_selection_modifier = bool(
                modifiers
                & (
                    Qt.KeyboardModifier.ShiftModifier
                    | Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            )
            self._press_resolved = (
                not has_selection_modifier and not self._multi_selected
            )
            if self._press_resolved:
                self.clicked.emit(self._index, int(modifiers.value))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Turn a held left-button drag into iPad-style scroll deltas.

        Emits `drag_scrolled` with the horizontal pixel delta since the
        last move event once the total displacement from the press point
        exceeds DRAG_THRESHOLD_PX -- TimelineWidget applies these deltas to
        its horizontal scrollbar. Before that threshold, this is still
        just a click in progress and nothing is emitted, so a tiny
        press-time wobble can't turn an intended click into a scroll.

        Backlog item #2: if this thumbnail is part of the current
        selection (`_drag_eligible`) -- which, per mousePressEvent above,
        is now already true for a freshly-selected single thumbnail by
        the time this runs -- crossing the threshold instead starts a
        reorder-drag -- `reorder_dragged` fires with this thumbnail's
        index and the current global position, and TimelineWidget (which
        alone knows every thumbnail's on-screen geometry) turns that into
        a drop-position indicator. Only a press deferred to release (an
        existing multi-selection member, or a modifier-click) can still
        fall through to the original drag-to-scroll gesture.
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
                self._reordering = self._drag_eligible
            if self._dragging:
                if self._reordering:
                    current_y = event.globalPosition().y()
                    self.reorder_dragged.emit(
                        self._index, int(current_x), int(current_y)
                    )
                else:
                    self.drag_scrolled.emit(int(current_x - self._last_global_x))
            self._last_global_x = current_x
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Emit `clicked` if this gesture ended as an unresolved click, or
        `reorder_dropped` if it ended a reorder-drag (backlog item #2).

        `clicked` now carries the release event's keyboard modifiers
        alongside the index, so TimelineWidget can tell a plain click from
        a Shift/Ctrl+click without needing its own event handling.

        Skipped if `_press_resolved` -- mousePressEvent already emitted
        `clicked` for this same press, and doing so again here would just
        needlessly re-run the same selection update.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            if (
                self._press_global_x is not None
                and not self._dragging
                and not self._press_resolved
            ):
                self.clicked.emit(self._index, int(event.modifiers().value))
            elif self._reordering:
                self.reorder_dropped.emit(self._index)
            self._press_global_x = None
            self._last_global_x = None
            self._dragging = False
            self._reordering = False
            self._press_resolved = False
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

    def _apply_outer_style(self) -> None:
        """Re-render this thumbnail's outer QFrame from marker + multi-
        select state together.

        QFrame.setStyleSheet() replaces rather than merges with whatever
        was set before -- the marker border and the multi-select
        background both live on this same outer frame (see class
        docstring), so both have to be reapplied together any time either
        one changes, or setting one would silently wipe out the other.
        """
        marker_width = MARKER_BORDER_WIDTH if self._marker else 0
        background = (
            f"background-color: {MULTI_SELECT_BACKGROUND};"
            if self._multi_selected
            else ""
        )
        self.setStyleSheet(
            f"QFrame {{ border: {marker_width}px solid {MARKER_BORDER_COLOR}; "
            f"{background} }}"
        )

    def set_multi_selected(self, multi_selected: bool) -> None:
        """Toggle the translucent multi-select highlight (backlog item #2).

        Independent of set_selected()'s teal border, which continues to
        mark only Timeline.current_index -- see MULTI_SELECT_BACKGROUND's
        module-level comment for why the two need separate treatments.
        """
        self._multi_selected = multi_selected
        self._apply_outer_style()

    def set_lifted(self, lifted: bool) -> None:
        """Dim this thumbnail while its ghost is airborne mid reorder-
        drag (backlog item #2 polish), standing in for the empty slot a
        lifted solitaire card leaves behind on the table.

        Uses a QGraphicsOpacityEffect rather than a stylesheet, since Qt
        stylesheets have no opacity property -- cleared (set back to
        None) rather than left at full opacity when `lifted` is False, so
        this thumbnail doesn't carry a needless effect object once the
        drag ends.
        """
        if lifted:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(LIFTED_SOURCE_OPACITY)
            self.setGraphicsEffect(effect)
        else:
            self.setGraphicsEffect(None)

    def set_drag_eligible(self, eligible: bool) -> None:
        """Mark whether a press-and-drag on this thumbnail should reorder
        the current Timeline selection (backlog item #2) rather than
        scroll the strip.

        Called by TimelineWidget whenever its selection changes, mirroring
        set_selected()/set_multi_selected() -- true exactly when this
        thumbnail is part of that selection. Never fired by any real
        interaction with this widget itself.
        """
        self._drag_eligible = eligible


class TimelineWidget(QScrollArea):
    """The real Feature 5 frame-thumbnail timeline strip.

    Horizontally scrollable. Holds no Timeline/Project of its own --
    MainWindow calls refresh() with the current frames, thumbnails
    folder, and playhead index whenever the frame list itself changes, and
    calls set_current_index() whenever only the playhead moves.
    """

    frame_selected = Signal(int)
    frame_context_menu_requested = Signal(int, QPoint)
    # Backlog item #2. Emitted on drop with (frame_numbers, insert_before):
    # frame_numbers is the dragged selection's frame numbers in their
    # original relative order; insert_before is the frame number the
    # selection should land immediately before, or None for "move to the
    # end". MainWindow resolves this into a real ReorderFramesCommand --
    # this widget only knows on-screen geometry, never Timeline/Project.
    frames_reorder_requested = Signal(list, object)

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

        # Backlog item #2 state. `_frames` mirrors whatever refresh() was
        # last given, so click/drag handlers can turn an index back into a
        # real Frame's number without this widget ever holding a Timeline.
        self._frames: list[Frame] = []
        self._selected_indices: set[int] = set()
        self._selection_anchor: int | None = None
        self._pending_drop_before_number: int | None = None
        # Cache of non-selected thumbnails' (index, left_x) and a parallel
        # center_x list, populated lazily by the first _on_reorder_dragged()
        # call of a drag gesture and reset to None on drop/refresh -- see
        # that method's docstring for why recomputing this every mouse-move
        # (the original implementation) was the actual source of drag lag.
        self._reorder_candidates: list[tuple[int, int]] | None = None
        self._reorder_candidate_centers: list[int] = []

        # Floating child of _strip (not part of _strip_layout), positioned
        # with raw setGeometry() calls during a reorder-drag rather than
        # inserted into the layout -- an absolute-position overlay avoids
        # relayouting every thumbnail on each mouse-move, and thumbnail
        # geometry stays valid throughout since nothing in the layout
        # actually moves until the drop.
        self._drop_indicator = QFrame(self._strip)
        self._drop_indicator.setFixedWidth(DROP_INDICATOR_WIDTH)
        self._drop_indicator.setStyleSheet(f"background-color: {DROP_INDICATOR_COLOR};")
        self._drop_indicator.hide()

        # The reorder-drag "picked-up card" ghost (backlog item #2
        # polish) -- a top-level _DragGhost, created on the first move
        # past the drag threshold and torn down on drop. None whenever no
        # reorder-drag is in progress.
        self._ghost: _DragGhost | None = None

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

        # A structural rebuild invalidates any in-progress multi-select --
        # the indices it was tracking may no longer refer to the same
        # frames once the strip is torn down and recreated. Also hide the
        # drop indicator in case a refresh() lands mid-drag.
        self._frames = list(frames)
        self._selected_indices = set()
        self._selection_anchor = None
        self._pending_drop_before_number = None
        self._reorder_candidates = None
        self._reorder_candidate_centers = []
        self._drop_indicator.hide()
        # A structural rebuild mid-drag would otherwise leak a floating
        # top-level ghost widget with nothing left to clean it up.
        if self._ghost is not None:
            self._ghost.drop()
            self._ghost = None

        for index, frame in enumerate(frames):
            thumbnail = FrameThumbnail(
                frame,
                thumbnails_dir,
                index,
                selected=(index == current_index),
            )
            thumbnail.clicked.connect(self._on_thumbnail_clicked)
            thumbnail.context_menu_requested.connect(
                self.frame_context_menu_requested.emit
            )
            thumbnail.drag_scrolled.connect(self._on_drag_scrolled)
            thumbnail.reorder_dragged.connect(self._on_reorder_dragged)
            thumbnail.reorder_dropped.connect(self._on_reorder_dropped)
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

    def _on_thumbnail_clicked(self, index: int, modifiers_int: int) -> None:
        """Update multi-select state (backlog item #2) and forward the
        click as a normal playhead move, same as every click always has.

        Shift+click extends/replaces the selection with the contiguous
        range from the last click (`_selection_anchor`) to `index`, the
        standard file-manager convention. Ctrl/Cmd+click toggles just
        `index` in or out of the selection independently. A plain click
        collapses the selection down to `index` alone. In every case,
        `frame_selected` still fires with `index` -- multi-select is a
        purely additive highlight layered on top of the existing
        single-playhead behavior, never a replacement for it.
        """
        modifiers = Qt.KeyboardModifier(modifiers_int)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and (
            self._selection_anchor is not None
        ):
            lo, hi = sorted((self._selection_anchor, index))
            self._selected_indices = set(range(lo, hi + 1))
        elif modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            if index in self._selected_indices:
                self._selected_indices.discard(index)
            else:
                self._selected_indices.add(index)
            self._selection_anchor = index
        else:
            self._selected_indices = {index}
            self._selection_anchor = index

        self._apply_selection_highlight()
        self.frame_selected.emit(index)

    def _apply_selection_highlight(self) -> None:
        """Sync every live thumbnail's multi-select highlight and drag-
        eligibility to `_selected_indices` (backlog item #2).

        The highlight itself only shows once 2+ frames are selected -- a
        single selected frame already has Timeline.current_index's own
        teal border, so painting the same frame's translucent background
        too would just be visual noise for the single-selection case that
        already looked right before this feature existed. Drag-eligibility
        has no such threshold: even a single selected frame should be
        draggable to reorder it.
        """
        show_multi = len(self._selected_indices) > 1
        for thumbnail in self._strip.findChildren(FrameThumbnail):
            is_selected = thumbnail._index in self._selected_indices
            thumbnail.set_drag_eligible(is_selected)
            thumbnail.set_multi_selected(show_multi and is_selected)

    def _on_reorder_dragged(
        self, dragged_index: int, global_x: int, global_y: int
    ) -> None:
        """Move the drop-position indicator, and the floating pick-up
        ghost, to match an in-progress reorder-drag (backlog item #2).

        Finds the first non-selected thumbnail whose horizontal center is
        past the drag position and places the indicator at its left edge
        (i.e. "drop before this frame"); if none qualifies, the indicator
        goes at the strip's right edge ("drop at the end"). Only
        non-selected thumbnails are considered, since the frames actually
        being dragged aren't valid drop targets for themselves.

        Also lazily spawns _ghost on the first call of a given drag (this
        is the earliest point a reorder-drag is confirmed in progress)
        and repositions it on every subsequent call, so the little
        thumbnail clone tracks the cursor for the whole gesture.

        This fires on every pixel of mouse movement for the whole drag,
        so it deliberately avoids any per-move Qt widget-tree walk:
        `_strip.findChildren(FrameThumbnail)` is a full traversal, and
        calling it (plus sorting the result) on every mouse-move event was
        the actual source of visible drag lag on timelines with more than
        a couple dozen frames -- geometry doesn't change mid-drag (the
        indicator is a floating overlay, nothing in the layout actually
        moves until the drop), so `_reorder_candidates` computes it once
        per drag gesture and every subsequent move just does an O(log n)
        bisect search over the cached, already-sorted x positions.
        """
        if not self._frames:
            return

        global_pos = QPoint(global_x, global_y)
        if self._ghost is None:
            self._spawn_ghost(dragged_index, global_pos)
        else:
            self._ghost.follow(global_pos)

        local_x = self._strip.mapFromGlobal(QPoint(global_x, 0)).x()

        if self._reorder_candidates is None:
            ordered = sorted(
                self._strip.findChildren(FrameThumbnail), key=lambda t: t._index
            )
            self._reorder_candidates = [
                (t._index, t.geometry().left())
                for t in ordered
                if t._index not in self._selected_indices
            ]
            self._reorder_candidate_centers = [
                t.geometry().center().x()
                for t in ordered
                if t._index not in self._selected_indices
            ]

        position = bisect.bisect_right(self._reorder_candidate_centers, local_x)
        if position < len(self._reorder_candidates):
            index, left_x = self._reorder_candidates[position]
            insert_before_number = self._frames[index].number
            indicator_x = left_x
        else:
            insert_before_number = None
            indicator_x = self._strip.width()

        self._pending_drop_before_number = insert_before_number
        self._drop_indicator.setGeometry(self._drop_indicator_geometry(indicator_x))
        if self._drop_indicator.isHidden():
            self._drop_indicator.show()
            self._drop_indicator.raise_()

    def _spawn_ghost(self, dragged_index: int, global_pos: QPoint) -> None:
        """Create and lift _ghost at the start of a reorder-drag
        (backlog item #2 polish).

        Clones dragged_index's own thumbnail pixmap (falling back to a
        plain rectangle if that thumbnail's image failed to load), tags
        it with a "+N" badge when more than one frame is riding along,
        and dims every dragged thumbnail's source in place so the
        strip reads as "these frames were just lifted out" rather than
        "a duplicate appeared on top of them."
        """
        thumbnails = {t._index: t for t in self._strip.findChildren(FrameThumbnail)}
        source = thumbnails.get(dragged_index)
        pixmap = source._thumbnail_pixmap if source is not None else None
        if pixmap is None:
            pixmap = QPixmap(THUMBNAIL_DISPLAY_HEIGHT, THUMBNAIL_DISPLAY_HEIGHT)
            pixmap.fill(QColor("#334155"))

        dragged_indices = self._selected_indices or {dragged_index}
        extra_count = max(0, len(dragged_indices) - 1)

        self._ghost = _DragGhost(pixmap, extra_count)
        self._ghost.lift_at(global_pos)

        for index in dragged_indices:
            thumbnail = thumbnails.get(index)
            if thumbnail is not None:
                thumbnail.set_lifted(True)

    def _drop_indicator_geometry(self, indicator_x: int):
        """Build the drop indicator's QRect at horizontal position
        `indicator_x`, spanning the strip's full height.

        Pulled out of _on_reorder_dragged only so that method's own body
        stays focused on *finding* the drop position rather than also
        constructing the geometry object for it.
        """
        return QRect(
            max(0, indicator_x - DROP_INDICATOR_WIDTH // 2),
            0,
            DROP_INDICATOR_WIDTH,
            self._strip.height(),
        )

    def _on_reorder_dropped(self, dragged_index: int) -> None:
        """Finish a reorder-drag: emit `frames_reorder_requested` and
        clear the drag/selection state (backlog item #2).

        Falls back to treating just `dragged_index` as the dragged frame
        if `_selected_indices` is somehow empty -- defensive only,
        reorder-drags can only start from a thumbnail set drag-eligible by
        _apply_selection_highlight(), which never leaves `dragged_index`
        out of `_selected_indices`.

        Also settles the pick-up ghost back down (backlog item #2
        polish) -- fades it out and un-dims whichever source thumbnails
        were lifted for it, mirroring a solitaire card being placed back
        onto the table.
        """
        self._drop_indicator.hide()
        self._reorder_candidates = None
        self._reorder_candidate_centers = []

        indices = (
            sorted(self._selected_indices)
            if self._selected_indices
            else [dragged_index]
        )
        for thumbnail in self._strip.findChildren(FrameThumbnail):
            if thumbnail._index in indices:
                thumbnail.set_lifted(False)
        if self._ghost is not None:
            self._ghost.drop()
            self._ghost = None

        if not self._frames:
            return

        frame_numbers = [self._frames[i].number for i in indices]

        self.frames_reorder_requested.emit(
            frame_numbers, self._pending_drop_before_number
        )

        self._selected_indices = set()
        self._selection_anchor = None
        self._pending_drop_before_number = None


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
        self.setStyleSheet("border: 1px solid #1f2d38;")

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

        # Bottom-right corner of the whole editor, per Chris's mockup --
        # this row is the bottommost thing in the central layout, and the
        # stretch above puts this at its far-right edge. Opens the Export
        # page rather than doing anything itself; starts disabled since
        # there's nothing to export before a project is open (see
        # MainWindow._adopt_project()).
        self.export_button = QPushButton("Export")
        self.export_button.setDefault(True)
        self.export_button.setEnabled(False)
        layout.addWidget(self.export_button)


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
        self.setStyleSheet("border: 1px solid #1f2d38;")

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
        self.setStyleSheet("border: 1px solid #1f2d38;" if visible else "")
        for button in self._buttons:
            button.setVisible(visible)
        self.notes_edit.setVisible(visible)

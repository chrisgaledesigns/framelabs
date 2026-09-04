"""Tests for the real Feature 5 TimelineWidget and FrameThumbnail.

Uses real generated JPEG thumbnails written to tmp_path (via cv2, matching
this repo's existing convention for any test needing a real image file) --
TimelineWidget's entire job is reading real thumbnail files off disk, so
mocking that read would test nothing real, the same reasoning already
applied to PluginManager's real .py files and frame_writer's real PNGs/
JPEGs elsewhere in this suite.
"""

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QLabel

from framelabs.project.project import Frame
from framelabs.ui.timeline_widget import (
    DRAG_THRESHOLD_PX,
    MARKER_BORDER_COLOR,
    MULTI_SELECT_BACKGROUND,
    SELECTION_BORDER_COLOR,
    FrameActionBar,
    FrameThumbnail,
    TimelineWidget,
)


def _press(
    widget,
    global_x: float,
    global_y: float = 50.0,
    modifiers=Qt.KeyboardModifier.NoModifier,
) -> None:
    """Synthesize a real left-button press at the given global position."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(global_x, global_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        modifiers,
    )
    widget.mousePressEvent(event)


def _move(widget, global_x: float, global_y: float = 50.0) -> None:
    """Synthesize a real mouse-move with the left button held down."""
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(5, 5),
        QPointF(global_x, global_y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseMoveEvent(event)


def _release(
    widget,
    global_x: float,
    global_y: float = 50.0,
    modifiers=Qt.KeyboardModifier.NoModifier,
) -> None:
    """Synthesize a real left-button release at the given global position."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(5, 5),
        QPointF(global_x, global_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        modifiers,
    )
    widget.mouseReleaseEvent(event)


def _write_real_thumbnail(thumbnails_dir: Path, frame_number: int) -> None:
    """Write a real, valid JPEG thumbnail file for the given frame number."""
    image = np.zeros((75, 100, 3), dtype=np.uint8)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(thumbnails_dir / f"{frame_number:06d}.jpg"), image)


def _all_style(widget) -> str:
    """Concatenate a widget's stylesheet with all its QFrame descendants'.

    The marker border lives on the outer FrameThumbnail itself; the
    selection border lives on the nested inner QFrame -- checking both in
    one string lets tests assert on either without caring which widget
    actually owns it.
    """
    from PySide6.QtWidgets import QFrame

    return widget.styleSheet() + "".join(
        child.styleSheet() for child in widget.findChildren(QFrame)
    )


def test_refresh_creates_one_thumbnail_per_frame(qtbot, tmp_path):
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [Frame(number=1, file="images/000001.png")]
    _write_real_thumbnail(tmp_path, 1)

    widget.refresh(frames, tmp_path, current_index=0)

    thumbnails = widget._strip.findChildren(FrameThumbnail)
    assert len(thumbnails) == 1


def test_refresh_creates_thumbnails_for_multiple_frames(qtbot, tmp_path):
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
        Frame(number=3, file="images/000003.png"),
    ]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)

    widget.refresh(frames, tmp_path, current_index=0)

    assert len(widget._strip.findChildren(FrameThumbnail)) == 3


def test_refresh_clears_previous_thumbnails_on_second_call(qtbot, tmp_path):
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    _write_real_thumbnail(tmp_path, 1)
    _write_real_thumbnail(tmp_path, 2)

    widget.refresh([Frame(number=1, file="images/000001.png")], tmp_path, 0)
    widget.refresh(
        [
            Frame(number=1, file="images/000001.png"),
            Frame(number=2, file="images/000002.png"),
        ],
        tmp_path,
        0,
    )

    # deleteLater() defers actual destruction, but the layout itself must
    # reflect the new count immediately -- checking layout count rather
    # than findChildren, since the old widgets may not be gone yet.
    assert widget._strip_layout.count() == 2


def test_refresh_with_empty_frames_creates_no_thumbnails(qtbot, tmp_path):
    widget = TimelineWidget()
    qtbot.addWidget(widget)

    widget.refresh([], tmp_path, current_index=0)

    assert widget._strip_layout.count() == 0


def test_selected_frame_has_selection_border(qtbot, tmp_path):
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=0,
        selected=True,
    )
    qtbot.addWidget(thumbnail)

    assert SELECTION_BORDER_COLOR in _all_style(thumbnail)


def test_unselected_frame_has_no_selection_border_color(qtbot, tmp_path):
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=0,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    assert "0px solid #00bc90" in _all_style(thumbnail)


def test_marked_frame_has_marker_border(qtbot, tmp_path):
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png", marker=True),
        tmp_path,
        index=0,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    assert MARKER_BORDER_COLOR in thumbnail.styleSheet()


def test_unmarked_frame_has_no_marker_border_color(qtbot, tmp_path):
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png", marker=False),
        tmp_path,
        index=0,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    assert "0px solid #f59e0b" in thumbnail.styleSheet()


def test_marked_and_selected_frame_has_both_borders(qtbot, tmp_path):
    """A frame can be both marked and selected at once -- per Chris's own
    choice of "border" for both states, they must stack rather than one
    overriding the other."""
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png", marker=True),
        tmp_path,
        index=0,
        selected=True,
    )
    qtbot.addWidget(thumbnail)

    style = _all_style(thumbnail)
    assert MARKER_BORDER_COLOR in style
    assert SELECTION_BORDER_COLOR in style


def test_missing_thumbnail_file_shows_placeholder_text(qtbot, tmp_path):
    """No thumbnail written for frame 1 -- must not raise, and must show
    an identifiable placeholder rather than a broken/blank image."""
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=0,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    labels = [lbl.text() for lbl in thumbnail.findChildren(QLabel)]
    assert any("No" in text and "Thumbnail" in text for text in labels)


def test_existing_thumbnail_file_shows_no_placeholder_text(qtbot, tmp_path):
    """Sanity check for the inverse of the above -- a real thumbnail must
    NOT trigger the missing-file placeholder text."""
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=0,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    labels = [lbl.text() for lbl in thumbnail.findChildren(QLabel)]
    assert not any("No" in text and "Thumbnail" in text for text in labels)


def test_clicking_thumbnail_emits_clicked_with_its_index(qtbot, tmp_path):
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=7,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    with qtbot.waitSignal(thumbnail.clicked, timeout=1000) as blocker:
        qtbot.mouseClick(thumbnail, Qt.MouseButton.LeftButton)

    assert blocker.args == [7, 0]


def test_widget_frame_selected_signal_carries_clicked_thumbnail_index(qtbot, tmp_path):
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)

    thumbnails = widget._strip.findChildren(FrameThumbnail)
    second_thumbnail = next(t for t in thumbnails if t._index == 1)

    with qtbot.waitSignal(widget.frame_selected, timeout=1000) as blocker:
        qtbot.mouseClick(second_thumbnail, Qt.MouseButton.LeftButton)

    assert blocker.args == [1]


def test_set_current_index_moves_selection_without_rebuilding(qtbot, tmp_path):
    """A playhead-only move must update the border without recreating any
    thumbnail widget -- the whole point of this method vs. refresh()."""
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)
    thumbnails_before = list(widget._strip.findChildren(FrameThumbnail))

    widget.set_current_index(1)

    thumbnails_after = list(widget._strip.findChildren(FrameThumbnail))
    assert thumbnails_before == thumbnails_after

    first = next(t for t in thumbnails_after if t._index == 0)
    second = next(t for t in thumbnails_after if t._index == 1)
    assert f"0px solid {SELECTION_BORDER_COLOR}" in _all_style(first)
    assert f"3px solid {SELECTION_BORDER_COLOR}" in _all_style(second)


def test_set_current_index_preserves_marker_border(qtbot, tmp_path):
    """Moving the selection border must not disturb an independent marker
    border on the same or another thumbnail."""
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [
        Frame(number=1, file="images/000001.png", marker=True),
        Frame(number=2, file="images/000002.png"),
    ]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)

    widget.set_current_index(1)

    marked = next(
        t for t in widget._strip.findChildren(FrameThumbnail) if t._index == 0
    )
    assert MARKER_BORDER_COLOR in _all_style(marked)


def test_thumbnail_context_menu_emits_index_and_position(qtbot, tmp_path):
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=7,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    local_pos = QPoint(5, 5)
    global_pos = QPoint(50, 60)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, local_pos, global_pos)

    with qtbot.waitSignal(thumbnail.context_menu_requested, timeout=1000) as blocker:
        thumbnail.contextMenuEvent(event)

    assert blocker.args == [7, global_pos]


def test_widget_frame_context_menu_requested_carries_thumbnail_index(qtbot, tmp_path):
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)

    thumbnails = widget._strip.findChildren(FrameThumbnail)
    second_thumbnail = next(t for t in thumbnails if t._index == 1)
    global_pos = QPoint(80, 90)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(10, 10), global_pos
    )

    with qtbot.waitSignal(widget.frame_context_menu_requested, timeout=1000) as blocker:
        second_thumbnail.contextMenuEvent(event)

    assert blocker.args == [1, global_pos]


def test_action_bar_starts_disabled_and_empty(qtbot):
    """No frame selected yet (fresh MainWindow, empty project) -- every
    control must be disabled, not just inert, so nothing looks clickable
    for an action that has no frame to act on."""
    bar = FrameActionBar()
    qtbot.addWidget(bar)

    assert not bar.delete_button.isEnabled()
    assert not bar.replace_button.isEnabled()
    assert not bar.duplicate_button.isEnabled()
    assert not bar.marker_button.isEnabled()
    assert not bar.notes_edit.isEnabled()
    assert bar.notes_edit.text() == ""
    assert not bar.marker_button.isChecked()


def test_action_bar_set_current_frame_enables_and_populates(qtbot):
    bar = FrameActionBar()
    qtbot.addWidget(bar)

    bar.set_current_frame(
        Frame(number=5, file="images/000005.png", notes="Arm raised", marker=True)
    )

    assert bar.delete_button.isEnabled()
    assert bar.replace_button.isEnabled()
    assert bar.duplicate_button.isEnabled()
    assert bar.marker_button.isEnabled()
    assert bar.notes_edit.isEnabled()
    assert bar.notes_edit.text() == "Arm raised"
    assert bar.marker_button.isChecked()


def test_action_bar_set_current_frame_none_disables_and_clears(qtbot):
    """Going from a selected frame back to none (e.g. the last frame in
    the project gets deleted) must reset the bar, not just leave the
    previous frame's notes/marker state stuck on screen."""
    bar = FrameActionBar()
    qtbot.addWidget(bar)
    bar.set_current_frame(
        Frame(number=5, file="images/000005.png", notes="Arm raised", marker=True)
    )

    bar.set_current_frame(None)

    assert not bar.delete_button.isEnabled()
    assert not bar.replace_button.isEnabled()
    assert not bar.duplicate_button.isEnabled()
    assert not bar.marker_button.isEnabled()
    assert not bar.notes_edit.isEnabled()
    assert bar.notes_edit.text() == ""
    assert not bar.marker_button.isChecked()


def test_action_bar_unmarked_frame_leaves_marker_unchecked(qtbot):
    bar = FrameActionBar()
    qtbot.addWidget(bar)

    bar.set_current_frame(Frame(number=1, file="images/000001.png", marker=False))

    assert not bar.marker_button.isChecked()


def test_action_bar_set_current_frame_does_not_emit_notes_editing_finished(qtbot):
    """set_current_frame() must use setText(), not anything that fires
    editingFinished -- otherwise every playhead move would spuriously
    look like the user just finished editing Notes."""
    bar = FrameActionBar()
    qtbot.addWidget(bar)

    with qtbot.assertNotEmitted(bar.notes_edit.editingFinished):
        bar.set_current_frame(
            Frame(number=1, file="images/000001.png", notes="Some note")
        )


def test_action_bar_set_current_frame_does_not_emit_marker_clicked(qtbot):
    """set_current_frame() must use setChecked(), not anything that fires
    clicked -- otherwise every playhead move onto a marked frame would
    spuriously look like the user just clicked Marker."""
    bar = FrameActionBar()
    qtbot.addWidget(bar)

    with qtbot.assertNotEmitted(bar.marker_button.clicked):
        bar.set_current_frame(Frame(number=1, file="images/000001.png", marker=True))


def test_small_press_release_movement_still_emits_clicked(qtbot, tmp_path):
    """A press/release that never exceeds DRAG_THRESHOLD_PX is still a
    plain click -- tiny hand tremor shouldn't cancel frame selection."""
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=3,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    with qtbot.waitSignal(thumbnail.clicked, timeout=1000) as blocker:
        _press(thumbnail, 100.0)
        _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX - 1)
        _release(thumbnail, 100.0 + DRAG_THRESHOLD_PX - 1)

    assert blocker.args == [3, 0]


def test_press_resolves_clicked_immediately_not_again_on_release(qtbot, tmp_path):
    """As of the reorder-on-drag work (backlog item #2 follow-up), a
    plain press with no selection modifier and no existing multi-
    selection resolves `clicked` immediately on press, not deferred to
    release -- this is what lets a single continuous press-and-drag
    reorder a not-yet-selected thumbnail without a separate prior click
    (see FrameThumbnail.mousePressEvent's docstring). Once resolved on
    press, `clicked` must not fire a second time on release even though
    the gesture goes on to cross DRAG_THRESHOLD_PX."""
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=3,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    clicks = []
    thumbnail.clicked.connect(lambda index, mods: clicks.append((index, mods)))

    _press(thumbnail, 100.0)
    assert clicks == [(3, 0)]  # resolved immediately on press

    _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)
    _release(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)

    assert clicks == [(3, 0)]  # not re-emitted on release


def test_movement_past_threshold_emits_drag_scrolled_with_delta(qtbot, tmp_path):
    """Once dragging, each move step must emit the incremental pixel
    delta since the last move (not the total displacement from press),
    so TimelineWidget can apply it directly to the scrollbar value."""
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=3,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    deltas = []
    thumbnail.drag_scrolled.connect(deltas.append)

    _press(thumbnail, 100.0)
    _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)  # crosses threshold
    _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 35)  # +15 more
    _release(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 35)

    assert deltas[-1] == 15


def test_widget_drag_scrolled_moves_horizontal_scrollbar(qtbot, tmp_path):
    """Drag-to-scroll (backlog item #1) still exists and still moves
    TimelineWidget's own horizontal scrollbar -- "content follows the
    finger" style, dragging right (positive delta) reveals earlier
    frames, so the scrollbar value goes down. As of the reorder-on-drag
    work (backlog item #2 follow-up), a *plain* drag on a previously
    unselected thumbnail now reorders instead of scrolling (see
    test_dragging_unselected_thumbnail_now_reorders_not_scrolls below),
    so this drag is held with Shift -- a selection modifier defers
    press-resolution to release, leaving the thumbnail's prior (here:
    unselected) drag-eligibility in effect for the drag itself, which is
    the one remaining path that still exercises the original drag-to-
    scroll gesture end to end."""
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [Frame(number=i, file=f"images/{i:06d}.png") for i in range(1, 21)]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)
    widget.resize(200, widget.height())
    widget.show()
    qtbot.waitExposed(widget)
    widget._strip.adjustSize()

    scrollbar = widget.horizontalScrollBar()
    assert scrollbar.maximum() > 0  # sanity check: strip really overflows
    scrollbar.setValue(scrollbar.maximum())
    start_value = scrollbar.value()

    thumbnail = next(iter(widget._strip.findChildren(FrameThumbnail)))
    _press(thumbnail, 100.0, modifiers=Qt.KeyboardModifier.ShiftModifier)
    _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)

    assert scrollbar.value() == start_value - (DRAG_THRESHOLD_PX + 20)


def test_widget_frame_selected_emitted_once_on_press_not_twice_on_drag(qtbot, tmp_path):
    """As of the reorder-on-drag work (backlog item #2 follow-up), a
    plain press on a not-yet-selected thumbnail selects it immediately
    -- `frame_selected` fires on press, not deferred to release -- so
    that a single continuous press-and-drag can reorder it. What must
    still hold: selecting it doesn't happen a *second* time just because
    the same press goes on to become a drag and is released."""
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)

    thumbnails = widget._strip.findChildren(FrameThumbnail)
    second_thumbnail = next(t for t in thumbnails if t._index == 1)

    selections = []
    widget.frame_selected.connect(selections.append)

    _press(second_thumbnail, 100.0)
    assert selections == [1]  # resolved immediately on press

    _move(second_thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)
    _release(second_thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)

    assert selections == [1]  # not emitted again on release


# ---------------------------------------------------------------------------
# Backlog item #2: Shift/Ctrl+click multi-select, drag-to-reorder.
# ---------------------------------------------------------------------------


def _setup_widget(qtbot, tmp_path, count: int) -> tuple:
    """Build a shown, laid-out TimelineWidget with `count` real frames.

    Shift/Ctrl+click range math and reorder-drag geometry both need real
    on-screen thumbnail positions, not the all-zero geometry a widget has
    before it's ever shown -- same reasoning
    test_widget_drag_scrolled_moves_horizontal_scrollbar already applies
    for the surviving modifier-held drag-to-scroll gesture.
    """
    widget = TimelineWidget()
    qtbot.addWidget(widget)
    frames = [Frame(number=i + 1, file=f"images/{i + 1:06d}.png") for i in range(count)]
    for frame in frames:
        _write_real_thumbnail(tmp_path, frame.number)
    widget.refresh(frames, tmp_path, current_index=0)
    widget.resize(200, widget.height())
    widget.show()
    qtbot.waitExposed(widget)
    widget._strip.adjustSize()
    thumbnails = sorted(
        widget._strip.findChildren(FrameThumbnail), key=lambda t: t._index
    )
    return widget, frames, thumbnails


def _center_x(thumbnail) -> float:
    """Global x of a thumbnail's horizontal center, for driving a click/drag."""
    return thumbnail.mapToGlobal(thumbnail.rect().center()).x()


def test_shift_click_selects_contiguous_range(qtbot, tmp_path):
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)

    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)
    _press(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    _release(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )

    assert widget._selected_indices == {0, 1, 2}


def test_ctrl_click_toggles_individual_frames(qtbot, tmp_path):
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)

    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)
    _press(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ControlModifier,
    )
    _release(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ControlModifier,
    )
    assert widget._selected_indices == {0, 2}

    # Ctrl+clicking an already-selected frame removes just that one.
    _press(
        thumbnails[0],
        _center_x(thumbnails[0]),
        modifiers=Qt.KeyboardModifier.ControlModifier,
    )
    _release(
        thumbnails[0],
        _center_x(thumbnails[0]),
        modifiers=Qt.KeyboardModifier.ControlModifier,
    )
    assert widget._selected_indices == {2}


def test_plain_click_collapses_multi_selection(qtbot, tmp_path):
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)

    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)
    _press(
        thumbnails[3],
        _center_x(thumbnails[3]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    _release(
        thumbnails[3],
        _center_x(thumbnails[3]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    assert widget._selected_indices == {0, 1, 2, 3}

    qtbot.mouseClick(thumbnails[1], Qt.MouseButton.LeftButton)
    assert widget._selected_indices == {1}


def test_single_selection_has_no_multi_select_background(qtbot, tmp_path):
    """A lone selected frame keeps only its existing teal border -- the
    translucent multi-select fill should only appear once 2+ frames are
    selected, so single-select behavior looks exactly as it did before."""
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 3)

    qtbot.mouseClick(thumbnails[1], Qt.MouseButton.LeftButton)

    assert MULTI_SELECT_BACKGROUND not in thumbnails[1].styleSheet()


def test_multi_selected_frames_show_highlight_background(qtbot, tmp_path):
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 3)

    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)
    _press(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    _release(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )

    assert MULTI_SELECT_BACKGROUND in thumbnails[0].styleSheet()
    assert MULTI_SELECT_BACKGROUND in thumbnails[1].styleSheet()
    assert MULTI_SELECT_BACKGROUND in thumbnails[2].styleSheet()


def test_dragging_unselected_thumbnail_now_reorders_not_scrolls(qtbot, tmp_path):
    """As of the reorder-on-drag work (backlog item #2 follow-up), a
    plain press-and-drag on a thumbnail that was never selected now
    reorders it -- press resolves selection immediately, making the
    thumbnail drag-eligible before the drag itself even starts, so the
    old "unselected drag always scrolls" contract (backlog item #1) no
    longer holds for a plain drag. See
    test_widget_drag_scrolled_moves_horizontal_scrollbar for the one
    remaining path (a modifier-held drag) that still exercises the
    original scroll gesture."""
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)

    with qtbot.assertNotEmitted(thumbnails[0].drag_scrolled):
        with qtbot.waitSignal(thumbnails[0].reorder_dragged, timeout=1000):
            _press(thumbnails[0], _center_x(thumbnails[0]))
            _move(thumbnails[0], _center_x(thumbnails[0]) + DRAG_THRESHOLD_PX + 20)


def test_dragging_selected_thumbnail_emits_reorder_not_scroll(qtbot, tmp_path):
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)
    qtbot.mouseClick(thumbnails[1], Qt.MouseButton.LeftButton)  # select it first

    with qtbot.assertNotEmitted(thumbnails[1].drag_scrolled):
        with qtbot.waitSignal(thumbnails[1].reorder_dragged, timeout=1000):
            _press(thumbnails[1], _center_x(thumbnails[1]))
            _move(thumbnails[1], _center_x(thumbnails[1]) + DRAG_THRESHOLD_PX + 20)


def test_reorder_drag_and_drop_emits_reorder_requested_with_frame_numbers(
    qtbot, tmp_path
):
    """Dragging a selected block past the last frame and releasing must
    request a move to the end (insert_before=None), carrying the moved
    frames' numbers in their original sequence order."""
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)

    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)
    _press(
        thumbnails[1],
        _center_x(thumbnails[1]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    _release(
        thumbnails[1],
        _center_x(thumbnails[1]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    assert widget._selected_indices == {0, 1}

    far_right = widget._strip.mapToGlobal(QPoint(widget._strip.width() + 500, 0)).x()

    with qtbot.waitSignal(widget.frames_reorder_requested, timeout=1000) as blocker:
        _press(thumbnails[0], _center_x(thumbnails[0]))
        _move(thumbnails[0], _center_x(thumbnails[0]) + DRAG_THRESHOLD_PX + 20)
        _move(thumbnails[0], far_right)
        _release(thumbnails[0], far_right)

    frame_numbers, insert_before = blocker.args
    assert frame_numbers == [1, 2]  # frames.number for index 0 and 1
    assert insert_before is None


def test_reorder_drop_clears_selection(qtbot, tmp_path):
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)
    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)

    far_right = widget._strip.mapToGlobal(QPoint(widget._strip.width() + 500, 0)).x()
    with qtbot.waitSignal(widget.frames_reorder_requested, timeout=1000):
        _press(thumbnails[0], _center_x(thumbnails[0]))
        _move(thumbnails[0], far_right)
        _release(thumbnails[0], far_right)

    assert widget._selected_indices == set()


def test_refresh_clears_multi_selection(qtbot, tmp_path):
    """A structural rebuild must not carry stale selection indices over
    onto a different frame list."""
    widget, frames, thumbnails = _setup_widget(qtbot, tmp_path, 4)
    qtbot.mouseClick(thumbnails[0], Qt.MouseButton.LeftButton)
    _press(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    _release(
        thumbnails[2],
        _center_x(thumbnails[2]),
        modifiers=Qt.KeyboardModifier.ShiftModifier,
    )
    assert widget._selected_indices == {0, 1, 2}

    new_frames = [Frame(number=1, file="images/000001.png")]
    _write_real_thumbnail(tmp_path, 1)
    widget.refresh(new_frames, tmp_path, current_index=0)

    assert widget._selected_indices == set()

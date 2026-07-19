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
    SELECTION_BORDER_COLOR,
    FrameActionBar,
    FrameThumbnail,
    TimelineWidget,
)


def _press(widget, global_x: float, global_y: float = 50.0) -> None:
    """Synthesize a real left-button press at the given global position."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(global_x, global_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
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


def _release(widget, global_x: float, global_y: float = 50.0) -> None:
    """Synthesize a real left-button release at the given global position."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(5, 5),
        QPointF(global_x, global_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
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

    assert "0px solid #3b82f6" in _all_style(thumbnail)


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

    assert blocker.args == [7]


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

    assert blocker.args == [3]


def test_movement_past_threshold_suppresses_clicked(qtbot, tmp_path):
    """Once movement crosses DRAG_THRESHOLD_PX, this becomes a drag-to-
    scroll gesture, not a click -- `clicked` must not fire on release."""
    _write_real_thumbnail(tmp_path, 1)
    thumbnail = FrameThumbnail(
        Frame(number=1, file="images/000001.png"),
        tmp_path,
        index=3,
        selected=False,
    )
    qtbot.addWidget(thumbnail)

    with qtbot.assertNotEmitted(thumbnail.clicked):
        _press(thumbnail, 100.0)
        _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)
        _release(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)


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
    """A drag on any thumbnail must scroll TimelineWidget's own
    horizontal scrollbar, "content follows the finger" style -- dragging
    right (positive delta) reveals earlier frames, so the scrollbar
    value goes down."""
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
    _press(thumbnail, 100.0)
    _move(thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)

    assert scrollbar.value() == start_value - (DRAG_THRESHOLD_PX + 20)


def test_widget_frame_selected_not_emitted_when_thumbnail_is_dragged(qtbot, tmp_path):
    """A drag that starts on a thumbnail must not also select that frame
    -- selection and scrolling are mutually exclusive outcomes of the
    same gesture."""
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

    with qtbot.assertNotEmitted(widget.frame_selected):
        _press(second_thumbnail, 100.0)
        _move(second_thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)
        _release(second_thumbnail, 100.0 + DRAG_THRESHOLD_PX + 20)

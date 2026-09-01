"""Tests for TheaterViewDialog (Project Browser follow-up, session 15).

Uses real Frame objects and real generated PNGs written to tmp_path (via
cv2, matching test_project_browser_widget.py/test_timeline_widget.py's
existing convention for anything reading real image files from disk), and
drives keyboard navigation via real QKeyEvent objects rather than mocking
Qt's event system.

The transport-control tests below (Play/Pause/Loop/Step/timecode) drive
_advance_playback() directly rather than waiting on the real QTimer --
same reasoning test_playback_controller.py uses for PlaybackController's
own timer: it keeps these tests fast and deterministic instead of
depending on real wall-clock time.
"""

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from framelabs.project.project import Frame
from framelabs.ui.theater_view_dialog import TheaterViewDialog


def _click_scrub_bar_at_value(dialog: TheaterViewDialog, value: int) -> None:
    """Simulate a real left-click landing on the scrub bar position that
    corresponds to `value`, exercising _SeekSlider's actual
    mousePressEvent/_value_at_x math end-to-end rather than emitting
    sliderMoved directly (that's what the drag-only tests above already
    do) -- this is what proves clicking, not just dragging, seeks.
    """
    scrub_bar = dialog._scrub_bar
    scrub_bar.resize(300, scrub_bar.sizeHint().height() or 20)
    # Invert _value_at_x's own mapping to find an x that resolves back to
    # `value`, rather than hard-coding a width-dependent pixel offset.
    target_x = next(
        x for x in range(scrub_bar.width()) if scrub_bar._value_at_x(x) == value
    )
    pos = QPointF(target_x, scrub_bar.height() / 2)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    scrub_bar.mousePressEvent(event)


def _write_real_image(project_path: Path, frame_number: int) -> None:
    """Write a real, tiny readable PNG at images/{number:06d}.png."""
    images_dir = project_path / "images"
    images_dir.mkdir(exist_ok=True)
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    cv2.imwrite(str(images_dir / f"{frame_number:06d}.png"), image)


def _press_key(dialog: TheaterViewDialog, key: Qt.Key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    dialog.keyPressEvent(event)


def test_opens_on_the_requested_start_index(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]

    dialog = TheaterViewDialog(tmp_path, frames, start_index=1)
    qtbot.addWidget(dialog)

    assert dialog._index == 1
    assert "Frame 2" in dialog._position_label.text()
    assert dialog._current_pixmap is not None


def test_start_index_out_of_range_is_clamped_not_raised(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    frames = [Frame(number=1, file="images/000001.png")]

    dialog = TheaterViewDialog(tmp_path, frames, start_index=99)
    qtbot.addWidget(dialog)

    assert dialog._index == 0


def test_missing_image_file_shows_placeholder_not_a_crash(qtbot, tmp_path):
    # Deliberately no image file written for this frame.
    frames = [Frame(number=1, file="images/000001.png")]

    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    assert dialog._current_pixmap is None
    assert dialog._image_label.text() == "No Image"


def test_right_arrow_advances_to_next_frame(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    _press_key(dialog, Qt.Key.Key_Right)

    assert dialog._index == 1
    assert "Frame 2" in dialog._position_label.text()


def test_left_arrow_steps_back_to_previous_frame(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    dialog = TheaterViewDialog(tmp_path, frames, start_index=1)
    qtbot.addWidget(dialog)

    _press_key(dialog, Qt.Key.Key_Left)

    assert dialog._index == 0
    assert "Frame 1" in dialog._position_label.text()


def test_arrow_navigation_does_not_step_past_the_first_or_last_frame(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    _press_key(dialog, Qt.Key.Key_Left)
    assert dialog._index == 0

    dialog.go_to_index(1)
    _press_key(dialog, Qt.Key.Key_Right)
    assert dialog._index == 1


def test_escape_closes_the_dialog(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    frames = [Frame(number=1, file="images/000001.png")]
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)
    dialog.show()

    _press_key(dialog, Qt.Key.Key_Escape)

    assert not dialog.isVisible()


def test_no_frames_shows_placeholder_and_does_not_crash(qtbot, tmp_path):
    dialog = TheaterViewDialog(tmp_path, [], start_index=0)
    qtbot.addWidget(dialog)

    assert dialog._current_pixmap is None
    assert dialog._image_label.text() == "No frames to preview"
    assert dialog._position_label.text() == ""

    # Arrow keys on an empty frame list must be safe no-ops.
    _press_key(dialog, Qt.Key.Key_Right)
    _press_key(dialog, Qt.Key.Key_Left)
    assert dialog._index == 0


def test_scrub_bar_range_matches_frame_count(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    _write_real_image(tmp_path, 3)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
        Frame(number=3, file="images/000003.png"),
    ]

    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    assert dialog._scrub_bar.minimum() == 0
    assert dialog._scrub_bar.maximum() == 2
    assert dialog._scrub_bar.isEnabled()


def test_scrub_bar_starts_positioned_on_the_start_index(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]

    dialog = TheaterViewDialog(tmp_path, frames, start_index=1)
    qtbot.addWidget(dialog)

    assert dialog._scrub_bar.value() == 1


def test_dragging_the_scrub_bar_navigates_to_that_frame(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    _write_real_image(tmp_path, 3)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
        Frame(number=3, file="images/000003.png"),
    ]
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    # sliderMoved is what a real drag emits -- exercise it directly
    # rather than simulating mouse events, same as this file already
    # drives keyboard navigation via real QKeyEvents rather than mocking.
    dialog._scrub_bar.sliderMoved.emit(2)

    assert dialog._index == 2
    assert "Frame 3" in dialog._position_label.text()


def test_arrow_key_navigation_keeps_the_scrub_bar_in_sync(qtbot, tmp_path):
    _write_real_image(tmp_path, 1)
    _write_real_image(tmp_path, 2)
    frames = [
        Frame(number=1, file="images/000001.png"),
        Frame(number=2, file="images/000002.png"),
    ]
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    _press_key(dialog, Qt.Key.Key_Right)

    assert dialog._scrub_bar.value() == 1


def test_scrub_bar_disabled_with_no_frames(qtbot, tmp_path):
    dialog = TheaterViewDialog(tmp_path, [], start_index=0)
    qtbot.addWidget(dialog)

    assert not dialog._scrub_bar.isEnabled()
    assert dialog._scrub_bar.maximum() == 0


def _make_frames(project_path: Path, count: int) -> list[Frame]:
    frames = []
    for number in range(1, count + 1):
        _write_real_image(project_path, number)
        frames.append(Frame(number=number, file=f"images/{number:06d}.png"))
    return frames


def test_timecode_reflects_fps_and_current_index(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)

    dialog = TheaterViewDialog(tmp_path, frames, start_index=0, fps=2)
    qtbot.addWidget(dialog)
    assert dialog._timecode_label.text() == "00:00:00:00"

    dialog.go_to_index(1)
    # At 2fps, frame index 1 is half a second in: 0 whole seconds, 1
    # leftover frame.
    assert dialog._timecode_label.text() == "00:00:00:01"


def test_play_button_starts_timer_and_updates_label(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    dialog._play_button.setChecked(True)

    assert dialog._timer.isActive()
    assert "Pause" in dialog._play_button.text()


def test_pause_button_stops_timer_and_restores_label(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    dialog._play_button.setChecked(True)
    dialog._play_button.setChecked(False)

    assert not dialog._timer.isActive()
    assert "Play" in dialog._play_button.text()


def test_play_button_disabled_with_fewer_than_two_frames(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 1)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    assert not dialog._play_button.isEnabled()


def test_advance_playback_moves_to_next_frame(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    dialog._advance_playback()

    assert dialog._index == 1


def test_advance_playback_stops_at_last_frame_without_loop(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 2)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=1)
    qtbot.addWidget(dialog)
    dialog._play_button.setChecked(True)

    dialog._advance_playback()

    assert dialog._index == 1
    assert not dialog._timer.isActive()
    assert not dialog._play_button.isChecked()


def test_advance_playback_wraps_to_first_frame_with_loop(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 2)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=1)
    qtbot.addWidget(dialog)
    dialog._loop_button.setChecked(True)
    dialog._play_button.setChecked(True)

    dialog._advance_playback()

    assert dialog._index == 0
    assert dialog._timer.isActive()


def test_step_forward_and_back_buttons_move_one_frame(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    dialog._step_forward()
    assert dialog._index == 1

    dialog._step_back()
    assert dialog._index == 0


def test_manual_navigation_pauses_playback(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)
    dialog._play_button.setChecked(True)
    assert dialog._timer.isActive()

    dialog._step_forward()

    assert not dialog._timer.isActive()
    assert not dialog._play_button.isChecked()


def test_scrub_drag_pauses_playback(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)
    dialog._play_button.setChecked(True)

    dialog._scrub_bar.sliderMoved.emit(2)

    assert not dialog._timer.isActive()
    assert not dialog._play_button.isChecked()
    assert dialog._index == 2


def test_space_key_toggles_play_pause(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    _press_key(dialog, Qt.Key.Key_Space)
    assert dialog._timer.isActive()

    _press_key(dialog, Qt.Key.Key_Space)
    assert not dialog._timer.isActive()


def test_closing_dialog_stops_the_timer(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._play_button.setChecked(True)
    assert dialog._timer.isActive()

    dialog.close()

    assert not dialog._timer.isActive()


def test_clicking_the_scrub_bar_seeks_directly_to_that_frame(qtbot, tmp_path):
    """The bug report this covers: previously, clicking a point on the
    scrub bar (as opposed to dragging the handle) did not seek there at
    all -- plain QSlider just pages one step toward the click. A single
    click landing exactly on the target frame is the fix.
    """
    frames = _make_frames(tmp_path, 5)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)
    dialog.show()

    _click_scrub_bar_at_value(dialog, 3)

    assert dialog._index == 3
    assert "Frame 4" in dialog._position_label.text()


def test_clicking_the_scrub_bar_while_playing_pauses_first(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 5)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._play_button.setChecked(True)

    _click_scrub_bar_at_value(dialog, 2)

    assert not dialog._timer.isActive()
    assert not dialog._play_button.isChecked()
    assert dialog._index == 2


def test_clicking_disabled_scrub_bar_does_not_seek(qtbot, tmp_path):
    dialog = TheaterViewDialog(tmp_path, [], start_index=0)
    qtbot.addWidget(dialog)
    dialog.show()

    scrub_bar = dialog._scrub_bar
    scrub_bar.resize(300, scrub_bar.sizeHint().height() or 20)
    pos = QPointF(150, scrub_bar.height() / 2)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    scrub_bar.mousePressEvent(event)

    assert dialog._index == 0


def test_scrub_bar_tooltip_text_reports_frame_and_timecode(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0, fps=2)
    qtbot.addWidget(dialog)

    text = dialog._scrub_bar_tooltip_text(1)

    assert "Frame 2" in text
    assert "00:00:00:01" in text


def test_scrub_bar_tooltip_text_empty_for_out_of_range_index(qtbot, tmp_path):
    frames = _make_frames(tmp_path, 3)
    dialog = TheaterViewDialog(tmp_path, frames, start_index=0)
    qtbot.addWidget(dialog)

    assert dialog._scrub_bar_tooltip_text(-1) == ""
    assert dialog._scrub_bar_tooltip_text(99) == ""


def test_scrub_bar_tooltip_text_empty_with_no_frames(qtbot, tmp_path):
    dialog = TheaterViewDialog(tmp_path, [], start_index=0)
    qtbot.addWidget(dialog)

    assert dialog._scrub_bar_tooltip_text(0) == ""

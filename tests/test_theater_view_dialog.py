"""Tests for TheaterViewDialog (Project Browser follow-up, session 15).

Uses real Frame objects and real generated PNGs written to tmp_path (via
cv2, matching test_project_browser_widget.py/test_timeline_widget.py's
existing convention for anything reading real image files from disk), and
drives keyboard navigation via real QKeyEvent objects rather than mocking
Qt's event system.
"""

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from framelabs.project.project import Frame
from framelabs.ui.theater_view_dialog import TheaterViewDialog


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

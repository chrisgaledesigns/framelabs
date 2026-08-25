"""Tests for TimecodeWidget and its format_timecode() helper."""

from framelabs.ui.timecode_widget import TimecodeWidget, format_timecode


def test_format_timecode_at_frame_zero():
    assert format_timecode(0, fps=12) == "00:00:00:00"


def test_format_timecode_rolls_seconds_minutes_hours():
    # 12 fps, frame 12 -> exactly 1 second elapsed, 0 frames into the next.
    assert format_timecode(12, fps=12) == "00:00:01:00"
    # 12 fps, frame 13 -> 1 second plus 1 frame.
    assert format_timecode(13, fps=12) == "00:00:01:01"
    # 12 fps, 60 seconds' worth of frames -> rolls into the minutes field.
    assert format_timecode(12 * 60, fps=12) == "00:01:00:00"
    # 12 fps, 3600 seconds' worth of frames -> rolls into the hours field.
    assert format_timecode(12 * 3600, fps=12) == "01:00:00:00"


def test_format_timecode_clamps_fps_to_at_least_one():
    """A malformed/unset fps of 0 must never divide by zero here."""
    assert format_timecode(5, fps=0) == "00:00:05:00"


def test_format_timecode_clamps_negative_frame_index_to_zero():
    assert format_timecode(-3, fps=12) == "00:00:00:00"


def test_widget_starts_in_empty_placeholder_state(qtbot):
    widget = TimecodeWidget()
    qtbot.addWidget(widget)

    assert widget._timecode_label.text() == "--:--:--:--"
    assert widget._frame_count_label.text() == "No frames"


def test_set_state_shows_timecode_and_one_based_frame_count(qtbot):
    widget = TimecodeWidget()
    qtbot.addWidget(widget)

    widget.set_state(current_index=3, total_frames=48, fps=12)

    assert widget._timecode_label.text() == "00:00:00:03"
    assert widget._frame_count_label.text() == "Frame 4 / 48"


def test_set_state_with_zero_total_frames_falls_back_to_placeholder(qtbot):
    widget = TimecodeWidget()
    qtbot.addWidget(widget)
    widget.set_state(current_index=0, total_frames=5, fps=12)

    widget.set_state(current_index=0, total_frames=0, fps=12)

    assert widget._timecode_label.text() == "--:--:--:--"
    assert widget._frame_count_label.text() == "No frames"


def test_clear_resets_to_placeholder(qtbot):
    widget = TimecodeWidget()
    qtbot.addWidget(widget)
    widget.set_state(current_index=3, total_frames=48, fps=12)

    widget.clear()

    assert widget._timecode_label.text() == "--:--:--:--"
    assert widget._frame_count_label.text() == "No frames"

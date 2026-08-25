"""Timecode readout widget -- sits centered between Live View and the
Timeline strip, showing exactly where the playhead currently is.

Purely a display, the same "dumb widget, MainWindow owns behavior" split
InspectorPanel and TimelineWidget already use -- it holds no Timeline/
Project of its own. MainWindow pushes updates into it via set_state()
from the same two call sites that already keep the Timeline strip's
selection border in sync: _refresh_timeline_widget() (frame list
changed -- new project, capture, delete, undo/redo, ...) and
_move_timeline_playhead() (a playhead-only move -- arrow keys, playback
ticks, thumbnail clicks). Both events can move the playhead, so both
need to refresh this widget too, not just whichever one happens to
rebuild thumbnails.

Shows two things side by side, both centered as one unit in the row
between Live View and the Timeline strip:
- A standard editing-style timecode (HH:MM:SS:FF), computed from the
  project's own fps -- see format_timecode()'s docstring for the exact
  math and why it's 0-based, unlike the frame counter beside it.
- A plain "Frame N / total" counter, 1-based to match Frame.number and
  every other panel (Project Browser, Inspector, ...) that already
  displays frame numbers starting at 1.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

# Placeholder text shown before any project is open / once the current
# project's frame list is empty. Dashes rather than "0" anywhere, so an
# empty timeline can never be mistaken for "on frame zero".
_EMPTY_TIMECODE = "--:--:--:--"
_EMPTY_FRAME_COUNT = "No frames"


def format_timecode(frame_index: int, fps: int) -> str:
    """Format a 0-based frame index as HH:MM:SS:FF at `fps`.

    Standard non-drop timecode math: convert the frame index to total
    elapsed whole seconds plus a remainder frame-within-the-second, then
    split the seconds into hours/minutes/seconds. 0-based (the very
    first frame reads 00:00:00:00), matching how every video editor's
    timecode field works, unlike the 1-based frame counter shown beside
    it in TimecodeWidget.

    `fps` is clamped to at least 1 so a malformed or not-yet-set project
    fps of 0 can never divide by zero here -- this is a display
    fallback, not validation, so it deliberately never raises.
    """
    fps = max(1, fps)
    frame_index = max(0, frame_index)
    total_seconds, frame_in_second = divmod(frame_index, fps)
    hours, remainder_seconds = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder_seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_in_second:02d}"


class TimecodeWidget(QWidget):
    """Centered HH:MM:SS:FF timecode + "Frame N / total" readout.

    A thin QWidget wrapping two QLabels laid out side by side -- see
    module docstring for the update contract (set_state()/clear(),
    called by MainWindow) and why both fields exist.
    """

    def __init__(self) -> None:
        """Build the readout, initially in the empty/no-project state."""
        super().__init__()
        self.setObjectName("timecodeWidget")
        # Plain QWidget subclasses don't paint their own QSS background/
        # border by default (only widgets Qt already treats as "chrome",
        # like QFrame, do) -- this opts TimecodeWidget into that so the
        # pill background/border defined in theme.py actually renders,
        # instead of silently doing nothing.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._timecode_label = QLabel(_EMPTY_TIMECODE)
        self._timecode_label.setObjectName("timecodeReadout")
        self._timecode_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )

        self._frame_count_label = QLabel(_EMPTY_FRAME_COUNT)
        self._frame_count_label.setObjectName("timecodeFrameCount")
        self._frame_count_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        # A plain QHBoxLayout with no stretch on either side -- the
        # widget itself is centered as one unit by its parent layout
        # (MainWindow adds it with Qt.AlignmentFlag.AlignHCenter), so
        # this widget only needs to size itself to its own content, not
        # center anything internally.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(10)
        layout.addWidget(self._timecode_label)
        layout.addWidget(self._frame_count_label)

    def set_state(self, current_index: int, total_frames: int, fps: int) -> None:
        """Update the readout to match the given playhead position.

        Args:
            current_index: 0-based playhead position, per
                Timeline.current_index.
            total_frames: Total frame count, per len(Timeline).
            fps: The open project's frames-per-second, per Project.fps --
                used only for the HH:MM:SS:FF field's math.

        Falls back to the empty placeholder (clear()) when total_frames
        is 0 or fewer, rather than showing a misleading "Frame 1 / 0" --
        an empty timeline has no current frame to report a position for.
        """
        if total_frames <= 0:
            self.clear()
            return
        self._timecode_label.setText(format_timecode(current_index, fps))
        self._frame_count_label.setText(f"Frame {current_index + 1} / {total_frames}")

    def clear(self) -> None:
        """Reset to the empty/no-project placeholder state."""
        self._timecode_label.setText(_EMPTY_TIMECODE)
        self._frame_count_label.setText(_EMPTY_FRAME_COUNT)

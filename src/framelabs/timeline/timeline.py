"""Timeline data model for FrameLabs.

Wraps a Project's ordered frame sequence and tracks the current playhead
position. This is the single source of truth for "where are we in the
sequence" that Playback and Onion Skin will both read from.

Per the Developer Handbook, Timeline is a pure data/logic module -- no
file I/O (that's Project/ProjectSerializer) and no Qt/UI code (that's
ui/timeline_widget.py). Frames are read directly from Project.frames, the
same list CaptureService appends to, so Timeline never gets out of sync
with what's captured or saved.
"""

from __future__ import annotations

from framelabs.project.project import Frame, Project


class Timeline:
    """Tracks ordered frame access and playhead position for a Project.

    Attributes:
        project: The Project whose frames this Timeline provides ordered
            access to. Timeline holds no frame data of its own -- it reads
            project.frames directly, so captures/deletes are reflected
            immediately with no manual refresh step.
    """

    def __init__(self, project: Project) -> None:
        """Create a Timeline over a Project's frames, playhead at index 0."""
        self.project = project
        self._current_index = 0

    @property
    def frames(self) -> list[Frame]:
        """Frames in sequence order, sorted by frame number.

        Sorted defensively on every access rather than assumed-sorted --
        cheap at realistic frame counts, and protects against any future
        code path (e.g. reorder) that appends out of order.
        """
        return sorted(self.project.frames, key=lambda f: f.number)

    def __len__(self) -> int:
        """Number of frames in the timeline."""
        return len(self.project.frames)

    @property
    def current_index(self) -> int:
        """The current playhead position, as an index into `frames`."""
        return self._current_index

    @property
    def current_frame(self) -> Frame | None:
        """The frame at the current playhead position, or None if empty."""
        frames = self.frames
        if not frames:
            return None
        return frames[self._current_index]

    def go_to_index(self, index: int) -> None:
        """Move the playhead to a specific index, clamped to valid range.

        Args:
            index: The target index. Out-of-range values are clamped
                rather than raising -- e.g. calling next past the last
                frame lands on the last frame instead of erroring, which
                matches how playback should behave at a boundary.
        """
        if not self.project.frames:
            self._current_index = 0
            return
        self._current_index = max(0, min(index, len(self.project.frames) - 1))

    def next_frame(self) -> Frame | None:
        """Advance the playhead by one frame and return the new current frame.

        Clamped at the last frame -- does not wrap. Looping is Playback's
        responsibility, not Timeline's.
        """
        self.go_to_index(self._current_index + 1)
        return self.current_frame

    def previous_frame(self) -> Frame | None:
        """Move the playhead back by one frame and return the new current frame.

        Clamped at the first frame -- does not wrap.
        """
        self.go_to_index(self._current_index - 1)
        return self.current_frame

    def frames_before_current(self, count: int) -> list[Frame]:
        """Return up to `count` frames immediately before the current one.

        Ordered nearest-first (current-1, current-2, ...), since Onion
        Skin's opacity typically falls off with distance from the current
        frame. Returns fewer than `count` if near the start of the
        sequence.
        """
        frames = self.frames
        start = max(0, self._current_index - count)
        return list(reversed(frames[start : self._current_index]))

    def frames_after_current(self, count: int) -> list[Frame]:
        """Return up to `count` frames immediately after the current one.

        Ordered nearest-first (current+1, current+2, ...).
        """
        frames = self.frames
        end = min(len(frames), self._current_index + 1 + count)
        return frames[self._current_index + 1 : end]

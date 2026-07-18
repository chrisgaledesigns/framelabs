"""Concrete Command subclasses wrapping capture_service's per-frame actions.

Per core/command.py's own module docstring, concrete commands live
alongside the service they wrap, not in core/ itself. This module
currently defines DuplicateFrameCommand only -- DeleteFrameCommand and
ReplaceFrameCommand are deferred until the right-click menu / action bar
UI that will actually trigger them exists (see the hand-off), but should
follow this same pattern when they're added.
"""

from __future__ import annotations

from framelabs.capture.capture_service import delete_frame, duplicate_frame
from framelabs.core.command import Command
from framelabs.core.event_bus import EventBus
from framelabs.project.project import Project


class DuplicateFrameCommand(Command):
    """Duplicate a frame; undoable by deleting the frame it created.

    Undo needs no backup data of its own (discard() stays the default
    no-op inherited from Command) -- undoing a duplicate is just removing
    a frame that's otherwise indistinguishable from any other frame in the
    project, and delete_frame() already does that safely.

    Redo re-runs duplicate_frame() from scratch rather than replaying
    stored file bytes. This means a redo occurring after other frames have
    since been added or removed can land on a different frame number than
    the original duplicate did -- that's correct, not a bug:
    capture_service's "no duplicate frame numbers" rule always takes
    priority over reproducing the exact prior number.
    """

    def __init__(
        self, project: Project, event_bus: EventBus, frame_number: int
    ) -> None:
        """Prepare to duplicate `frame_number`. Does not execute anything yet.

        Args:
            project: The active project. Must have a non-None project_path.
            event_bus: The event bus duplicate_frame()/delete_frame() will
                publish on.
            frame_number: The existing frame to duplicate.
        """
        self._project = project
        self._event_bus = event_bus
        self._source_frame_number = frame_number
        # Set by do() on every call (initial execution AND every redo) --
        # see the class docstring for why a redo is not guaranteed to
        # reproduce the same number as the original duplicate.
        self._duplicate_frame_number: int | None = None

    @property
    def description(self) -> str:
        """Human-readable label, e.g. "Duplicate Frame 12"."""
        return f"Duplicate Frame {self._source_frame_number}"

    def do(self) -> None:
        """Duplicate the source frame, appended as a new frame at the end."""
        new_frame = duplicate_frame(
            self._project, self._event_bus, self._source_frame_number
        )
        self._duplicate_frame_number = new_frame.number

    def undo(self) -> None:
        """Delete the frame this command's most recent do() created.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._duplicate_frame_number is None:
            raise RuntimeError(
                "DuplicateFrameCommand.undo() called before do() -- "
                "nothing to undo yet."
            )
        delete_frame(self._project, self._event_bus, self._duplicate_frame_number)

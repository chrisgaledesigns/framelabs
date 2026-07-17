"""Base class for undoable/redoable actions.

Concrete subclasses live alongside the service they wrap (e.g. a future
DeleteFrameCommand in capture/commands.py, wrapping CaptureService.delete_
frame), not here -- this module only defines the shape every action must
follow so UndoManager can treat them all the same way.

Example:
    class RenameProjectCommand(Command):
        def __init__(self, project, old_name, new_name):
            self._project = project
            self._old_name = old_name
            self._new_name = new_name

        @property
        def description(self):
            return f"Rename Project to {self._new_name}"

        def do(self):
            self._project.name = self._new_name

        def undo(self):
            self._project.name = self._old_name
"""

from abc import ABC, abstractmethod


class Command(ABC):
    """A single undoable/redoable action.

    A Command must capture whatever data it needs to reverse itself
    *before* do() first runs, since undo() has to restore prior state
    without re-deriving it from anything that may have already changed
    by the time undo() is called.
    """

    @property
    @abstractmethod
    def description(self) -> str:
        """Short, human-readable label for this action.

        E.g. "Delete Frame 152". Used for logging, and can back a future
        Edit menu's "Undo Delete Frame 152" label.
        """

    @abstractmethod
    def do(self) -> None:
        """Perform the action. Called on initial execution and again on redo."""

    @abstractmethod
    def undo(self) -> None:
        """Reverse the action performed by do()."""

    def discard(self) -> None:
        """Release any backup data held outside normal project state.

        Called by UndoManager when this command permanently falls out of
        history -- either evicted past the history limit, or the project
        closes. Default is a no-op; only commands holding onto something
        outside the project's own state (e.g. a deleted frame's image kept
        in cache/ so undo can restore it) need to override this.
        """
        return None

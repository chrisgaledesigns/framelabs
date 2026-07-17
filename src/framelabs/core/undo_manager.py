"""Command history: the undo/redo stack for user-initiated actions.

Example:
    manager = UndoManager()
    manager.execute(DeleteFrameCommand(capture_service, frame_number=152))
    manager.undo()  # frame 152 is restored
    manager.redo()  # frame 152 is deleted again
"""

from collections import deque

from framelabs.core.command import Command
from framelabs.core.logger import get_logger

logger = get_logger("core.undo_manager")

# Developer Handbook, Feature 9: "History: 100 actions minimum."
MAX_HISTORY = 100


class UndoManager:
    """Tracks executed Commands and lets them be undone/redone.

    Session-only for now: history lives in memory and is not persisted
    across a project closing and reopening -- a deliberate alpha-scope
    decision, may be revisited later.
    """

    def __init__(self, max_history: int = MAX_HISTORY) -> None:
        self._undo_stack: deque[Command] = deque(maxlen=max_history)
        self._redo_stack: list[Command] = []

    def execute(self, command: Command) -> None:
        """Run a new command and push it onto the undo stack.

        Any pending redo history is discarded -- once a new action happens,
        the "future" a pending redo would have replayed no longer applies,
        same as every other undo/redo implementation.
        """
        command.do()
        self._push_undo(command)
        self._redo_stack.clear()
        logger.info("Command executed: %s", command.description)

    def undo(self) -> bool:
        """Undo the most recently executed command, if any.

        Returns True if a command was undone, False if there was nothing
        to undo -- lets a caller check without a separate can_undo() call.
        """
        if not self._undo_stack:
            logger.info("Undo requested with empty undo stack; no-op.")
            return False

        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        logger.info("Command undone: %s", command.description)
        return True

    def redo(self) -> bool:
        """Redo the most recently undone command, if any.

        Returns True if a command was redone, False if there was nothing
        to redo.
        """
        if not self._redo_stack:
            logger.info("Redo requested with empty redo stack; no-op.")
            return False

        command = self._redo_stack.pop()
        command.do()
        self._push_undo(command)
        logger.info("Command redone: %s", command.description)
        return True

    def can_undo(self) -> bool:
        """Whether there is a command available to undo."""
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """Whether there is a command available to redo."""
        return bool(self._redo_stack)

    def clear(self) -> None:
        """Discard all undo/redo history, e.g. when a project closes.

        Calls discard() on every held command first, so any backup data
        they're holding outside normal project state doesn't outlive the
        session.
        """
        for command in list(self._undo_stack) + self._redo_stack:
            command.discard()
        self._undo_stack.clear()
        self._redo_stack.clear()
        logger.info("Undo/redo history cleared.")

    def _push_undo(self, command: Command) -> None:
        """Append to the undo stack, discarding the oldest entry if full.

        deque(maxlen=...) would otherwise evict the oldest entry silently
        on append, with no chance for that command to release any backup
        data it's holding (e.g. a deleted frame's image in cache/). This
        pops and discards it explicitly first instead.
        """
        if len(self._undo_stack) == self._undo_stack.maxlen:
            evicted = self._undo_stack.popleft()
            evicted.discard()
            logger.info(
                "Command evicted at %d-action history limit: %s",
                self._undo_stack.maxlen,
                evicted.description,
            )
        self._undo_stack.append(command)

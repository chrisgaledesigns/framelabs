"""Tests for UndoManager."""

from framelabs.core.command import Command
from framelabs.core.undo_manager import UndoManager


class _FakeCommand(Command):
    """A minimal real Command for exercising UndoManager -- not a mock.

    Appends to a shared events list so tests can assert on the actual
    order do/undo/discard happened in.
    """

    def __init__(self, label, events):
        self._label = label
        self._events = events

    @property
    def description(self):
        return self._label

    def do(self):
        self._events.append(f"do:{self._label}")

    def undo(self):
        self._events.append(f"undo:{self._label}")

    def discard(self):
        self._events.append(f"discard:{self._label}")


def test_execute_runs_command_and_adds_to_undo_stack():
    events = []
    manager = UndoManager()

    manager.execute(_FakeCommand("a", events))

    assert events == ["do:a"]
    assert manager.can_undo() is True
    assert manager.can_redo() is False


def test_undo_reverses_most_recent_command():
    events = []
    manager = UndoManager()
    manager.execute(_FakeCommand("a", events))

    result = manager.undo()

    assert result is True
    assert events == ["do:a", "undo:a"]
    assert manager.can_undo() is False
    assert manager.can_redo() is True


def test_undo_with_empty_stack_returns_false():
    manager = UndoManager()

    assert manager.undo() is False


def test_redo_reruns_the_undone_command():
    events = []
    manager = UndoManager()
    manager.execute(_FakeCommand("a", events))
    manager.undo()

    result = manager.redo()

    assert result is True
    assert events == ["do:a", "undo:a", "do:a"]
    assert manager.can_undo() is True
    assert manager.can_redo() is False


def test_redo_with_empty_stack_returns_false():
    manager = UndoManager()

    assert manager.redo() is False


def test_new_command_after_undo_clears_redo_stack():
    events = []
    manager = UndoManager()
    manager.execute(_FakeCommand("a", events))
    manager.undo()

    manager.execute(_FakeCommand("b", events))

    assert manager.can_redo() is False


def test_undo_redo_multiple_commands_in_correct_order():
    events = []
    manager = UndoManager()
    manager.execute(_FakeCommand("a", events))
    manager.execute(_FakeCommand("b", events))

    manager.undo()
    manager.undo()

    assert events == ["do:a", "do:b", "undo:b", "undo:a"]


def test_history_beyond_max_evicts_oldest_and_calls_discard():
    events = []
    manager = UndoManager(max_history=2)
    manager.execute(_FakeCommand("a", events))
    manager.execute(_FakeCommand("b", events))
    manager.execute(_FakeCommand("c", events))

    assert "discard:a" in events

    # Only "b" and "c" remain reachable -- "a" was evicted, not just hidden.
    manager.undo()
    manager.undo()
    assert manager.undo() is False


def test_clear_discards_all_held_commands():
    events = []
    manager = UndoManager()
    manager.execute(_FakeCommand("a", events))
    manager.execute(_FakeCommand("b", events))
    manager.undo()  # "b" moves to the redo stack, "a" stays on the undo stack

    manager.clear()

    assert "discard:a" in events
    assert "discard:b" in events
    assert manager.can_undo() is False
    assert manager.can_redo() is False


def test_default_discard_is_a_noop():
    class _MinimalCommand(Command):
        @property
        def description(self):
            return "minimal"

        def do(self):
            pass

        def undo(self):
            pass

    # Should not raise -- Command's own discard() is a no-op by default.
    _MinimalCommand().discard()

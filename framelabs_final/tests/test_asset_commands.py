"""Tests for framelabs.project.asset_commands."""

import pytest

from framelabs.core.event_bus import EventBus
from framelabs.core.undo_manager import UndoManager
from framelabs.project.asset_commands import AddAssetCommand, RemoveAssetCommand
from framelabs.project.creator import create_new_project


def _make_project(tmp_path):
    return create_new_project(
        name="Test Project", parent_dir=tmp_path, fps=12, resolution=(1920, 1080)
    )


def _make_source_file(tmp_path, name="clip.wav", content=b"fake audio bytes"):
    source = tmp_path / name
    source.write_bytes(content)
    return source


def test_add_asset_command_do_copies_and_tracks(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)

    command = AddAssetCommand(project, event_bus, "audio", source)
    command.do()

    assert project.audio == ["audio/clip.wav"]
    assert (project.project_path / "audio" / "clip.wav").exists()


def test_add_asset_command_undo_removes_it(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)

    command = AddAssetCommand(project, event_bus, "audio", source)
    command.do()
    command.undo()

    assert project.audio == []
    assert not (project.project_path / "audio" / "clip.wav").exists()
    # Original source file is never touched.
    assert source.exists()


def test_add_asset_command_redo_recopies_file(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)

    command = AddAssetCommand(project, event_bus, "audio", source)
    command.do()
    command.undo()
    command.do()

    assert project.audio == ["audio/clip.wav"]
    assert (project.project_path / "audio" / "clip.wav").exists()


def test_add_asset_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)

    command = AddAssetCommand(project, event_bus, "audio", source)

    with pytest.raises(RuntimeError):
        command.undo()


def test_add_asset_command_description(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path, "scratch_track.wav")

    command = AddAssetCommand(project, event_bus, "audio", source)

    assert command.description == "Add Audio scratch_track.wav"


def test_remove_asset_command_do_deletes_and_untracks(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    AddAssetCommand(project, event_bus, "audio", source).do()

    command = RemoveAssetCommand(project, event_bus, "audio", "audio/clip.wav")
    command.do()

    assert project.audio == []
    assert not (project.project_path / "audio" / "clip.wav").exists()


def test_remove_asset_command_undo_restores_file_and_tracking(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    AddAssetCommand(project, event_bus, "audio", source).do()

    command = RemoveAssetCommand(project, event_bus, "audio", "audio/clip.wav")
    command.do()
    command.undo()

    assert project.audio == ["audio/clip.wav"]
    restored = project.project_path / "audio" / "clip.wav"
    assert restored.exists()
    assert restored.read_bytes() == b"fake audio bytes"


def test_remove_asset_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    command = RemoveAssetCommand(project, event_bus, "audio", "audio/clip.wav")

    with pytest.raises(RuntimeError):
        command.undo()


def test_remove_asset_command_discard_deletes_backup(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    AddAssetCommand(project, event_bus, "audio", source).do()

    command = RemoveAssetCommand(project, event_bus, "audio", "audio/clip.wav")
    command.do()
    backup_dir = command._backup_dir
    assert backup_dir.exists()

    command.discard()

    assert not backup_dir.exists()


def test_add_then_remove_asset_via_undo_manager_full_cycle(tmp_path):
    """Exercise both commands through the real UndoManager, not called directly."""
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    manager = UndoManager()

    manager.execute(AddAssetCommand(project, event_bus, "audio", source))
    assert project.audio == ["audio/clip.wav"]

    manager.execute(RemoveAssetCommand(project, event_bus, "audio", "audio/clip.wav"))
    assert project.audio == []
    assert manager.can_undo() is True

    manager.undo()
    assert project.audio == ["audio/clip.wav"]

    manager.undo()
    assert project.audio == []
    assert manager.can_redo() is True

    manager.redo()
    assert project.audio == ["audio/clip.wav"]

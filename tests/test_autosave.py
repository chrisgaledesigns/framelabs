"""Tests for project/autosave.py (Feature 8)."""

import time

import pytest

from framelabs.project.autosave import (
    MAX_AUTOSAVES,
    find_latest_autosave,
    has_recoverable_autosave,
    restore_autosave,
    write_autosave,
)
from framelabs.project.project import Frame, Project
from framelabs.project.serializer import CURRENT_VERSION, ProjectSerializer


def _make_project(project_path, name="Robot Walk Cycle", frame_count=1):
    return Project(
        version=CURRENT_VERSION,
        name=name,
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[
            Frame(number=n, file=f"images/{n:06d}.png")
            for n in range(1, frame_count + 1)
        ],
        project_path=project_path,
    )


def test_write_autosave_creates_autosave_dir_and_file(tmp_path):
    project = _make_project(tmp_path)

    autosave_path = write_autosave(project)

    assert autosave_path.exists()
    assert autosave_path.parent == tmp_path / ".autosave"


def test_write_autosave_raises_with_no_project_path():
    project = _make_project(project_path=None)

    with pytest.raises(ValueError):
        write_autosave(project)


def test_write_autosave_matches_project_state(tmp_path):
    project = _make_project(tmp_path, frame_count=3)

    autosave_path = write_autosave(project)
    restored = ProjectSerializer.load_from_path(autosave_path, tmp_path)

    assert [f.number for f in restored.frames] == [1, 2, 3]
    assert restored.name == "Robot Walk Cycle"


def test_find_latest_autosave_returns_none_when_no_autosaves(tmp_path):
    assert find_latest_autosave(tmp_path) is None


def test_find_latest_autosave_returns_most_recent(tmp_path):
    project = _make_project(tmp_path)

    write_autosave(project)
    time.sleep(0.01)
    project.name = "Renamed Mid-Session"
    latest_path = write_autosave(project)

    assert find_latest_autosave(tmp_path) == latest_path


def test_write_autosave_prunes_beyond_max_autosaves(tmp_path):
    project = _make_project(tmp_path)

    for _ in range(MAX_AUTOSAVES + 5):
        write_autosave(project)
        time.sleep(0.001)

    remaining = sorted((tmp_path / ".autosave").glob("autosave_*.ffproj"))
    assert len(remaining) == MAX_AUTOSAVES


def test_write_autosave_keeps_the_newest_snapshots_when_pruning(tmp_path):
    project = _make_project(tmp_path)

    first_autosave = write_autosave(project)
    for _ in range(MAX_AUTOSAVES):
        time.sleep(0.001)
        write_autosave(project)

    assert not first_autosave.exists()


def test_has_recoverable_autosave_false_with_no_autosave(tmp_path):
    assert has_recoverable_autosave(tmp_path) is False


def test_has_recoverable_autosave_true_when_project_ffproj_missing(tmp_path):
    project = _make_project(tmp_path)
    write_autosave(project)

    assert has_recoverable_autosave(tmp_path) is True


def test_has_recoverable_autosave_true_when_autosave_newer(tmp_path):
    project = _make_project(tmp_path)

    ProjectSerializer.save(project)
    time.sleep(0.01)
    write_autosave(project)

    assert has_recoverable_autosave(tmp_path) is True


def test_has_recoverable_autosave_false_when_project_ffproj_is_current(tmp_path):
    project = _make_project(tmp_path)

    write_autosave(project)
    time.sleep(0.01)
    ProjectSerializer.save(project)

    assert has_recoverable_autosave(tmp_path) is False


def test_restore_autosave_raises_when_none_exists(tmp_path):
    with pytest.raises(FileNotFoundError):
        restore_autosave(tmp_path)


def test_restore_autosave_returns_project_with_real_project_path(tmp_path):
    project = _make_project(tmp_path, frame_count=2)
    write_autosave(project)

    restored = restore_autosave(tmp_path)

    assert restored.project_path == tmp_path
    assert [f.number for f in restored.frames] == [1, 2]

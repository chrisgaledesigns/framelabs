"""Tests for Project.working_range: SetWorkingRangeCommand and serializer.

Self-contained (builds its own Project/EventBus fixtures directly rather
than relying on conftest fixtures shared with other test modules), since
working_range cuts across project/composite_commands.py and
project/serializer.py rather than living in either's existing test file.
"""

from __future__ import annotations

import json

import pytest

from framelabs.core.event_bus import EventBus
from framelabs.project.composite_commands import SetWorkingRangeCommand
from framelabs.project.project import Frame, Project
from framelabs.project.serializer import (
    CURRENT_VERSION,
    ProjectSerializer,
)


@pytest.fixture
def project(tmp_path):
    """A minimal Project with 10 frames, saved under a temp project_path."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()
    proj = Project(
        version=CURRENT_VERSION,
        name="Test Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=[Frame(number=i, file=f"images/{i:06d}.png") for i in range(10)],
        project_path=project_path,
    )
    # save()/load() create these on load, but save() alone doesn't --
    # create them up front so save() (called by the command under test)
    # never has to.
    for subfolder in ("audio", "references", "overlays"):
        (project_path / subfolder).mkdir(exist_ok=True)
    return proj


@pytest.fixture
def event_bus():
    return EventBus()


class TestSetWorkingRangeCommand:
    def test_do_sets_working_range(self, project, event_bus):
        command = SetWorkingRangeCommand(project, event_bus, (2, 7))
        command.do()
        assert project.working_range == (2, 7)

    def test_do_publishes_working_range_changed(self, project, event_bus):
        received = []
        event_bus.subscribe("WORKING_RANGE_CHANGED", received.append)

        command = SetWorkingRangeCommand(project, event_bus, (2, 7))
        command.do()

        assert received == [{"working_range": (2, 7)}]

    def test_undo_restores_previous_range(self, project, event_bus):
        project.working_range = (0, 3)
        command = SetWorkingRangeCommand(project, event_bus, (2, 7))
        command.do()
        command.undo()
        assert project.working_range == (0, 3)

    def test_undo_publishes_working_range_changed_with_old_value(
        self, project, event_bus
    ):
        project.working_range = (0, 3)
        received = []
        command = SetWorkingRangeCommand(project, event_bus, (2, 7))
        command.do()
        event_bus.subscribe("WORKING_RANGE_CHANGED", received.append)
        command.undo()

        assert received == [{"working_range": (0, 3)}]

    def test_none_clears_working_range(self, project, event_bus):
        project.working_range = (2, 7)
        command = SetWorkingRangeCommand(project, event_bus, None)
        command.do()
        assert project.working_range is None

    def test_rejects_start_greater_than_end(self, project, event_bus):
        with pytest.raises(ValueError):
            SetWorkingRangeCommand(project, event_bus, (7, 2))

    def test_do_saves_project(self, project, event_bus):
        command = SetWorkingRangeCommand(project, event_bus, (2, 7))
        command.do()

        on_disk = json.loads(
            (project.project_path / "project.ffproj").read_text(encoding="utf-8")
        )
        assert on_disk["working_range"] == [2, 7]


class TestWorkingRangeSerialization:
    def test_round_trip_with_range_set(self, project):
        project.working_range = (3, 8)
        ProjectSerializer.save(project)

        loaded = ProjectSerializer.load(project.project_path)

        assert loaded.working_range == (3, 8)

    def test_round_trip_with_no_range_set(self, project):
        assert project.working_range is None
        ProjectSerializer.save(project)

        loaded = ProjectSerializer.load(project.project_path)

        assert loaded.working_range is None

    def test_loading_pre_v5_file_defaults_to_none(self, project):
        """A v4 file (or earlier) has no 'working_range' key at all --
        confirms the .get()-based default keeps old projects loadable
        without a hard failure, per the Handbook's forward-compatibility
        rule the same way composite_layers handled this for v1-v3 files.
        """
        ProjectSerializer.save(project)
        file_path = project.project_path / "project.ffproj"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        data["version"] = 4
        del data["working_range"]
        file_path.write_text(json.dumps(data), encoding="utf-8")

        loaded = ProjectSerializer.load(project.project_path)

        assert loaded.working_range is None
        assert loaded.version == CURRENT_VERSION  # upgraded in memory

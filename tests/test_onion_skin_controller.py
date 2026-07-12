"""Tests for OnionSkinController -- real file I/O via tmp_path, no real
QThread (calls the handler directly and inspects emitted signal args via
a MagicMock connected to the real signal, per the project's established
QObject/Signal testing pattern).
"""

from unittest.mock import MagicMock

import pytest

from framelabs.project.project import Frame, Project
from framelabs.timeline.onion_skin import OnionSkinSettings
from framelabs.timeline.timeline import Timeline
from framelabs.ui.onion_skin_controller import OnionSkinController


def _make_project_with_frames(tmp_path, frame_numbers):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    frames = []
    for number in frame_numbers:
        file_name = f"images/{number:06d}.png"
        (tmp_path / file_name).write_bytes(f"fake-png-{number}".encode())
        frames.append(Frame(number=number, file=file_name))
    return Project(
        version=1,
        name="Test",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=frames,
        project_path=tmp_path,
    )


@pytest.fixture
def controller():
    controller = OnionSkinController()
    controller.frames_ready_slot = MagicMock()
    controller.frames_ready.connect(controller.frames_ready_slot)
    return controller


def test_disabled_settings_emits_empty_lists(tmp_path, controller):
    project = _make_project_with_frames(tmp_path, [1, 2, 3])
    timeline = Timeline(project)
    timeline.go_to_index(1)
    settings = OnionSkinSettings(enabled=False)

    controller._handle_refresh_requested(timeline, settings)

    controller.frames_ready_slot.assert_called_once_with([], [])


def test_loads_before_and_after_frames_nearest_first(tmp_path, controller):
    project = _make_project_with_frames(tmp_path, [1, 2, 3, 4, 5])
    timeline = Timeline(project)
    timeline.go_to_index(2)  # current frame = 3
    settings = OnionSkinSettings(
        enabled=True,
        opacity=0.4,
        previous_count=2,
        next_count=1,
        previous_tint="#3399ff",
        next_tint="#ff3333",
    )

    controller._handle_refresh_requested(timeline, settings)

    before_layers, after_layers = controller.frames_ready_slot.call_args[0]

    assert len(before_layers) == 2
    assert before_layers[0] == (b"fake-png-2", pytest.approx(0.4), "#3399ff")
    assert before_layers[1] == (b"fake-png-1", pytest.approx(0.2), "#3399ff")

    assert len(after_layers) == 1
    assert after_layers[0] == (b"fake-png-4", pytest.approx(0.4), "#ff3333")


def test_missing_frame_file_is_skipped(tmp_path, controller):
    project = _make_project_with_frames(tmp_path, [1, 2])
    # Delete frame 1's file to simulate a missing frame.
    (tmp_path / "images" / "000001.png").unlink()
    timeline = Timeline(project)
    timeline.go_to_index(1)  # current frame = 2
    settings = OnionSkinSettings(enabled=True, previous_count=1, next_count=0)

    controller._handle_refresh_requested(timeline, settings)

    before_layers, after_layers = controller.frames_ready_slot.call_args[0]
    assert before_layers == []
    assert after_layers == []


def test_no_project_path_returns_empty_layers(tmp_path, controller):
    project = _make_project_with_frames(tmp_path, [1, 2, 3])
    project.project_path = None
    timeline = Timeline(project)
    timeline.go_to_index(1)
    settings = OnionSkinSettings(enabled=True, previous_count=1, next_count=1)

    controller._handle_refresh_requested(timeline, settings)

    before_layers, after_layers = controller.frames_ready_slot.call_args[0]
    assert before_layers == []
    assert after_layers == []


def test_near_start_returns_fewer_before_layers(tmp_path, controller):
    project = _make_project_with_frames(tmp_path, [1, 2, 3])
    timeline = Timeline(project)
    timeline.go_to_index(0)  # current frame = 1, nothing before it
    settings = OnionSkinSettings(enabled=True, previous_count=2, next_count=2)

    controller._handle_refresh_requested(timeline, settings)

    before_layers, after_layers = controller.frames_ready_slot.call_args[0]
    assert before_layers == []
    assert len(after_layers) == 2

"""Unit tests for Timeline."""

from pathlib import Path

from framelabs.project.project import Frame, Project
from framelabs.timeline.timeline import Timeline


def _make_project(frame_numbers: list[int]) -> Project:
    return Project(
        version=1,
        name="Test",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=[Frame(number=n, file=f"images/{n:06d}.png") for n in frame_numbers],
        project_path=Path("/fake/path"),
    )


def test_empty_timeline_has_no_current_frame():
    timeline = Timeline(_make_project([]))
    assert len(timeline) == 0
    assert timeline.current_frame is None


def test_frames_are_sorted_by_number():
    timeline = Timeline(_make_project([3, 1, 2]))
    assert [f.number for f in timeline.frames] == [1, 2, 3]


def test_current_frame_starts_at_first():
    timeline = Timeline(_make_project([1, 2, 3]))
    assert timeline.current_index == 0
    assert timeline.current_frame.number == 1


def test_next_frame_advances():
    timeline = Timeline(_make_project([1, 2, 3]))
    frame = timeline.next_frame()
    assert frame.number == 2
    assert timeline.current_index == 1


def test_next_frame_clamps_at_end():
    timeline = Timeline(_make_project([1, 2]))
    timeline.next_frame()
    frame = timeline.next_frame()
    assert frame.number == 2
    assert timeline.current_index == 1


def test_previous_frame_moves_back():
    timeline = Timeline(_make_project([1, 2, 3]))
    timeline.go_to_index(2)
    frame = timeline.previous_frame()
    assert frame.number == 2
    assert timeline.current_index == 1


def test_previous_frame_clamps_at_start():
    timeline = Timeline(_make_project([1, 2, 3]))
    frame = timeline.previous_frame()
    assert frame.number == 1
    assert timeline.current_index == 0


def test_go_to_index_clamps_high():
    timeline = Timeline(_make_project([1, 2, 3]))
    timeline.go_to_index(99)
    assert timeline.current_index == 2


def test_go_to_index_clamps_low():
    timeline = Timeline(_make_project([1, 2, 3]))
    timeline.go_to_index(-5)
    assert timeline.current_index == 0


def test_go_to_index_on_empty_timeline_stays_zero():
    timeline = Timeline(_make_project([]))
    timeline.go_to_index(5)
    assert timeline.current_index == 0


def test_timeline_reflects_live_append_to_project_frames():
    project = _make_project([1, 2])
    timeline = Timeline(project)
    assert len(timeline) == 2
    project.frames.append(Frame(number=3, file="images/000003.png"))
    assert len(timeline) == 3
    assert timeline.frames[-1].number == 3


def test_frames_before_current_nearest_first():
    timeline = Timeline(_make_project([1, 2, 3, 4, 5]))
    timeline.go_to_index(4)
    before = timeline.frames_before_current(2)
    assert [f.number for f in before] == [4, 3]


def test_frames_before_current_near_start_returns_fewer():
    timeline = Timeline(_make_project([1, 2, 3]))
    timeline.go_to_index(1)
    before = timeline.frames_before_current(5)
    assert [f.number for f in before] == [1]


def test_frames_after_current_nearest_first():
    timeline = Timeline(_make_project([1, 2, 3, 4, 5]))
    timeline.go_to_index(0)
    after = timeline.frames_after_current(2)
    assert [f.number for f in after] == [2, 3]


def test_frames_after_current_near_end_returns_fewer():
    timeline = Timeline(_make_project([1, 2, 3]))
    timeline.go_to_index(1)
    after = timeline.frames_after_current(5)
    assert [f.number for f in after] == [3]

"""Tests for framelabs.ui.playback_controller.PlaybackController."""

from unittest.mock import MagicMock

from framelabs.project.project import Frame, Project
from framelabs.timeline.playback import PlaybackSettings
from framelabs.timeline.timeline import Timeline
from framelabs.ui.playback_controller import PlaybackController


def _make_project(tmp_path, frame_numbers, fps=12):
    """Build a real Project with real frame files on disk under tmp_path."""
    project = Project(
        version=1,
        name="Test Project",
        fps=fps,
        resolution=(640, 480),
        camera_model=None,
        camera_lens=None,
        project_path=tmp_path,
    )
    (tmp_path / "images").mkdir()
    for number in frame_numbers:
        file_name = f"images/{number:06d}.png"
        (tmp_path / file_name).write_bytes(f"fake-png-bytes-{number}".encode())
        project.frames.append(Frame(number=number, file=file_name))
    return project


def test_advance_with_no_timeline_or_settings_is_noop():
    controller = PlaybackController()
    frame_ready = MagicMock()
    controller.frame_ready.connect(frame_ready)

    controller._advance()

    frame_ready.assert_not_called()


def test_handle_start_requested_starts_timer_with_correct_interval(tmp_path):
    project = _make_project(tmp_path, [1, 2, 3], fps=12)
    timeline = Timeline(project)
    settings = PlaybackSettings(speed_percent=100)

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    assert controller._timer.isActive()
    assert controller._timer.interval() == round(1000 / 12)


def test_handle_stop_requested_stops_timer(tmp_path):
    project = _make_project(tmp_path, [1, 2], fps=12)
    timeline = Timeline(project)
    settings = PlaybackSettings()

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)
    controller._handle_stop_requested()

    assert not controller._timer.isActive()


def test_advance_with_empty_timeline_stops_and_emits_finished(tmp_path):
    project = _make_project(tmp_path, [])
    timeline = Timeline(project)
    settings = PlaybackSettings()

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    finished = MagicMock()
    controller.playback_finished.connect(finished)

    controller._advance()

    finished.assert_called_once()
    assert not controller._timer.isActive()


def test_advance_not_at_end_advances_playhead_and_emits_frame(tmp_path):
    project = _make_project(tmp_path, [1, 2, 3], fps=12)
    timeline = Timeline(project)
    settings = PlaybackSettings()

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    frame_ready = MagicMock()
    playhead_advanced = MagicMock()
    controller.frame_ready.connect(frame_ready)
    controller.playhead_advanced.connect(playhead_advanced)

    controller._advance()

    assert timeline.current_index == 1
    frame_ready.assert_called_once_with(b"fake-png-bytes-2")
    playhead_advanced.assert_called_once()


def test_advance_at_end_without_loop_stops_and_emits_finished(tmp_path):
    """Reaching the end with Loop off should stop playback AND reset the
    playhead back to frame 0, so the sequence is immediately ready to play
    again without the user manually reselecting a starting frame.
    playhead_advanced must fire alongside playback_finished so MainWindow's
    existing handler refreshes the Timeline widget's selection border to
    match frame 0.
    """
    project = _make_project(tmp_path, [1, 2], fps=12)
    timeline = Timeline(project)
    timeline.go_to_index(1)  # already at the last frame
    settings = PlaybackSettings(loop=False)

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    finished = MagicMock()
    frame_ready = MagicMock()
    playhead_advanced = MagicMock()
    controller.playback_finished.connect(finished)
    controller.frame_ready.connect(frame_ready)
    controller.playhead_advanced.connect(playhead_advanced)

    controller._advance()

    finished.assert_called_once()
    playhead_advanced.assert_called_once()
    frame_ready.assert_not_called()
    assert not controller._timer.isActive()
    assert timeline.current_index == 0


def test_advance_at_end_with_loop_wraps_to_start(tmp_path):
    project = _make_project(tmp_path, [1, 2], fps=12)
    timeline = Timeline(project)
    timeline.go_to_index(1)
    settings = PlaybackSettings(loop=True)

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    frame_ready = MagicMock()
    controller.frame_ready.connect(frame_ready)

    controller._advance()

    assert timeline.current_index == 0
    frame_ready.assert_called_once_with(b"fake-png-bytes-1")


def test_advance_recomputes_interval_from_live_speed_change(tmp_path):
    project = _make_project(tmp_path, [1, 2, 3], fps=12)
    timeline = Timeline(project)
    settings = PlaybackSettings(speed_percent=100)

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)
    assert controller._timer.interval() == round(1000 / 12)

    settings.speed_percent = 200
    controller._advance()

    assert controller._timer.interval() == round((1000 / 12) / 2)


def test_read_frame_bytes_missing_file_still_advances_playhead(tmp_path):
    project = _make_project(tmp_path, [1, 2], fps=12)
    timeline = Timeline(project)
    (tmp_path / "images" / "000002.png").unlink()
    settings = PlaybackSettings()

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    frame_ready = MagicMock()
    playhead_advanced = MagicMock()
    controller.frame_ready.connect(frame_ready)
    controller.playhead_advanced.connect(playhead_advanced)

    controller._advance()

    frame_ready.assert_not_called()
    playhead_advanced.assert_called_once()
    assert timeline.current_index == 1


def test_read_frame_bytes_no_project_path_returns_none(tmp_path):
    project = _make_project(tmp_path, [1, 2], fps=12)
    project.project_path = None
    timeline = Timeline(project)
    settings = PlaybackSettings()

    controller = PlaybackController()
    controller._handle_start_requested(timeline, settings)

    frame_ready = MagicMock()
    controller.frame_ready.connect(frame_ready)

    controller._advance()

    frame_ready.assert_not_called()

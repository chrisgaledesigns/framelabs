"""Tests for framelabs.export.export_service."""

import cv2
import numpy as np
import pytest
from PIL import Image

from framelabs.core.event_bus import EventBus
from framelabs.export.export_service import (
    ExportProgress,
    ExportRequest,
    ExportServiceError,
    export_all,
    export_gif,
    export_image_sequence,
    export_video,
)
from framelabs.project.creator import create_new_project
from framelabs.project.project import Frame


def _make_project(tmp_path, fps=12, resolution=(64, 48)):
    return create_new_project(
        name="Robot Walk Cycle",
        parent_dir=tmp_path,
        fps=fps,
        resolution=resolution,
    )


def _add_frame(project, number):
    """Write a real, correctly-sized PNG and append a matching Frame.

    Each frame's fill value varies with `number` so consecutive frames
    are never byte-identical -- Pillow's GIF writer silently merges
    truly-identical consecutive frames into one, which would make
    test_export_gif_writes_looping_animation's frame count assertion
    fail for reasons that have nothing to do with export_gif() itself.
    """
    width, height = project.resolution
    image = np.full((height, width, 3), number % 255, dtype=np.uint8)
    filename = f"images/{number:06d}.png"
    cv2.imwrite(str(project.project_path / filename), image)
    project.frames.append(Frame(number=number, file=filename))


def test_export_video_writes_playable_mp4(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()

    output_path = export_video(project, event_bus, "basename")

    assert output_path.exists()
    assert output_path.suffix == ".mp4"
    capture = cv2.VideoCapture(str(output_path))
    assert capture.isOpened()
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 2
    capture.release()


def test_export_video_publishes_event(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()
    received = []
    event_bus.subscribe("VIDEO_EXPORTED", received.append)

    export_video(project, event_bus, "basename")

    assert len(received) == 1


def test_export_video_no_frames_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    with pytest.raises(ExportServiceError):
        export_video(project, event_bus, "basename")


def test_export_video_explicit_codec_is_honored(tmp_path):
    """Passing an explicit FourCC rather than "auto" should use only
    that codec -- mirrors the Export dialog's codec dropdown letting the
    user pick MPEG-4 deliberately rather than always trying H.264
    first."""
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()

    output_path = export_video(project, event_bus, "basename", codec="mp4v")

    assert output_path.exists()
    capture = cv2.VideoCapture(str(output_path))
    assert capture.isOpened()
    capture.release()


def test_export_video_explicit_unsupported_codec_raises_no_fallback(tmp_path):
    """An explicit, bogus codec should raise rather than silently
    falling back to another FourCC -- a fallback here would give the
    user a different format than the one they deliberately chose."""
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()

    with pytest.raises(ExportServiceError):
        export_video(project, event_bus, "basename", codec="bogus_fourcc")


def test_export_image_sequence_renumbers_sequentially(tmp_path):
    project = _make_project(tmp_path)
    # Non-contiguous numbers, e.g. after a Delete Frame.
    _add_frame(project, 5)
    _add_frame(project, 12)
    event_bus = EventBus()

    sequence_dir = export_image_sequence(project, event_bus, "basename")

    assert sequence_dir.is_dir()
    assert sequence_dir.name == "basename_sequence"
    assert sorted(p.name for p in sequence_dir.iterdir()) == [
        "000001.png",
        "000002.png",
    ]


def test_export_image_sequence_publishes_event(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()
    received = []
    event_bus.subscribe("IMAGE_SEQUENCE_EXPORTED", received.append)

    export_image_sequence(project, event_bus, "basename")

    assert len(received) == 1


def test_export_gif_writes_looping_animation(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()

    output_path = export_gif(project, event_bus, "basename")

    assert output_path.exists()
    with Image.open(output_path) as gif:
        assert gif.is_animated
        assert gif.n_frames == 2
        assert gif.info.get("loop") == 0


def test_export_gif_wraps_non_oserror_frame_failure(tmp_path, monkeypatch):
    """A frame-read failure that isn't an OSError (e.g. Pillow raising
    something else on a corrupt/truncated image) must still come out as
    ExportServiceError, not escape uncaught -- see export_controller.py's
    matching defense-in-depth fix for why an unwrapped exception here is
    dangerous (it silently kills the worker thread's caller)."""
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()

    def _raise(*args, **kwargs):
        raise ValueError("simulated non-OSError Pillow failure")

    monkeypatch.setattr("framelabs.export.export_service.Image.open", _raise)

    with pytest.raises(ExportServiceError):
        export_gif(project, event_bus, "basename")


def test_export_gif_fps_override_changes_frame_duration(tmp_path):
    """An explicit fps should change the GIF's per-frame duration rather
    than always deriving it from project.fps -- mirrors the Export
    dialog's editable FPS field."""
    project = _make_project(tmp_path, fps=12)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()

    output_path = export_gif(project, event_bus, "basename", fps=24)

    with Image.open(output_path) as gif:
        # GIF stores delay in centiseconds, so Pillow quantizes our
        # millisecond duration to the nearest 10ms on save.
        assert gif.info.get("duration") == round(round(1000 / 24) / 10) * 10


def test_export_gif_no_fps_uses_project_fps(tmp_path):
    project = _make_project(tmp_path, fps=10)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()

    output_path = export_gif(project, event_bus, "basename")

    with Image.open(output_path) as gif:
        assert gif.info.get("duration") == round(round(1000 / 10) / 10) * 10


def test_export_all_runs_only_requested_formats(tmp_path):
    """A request checking only GIF should export just the GIF, not
    video or the image sequence -- the whole point of the Export
    dialog letting the user pick specific formats."""
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()
    request = ExportRequest(project=project, want_gif=True)

    result = export_all(request, event_bus)

    assert set(result.succeeded) == {"gif"}
    assert not result.failed


def test_export_all_shares_one_basename(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()
    request = ExportRequest(
        project=project,
        want_video=True,
        want_image_sequence=True,
        want_gif=True,
    )

    result = export_all(request, event_bus)

    assert set(result.succeeded) == {"video", "image_sequence", "gif"}
    assert not result.failed
    stems = {
        path.name.split(".")[0].removesuffix("_sequence")
        for path in result.succeeded.values()
    }
    assert len(stems) == 1


def test_export_all_no_frames_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    request = ExportRequest(project=project, want_video=True)

    with pytest.raises(ExportServiceError):
        export_all(request, event_bus)


def test_export_all_nothing_selected_raises(tmp_path):
    """A request with every want_* flag left False should raise rather
    than silently doing nothing -- belt-and-suspenders behind the
    Export dialog's own Export-button-disabled guard."""
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()
    request = ExportRequest(project=project)

    with pytest.raises(ExportServiceError):
        export_all(request, event_bus)


def test_export_all_passes_video_codec_through(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()
    request = ExportRequest(project=project, want_video=True, video_codec="mp4v")

    result = export_all(request, event_bus)

    assert "video" in result.succeeded
    assert not result.failed


def test_export_all_passes_gif_fps_through(tmp_path):
    project = _make_project(tmp_path, fps=12)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()
    request = ExportRequest(project=project, want_gif=True, gif_fps=30)

    result = export_all(request, event_bus)

    with Image.open(result.succeeded["gif"]) as gif:
        assert gif.info.get("duration") == round(round(1000 / 30) / 10) * 10


# --- Progress reporting (on_progress) -------------------------------------


def test_export_video_reports_progress_per_frame(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    _add_frame(project, 2)
    _add_frame(project, 3)
    event_bus = EventBus()
    updates = []

    export_video(project, event_bus, "basename", on_progress=updates.append)

    assert [u.current for u in updates] == [1, 2, 3]
    assert all(u.total == 3 for u in updates)
    assert all(u.format_key == "video" for u in updates)


def test_export_video_no_progress_callback_is_fine(tmp_path):
    """on_progress is optional -- omitting it entirely must not raise."""
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()

    output_path = export_video(project, event_bus, "basename")

    assert output_path.exists()


def test_export_image_sequence_reports_progress_per_frame(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 5)
    _add_frame(project, 12)
    event_bus = EventBus()
    updates = []

    export_image_sequence(project, event_bus, "basename", on_progress=updates.append)

    assert [u.current for u in updates] == [1, 2]
    assert all(u.total == 2 for u in updates)
    assert all(u.format_key == "image_sequence" for u in updates)


def test_export_gif_reports_progress_per_frame(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()
    updates = []

    export_gif(project, event_bus, "basename", on_progress=updates.append)

    assert [u.current for u in updates] == [1, 2]
    assert all(u.total == 2 for u in updates)
    assert all(u.format_key == "gif" for u in updates)
    # The last update should always land at 100% before save() -- the
    # UI's progress bar has nothing else to advance it during the final
    # encode, which has no per-frame hook of its own (see export_gif's
    # docstring).
    assert updates[-1].current == updates[-1].total


def test_export_all_forwards_progress_from_each_requested_format(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    _add_frame(project, 2)
    event_bus = EventBus()
    request = ExportRequest(
        project=project, want_video=True, want_gif=True, video_codec="mp4v"
    )
    updates = []

    export_all(request, event_bus, on_progress=updates.append)

    format_keys = {u.format_key for u in updates}
    assert format_keys == {"video", "gif"}
    assert isinstance(updates[0], ExportProgress)

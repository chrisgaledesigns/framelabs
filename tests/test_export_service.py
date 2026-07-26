"""Tests for framelabs.export.export_service."""

import cv2
import numpy as np
import pytest
from PIL import Image

from framelabs.core.event_bus import EventBus
from framelabs.export.export_service import (
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


def test_export_all_shares_one_basename(tmp_path):
    project = _make_project(tmp_path)
    _add_frame(project, 1)
    event_bus = EventBus()

    result = export_all(project, event_bus)

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

    with pytest.raises(ExportServiceError):
        export_all(project, event_bus)

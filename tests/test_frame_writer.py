"""Tests for frame_writer.py."""

from unittest.mock import patch

import cv2
import numpy as np
import pytest

from framelabs.capture.frame_writer import (
    CaptureWriteError,
    generate_thumbnail,
    write_frame,
)
from framelabs.project.project import Project


def _real_png_bytes(width=800, height=600, color=(60, 180, 75)):
    """Build a genuine, decodable PNG's worth of encoded bytes."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    success, encoded = cv2.imencode(".png", img)
    assert success
    return encoded.tobytes()


def _make_project(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "thumbnails").mkdir()
    return Project(
        version=1,
        name="Smoke Test",
        fps=12,
        resolution=(800, 600),
        camera_model=None,
        camera_lens=None,
        project_path=tmp_path,
    )


def test_write_frame_writes_real_png(tmp_path):
    project = _make_project(tmp_path)
    image_bytes = _real_png_bytes()

    result_path = write_frame(image_bytes, project, 1)

    assert result_path == tmp_path / "images" / "000001.png"
    assert result_path.exists()
    written_back = cv2.imread(str(result_path))
    assert written_back.shape == (600, 800, 3)


def test_write_frame_uses_zero_padded_frame_number(tmp_path):
    project = _make_project(tmp_path)
    image_bytes = _real_png_bytes()

    result_path = write_frame(image_bytes, project, 42)

    assert result_path.name == "000042.png"


def test_write_frame_no_project_path_raises(tmp_path):
    project = _make_project(tmp_path)
    project.project_path = None
    image_bytes = _real_png_bytes()

    with pytest.raises(CaptureWriteError):
        write_frame(image_bytes, project, 1)


def test_write_frame_corrupt_data_raises_and_writes_nothing(tmp_path):
    project = _make_project(tmp_path)

    with pytest.raises(CaptureWriteError):
        write_frame(b"not a real image at all", project, 1)

    assert list((tmp_path / "images").iterdir()) == []


def test_write_frame_retries_once_then_succeeds(tmp_path):
    project = _make_project(tmp_path)
    image_bytes = _real_png_bytes()

    # write_frame now writes to a temp file and os.replace()'s it into place,
    # so the mock's "successful" call must actually create a real file on
    # disk -- just faking the True return value (as the old version of this
    # test did) leaves nothing for os.replace() to find. real_imwrite is
    # captured before patching so the fake can still perform a genuine write
    # on the second call without recursing into itself.
    real_imwrite = cv2.imwrite
    call_count = {"count": 0}

    def fake_imwrite(path, img, *args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return False
        return real_imwrite(path, img, *args, **kwargs)

    with patch(
        "framelabs.capture.frame_writer.cv2.imwrite", side_effect=fake_imwrite
    ) as mock_imwrite:
        result_path = write_frame(image_bytes, project, 1)

    assert mock_imwrite.call_count == 2
    assert result_path == tmp_path / "images" / "000001.png"
    assert result_path.exists()


def test_write_frame_fails_after_retry_exhausted(tmp_path):
    project = _make_project(tmp_path)
    image_bytes = _real_png_bytes()

    with patch(
        "framelabs.capture.frame_writer.cv2.imwrite", side_effect=[False, False]
    ) as mock_imwrite:
        with pytest.raises(CaptureWriteError):
            write_frame(image_bytes, project, 1)

    assert mock_imwrite.call_count == 2


def test_generate_thumbnail_writes_real_jpeg_at_target_width(tmp_path):
    project = _make_project(tmp_path)
    image_bytes = _real_png_bytes(width=800, height=600)

    result_path = generate_thumbnail(image_bytes, project, 1)

    assert result_path == tmp_path / "thumbnails" / "000001.jpg"
    assert result_path.exists()
    thumb = cv2.imread(str(result_path))
    assert thumb.shape == (300, 400, 3)  # 800x600 scaled to 400 wide


def test_generate_thumbnail_preserves_aspect_ratio_for_non_4_3_image(tmp_path):
    project = _make_project(tmp_path)
    image_bytes = _real_png_bytes(width=1000, height=500)

    result_path = generate_thumbnail(image_bytes, project, 1)

    thumb = cv2.imread(str(result_path))
    assert thumb.shape == (200, 400, 3)  # 1000x500 scaled to 400 wide -> 200 tall


def test_generate_thumbnail_no_project_path_raises(tmp_path):
    project = _make_project(tmp_path)
    project.project_path = None
    image_bytes = _real_png_bytes()

    with pytest.raises(CaptureWriteError):
        generate_thumbnail(image_bytes, project, 1)


def test_generate_thumbnail_corrupt_data_raises_and_writes_nothing(tmp_path):
    project = _make_project(tmp_path)

    with pytest.raises(CaptureWriteError):
        generate_thumbnail(b"not a real image at all", project, 1)

    assert list((tmp_path / "thumbnails").iterdir()) == []

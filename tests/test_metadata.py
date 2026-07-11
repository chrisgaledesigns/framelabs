"""Tests for framelabs.capture.metadata."""

import json

import pytest

from framelabs.camera.camera_interface import CameraMetadata
from framelabs.capture.metadata import MetadataWriteError, write_metadata
from framelabs.project.project import Project


def _make_project(tmp_path):
    """Build a real Project pointed at a real temp folder with metadata/."""
    (tmp_path / "metadata").mkdir()
    return Project(
        version=1,
        name="Test Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        project_path=tmp_path,
    )


def _make_camera_metadata():
    return CameraMetadata(
        camera_id="0",
        display_name="Integrated Camera",
        backend_type="webcam",
    )


def test_write_metadata_creates_file(tmp_path):
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    path = write_metadata(project, 1, cam_meta)

    assert path.exists()
    assert path == tmp_path / "metadata" / "000001.json"


def test_write_metadata_content_shape(tmp_path):
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    path = write_metadata(project, 1, cam_meta)
    data = json.loads(path.read_text())

    assert data["frame_number"] == 1
    assert "captured_at" in data
    assert data["camera"] == {
        "camera_id": "0",
        "display_name": "Integrated Camera",
        "backend_type": "webcam",
    }


def test_write_metadata_no_exposure_settings(tmp_path):
    """Confirms we never invent ISO/shutter/aperture values."""
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    path = write_metadata(project, 1, cam_meta)
    data = json.loads(path.read_text())

    assert "iso" not in data["camera"]
    assert "shutter" not in data["camera"]
    assert "aperture" not in data["camera"]


def test_write_metadata_zero_padded_naming(tmp_path):
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    path = write_metadata(project, 42, cam_meta)

    assert path.name == "000042.json"


def test_write_metadata_captured_at_is_utc_iso_format(tmp_path):
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    path = write_metadata(project, 1, cam_meta)
    data = json.loads(path.read_text())

    # Must include a UTC offset, not be a naive local timestamp.
    assert "+00:00" in data["captured_at"] or data["captured_at"].endswith("Z")


def test_write_metadata_missing_project_path_raises_value_error():
    project = Project(
        version=1,
        name="No Path",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        project_path=None,
    )
    cam_meta = _make_camera_metadata()

    with pytest.raises(ValueError):
        write_metadata(project, 1, cam_meta)


def test_write_metadata_write_failure_raises_metadata_write_error(
    tmp_path, monkeypatch
):
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    def _boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_text", _boom)

    with pytest.raises(MetadataWriteError):
        write_metadata(project, 1, cam_meta)


def test_write_metadata_different_frames_dont_collide(tmp_path):
    project = _make_project(tmp_path)
    cam_meta = _make_camera_metadata()

    path1 = write_metadata(project, 1, cam_meta)
    path2 = write_metadata(project, 2, cam_meta)

    assert path1 != path2
    assert path1.exists()
    assert path2.exists()

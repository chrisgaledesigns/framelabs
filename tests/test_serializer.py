"""Tests for ProjectSerializer save/load."""

import json

import pytest

from framelabs.project.project import Frame, Project
from framelabs.project.serializer import ProjectLoadError, ProjectSerializer


def _make_project(project_path):
    return Project(
        version=1,
        name="Robot Walk Cycle",
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[Frame(number=1, file="images/000001.png")],
        project_path=project_path,
    )


def test_save_then_load_round_trips(tmp_path):
    original = _make_project(tmp_path)

    ProjectSerializer.save(original)
    loaded = ProjectSerializer.load(tmp_path)

    assert loaded == original


def test_save_writes_expected_json_shape(tmp_path):
    project = _make_project(tmp_path)

    ProjectSerializer.save(project)
    data = json.loads((tmp_path / "project.ffproj").read_text(encoding="utf-8"))

    assert data["version"] == 1
    assert data["name"] == "Robot Walk Cycle"
    assert data["fps"] == 12
    assert data["resolution"] == [6000, 4000]
    assert data["camera"] == {"model": "Canon EOS R50", "lens": "50mm"}
    assert data["frames"] == [{"number": 1, "file": "images/000001.png"}]


def test_save_without_project_path_raises_value_error():
    project = _make_project(project_path=None)

    with pytest.raises(ValueError):
        ProjectSerializer.save(project)


def test_load_missing_file_raises_project_load_error(tmp_path):
    with pytest.raises(ProjectLoadError):
        ProjectSerializer.load(tmp_path)


def test_load_malformed_json_raises_project_load_error(tmp_path):
    (tmp_path / "project.ffproj").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ProjectLoadError):
        ProjectSerializer.load(tmp_path)


def test_load_missing_version_raises_project_load_error(tmp_path):
    (tmp_path / "project.ffproj").write_text(
        json.dumps({"name": "No Version"}), encoding="utf-8"
    )

    with pytest.raises(ProjectLoadError):
        ProjectSerializer.load(tmp_path)


def test_load_unsupported_version_raises_project_load_error(tmp_path):
    (tmp_path / "project.ffproj").write_text(
        json.dumps({"version": 99, "name": "Future Project"}), encoding="utf-8"
    )

    with pytest.raises(ProjectLoadError):
        ProjectSerializer.load(tmp_path)


def test_load_missing_required_field_raises_project_load_error(tmp_path):
    (tmp_path / "project.ffproj").write_text(
        json.dumps({"version": 1, "name": "Missing FPS"}), encoding="utf-8"
    )

    with pytest.raises(ProjectLoadError):
        ProjectSerializer.load(tmp_path)

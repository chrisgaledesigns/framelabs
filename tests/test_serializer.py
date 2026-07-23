"""Tests for ProjectSerializer save/load."""

import json

import pytest

from framelabs.project.project import Frame, Project
from framelabs.project.serializer import (
    CURRENT_VERSION,
    ProjectLoadError,
    ProjectSerializer,
)


def _make_project(project_path):
    return Project(
        version=CURRENT_VERSION,
        name="Robot Walk Cycle",
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[
            Frame(number=1, file="images/000001.png", notes="First frame", marker=True)
        ],
        audio=["audio/scratch_track.wav"],
        references=["references/pose_sketch.png"],
        overlays=["overlays/rough_layout.png"],
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

    assert data["version"] == CURRENT_VERSION
    assert data["name"] == "Robot Walk Cycle"
    assert data["fps"] == 12
    assert data["resolution"] == [6000, 4000]
    assert data["camera"] == {"model": "Canon EOS R50", "lens": "50mm"}
    assert data["frames"] == [
        {
            "number": 1,
            "file": "images/000001.png",
            "notes": "First frame",
            "marker": True,
        }
    ]
    assert data["audio"] == ["audio/scratch_track.wav"]
    assert data["references"] == ["references/pose_sketch.png"]
    assert data["overlays"] == ["overlays/rough_layout.png"]


def test_load_v2_file_defaults_audio_references_overlays_to_empty(tmp_path):
    # v2 files predate Project.audio/references/overlays -- loading one
    # must not fail, and the new fields must default to empty lists per
    # the Developer Handbook's forward-compatibility rule.
    (tmp_path / "project.ffproj").write_text(
        json.dumps(
            {
                "version": 2,
                "name": "Old Project",
                "fps": 12,
                "resolution": [1920, 1080],
                "camera": {"model": None, "lens": None},
                "frames": [],
            }
        ),
        encoding="utf-8",
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.version == CURRENT_VERSION
    assert project.audio == []
    assert project.references == []
    assert project.overlays == []


def test_load_creates_missing_audio_references_overlays_folders(tmp_path):
    # An old project folder (pre-dating this feature) won't have these
    # subfolders on disk. Opening it should create them transparently.
    original = _make_project(tmp_path)
    ProjectSerializer.save(original)
    for stale_folder in ("audio", "references", "overlays"):
        assert not (tmp_path / stale_folder).exists()

    ProjectSerializer.load(tmp_path)

    for folder in ("audio", "references", "overlays"):
        assert (tmp_path / folder).is_dir()


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


def test_load_v1_file_defaults_notes_and_marker(tmp_path):
    """A pre-Feature-5 v1 file has no notes/marker keys on its frames at
    all -- load() must default them rather than raising, since v1 is still
    a supported version."""
    (tmp_path / "project.ffproj").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Old Project",
                "fps": 12,
                "resolution": [1920, 1080],
                "camera": {"model": None, "lens": None},
                "frames": [{"number": 1, "file": "images/000001.png"}],
            }
        ),
        encoding="utf-8",
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.frames[0].notes == ""
    assert project.frames[0].marker is False


def test_load_v1_file_upgrades_to_current_version_in_memory(tmp_path):
    """Loading an old v1 file returns a Project already at
    CURRENT_VERSION -- the next save() call persists it at the current
    schema without any separate migration step."""
    (tmp_path / "project.ffproj").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Old Project",
                "fps": 12,
                "resolution": [1920, 1080],
                "camera": {"model": None, "lens": None},
                "frames": [],
            }
        ),
        encoding="utf-8",
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.version == CURRENT_VERSION

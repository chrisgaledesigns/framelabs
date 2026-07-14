"""Tests for create_new_project."""

import pytest

from framelabs.project.creator import (
    SUBFOLDERS,
    ProjectCreationError,
    create_new_project,
)
from framelabs.project.serializer import CURRENT_VERSION


def test_create_new_project_creates_folder_and_subfolders(tmp_path):
    project = create_new_project(
        name="Robot Walk Cycle",
        parent_dir=tmp_path,
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
    )

    project_dir = tmp_path / "Robot Walk Cycle"
    assert project_dir.is_dir()
    for subfolder in SUBFOLDERS:
        assert (project_dir / subfolder).is_dir()
    assert (project_dir / "project.ffproj").is_file()
    assert project.project_path == project_dir


def test_create_new_project_returns_project_with_given_fields(tmp_path):
    project = create_new_project(
        name="Robot Walk Cycle",
        parent_dir=tmp_path,
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
    )

    assert project.version == CURRENT_VERSION
    assert project.name == "Robot Walk Cycle"
    assert project.fps == 12
    assert project.resolution == (6000, 4000)
    assert project.camera_model == "Canon EOS R50"
    assert project.camera_lens == "50mm"
    assert project.frames == []


def test_create_new_project_without_camera_info(tmp_path):
    project = create_new_project(
        name="No Camera Yet",
        parent_dir=tmp_path,
        fps=24,
        resolution=(1920, 1080),
    )

    assert project.camera_model is None
    assert project.camera_lens is None


def test_create_new_project_existing_folder_raises(tmp_path):
    create_new_project("Robot Walk Cycle", tmp_path, 12, (6000, 4000))

    with pytest.raises(ProjectCreationError):
        create_new_project("Robot Walk Cycle", tmp_path, 12, (6000, 4000))


def test_create_new_project_existing_folder_does_not_touch_it(tmp_path):
    create_new_project("Robot Walk Cycle", tmp_path, 12, (6000, 4000))
    project_dir = tmp_path / "Robot Walk Cycle"
    marker = project_dir / "images" / "000001.png"
    marker.write_bytes(b"not a real png, just a marker")

    with pytest.raises(ProjectCreationError):
        create_new_project("Robot Walk Cycle", tmp_path, 12, (6000, 4000))

    assert marker.exists()


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "   ",
        "Bad:Name",
        "Bad/Name",
        "Bad\\Name",
        "Bad*Name",
        "Bad?Name",
        "Bad<Name>",
        'Bad"Name',
        "Bad|Name",
        " LeadingSpace",
        "TrailingSpace ",
        "TrailingPeriod.",
        "CON",
        "con",
        "NUL",
        "LPT1",
    ],
)
def test_create_new_project_invalid_name_raises(tmp_path, bad_name):
    with pytest.raises(ProjectCreationError):
        create_new_project(bad_name, tmp_path, 12, (6000, 4000))


def test_create_new_project_invalid_name_creates_no_folder(tmp_path):
    with pytest.raises(ProjectCreationError):
        create_new_project("Bad:Name", tmp_path, 12, (6000, 4000))

    assert list(tmp_path.iterdir()) == []


def test_create_new_project_permission_error_rolls_back(tmp_path, monkeypatch):
    def _raise_permission_error(*args, **kwargs):
        raise PermissionError("mocked: no permission")

    monkeypatch.setattr(
        "framelabs.project.creator.ProjectSerializer.save",
        _raise_permission_error,
    )

    with pytest.raises(ProjectCreationError):
        create_new_project("Robot Walk Cycle", tmp_path, 12, (6000, 4000))

    assert not (tmp_path / "Robot Walk Cycle").exists()


def test_create_new_project_os_error_rolls_back(tmp_path, monkeypatch):
    def _raise_os_error(*args, **kwargs):
        raise OSError("mocked: disk full")

    monkeypatch.setattr(
        "framelabs.project.creator.ProjectSerializer.save",
        _raise_os_error,
    )

    with pytest.raises(ProjectCreationError):
        create_new_project("Robot Walk Cycle", tmp_path, 12, (6000, 4000))

    assert not (tmp_path / "Robot Walk Cycle").exists()

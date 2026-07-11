"""Tests for the Project and Frame data model."""

from pathlib import Path

from framelabs.project.project import Frame, Project


def test_frame_holds_number_and_file():
    frame = Frame(number=1, file="images/000001.png")

    assert frame.number == 1
    assert frame.file == "images/000001.png"


def test_project_holds_all_fields():
    project = Project(
        version=1,
        name="Robot Walk Cycle",
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[Frame(number=1, file="images/000001.png")],
        project_path=Path("C:/fake/path"),
    )

    assert project.version == 1
    assert project.name == "Robot Walk Cycle"
    assert project.fps == 12
    assert project.resolution == (6000, 4000)
    assert project.camera_model == "Canon EOS R50"
    assert project.camera_lens == "50mm"
    assert project.frames == [Frame(number=1, file="images/000001.png")]
    assert project.project_path == Path("C:/fake/path")


def test_project_frames_defaults_to_empty_list():
    project = Project(
        version=1,
        name="Empty Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
    )

    assert project.frames == []


def test_project_path_defaults_to_none():
    project = Project(
        version=1,
        name="No Path Yet",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
    )

    assert project.project_path is None

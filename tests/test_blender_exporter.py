"""Tests for blender/exporter.py."""

import json
from pathlib import Path

import pytest

from framelabs.blender.exporter import (
    DEFAULT_FOCAL_LENGTH_MM,
    BlenderExportError,
    build_manifest,
    parse_focal_length_mm,
    write_manifest,
)
from framelabs.project.project import Frame, Project


def _make_project(tmp_path, camera_lens=None, frames=None):
    project_path = tmp_path / "TestProject"
    project_path.mkdir()
    (project_path / "images").mkdir()
    for f in frames or []:
        (project_path / f.file).write_bytes(b"fake png")
    return Project(
        version=1,
        name="Test Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model="Canon EOS R50",
        camera_lens=camera_lens,
        frames=frames or [],
        project_path=project_path,
    )


class TestParseFocalLengthMm:
    def test_simple_mm_string(self):
        assert parse_focal_length_mm("50mm") == 50.0

    def test_decimal_value(self):
        assert parse_focal_length_mm("35.5mm lens") == 35.5

    def test_range_returns_first_number(self):
        assert parse_focal_length_mm("24-70mm f/2.8") == 24.0

    def test_none_returns_default(self):
        assert parse_focal_length_mm(None) == DEFAULT_FOCAL_LENGTH_MM

    def test_empty_string_returns_default(self):
        assert parse_focal_length_mm("") == DEFAULT_FOCAL_LENGTH_MM

    def test_no_number_returns_default(self):
        assert parse_focal_length_mm("nifty fifty") == DEFAULT_FOCAL_LENGTH_MM

    def test_custom_default_used(self):
        assert parse_focal_length_mm(None, default=35.0) == 35.0


class TestBuildManifest:
    def test_no_project_path_raises(self):
        project = Project(
            version=1,
            name="X",
            fps=12,
            resolution=(1920, 1080),
            camera_model=None,
            camera_lens=None,
            frames=[Frame(number=1, file="images/000001.png")],
            project_path=None,
        )
        with pytest.raises(BlenderExportError):
            build_manifest(project)

    def test_no_frames_raises(self, tmp_path):
        project = _make_project(tmp_path)
        with pytest.raises(BlenderExportError):
            build_manifest(project)

    def test_frames_ordered_by_number_not_insertion(self, tmp_path):
        frames = [
            Frame(number=3, file="images/000003.png"),
            Frame(number=1, file="images/000001.png"),
            Frame(number=2, file="images/000002.png"),
        ]
        project = _make_project(tmp_path, frames=frames)
        manifest = build_manifest(project)
        names = [Path(p).name for p in manifest.frame_paths]
        assert names == ["000001.png", "000002.png", "000003.png"]

    def test_frame_paths_absolute(self, tmp_path):
        frames = [Frame(number=1, file="images/000001.png")]
        project = _make_project(tmp_path, frames=frames)
        manifest = build_manifest(project)
        assert Path_is_absolute(manifest.frame_paths[0])

    def test_focal_length_parsed_from_camera_lens(self, tmp_path):
        frames = [Frame(number=1, file="images/000001.png")]
        project = _make_project(tmp_path, camera_lens="85mm", frames=frames)
        manifest = build_manifest(project)
        assert manifest.focal_length_mm == 85.0

    def test_focal_length_defaults_when_lens_missing(self, tmp_path):
        frames = [Frame(number=1, file="images/000001.png")]
        project = _make_project(tmp_path, camera_lens=None, frames=frames)
        manifest = build_manifest(project)
        assert manifest.focal_length_mm == DEFAULT_FOCAL_LENGTH_MM

    def test_blend_output_path_uses_project_name(self, tmp_path):
        frames = [Frame(number=1, file="images/000001.png")]
        project = _make_project(tmp_path, frames=frames)
        manifest = build_manifest(project)
        assert manifest.blend_output_path.endswith("Test Project.blend")


class TestWriteManifest:
    def test_writes_valid_json_under_cache_blender(self, tmp_path):
        frames = [Frame(number=1, file="images/000001.png")]
        project = _make_project(tmp_path, camera_lens="50mm", frames=frames)
        manifest_path = write_manifest(project)

        assert (
            manifest_path
            == project.project_path / "cache" / "blender" / "blender_manifest.json"
        )
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["project_name"] == "Test Project"
        assert data["focal_length_mm"] == 50.0
        assert data["fps"] == 12

    def test_creates_cache_blender_dir_if_missing(self, tmp_path):
        frames = [Frame(number=1, file="images/000001.png")]
        project = _make_project(tmp_path, frames=frames)
        assert not (project.project_path / "cache").exists()
        write_manifest(project)
        assert (project.project_path / "cache" / "blender").is_dir()

    def test_no_frames_raises_before_writing(self, tmp_path):
        project = _make_project(tmp_path)
        with pytest.raises(BlenderExportError):
            write_manifest(project)


def Path_is_absolute(path_str: str) -> bool:
    from pathlib import Path

    return Path(path_str).is_absolute()

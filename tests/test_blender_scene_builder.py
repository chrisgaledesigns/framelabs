"""Tests for blender/scene_builder.py."""

from framelabs.blender.exporter import BlenderManifest
from framelabs.blender.scene_builder import (
    SCENE_SCRIPT_FILENAME,
    generate_scene_script,
    write_scene_script,
)


def _make_manifest(**overrides) -> BlenderManifest:
    defaults = dict(
        project_name="Robot Walk Cycle",
        fps=12,
        resolution=(1920, 1080),
        focal_length_mm=50.0,
        frame_paths=["/proj/images/000001.png", "/proj/images/000002.png"],
        blend_output_path="/proj/exports/Robot Walk Cycle.blend",
    )
    defaults.update(overrides)
    return BlenderManifest(**defaults)


class TestGenerateSceneScript:
    def test_produces_syntactically_valid_python(self):
        script = generate_scene_script(_make_manifest())
        # Doesn't require bpy to be installed -- just confirms the
        # generated source itself is valid Python, which is the one
        # thing this test environment (no real Blender) can verify.
        compile(script, "<generated_scene_script>", "exec")

    def test_embeds_fps(self):
        script = generate_scene_script(_make_manifest(fps=24))
        assert "FPS = 24" in script

    def test_embeds_resolution(self):
        script = generate_scene_script(_make_manifest(resolution=(3840, 2160)))
        assert "RESOLUTION = [3840, 2160]" in script

    def test_embeds_focal_length(self):
        script = generate_scene_script(_make_manifest(focal_length_mm=85.0))
        assert "FOCAL_LENGTH_MM = 85.0" in script

    def test_embeds_blend_output_path(self):
        script = generate_scene_script(
            _make_manifest(blend_output_path="/proj/exports/My Film.blend")
        )
        assert "/proj/exports/My Film.blend" in script

    def test_embeds_every_frame_path_in_order(self):
        frame_paths = [
            "/proj/images/000001.png",
            "/proj/images/000002.png",
            "/proj/images/000003.png",
        ]
        script = generate_scene_script(_make_manifest(frame_paths=frame_paths))
        first_index = script.index("000001.png")
        second_index = script.index("000002.png")
        third_index = script.index("000003.png")
        assert first_index < second_index < third_index

    def test_empty_frame_paths_still_produces_valid_script(self):
        # build_manifest() itself never allows this (BlenderExportError
        # if a project has no frames), but this module doesn't assume
        # that guarantee -- it should degrade gracefully, not crash,
        # if it's ever handed an empty list directly.
        script = generate_scene_script(_make_manifest(frame_paths=[]))
        compile(script, "<generated_scene_script>", "exec")
        assert "FRAME_PATHS = []" in script

    def test_windows_style_paths_do_not_break_the_script(self):
        # Chris's real machine is Windows -- backslash path separators
        # must not corrupt the generated string literals.
        script = generate_scene_script(
            _make_manifest(
                frame_paths=[r"C:\Users\shelb\framelabs\images\000001.png"],
                blend_output_path=r"C:\Users\shelb\framelabs\exports\Film.blend",
            )
        )
        compile(script, "<generated_scene_script>", "exec")


class TestWriteSceneScript:
    def test_writes_file_with_expected_name(self, tmp_path):
        output_dir = tmp_path / "cache" / "blender"
        script_path = write_scene_script(_make_manifest(), output_dir)
        assert script_path == output_dir / SCENE_SCRIPT_FILENAME
        assert script_path.exists()

    def test_creates_output_dir_if_missing(self, tmp_path):
        output_dir = tmp_path / "cache" / "blender"
        assert not output_dir.exists()
        write_scene_script(_make_manifest(), output_dir)
        assert output_dir.is_dir()

    def test_written_file_matches_generate_scene_script(self, tmp_path):
        manifest = _make_manifest()
        output_dir = tmp_path / "cache" / "blender"
        script_path = write_scene_script(manifest, output_dir)
        assert script_path.read_text() == generate_scene_script(manifest)

    def test_overwrites_existing_script_on_second_call(self, tmp_path):
        output_dir = tmp_path / "cache" / "blender"
        write_scene_script(_make_manifest(fps=12), output_dir)
        write_scene_script(_make_manifest(fps=24), output_dir)
        script_path = output_dir / SCENE_SCRIPT_FILENAME
        assert "FPS = 24" in script_path.read_text()
        assert "FPS = 12" not in script_path.read_text()

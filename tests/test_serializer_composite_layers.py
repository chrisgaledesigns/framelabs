"""Round-trip and backward-compatibility tests for schema v4's
composite_layers field -- the single riskiest untested piece per the
session-22 hand-off, since a serializer bug here risks real project-file
corruption, not just a UI glitch.
"""

import json

from framelabs.project.project import CompositeLayer, Frame, Project
from framelabs.project.serializer import (
    CURRENT_VERSION,
    SUPPORTED_VERSIONS,
    ProjectSerializer,
)


def _make_project_with_layers(project_path):
    return Project(
        version=CURRENT_VERSION,
        name="Robot Walk Cycle",
        fps=12,
        resolution=(6000, 4000),
        camera_model="Canon EOS R50",
        camera_lens="50mm",
        frames=[Frame(number=1, file="images/000001.png")],
        audio=[],
        references=[],
        overlays=["overlays/vignette.png", "overlays/grain.png"],
        composite_layers=[
            CompositeLayer(
                source="overlays/vignette.png",
                opacity=0.75,
                blend_mode="multiply",
                visible=True,
            ),
            CompositeLayer(
                source="overlays/grain.png",
                opacity=0.3,
                blend_mode="screen",
                visible=False,
            ),
        ],
        project_path=project_path,
    )


# ---------------------------------------------------------------------------
# Current-version round trip
# ---------------------------------------------------------------------------


def test_save_then_load_round_trips_composite_layers(tmp_path):
    original = _make_project_with_layers(tmp_path)

    ProjectSerializer.save(original)
    loaded = ProjectSerializer.load(tmp_path)

    assert loaded == original


def test_save_then_load_preserves_layer_order(tmp_path):
    original = _make_project_with_layers(tmp_path)

    ProjectSerializer.save(original)
    loaded = ProjectSerializer.load(tmp_path)

    assert [layer.source for layer in loaded.composite_layers] == [
        "overlays/vignette.png",
        "overlays/grain.png",
    ]


def test_save_then_load_preserves_each_layer_field_exactly(tmp_path):
    original = _make_project_with_layers(tmp_path)

    ProjectSerializer.save(original)
    loaded = ProjectSerializer.load(tmp_path)

    first = loaded.composite_layers[0]
    assert first.source == "overlays/vignette.png"
    assert first.opacity == 0.75
    assert first.blend_mode == "multiply"
    assert first.visible is True

    second = loaded.composite_layers[1]
    assert second.source == "overlays/grain.png"
    assert second.opacity == 0.3
    assert second.blend_mode == "screen"
    assert second.visible is False


def test_project_with_no_composite_layers_round_trips_to_empty_list(tmp_path):
    original = Project(
        version=CURRENT_VERSION,
        name="No Layers Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=[],
        project_path=tmp_path,
    )

    ProjectSerializer.save(original)
    loaded = ProjectSerializer.load(tmp_path)

    assert loaded.composite_layers == []


def test_save_writes_composite_layers_json_shape(tmp_path):
    project = _make_project_with_layers(tmp_path)

    ProjectSerializer.save(project)
    data = json.loads((tmp_path / "project.ffproj").read_text(encoding="utf-8"))

    assert data["version"] == 4
    assert data["composite_layers"] == [
        {
            "source": "overlays/vignette.png",
            "opacity": 0.75,
            "blend_mode": "multiply",
            "visible": True,
        },
        {
            "source": "overlays/grain.png",
            "opacity": 0.3,
            "blend_mode": "screen",
            "visible": False,
        },
    ]


# ---------------------------------------------------------------------------
# Schema bump / SUPPORTED_VERSIONS sanity
# ---------------------------------------------------------------------------


def test_current_version_is_4():
    assert CURRENT_VERSION == 4


def test_supported_versions_includes_1_through_4():
    assert SUPPORTED_VERSIONS == (1, 2, 3, 4)


# ---------------------------------------------------------------------------
# Backward compatibility: v1/v2/v3 files predate composite_layers entirely
# ---------------------------------------------------------------------------


def _write_raw_project_file(tmp_path, version: int, extra: dict | None = None):
    data = {
        "version": version,
        "name": "Old Project",
        "fps": 12,
        "resolution": [1920, 1080],
        "camera": {"model": None, "lens": None},
        "frames": [],
    }
    if extra:
        data.update(extra)
    (tmp_path / "project.ffproj").write_text(json.dumps(data), encoding="utf-8")


def test_load_v1_file_defaults_composite_layers_to_empty(tmp_path):
    _write_raw_project_file(tmp_path, version=1)

    project = ProjectSerializer.load(tmp_path)

    assert project.composite_layers == []


def test_load_v2_file_defaults_composite_layers_to_empty(tmp_path):
    _write_raw_project_file(tmp_path, version=2)

    project = ProjectSerializer.load(tmp_path)

    assert project.composite_layers == []


def test_load_v3_file_defaults_composite_layers_to_empty(tmp_path):
    # v3 predates the Composite workspace specifically (it already has
    # audio/references/overlays from v2, but no composite_layers key at
    # all) -- this is the exact upgrade path a real user hits going from
    # last session's schema to this one.
    _write_raw_project_file(
        tmp_path,
        version=3,
        extra={
            "audio": ["audio/track.wav"],
            "references": ["references/sketch.png"],
            "overlays": ["overlays/vignette.png"],
        },
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.composite_layers == []
    # Confirm the v3 fields it DOES have still load correctly alongside
    # the new default -- i.e. this isn't accidentally clobbering v3 data.
    assert project.audio == ["audio/track.wav"]
    assert project.references == ["references/sketch.png"]
    assert project.overlays == ["overlays/vignette.png"]


def test_load_v3_file_upgrades_to_current_version_in_memory(tmp_path):
    _write_raw_project_file(tmp_path, version=3)

    project = ProjectSerializer.load(tmp_path)

    assert project.version == CURRENT_VERSION


def test_load_v3_file_then_resave_persists_composite_layers_key(tmp_path):
    """The real upgrade path: open an old v3 project, save it once, and
    the file on disk should now be a full v4 file with the
    composite_layers key present (even if empty) -- not still missing
    the key until a layer is actually added."""
    _write_raw_project_file(tmp_path, version=3)
    project = ProjectSerializer.load(tmp_path)

    ProjectSerializer.save(project)
    data = json.loads((tmp_path / "project.ffproj").read_text(encoding="utf-8"))

    assert data["version"] == 4
    assert data["composite_layers"] == []


# ---------------------------------------------------------------------------
# Per-field .get() defaults on a v4 file with a partially-specified layer
# ---------------------------------------------------------------------------


def test_load_layer_missing_opacity_defaults_to_1(tmp_path):
    _write_raw_project_file(
        tmp_path,
        version=4,
        extra={"composite_layers": [{"source": "overlays/vignette.png"}]},
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.composite_layers[0].opacity == 1.0


def test_load_layer_missing_blend_mode_defaults_to_normal(tmp_path):
    _write_raw_project_file(
        tmp_path,
        version=4,
        extra={"composite_layers": [{"source": "overlays/vignette.png"}]},
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.composite_layers[0].blend_mode == "normal"


def test_load_layer_missing_visible_defaults_to_true(tmp_path):
    _write_raw_project_file(
        tmp_path,
        version=4,
        extra={"composite_layers": [{"source": "overlays/vignette.png"}]},
    )

    project = ProjectSerializer.load(tmp_path)

    assert project.composite_layers[0].visible is True


def test_load_layer_with_all_fields_specified_uses_file_values_not_defaults(
    tmp_path,
):
    _write_raw_project_file(
        tmp_path,
        version=4,
        extra={
            "composite_layers": [
                {
                    "source": "overlays/vignette.png",
                    "opacity": 0.2,
                    "blend_mode": "add",
                    "visible": False,
                }
            ]
        },
    )

    project = ProjectSerializer.load(tmp_path)

    layer = project.composite_layers[0]
    assert layer.opacity == 0.2
    assert layer.blend_mode == "add"
    assert layer.visible is False

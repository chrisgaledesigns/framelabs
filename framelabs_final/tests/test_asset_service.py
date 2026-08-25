"""Tests for framelabs.project.asset_service."""

import pytest

from framelabs.core.event_bus import EventBus
from framelabs.project.asset_service import AssetServiceError, add_asset, remove_asset
from framelabs.project.creator import create_new_project
from framelabs.project.serializer import ProjectSerializer


def _make_project(tmp_path):
    return create_new_project(
        name="Test Project", parent_dir=tmp_path, fps=12, resolution=(1920, 1080)
    )


def _make_source_file(tmp_path, name="clip.wav", content=b"fake audio bytes"):
    source = tmp_path / name
    source.write_bytes(content)
    return source


@pytest.mark.parametrize(
    "kind,subfolder",
    [
        ("audio", "audio"),
        ("references", "references"),
        ("overlays", "overlays"),
    ],
)
def test_add_asset_copies_file_and_tracks_it(tmp_path, kind, subfolder):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path, "thing.png")

    relative_path = add_asset(project, event_bus, kind, source)

    assert relative_path == f"{subfolder}/thing.png"
    assert (project.project_path / subfolder / "thing.png").exists()
    assert getattr(project, kind) == [relative_path]
    # Source file untouched (copied, not moved).
    assert source.exists()


def test_add_asset_invalid_kind_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)

    with pytest.raises(AssetServiceError):
        add_asset(project, event_bus, "not_a_kind", source)


def test_add_asset_missing_source_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    with pytest.raises(AssetServiceError):
        add_asset(project, event_bus, "audio", tmp_path / "does_not_exist.wav")


def test_add_asset_handles_filename_collision(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    source1 = tmp_path / "src1" / "track.wav"
    source1.parent.mkdir()
    source1.write_bytes(b"one")

    source2 = tmp_path / "src2" / "track.wav"
    source2.parent.mkdir()
    source2.write_bytes(b"two")

    path1 = add_asset(project, event_bus, "audio", source1)
    path2 = add_asset(project, event_bus, "audio", source2)

    assert path1 == "audio/track.wav"
    assert path2 == "audio/track (2).wav"
    assert (project.project_path / "audio" / "track.wav").read_bytes() == b"one"
    assert (project.project_path / "audio" / "track (2).wav").read_bytes() == b"two"


def test_add_asset_persists_across_reload(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)

    add_asset(project, event_bus, "audio", source)

    reloaded = ProjectSerializer.load(project.project_path)
    assert reloaded.audio == ["audio/clip.wav"]


def test_add_asset_publishes_event(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    received = []
    event_bus.subscribe("AUDIO_ADDED", lambda payload: received.append(payload))

    relative_path = add_asset(project, event_bus, "audio", source)

    assert received == [{"path": relative_path}]


def test_remove_asset_untracks_and_deletes_file(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    relative_path = add_asset(project, event_bus, "references", source)

    remove_asset(project, event_bus, "references", relative_path)

    assert project.references == []
    assert not (project.project_path / relative_path).exists()


def test_remove_asset_not_tracked_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    with pytest.raises(AssetServiceError):
        remove_asset(project, event_bus, "overlays", "overlays/nope.png")


def test_remove_asset_invalid_kind_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    with pytest.raises(AssetServiceError):
        remove_asset(project, event_bus, "not_a_kind", "not_a_kind/x")


def test_remove_asset_persists_across_reload(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    relative_path = add_asset(project, event_bus, "overlays", source)

    remove_asset(project, event_bus, "overlays", relative_path)

    reloaded = ProjectSerializer.load(project.project_path)
    assert reloaded.overlays == []


def test_remove_asset_publishes_event(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    source = _make_source_file(tmp_path)
    relative_path = add_asset(project, event_bus, "overlays", source)
    received = []
    event_bus.subscribe("OVERLAY_REMOVED", lambda payload: received.append(payload))

    remove_asset(project, event_bus, "overlays", relative_path)

    assert received == [{"path": relative_path}]

"""Tests for blender/sync_protocol.py."""

import pytest

from framelabs.blender.sync_protocol import (
    LIVE_SYNC_PORT_FILENAME,
    SyncMessage,
    SyncProtocolError,
    build_sync_message,
    decode_message,
    encode_message,
)
from framelabs.project.project import Frame, Project


def _make_project(tmp_path, frames=None):
    project_path = tmp_path / "TestProject"
    project_path.mkdir()
    return Project(
        version=1,
        name="Test Project",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=frames or [],
        project_path=project_path,
    )


class TestEncodeDecodeMessage:
    def test_round_trips(self):
        message = SyncMessage(
            frame_number=3,
            frame_path="/proj/images/000003.png",
            fps=12,
            frame_count=3,
        )
        wire = encode_message(message)
        decoded = decode_message(wire.decode("utf-8").strip())
        assert decoded == message

    def test_encode_ends_with_newline(self):
        message = SyncMessage(1, "/a.png", 12, 1)
        assert encode_message(message).endswith(b"\n")

    def test_decode_malformed_json_raises(self):
        with pytest.raises(SyncProtocolError):
            decode_message("not json")

    def test_decode_missing_fields_raises(self):
        with pytest.raises(SyncProtocolError):
            decode_message('{"frame_number": 1}')

    def test_decode_unexpected_field_raises(self):
        with pytest.raises(SyncProtocolError):
            decode_message(
                '{"frame_number": 1, "frame_path": "a", "fps": 12, '
                '"frame_count": 1, "extra": true}'
            )


class TestBuildSyncMessage:
    def test_builds_from_project_and_frame_number(self, tmp_path):
        project = _make_project(
            tmp_path,
            frames=[
                Frame(number=1, file="images/000001.png"),
                Frame(number=2, file="images/000002.png"),
            ],
        )

        message = build_sync_message(project, 2)

        assert message.frame_number == 2
        assert message.frame_path == str(project.project_path / "images/000002.png")
        assert message.fps == 12
        assert message.frame_count == 2

    def test_no_project_path_raises(self, tmp_path):
        project = _make_project(tmp_path, frames=[Frame(1, "images/000001.png")])
        project.project_path = None
        with pytest.raises(SyncProtocolError):
            build_sync_message(project, 1)

    def test_unknown_frame_number_raises(self, tmp_path):
        project = _make_project(tmp_path, frames=[Frame(1, "images/000001.png")])
        with pytest.raises(SyncProtocolError):
            build_sync_message(project, 99)


def test_port_filename_is_a_bare_filename():
    # discover_port()/start_live_sync_listener() both join this onto a
    # directory -- it must never itself contain a path separator.
    assert "/" not in LIVE_SYNC_PORT_FILENAME
    assert "\\" not in LIVE_SYNC_PORT_FILENAME

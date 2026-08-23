"""Tests for blender/sync_listener_script.py.

The content/compile-only tests match this codebase's existing testing
boundary for Blender-side generated code (see
test_blender_scene_builder.py's own module docstring) -- no real
Blender install anywhere in the test environment.

TestListenerRunsAgainstAFakeBpy goes one step further: it executes the
*actual* generated script with a minimal fake `bpy` stubbed into
sys.modules, and talks to the real socket server it starts over a real
loopback connection. This exercises the socket-server, background
-thread, and bpy.app.timers-polling wiring for real, not just its
source text -- only the bpy scene-mutation calls themselves are fakes.
"""

from __future__ import annotations

import socket
import sys
import time
import types
from unittest.mock import MagicMock

import pytest

from framelabs.blender.sync_listener_script import generate_listener_script
from framelabs.blender.sync_protocol import (
    LIVE_SYNC_PORT_FILENAME,
    SyncMessage,
    encode_message,
)


class TestGenerateListenerScript:
    def test_compiles_as_valid_python(self):
        script = generate_listener_script()
        compile(script, "<generated_listener_script>", "exec")

    def test_starts_the_listener_unconditionally(self):
        script = generate_listener_script()
        assert script.rstrip().endswith("start_live_sync_listener()")

    def test_binds_port_zero_for_os_assignment(self):
        script = generate_listener_script()
        assert "('127.0.0.1', 0)" in script

    def test_writes_the_port_file_next_to_the_script(self):
        script = generate_listener_script()
        assert "os.path.dirname(os.path.abspath(__file__))" in script
        assert LIVE_SYNC_PORT_FILENAME in script

    def test_registers_a_persistent_main_thread_timer(self):
        # persistent=True is required -- without it, bpy.app.timers only
        # fires once and live sync would silently stop after the first
        # queued message.
        script = generate_listener_script()
        assert "bpy.app.timers.register(_drain_live_sync_queue, persistent=True)" in (
            script
        )

    def test_bad_message_does_not_kill_the_polling_loop(self):
        # A try/except around _apply_live_sync_message() inside the
        # drain loop, not just around the whole function -- otherwise
        # one malformed message would deregister the timer and end
        # live sync for the rest of the session.
        script = generate_listener_script()
        assert "except Exception as exc:" in script
        assert "return " in script.rsplit("def _drain_live_sync_queue", 1)[1]


def _make_fake_bpy():
    """A minimal stand-in for the `bpy` module, just enough surface
    area for _apply_live_sync_message() to run against."""
    fake_bpy = types.ModuleType("bpy")

    scene = MagicMock()
    scene.sequence_editor = None

    strip = MagicMock()
    strip.name = "FrameLabs Sequence"

    def _sequence_editor_create():
        seq_editor = MagicMock()
        seq_editor.strips = MagicMock()
        seq_editor.strips.new_image.return_value = strip
        seq_editor.strips.__iter__.return_value = iter([])
        scene.sequence_editor = seq_editor

    scene.sequence_editor_create.side_effect = _sequence_editor_create

    camera_obj = MagicMock()
    camera_obj.data.background_images = MagicMock()
    camera_obj.data.background_images.__iter__.return_value = iter([])
    camera_obj.data.background_images.__len__.return_value = 0
    scene.camera = camera_obj

    fake_bpy.context = MagicMock()
    fake_bpy.context.scene = scene

    fake_bpy.app = MagicMock()
    registered_timers = []
    fake_bpy.app.timers.register.side_effect = (
        lambda fn, persistent=False: registered_timers.append(fn)
    )

    fake_bpy.data = MagicMock()

    return fake_bpy, scene, registered_timers


@pytest.fixture
def fake_bpy_module():
    fake_bpy, scene, registered_timers = _make_fake_bpy()
    sys.modules["bpy"] = fake_bpy
    try:
        yield fake_bpy, scene, registered_timers
    finally:
        del sys.modules["bpy"]


class TestListenerRunsAgainstAFakeBpy:
    """Executes the real generated script (bpy stubbed out) so the
    socket server, background thread, and port-file handshake are
    tested for real, matching how sync_client.discover_port() and
    BlenderSyncClient actually talk to it."""

    def _run_listener(self, tmp_path, fake_bpy):
        script_path = tmp_path / "generate_scene.py"
        namespace = {
            "__file__": str(script_path),
            "bpy": fake_bpy,
            "os": __import__("os"),
            "json": __import__("json"),
        }
        exec(compile(generate_listener_script(), str(script_path), "exec"), namespace)
        return namespace

    def test_writes_a_real_port_file(self, tmp_path, fake_bpy_module):
        fake_bpy, _scene, _timers = fake_bpy_module
        self._run_listener(tmp_path, fake_bpy)

        port_path = tmp_path / LIVE_SYNC_PORT_FILENAME
        deadline = time.monotonic() + 2.0
        while not port_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)

        assert port_path.exists()
        port = int(port_path.read_text().strip())
        assert 0 < port < 65536

    def test_registers_the_drain_timer(self, tmp_path, fake_bpy_module):
        fake_bpy, _scene, registered_timers = fake_bpy_module
        self._run_listener(tmp_path, fake_bpy)
        assert len(registered_timers) == 1

    def test_sent_message_reaches_the_queue_and_applies_via_the_timer(
        self, tmp_path, fake_bpy_module
    ):
        fake_bpy, scene, registered_timers = fake_bpy_module
        self._run_listener(tmp_path, fake_bpy)

        port_path = tmp_path / LIVE_SYNC_PORT_FILENAME
        deadline = time.monotonic() + 2.0
        while not port_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        port = int(port_path.read_text().strip())

        message = SyncMessage(
            frame_number=1,
            frame_path="/proj/images/000001.png",
            fps=24,
            frame_count=1,
        )
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
            sock.sendall(encode_message(message))
            time.sleep(0.3)  # let the handler thread enqueue the message

        # Drive the main-thread drain callback manually -- in real
        # Blender, bpy.app.timers itself would call this on a schedule.
        drain_callback = registered_timers[0]
        interval = drain_callback()

        assert scene.frame_end == 1
        assert scene.render.fps == 24
        assert isinstance(interval, float)

"""Blender-side live-sync listener script builder for Feature 11.

Like scene_builder.py, this module builds the *text* of Python source
that runs inside Blender's own process (via `--python`) -- it never
imports `bpy` itself and stays fully unit-testable with no real Blender
install. Kept as its own module rather than folded into
scene_builder.py: scene construction (a one-shot build) and the live
-sync listener (a long-running background service started at the end
of that same script) are two different concerns, per the Handbook's
"Small Modules" rule.

The generated listener:
    - binds a TCP socket on 127.0.0.1, port 0 (OS-assigned), inside a
      background Python thread, and writes the bound port number to
      sync_protocol.LIVE_SYNC_PORT_FILENAME next to the generator
      script itself -- this is how sync_client.py, running in
      FrameLabs' own process, finds it.
    - queues every received message rather than touching bpy directly
      from that background thread -- bpy objects may only be mutated
      from Blender's main thread. A bpy.app.timers callback drains the
      queue and applies each update on the main thread instead.
    - is started unconditionally, every time "Open in Blender" runs,
      regardless of whether the user has Live Blender Sync turned on
      in FrameLabs -- enabling the feature after Blender is already
      open needs no relaunch, since the listener was already there,
      idle, waiting for messages that simply hadn't been sent yet.

This module hand-writes a JSON message shape that mirrors
sync_protocol.SyncMessage's fields, rather than importing
sync_protocol.py into the generated script -- the generated script runs
inside Blender's bundled Python, entirely separate from the FrameLabs
install (no guarantee framelabs.* is even importable there), the same
reasoning scene_builder.py's own docstring gives for embedding manifest
data as literals instead of re-reading JSON at runtime.
"""

from __future__ import annotations

import json

from framelabs.blender.sync_protocol import LIVE_SYNC_PORT_FILENAME

# How often the main-thread timer checks for queued messages. Frequent
# enough that a capture feels "live" without any visible lag, cheap
# enough (an empty-queue check) to run every tick indefinitely for the
# rest of the Blender session.
_POLL_INTERVAL_SECONDS = 0.2


def generate_listener_script() -> str:
    """Build the live-sync listener source, appended after build_scene()
    in the full generated script (see scene_builder.generate_scene_script()).

    Returns:
        A self-contained block of Python source. Assumes `bpy`, `os`,
        and `json` are already imported by the surrounding script (see
        scene_builder.py) -- only imports the additional stdlib modules
        it alone needs (queue, socketserver, threading).
    """
    port_filename_literal = json.dumps(LIVE_SYNC_PORT_FILENAME)
    poll_interval_literal = json.dumps(_POLL_INTERVAL_SECONDS)

    lines = [
        "# --- Feature 11: Live Blender Sync listener ---",
        "# Started unconditionally -- see this module's docstring for why.",
        "import queue",
        "import socketserver",
        "import threading",
        "",
        f"_LIVE_SYNC_PORT_FILENAME = {port_filename_literal}",
        "_live_sync_queue = queue.Queue()",
        "",
        "",
        "class _LiveSyncHandler(socketserver.StreamRequestHandler):",
        "    def handle(self):",
        "        # One connection, read for as long as FrameLabs keeps it",
        "        # open -- newline-delimited JSON, one message per line,",
        "        # matching sync_protocol.encode_message() on the sending",
        "        # side. A malformed line is skipped, not fatal to the",
        "        # connection -- one bad message should not sever sync for",
        "        # the rest of the session.",
        "        for raw_line in self.rfile:",
        "            text = raw_line.decode('utf-8').strip()",
        "            if not text:",
        "                continue",
        "            try:",
        "                data = json.loads(text)",
        "            except ValueError:",
        "                continue",
        "            _live_sync_queue.put(data)",
        "",
        "",
        "def _apply_live_sync_message(data):",
        "    scene = bpy.context.scene",
        "    frame_path = data.get('frame_path')",
        "    frame_count = data.get('frame_count') or 0",
        "    fps = data.get('fps')",
        "",
        "    if fps:",
        "        scene.render.fps = fps",
        "    scene.frame_end = max(1, frame_count)",
        "",
        "    if scene.sequence_editor is None:",
        "        scene.sequence_editor_create()",
        "    existing = [",
        "        s for s in scene.sequence_editor.strips",
        "        if s.name == 'FrameLabs Sequence'",
        "    ]",
        "    if existing:",
        "        if frame_path:",
        "            existing[0].elements.append(os.path.basename(frame_path))",
        "    elif frame_path:",
        "        # No strip yet -- the project had no frames when the",
        "        # scene was first built (see scene_builder.py's own",
        "        # `if FRAME_PATHS:` guard). This is the first frame ever",
        "        # sent, so create it fresh instead of appending.",
        "        scene.sequence_editor.strips.new_image(",
        "            name='FrameLabs Sequence',",
        "            filepath=frame_path,",
        "            channel=1,",
        "            frame_start=1,",
        "        )",
        "",
        "    camera_obj = scene.camera",
        "    if camera_obj is not None:",
        "        backgrounds = camera_obj.data.background_images",
        "        if backgrounds:",
        "            backgrounds[0].image_user.frame_duration = frame_count",
        "        elif frame_path:",
        "            # Same 'nothing existed yet' case as the VSE strip",
        "            # above, for the camera background image.",
        "            bg_image = bpy.data.images.load(frame_path)",
        "            bg_image.source = 'SEQUENCE'",
        "            camera_obj.data.show_background_images = True",
        "            background = backgrounds.new()",
        "            background.image = bg_image",
        "            background.alpha = 0.5",
        "            background.image_user.frame_start = 1",
        "            background.image_user.frame_duration = frame_count",
        "            background.image_user.use_auto_refresh = True",
        "",
        "",
        "def _drain_live_sync_queue():",
        "    # Runs on Blender's main thread (bpy.app.timers guarantees",
        "    # this), unlike _LiveSyncHandler.handle() above -- this is",
        "    # the only place _apply_live_sync_message() may be called",
        "    # from. A bad message is logged to Blender's system console",
        "    # and skipped, never left to kill this timer permanently --",
        "    # an unhandled exception here would silently end all future",
        "    # live-sync updates for the rest of the session.",
        "    try:",
        "        while True:",
        "            data = _live_sync_queue.get_nowait()",
        "            try:",
        "                _apply_live_sync_message(data)",
        "            except Exception as exc:",
        "                print(f'FrameLabs live sync: failed to apply update: {exc}')",
        "    except queue.Empty:",
        "        pass",
        f"    return {poll_interval_literal}",
        "",
        "",
        "def start_live_sync_listener():",
        "    server = socketserver.ThreadingTCPServer(",
        "        ('127.0.0.1', 0), _LiveSyncHandler",
        "    )",
        "    server.daemon_threads = True",
        "    port = server.server_address[1]",
        "    port_file = os.path.join(",
        "        os.path.dirname(os.path.abspath(__file__)), _LIVE_SYNC_PORT_FILENAME",
        "    )",
        "    with open(port_file, 'w') as f:",
        "        f.write(str(port))",
        "    thread = threading.Thread(target=server.serve_forever, daemon=True)",
        "    thread.start()",
        "    bpy.app.timers.register(_drain_live_sync_queue, persistent=True)",
        "",
        "",
        "start_live_sync_listener()",
    ]
    return "\n".join(lines)

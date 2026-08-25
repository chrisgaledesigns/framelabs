"""Wire protocol for Feature 11, Live Blender Sync.

Pure data/logic module, per the Developer Handbook -- no bpy and no Qt.
Shared by both sides of the connection: sync_client.py (FrameLabs'
process, the sender) and sync_listener_script.py (the Blender-side
listener this generates the *text* of, the receiver -- see that
module's docstring for why the Blender-side copy of this protocol is
a hand-written mirror rather than an import).

Messages are newline-delimited JSON objects sent over a plain TCP
socket -- the simplest framing that works for a same-machine,
localhost-only connection with no need for a real RPC framework.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from framelabs.project.project import Project

# Filename (not a full path) the Blender-side listener writes its
# bound port number into, alongside the generator script itself
# (project_path/cache/blender/). A filename rather than a fixed port
# number because a fixed port can already be in use by something else
# on the user's machine -- the listener binds to port 0 (OS-assigned)
# and reports back what it actually got.
LIVE_SYNC_PORT_FILENAME = "live_sync_port.txt"


class SyncProtocolError(Exception):
    """Raised when a SyncMessage can't be built or a wire message can't
    be decoded."""


@dataclass
class SyncMessage:
    """One "a frame was captured" update sent to a running Blender.

    Attributes:
        frame_number: The captured frame's number.
        frame_path: Absolute path to the frame's image file -- absolute
            for the same reason exporter.BlenderManifest.frame_paths is:
            the Blender-side listener runs in its own process with no
            guaranteed cwd relationship to the project folder.
        fps: The project's current frames-per-second, resent with every
            message (not just once at connect time) so a mid-session
            fps change is never silently missed.
        frame_count: Total frame count after this capture -- the
            listener uses this to extend the scene's frame range and
            the background image's playback duration.
    """

    frame_number: int
    frame_path: str
    fps: int
    frame_count: int


def encode_message(message: SyncMessage) -> bytes:
    """Serialize a SyncMessage as one newline-terminated JSON line.

    Args:
        message: The message to encode.

    Returns:
        UTF-8 bytes ready to write straight to the socket -- a trailing
        newline is always included, since the listener reads line by
        line.
    """
    return (json.dumps(asdict(message)) + "\n").encode("utf-8")


def decode_message(line: str) -> SyncMessage:
    """Parse one wire line back into a SyncMessage.

    Args:
        line: A single line of text, as produced by encode_message()
            (trailing newline optional -- callers typically pass an
            already-stripped line).

    Returns:
        The decoded SyncMessage.

    Raises:
        SyncProtocolError: If `line` isn't valid JSON, or doesn't
            contain exactly the fields SyncMessage requires.
    """
    try:
        data = json.loads(line)
        return SyncMessage(**data)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SyncProtocolError(f"Malformed live-sync message: {exc}") from exc


def build_sync_message(project: Project, frame_number: int) -> SyncMessage:
    """Build the SyncMessage for a just-captured frame.

    Args:
        project: The active project, with the new frame already added
            to project.frames (i.e. called after capture_frame()
            succeeds, same ordering CaptureController already uses).
        frame_number: The newly captured frame's number.

    Returns:
        A SyncMessage ready for sync_client.BlenderSyncClient.send().

    Raises:
        SyncProtocolError: If project has no project_path, or has no
            frame numbered frame_number -- either means there is
            nothing valid to send.
    """
    if project.project_path is None:
        raise SyncProtocolError("Project has no project_path set.")
    frame = next((f for f in project.frames if f.number == frame_number), None)
    if frame is None:
        raise SyncProtocolError(f"No frame numbered {frame_number} in project.")

    return SyncMessage(
        frame_number=frame_number,
        frame_path=str(project.project_path / frame.file),
        fps=project.fps,
        frame_count=len(project.frames),
    )

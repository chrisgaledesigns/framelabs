"""FrameLabs-side client for Feature 11, Live Blender Sync.

Connects to the socket server sync_listener_script.py starts inside a
launched Blender process, and sends SyncMessages to it. Pure Python --
no bpy (this runs in FrameLabs' own process, never Blender's) and no
Qt (threading/worker-thread concerns belong to
ui/blender_sync_controller.py, same split as launcher.py/
blender_controller.py). Per the Developer Handbook, Blender integration
is isolated to this package.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

from framelabs.blender.sync_protocol import (
    LIVE_SYNC_PORT_FILENAME,
    SyncMessage,
    encode_message,
)
from framelabs.core.logger import get_logger

logger = get_logger("blender.sync_client")

# How long to wait for the Blender-side listener's port file to appear
# after "Open in Blender" launches -- Blender itself needs a moment to
# start, load its Python environment, and run the generated script
# before the listener binds and writes the file, so a short poll loop
# is needed rather than expecting it immediately.
PORT_DISCOVERY_TIMEOUT_S = 15.0
PORT_DISCOVERY_POLL_INTERVAL_S = 0.2

# TCP connect timeout -- localhost-only, so a real listener should
# accept near-instantly; this only guards against a genuinely hung or
# unreachable process.
CONNECT_TIMEOUT_S = 5.0


class BlenderSyncError(Exception):
    """Raised when discovering, connecting to, or sending on Blender's
    live-sync listener fails."""


def discover_port(script_dir: Path, timeout: float = PORT_DISCOVERY_TIMEOUT_S) -> int:
    """Poll for the port file the Blender-side listener writes at startup.

    Args:
        script_dir: The directory the generator script (and therefore
            the port file, written alongside it) was written to -- the
            same `project_path / "cache" / "blender"` every other
            Blender bridge path already uses.
        timeout: How long to keep polling before giving up.

    Returns:
        The port number the listener bound to.

    Raises:
        BlenderSyncError: If no valid port file appears within timeout
            -- e.g. Blender failed to start, is still loading, or is an
            old FrameLabs-generated script from before this feature
            existed.
    """
    port_path = script_dir / LIVE_SYNC_PORT_FILENAME
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_path.is_file():
            try:
                return int(port_path.read_text().strip())
            except ValueError:
                pass  # File exists but hasn't been fully written yet.
        time.sleep(PORT_DISCOVERY_POLL_INTERVAL_S)
    raise BlenderSyncError(
        "Timed out waiting for Blender's live-sync listener to start " f"({port_path})"
    )


class BlenderSyncClient:
    """A persistent TCP connection to one running Blender's live-sync
    listener.

    One instance per launched Blender instance -- not reused across
    "Open in Blender" launches, since each launch starts a listener on
    a freshly-assigned port. Deliberately holds the socket open across
    many send() calls rather than reconnecting per-message: Feature 11
    fires on every capture, and a stop-motion session can easily
    involve hundreds of captures.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None

    @property
    def is_connected(self) -> bool:
        """Whether a live socket connection is currently held open."""
        return self._socket is not None

    def connect(self) -> None:
        """Open the TCP connection.

        Raises:
            BlenderSyncError: If the connection can't be established.
        """
        try:
            self._socket = socket.create_connection(
                (self._host, self._port), timeout=CONNECT_TIMEOUT_S
            )
        except OSError as exc:
            raise BlenderSyncError(
                f"Could not connect to Blender's live-sync listener: {exc}"
            ) from exc
        logger.info("Live sync connected to Blender at %s:%d", self._host, self._port)

    def send(self, message: SyncMessage) -> None:
        """Send one SyncMessage to the connected listener.

        Args:
            message: The message to send.

        Raises:
            BlenderSyncError: If not currently connected, or the send
                fails (e.g. Blender was closed) -- the connection is
                closed automatically on failure, so is_connected
                reflects the real state afterward without a separate
                call.
        """
        if self._socket is None:
            raise BlenderSyncError("Not connected to Blender's live-sync listener.")
        try:
            self._socket.sendall(encode_message(message))
        except OSError as exc:
            self.close()
            raise BlenderSyncError(f"Failed to send to Blender: {exc}") from exc

    def close(self) -> None:
        """Close the connection, if one is open. Safe to call more than
        once, or on a connection that already failed."""
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

"""Live Blender Sync controller for the UI layer.

Feature 11: once connected, every subsequent capture is pushed straight
into an already-open Blender window -- no re-export, no reload button.
Drives connection discovery and per-frame sends off the main thread,
per the Developer Handbook's "UI Never Blocks" rule -- discover_port()
polls the filesystem for up to PORT_DISCOVERY_TIMEOUT_S, and a socket
send can briefly block, neither of which belongs on the UI thread.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from every other worker thread --
in particular separate from BlenderBridgeController's own thread, since
a slow per-frame sync send should never make "Open in Blender" or
"Export .blend" wait, and vice versa.

Deliberately does NOT subscribe to the shared EventBus's FRAME_CAPTURED
directly -- that event is published from inside capture_service on
CaptureController's own worker thread, and EventBus dispatches
synchronously on whatever thread calls publish(). Reacting to it here
would mean this controller's connection state gets touched from a
thread that isn't its own. Instead, MainWindow's existing
_on_capture_succeeded() (already the main-thread funnel for
"a capture just finished") emits frame_sync_requested with the data
this controller needs -- the same "carry the request on the signal
itself" pattern every other controller in this package uses.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from framelabs.blender.sync_client import (
    BlenderSyncClient,
    BlenderSyncError,
    discover_port,
)
from framelabs.blender.sync_protocol import SyncProtocolError, build_sync_message
from framelabs.project.project import Project

logger = logging.getLogger(__name__)


class BlenderSyncController(QObject):
    """Discovers and holds the live-sync connection to a launched
    Blender instance, and forwards captured frames to it.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    sync_connected = Signal()
    # Distinct from sync_connect_failed: emitted after a send fails on
    # an already-connected client (e.g. the user closed the Blender
    # window mid-session), vs. never having connected in the first
    # place.
    sync_disconnected = Signal()
    sync_connect_failed = Signal(str)

    # Emitted from the main thread once "Open in Blender" succeeds;
    # connected to _handle_connect_requested below, which -- because
    # this object lives on the worker thread once moved -- Qt
    # automatically delivers via a queued connection.
    connect_requested = Signal(object)  # Project

    # Emitted from the main thread after every successful capture, but
    # only actually sent on to Blender if a connection is currently
    # held -- see _handle_frame_sync_requested(). Carries the Project
    # (for frame lookup/paths) and the captured frame's number.
    frame_sync_requested = Signal(object, int)  # Project, frame_number

    # Emitted from the main thread when the user turns Live Blender
    # Sync off, or switches/closes the active project.
    disconnect_requested = Signal()

    def __init__(self) -> None:
        """Build the controller. Stateless between projects by design --
        connect_requested always carries the Project it needs, so
        there's no separately-tracked "current project" to get out of
        sync with whichever one is actually open.
        """
        super().__init__()
        self._client: BlenderSyncClient | None = None

        self.connect_requested.connect(self._handle_connect_requested)
        self.frame_sync_requested.connect(self._handle_frame_sync_requested)
        self.disconnect_requested.connect(self._handle_disconnect_requested)

    def _handle_connect_requested(self, project: Project) -> None:
        """Discover the just-launched Blender's listener port and
        connect to it. Always runs on the worker thread.

        Replaces any previous connection outright rather than erroring
        if one is already held -- reaching this handler at all means
        "Open in Blender" just succeeded again, which only happens for
        a fresh launch (a new listener on a new port), so any earlier
        connection is necessarily stale.
        """
        if self._client is not None:
            self._client.close()
            self._client = None

        if project.project_path is None:
            logger.warning("Live sync connect requested with no project_path; skipping")
            self.sync_connect_failed.emit("Project has no project_path set.")
            return

        script_dir = project.project_path / "cache" / "blender"
        try:
            port = discover_port(script_dir)
            client = BlenderSyncClient("127.0.0.1", port)
            client.connect()
        except BlenderSyncError as exc:
            logger.error("Live sync connect failed: %s", exc)
            self.sync_connect_failed.emit(str(exc))
            return

        self._client = client
        self.sync_connected.emit()

    def _handle_frame_sync_requested(self, project: Project, frame_number: int) -> None:
        """Send one captured frame to Blender, if connected. Always runs
        on the worker thread.

        A no-op, not an error, when nothing is connected -- Live
        Blender Sync being off (or "Open in Blender" never having been
        run this session) is the ordinary case for most captures, not
        a failure.
        """
        if self._client is None:
            return

        try:
            message = build_sync_message(project, frame_number)
            self._client.send(message)
        except SyncProtocolError as exc:
            # Malformed request (e.g. frame_number not actually in the
            # project) -- the connection itself is still fine, so don't
            # tear it down over this one message.
            logger.error("Live sync: could not build message: %s", exc)
        except BlenderSyncError as exc:
            # The send itself failed -- BlenderSyncClient.send() already
            # closed the socket on failure, so this connection is dead;
            # drop the reference and tell the UI so it can reflect
            # "disconnected" (e.g. the user closed the Blender window).
            logger.warning("Live sync: send failed, disconnecting: %s", exc)
            self._client = None
            self.sync_disconnected.emit()

    def _handle_disconnect_requested(self) -> None:
        """Close the current connection, if any. Always runs on the
        worker thread."""
        if self._client is None:
            return
        self._client.close()
        self._client = None
        self.sync_disconnected.emit()

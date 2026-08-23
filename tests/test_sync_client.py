"""Tests for blender/sync_client.py.

Uses a real local TCP socket server (stdlib socketserver) rather than
mocking the socket module -- this is a thin networking wrapper, and a
real loopback connection is both simpler to set up correctly and a
more meaningful test than mocking every socket call.
"""

from __future__ import annotations

import socketserver
import threading
import time

import pytest

from framelabs.blender.sync_client import (
    PORT_DISCOVERY_POLL_INTERVAL_S,
    BlenderSyncClient,
    BlenderSyncError,
    discover_port,
)
from framelabs.blender.sync_protocol import SyncMessage, decode_message


class _EchoHandler(socketserver.StreamRequestHandler):
    """Records every decoded line it receives onto the server instance."""

    def handle(self):
        for raw_line in self.rfile:
            text = raw_line.decode("utf-8").strip()
            if text:
                self.server.received.append(text)


class _RefusingHandler(socketserver.StreamRequestHandler):
    """Accepts the connection, then closes it immediately -- simulates
    Blender having been closed mid-session."""

    def handle(self):
        self.request.close()


def _start_server(handler_cls):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler_cls)
    server.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def echo_server():
    server, thread = _start_server(_EchoHandler)
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


class TestDiscoverPort:
    def test_reads_port_once_file_appears(self, tmp_path):
        port_path = tmp_path / "live_sync_port.txt"
        port_path.write_text("54321")

        assert discover_port(tmp_path, timeout=1.0) == 54321

    def test_picks_up_a_file_written_shortly_after(self, tmp_path):
        port_path = tmp_path / "live_sync_port.txt"

        def _write_late():
            time.sleep(PORT_DISCOVERY_POLL_INTERVAL_S * 2)
            port_path.write_text("9999")

        threading.Thread(target=_write_late).start()

        assert discover_port(tmp_path, timeout=2.0) == 9999

    def test_times_out_if_file_never_appears(self, tmp_path):
        with pytest.raises(BlenderSyncError):
            discover_port(tmp_path, timeout=0.3)


class TestBlenderSyncClient:
    def test_connect_and_send_reaches_the_server(self, echo_server):
        client = BlenderSyncClient("127.0.0.1", echo_server.server_address[1])
        client.connect()
        assert client.is_connected

        message = SyncMessage(
            frame_number=1, frame_path="/proj/images/000001.png", fps=12, frame_count=1
        )
        client.send(message)
        client.close()

        # Give the server's handler thread a moment to process the line.
        deadline = time.monotonic() + 2.0
        while not echo_server.received and time.monotonic() < deadline:
            time.sleep(0.05)

        assert len(echo_server.received) == 1
        assert decode_message(echo_server.received[0]) == message

    def test_connect_to_nothing_listening_raises(self):
        client = BlenderSyncClient("127.0.0.1", 1)  # port 1: nothing listens here
        with pytest.raises(BlenderSyncError):
            client.connect()

    def test_send_without_connect_raises(self):
        client = BlenderSyncClient("127.0.0.1", 12345)
        message = SyncMessage(1, "/a.png", 12, 1)
        with pytest.raises(BlenderSyncError):
            client.send(message)

    def test_send_after_peer_closes_raises_and_disconnects(self):
        server, thread = _start_server(_RefusingHandler)
        try:
            client = BlenderSyncClient("127.0.0.1", server.server_address[1])
            client.connect()

            message = SyncMessage(1, "/a.png", 12, 1)
            # The peer closes its end right after accepting; the local
            # send may succeed once before the closed state is
            # detected (TCP doesn't guarantee immediate feedback), so
            # send a few times to reliably surface the failure.
            for _ in range(20):
                try:
                    client.send(message)
                except BlenderSyncError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Expected BlenderSyncError from a closed peer")

            assert not client.is_connected
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_close_is_safe_to_call_twice(self, echo_server):
        client = BlenderSyncClient("127.0.0.1", echo_server.server_address[1])
        client.connect()
        client.close()
        client.close()
        assert not client.is_connected

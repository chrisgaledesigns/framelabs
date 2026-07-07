"""Tests for the EventBus."""

from framelabs.core.event_bus import EventBus


def test_subscriber_receives_published_event():
    bus = EventBus()
    received = {}

    def handler(payload):
        received["frame_number"] = payload["frame_number"]

    bus.subscribe("FRAME_CAPTURED", handler)
    bus.publish("FRAME_CAPTURED", {"frame_number": 7})

    assert received["frame_number"] == 7


def test_unsubscribed_handler_does_not_receive_event():
    bus = EventBus()
    received = []

    def handler(payload):
        received.append(payload)

    bus.subscribe("FRAME_CAPTURED", handler)
    bus.unsubscribe("FRAME_CAPTURED", handler)
    bus.publish("FRAME_CAPTURED", {"frame_number": 7})

    assert received == []


def test_handler_exception_does_not_stop_other_handlers():
    bus = EventBus()
    results = []

    def bad_handler(payload):
        raise ValueError("boom")

    def good_handler(payload):
        results.append("ran")

    bus.subscribe("FRAME_CAPTURED", bad_handler)
    bus.subscribe("FRAME_CAPTURED", good_handler)
    bus.publish("FRAME_CAPTURED", {})

    assert results == ["ran"]
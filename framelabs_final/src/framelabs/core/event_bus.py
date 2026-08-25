"""Application-wide event bus.

Modules communicate through events rather than calling each other
directly. This keeps modules decoupled, per the FrameLabs Developer
Handbook's "Explicit Over Clever" and layering rules.

Example:
    bus = EventBus()
    bus.subscribe("FRAME_CAPTURED", on_frame_captured)
    bus.publish("FRAME_CAPTURED", {"frame_number": 42})
"""

from collections import defaultdict
from typing import Any, Callable

from framelabs.core.logger import get_logger

logger = get_logger("core.event_bus")

EventHandler = Callable[[dict[str, Any]], None]


class EventBus:
    """A simple publish/subscribe event bus.

    Event names should describe something that has already happened,
    in past tense (e.g. "FRAME_CAPTURED", not "CAPTURE_FRAME").
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register a handler to be called whenever event_name is published."""
        self._subscribers[event_name].append(handler)
        logger.info("Subscriber added for event: %s", event_name)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        if handler in self._subscribers[event_name]:
            self._subscribers[event_name].remove(handler)
            logger.info("Subscriber removed for event: %s", event_name)

    def publish(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Notify all subscribers that event_name has occurred.

        Never silently swallows handler exceptions -- per the handbook's
        error handling rule, exceptions are logged, not hidden.
        """
        payload = payload or {}
        logger.info("Event published: %s", event_name)

        for handler in list(self._subscribers[event_name]):
            try:
                handler(payload)
            except Exception as exc:  # noqa: BLE001
                logger.error("Handler for %s raised an exception: %s", event_name, exc)

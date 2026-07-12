"""Onion skin frame-loading controller for the UI layer.

Reads previous/next frame image bytes off disk, per the Developer
Handbook's "UI Never Blocks" rule -- file I/O must never run on the main
thread by policy, even for the handful of small files onion skin needs.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from every other worker thread --
onion skin refreshes happen on capture and on playhead/settings changes,
and shouldn't contend with camera scanning, capture, live preview, or
project save/load.

Only raw image bytes are emitted, never QImage/QPixmap -- decoding
happens on the main thread inside LiveViewWidget, the same pattern
LiveViewController already uses for live preview frames. Building Qt
image objects off the main thread is avoided deliberately.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from framelabs.timeline.onion_skin import OnionSkinSettings
from framelabs.timeline.timeline import Timeline

logger = logging.getLogger(__name__)

# Each entry: (image_bytes, opacity, tint_hex).
OnionLayer = tuple[bytes, float, str]


class OnionSkinController(QObject):
    """Loads onion skin frame bytes on a worker thread for the UI.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    # before_layers, after_layers -- nearest-frame-first in each list,
    # matching Timeline.frames_before_current()/frames_after_current().
    frames_ready = Signal(list, list)

    refresh_requested = Signal(object, object)  # Timeline, OnionSkinSettings

    def __init__(self) -> None:
        """Build the controller. Stateless between requests by design --
        every refresh is given the Timeline and settings it needs, so
        there's nothing to get out of sync.
        """
        super().__init__()
        self.refresh_requested.connect(self._handle_refresh_requested)

    def _handle_refresh_requested(
        self, timeline: Timeline, settings: OnionSkinSettings
    ) -> None:
        """Load previous/next frame bytes and emit them. Worker thread only.

        Missing or unreadable frame files are skipped with a warning
        rather than failing the whole refresh -- one bad frame shouldn't
        blank out the rest of the onion skin overlay.
        """
        if not settings.enabled:
            self.frames_ready.emit([], [])
            return

        before_layers = self._load_layers(
            timeline,
            timeline.frames_before_current(settings.previous_count),
            settings.previous_tint,
            settings,
        )
        after_layers = self._load_layers(
            timeline,
            timeline.frames_after_current(settings.next_count),
            settings.next_tint,
            settings,
        )
        self.frames_ready.emit(before_layers, after_layers)

    @staticmethod
    def _load_layers(
        timeline: Timeline,
        frames: list,
        tint: str,
        settings: OnionSkinSettings,
    ) -> list[OnionLayer]:
        """Read each frame's image bytes off disk, nearest-first.

        Args:
            timeline: Used only for its project's project_path, to resolve
                each frame's relative file path.
            frames: Frames to load, already ordered nearest-first by the
                caller (Timeline.frames_before_current()/
                frames_after_current()).
            tint: Hex tint color to pair with every layer in this list.
            settings: Used for opacity_for_distance() -- distance is this
                frame's 1-indexed position in `frames`.
        """
        project_path = timeline.project.project_path
        if project_path is None:
            logger.warning("Onion skin refresh with no project_path; skipping")
            return []

        layers: list[OnionLayer] = []
        for distance, frame in enumerate(frames, start=1):
            frame_path = project_path / frame.file
            try:
                image_bytes = frame_path.read_bytes()
            except OSError as exc:
                logger.warning(
                    "Onion skin: could not read frame %d (%s): %s",
                    frame.number,
                    frame_path,
                    exc,
                )
                continue
            opacity = settings.opacity_for_distance(distance)
            layers.append((image_bytes, opacity, tint))
        return layers

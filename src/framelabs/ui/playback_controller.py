"""Playback controller for Feature 7 -- drives the Timeline's playhead on
a background QTimer and emits the frame at each new position for display.

Meant to be moved to its own dedicated QThread via moveToThread(), separate
from every other worker thread -- playback runs continuously while active
and reads a frame image off disk on every tick (per the Handbook's "UI
Never Blocks" rule, that file I/O must not run on the main thread), so it
shouldn't contend with camera scanning, capture, live preview, onion skin
refreshes, or project save/load.

Threading contract: __init__ and moveToThread() happen on the main thread.
start_requested/stop_requested are Signals connected from the main thread
and queued onto this controller's own thread automatically by Qt. The
QTimer itself is only ever started/stopped from
_handle_start_requested/_handle_stop_requested, which only run on this
controller's own thread once it's been moved -- never call those directly
from the main thread.

QTimer must be constructed with `self` as its parent (see __init__) -- an
unparented QTimer keeps the thread affinity of whichever thread *created*
it, and moveToThread() only carries an object's CHILDREN along with it, not
unparented sibling objects. Since PlaybackController() itself is
constructed on the main thread before moveToThread() moves it to its
worker thread, an unparented `QTimer()` here would silently stay stuck on
the main thread forever, and QTimer.start() calls made later from the
worker thread would fail with "QObject::startTimer: Timers cannot be
started from another thread" -- the timer would never actually tick, so
Playback would appear completely inert (Play/Pause toggles fine, Loop and
speed settings update fine, but no frames ever advance) with no exception
raised anywhere to point at why.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from framelabs.timeline.playback import PlaybackSettings
from framelabs.timeline.timeline import Timeline

logger = logging.getLogger(__name__)


class PlaybackController(QObject):
    """Drives Timeline playback on a worker thread via QTimer.

    Looping is handled here, not in Timeline -- Timeline.next_frame()
    deliberately clamps rather than wraps at the last frame (see its own
    docstring), since "where the playhead sits" and "what happens when
    playback reaches the end" are different responsibilities.
    """

    # Emits the newly-current frame's raw image bytes for display.
    frame_ready = Signal(bytes)

    # Emitted every time the playhead advances, so the main window can
    # refresh Onion Skin to match -- Playback and Onion Skin both read the
    # same Timeline.current_index, so Onion Skin must be told to reload
    # whenever Playback moves it, not only on capture.
    playhead_advanced = Signal()

    # Emitted when playback stops itself (reached the end, not looping) --
    # lets the main window un-press the Play button to match reality.
    playback_finished = Signal()

    start_requested = Signal(object, object)  # Timeline, PlaybackSettings
    stop_requested = Signal()

    def __init__(self) -> None:
        """Build the controller. The QTimer is created here but only
        started/stopped once this object has been moved to its worker
        thread -- see module docstring.

        The timer is parented to `self` specifically so that a later
        moveToThread() call on the controller carries the timer's thread
        affinity along with it -- an unparented QTimer would not move,
        and would then fail to start when triggered from the worker
        thread. See the module docstring for the full explanation.
        """
        super().__init__()
        self._timeline: Timeline | None = None
        self._settings: PlaybackSettings | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        self.start_requested.connect(self._handle_start_requested)
        self.stop_requested.connect(self._handle_stop_requested)

    def _handle_start_requested(
        self, timeline: Timeline, settings: PlaybackSettings
    ) -> None:
        """Begin ticking the timer at the given settings' speed. Worker
        thread only -- QTimer.start() must run on the thread that owns
        the timer.
        """
        self._timeline = timeline
        self._settings = settings
        interval = settings.interval_ms(timeline.project.fps)
        self._timer.start(interval)
        logger.info(
            "Playback started at %d%% speed (%dms/frame), loop=%s",
            settings.speed_percent,
            interval,
            settings.loop,
        )

    def _handle_stop_requested(self) -> None:
        """Stop the timer. Worker thread only."""
        self._timer.stop()
        logger.info("Playback stopped")

    def _advance(self) -> None:
        """Advance the playhead by one frame and emit it for display.

        At the last frame: loops back to the first frame if
        settings.loop is enabled, otherwise stops the timer and emits
        playback_finished so the UI can reset its Play button. Recomputes
        the timer interval from settings every tick (not just at start),
        so a live speed change -- settings is the same shared object the
        whole time, mutated directly from the main thread -- takes effect
        on the very next frame rather than only after Play is stopped and
        restarted.
        """
        if self._timeline is None or self._settings is None:
            return

        if not self._timeline.frames:
            self._handle_stop_requested()
            self.playback_finished.emit()
            return

        interval = self._settings.interval_ms(self._timeline.project.fps)
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

        at_last_frame = self._timeline.current_index >= len(self._timeline) - 1
        if at_last_frame:
            if self._settings.loop:
                self._timeline.go_to_index(0)
            else:
                self._handle_stop_requested()
                self.playback_finished.emit()
                return
        else:
            self._timeline.next_frame()

        frame = self._timeline.current_frame
        if frame is None:
            return

        image_bytes = self._read_frame_bytes(frame)
        if image_bytes is not None:
            self.frame_ready.emit(image_bytes)
        self.playhead_advanced.emit()

    def _read_frame_bytes(self, frame) -> bytes | None:
        """Read a frame's image bytes off disk, or None if unreadable.

        Missing/unreadable frames are skipped with a warning rather than
        stopping playback entirely -- one bad frame shouldn't halt the
        whole sequence, same reasoning OnionSkinController uses.
        """
        project_path = self._timeline.project.project_path
        if project_path is None:
            logger.warning("Playback tick with no project_path; skipping")
            return None
        frame_path = project_path / frame.file
        try:
            return frame_path.read_bytes()
        except OSError as exc:
            logger.warning(
                "Playback: could not read frame %d (%s): %s",
                frame.number,
                frame_path,
                exc,
            )
            return None

"""Theater View dialog -- movable/resizable frame preview for the Project
Browser.

Implements Chris's session-15 follow-up on the Project Browser panel
(backlog item #3): double-clicking a frame tile in the Frames grid opens a
large preview of that frame's real image, in a normal, movable, resizable
window (not full-screen -- Chris asked for this explicitly after the
initial full-screen version). This is deliberately
DIFFERENT from every other double-click/click path already in this app
(the Timeline strip, and the Project Browser's own Notes list), which
moves the Timeline's playhead. Per Chris's explicit choice, opening this
dialog must NOT move the playhead or change the Timeline/frame-action-bar
selection -- it's a pure, read-only preview, the same "never modifies the
project" guarantee Feature 7 (Playback) already gives its own frame
stepping.

This dialog owns its own local browsing position entirely separately from
Timeline.current_index -- arrow-key Left/Right here steps through frames
for browsing only, and the scrub bar along the bottom is just another way
to drive that same local position (dragging it calls go_to_index(), the
identical method Left/Right and the initial start_index already go
through -- there's only one code path that ever changes _index). Closing
the dialog (Escape or the Close button) leaves the Timeline's real
playhead exactly where it was before the dialog opened, since nothing
here ever touches Project/Timeline state.

Reads the frame's real, full-resolution image at
project_path/frame.file (e.g. images/000001.png) -- NOT the small
thumbnail ProjectBrowserWidget/TimelineWidget read from thumbnails/ --
since the point of a "theater view" is to see the real captured frame at
full size, scaled to fit the screen.

Transport controls (Play/Pause, Loop, Step Back/Forward) and the
timecode readout are this dialog's own local playback -- a lightweight,
single-QTimer loop that lives entirely inside this class, deliberately
NOT a reuse of ui/playback_controller.py's PlaybackController. That
controller is built for the main window's Timeline: it runs on a
dedicated worker thread, reads frames off disk on every tick, and writes
to Timeline.current_index -- none of which fits here. This dialog reads
already-loaded pixmaps from a plain Python list its own _load_current_
frame() populates, has no Timeline to write to (see above -- it must
never move the real playhead), and is a modal dialog with its own event
loop rather than a long-lived main-window widget, so a plain QTimer on
the GUI thread is both sufficient and simpler. It shares only the
*meaning* of playback with Feature 7 (play/pause, loop-or-stop-at-the-
end, speed derived from fps) -- see _advance_playback()'s docstring for
exactly how the end-of-sequence behavior differs from PlaybackController
's, and why.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from framelabs.project.project import Frame
from framelabs.ui.timecode_widget import format_timecode


class _SeekSlider(QSlider):
    """Horizontal QSlider that jumps straight to wherever it's clicked,
    instead of stock QSlider's default of paging one step toward the
    click -- and shows a "Frame N  HH:MM:SS:FF" tooltip under the cursor
    while hovering or dragging, so a click always lands on the frame the
    tooltip just promised.

    Plain QSlider only warps its handle to the exact click position when
    you grab the handle itself and drag it; clicking anywhere else on the
    groove just pages toward that point one step at a time, which from a
    user's chair looks like "the scrub bar doesn't let me jump into the
    middle of the timeline" -- exactly the gap this subclass closes for
    TheaterViewDialog's scrub bar. Reports position the same way a real
    drag already does (via the inherited sliderMoved signal), so
    TheaterViewDialog's existing _on_scrub_bar_moved() wiring below needs
    no changes to benefit from this.
    """

    def __init__(
        self, tooltip_formatter, parent: QWidget | None = None
    ) -> None:
        """`tooltip_formatter` maps a frame index to the tooltip string to
        show for it (or a falsy value to show nothing) -- kept as an
        injected callback rather than this class reaching into
        TheaterViewDialog's frame list directly, so this slider stays a
        generic, dialog-agnostic widget.
        """
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._tooltip_formatter = tooltip_formatter
        # Tracks the last frame index the tooltip was shown for, so
        # _maybe_show_tooltip() only re-issues QToolTip.showText() when
        # that index actually changes. setMouseTracking(True) below
        # delivers a mouseMoveEvent for every single pixel the cursor
        # crosses -- calling showText() unconditionally on every one of
        # those (the first version of this class did) reissues the
        # tooltip dozens of times a second even for near-stationary
        # movement, which reads as the tooltip flashing/flickering.
        self._last_tooltip_value: int | None = None
        # Needed so mouseMoveEvent fires on plain hovering, not just while
        # a button is held down -- that's what makes the tooltip preview
        # available *before* the user commits to a click.
        self.setMouseTracking(True)

    def _value_at_x(self, x: int) -> int:
        """Map a click/hover x-coordinate to the frame index under it,
        accounting for the handle's own width the same way Qt's internal
        paging logic does (QStyle.sliderValueFromPosition), so the frame
        that ends up selected is the one actually under the cursor rather
        than off by the handle's radius.
        """
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        slider_length = handle.width()
        slider_min = groove.x()
        slider_max = groove.right() - slider_length + 1
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            x - slider_min - slider_length // 2,
            slider_max - slider_min,
        )

    def _maybe_show_tooltip(self, value: int, global_pos: QPoint) -> None:
        """Show the tooltip for `value`, but only if it's different from
        the last one shown -- see `_last_tooltip_value`'s docstring for
        why re-issuing on every pixel of movement is what caused the
        flashing/flickering.
        """
        if value == self._last_tooltip_value:
            return
        self._last_tooltip_value = value
        text = self._tooltip_formatter(value)
        if text:
            QToolTip.showText(global_pos, text, self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Left-click anywhere on the groove: jump straight to that
        frame, then hand off to QSlider's own stock press handling via
        super() -- deliberately NOT reimplemented from scratch.

        Setting the value first moves the handle to sit exactly under
        the click, so when super().mousePressEvent() runs its own
        hit-test immediately after, it finds the click landing on the
        handle and treats this as a normal handle-grab (anchoring for a
        possible drag) rather than fighting the jump with its own
        page-step-towards-click logic.

        Calling super() here -- rather than this class managing
        isSliderDown()/pressed state by hand, as an earlier version of
        this method did -- matters for a reason that isn't obvious from
        the press side alone: QSlider's stock mouseReleaseEvent only
        clears the "pressed" state if QSlider's OWN mousePressEvent set
        up its internal pressedControl bookkeeping first. Skipping
        super() here left that bookkeeping never set, so the inherited
        release handler had nothing to clear -- the slider stayed
        "pressed" forever after the very first click. With the slider
        stuck pressed, every later setValue() call from
        TheaterViewDialog._sync_scrub_bar() (which runs on every
        playback tick) started being treated like an interactive drag
        update and re-emitted sliderMoved, which
        TheaterViewDialog._on_scrub_bar_moved() responds to by pausing
        playback -- so Play would advance exactly one frame and then
        self-pause, on every play after the first click. Always
        deferring to super() for the actual press/drag/release state
        machine avoids re-introducing that.
        """
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            value = self._value_at_x(int(event.position().x()))
            self.setValue(value)
            self.sliderMoved.emit(value)
            self._maybe_show_tooltip(value, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Preview the frame under the cursor via tooltip, both while
        merely hovering and while actively dragging. The seek itself
        during an active drag is entirely QSlider's own stock behavior
        (it already emits sliderMoved as the drag proceeds) -- this
        method only adds the tooltip on top via super(), never a second,
        competing seek.
        """
        if self.isEnabled():
            value = self._value_at_x(int(event.position().x()))
            self._maybe_show_tooltip(value, event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Hide any hover tooltip left showing once the cursor leaves the
        bar entirely, so it doesn't linger over unrelated widgets, and
        forget the last shown value so re-entering shows fresh.
        """
        QToolTip.hideText()
        self._last_tooltip_value = None
        super().leaveEvent(event)

# A deliberately near-black (not pure #000) backdrop, so a fully black
# source frame still reads as distinct from the surrounding dialog --
# matches LiveViewWidget's own dark letterbox background.
_BACKGROUND_STYLE = "background-color: #141414;"
_POSITION_LABEL_STYLE = "color: white; font-size: 14px;"
_PLACEHOLDER_LABEL_STYLE = "color: white;"
_TIMECODE_LABEL_STYLE = "color: white; font-size: 13px; font-family: monospace;"
_TRANSPORT_BUTTON_STYLE = "color: white; min-width: 32px;"
# Loop's checked/unchecked look needs to be visibly different at a glance
# (it's a toggle, not a momentary action like Step Back/Forward), so it
# gets its own stylesheet with a highlighted checked state rather than
# sharing _TRANSPORT_BUTTON_STYLE.
_LOOP_BUTTON_STYLE = """
    QPushButton { color: white; min-width: 56px; }
    QPushButton:checked { color: #141414; background-color: #4da3ff; }
"""

# Fallback used only if the dialog is ever constructed without an
# explicit fps (e.g. by older call sites/tests predating this
# parameter) -- matches config.py's own DEFAULT_SETTINGS["default_fps"],
# so an un-migrated call site still plays back at the same speed a new
# project would default to, rather than some arbitrary other number.
_DEFAULT_FPS = 12

# Default size is generous enough to read a frame clearly on a typical
# monitor without opening full-screen; minimum keeps the position label
# and Close button usable if Chris shrinks the window a lot.
_DEFAULT_WIDTH = 1100
_DEFAULT_HEIGHT = 750
_MINIMUM_WIDTH = 400
_MINIMUM_HEIGHT = 300


class TheaterViewDialog(QDialog):
    """Movable, resizable, read-only preview of a project's frames.

    Construct with the project's full ordered frame list (Timeline.frames
    -- already sorted by frame number, the same list every raw frame
    index elsewhere in the app indexes into) plus the index to start on.
    Opening this dialog never touches Timeline, Project, or any other app
    state -- it only reads image files from disk.
    """

    def __init__(
        self,
        project_path: Path,
        frames: list[Frame],
        start_index: int,
        fps: int = _DEFAULT_FPS,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and show `frames[start_index]` first.

        `start_index` is clamped into range (matching Timeline.go_to_index's
        own clamping convention) rather than raising, so a stale/edge-case
        index can't crash the preview.

        `fps` drives both the timecode readout's HH:MM:SS:FF math and the
        Play button's frame-advance interval -- pass the open project's
        real fps (Project.fps) so this dialog's own local playback moves
        at the same speed the project actually plays at everywhere else.
        Falls back to _DEFAULT_FPS if omitted; clamped to at least 1 the
        same way format_timecode() and PlaybackSettings.interval_ms()
        both already guard against a malformed/zero fps.
        """
        super().__init__(parent)
        self._project_path = project_path
        self._frames = frames
        self._index = max(0, min(start_index, len(frames) - 1)) if frames else 0
        self._fps = max(1, fps)
        self._current_pixmap: QPixmap | None = None
        self._loop = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_playback)

        self.setWindowTitle("Theater View")
        self.setStyleSheet(_BACKGROUND_STYLE)
        # Normal, movable, resizable window -- not full-screen. QDialog is
        # resizable by default (no fixed size policy is set below), and
        # keeping the native title bar is what makes it draggable.
        self.setSizeGripEnabled(True)
        self.resize(_DEFAULT_WIDTH, _DEFAULT_HEIGHT)
        self.setMinimumSize(_MINIMUM_WIDTH, _MINIMUM_HEIGHT)

        self._build_ui()
        self._load_current_frame()

    def _build_ui(self) -> None:
        """Build the image label, frame-position label, transport
        controls, scrub bar, timecode readout, and Close button.
        """
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._position_label = QLabel()
        self._position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._position_label.setStyleSheet(_POSITION_LABEL_STYLE)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(8, 8, 8, 0)
        top_bar_layout.addWidget(self._position_label, 1)
        top_bar_layout.addWidget(close_button)

        # Scrub bar: one tick per frame, so dragging (or now, clicking)
        # it lands exactly on a frame boundary rather than some
        # fractional position with nothing to show -- there's no
        # "in-between" state for a sequence of still images the way
        # there is for video. sliderMoved (not valueChanged) drives
        # navigation, since valueChanged also fires for the programmatic
        # setValue() calls _sync_scrub_bar() makes after a Left/Right key
        # press or the initial start_index -- using sliderMoved keeps
        # those two update paths (keyboard -> slider, slider ->
        # keyboard-equivalent) from feeding back into each other.
        #
        # _SeekSlider (not a plain QSlider) so a click anywhere on the
        # bar jumps straight to that frame instead of paging one step
        # toward it -- see that class's docstring for why plain QSlider
        # doesn't already do this -- and so hovering previews the frame
        # under the cursor via a "Frame N  timecode" tooltip before the
        # user commits to a click.
        self._scrub_bar = _SeekSlider(self._scrub_bar_tooltip_text)
        self._scrub_bar.setMinimum(0)
        self._scrub_bar.setMaximum(max(0, len(self._frames) - 1))
        self._scrub_bar.setEnabled(bool(self._frames))
        self._scrub_bar.setTracking(True)
        self._scrub_bar.sliderMoved.connect(self._on_scrub_bar_moved)

        scrub_row = QWidget()
        scrub_row_layout = QHBoxLayout(scrub_row)
        scrub_row_layout.setContentsMargins(8, 0, 8, 0)
        scrub_row_layout.addWidget(self._scrub_bar)

        # Transport row: Step Back / Play-Pause / Step Forward / Loop on
        # the left, the HH:MM:SS:FF timecode readout on the right --
        # mirrors a conventional media-player layout (playback buttons
        # grouped together, time reading off to the side) so it's
        # immediately familiar despite being local to this dialog rather
        # than the app's own Feature 7 transport.
        can_play = len(self._frames) > 1

        step_back_button = QPushButton("\u23ee")  # step-back glyph
        step_back_button.setToolTip("Step to previous frame")
        step_back_button.setStyleSheet(_TRANSPORT_BUTTON_STYLE)
        step_back_button.setEnabled(bool(self._frames))
        step_back_button.clicked.connect(self._step_back)

        self._play_button = QPushButton("\u25b6 Play")  # play glyph
        self._play_button.setCheckable(True)
        self._play_button.setEnabled(can_play)
        self._play_button.setStyleSheet(_TRANSPORT_BUTTON_STYLE)
        self._play_button.toggled.connect(self._on_play_toggled)

        step_forward_button = QPushButton("\u23ed")  # step-forward glyph
        step_forward_button.setToolTip("Step to next frame")
        step_forward_button.setStyleSheet(_TRANSPORT_BUTTON_STYLE)
        step_forward_button.setEnabled(bool(self._frames))
        step_forward_button.clicked.connect(self._step_forward)

        self._loop_button = QPushButton("Loop")
        self._loop_button.setCheckable(True)
        self._loop_button.setToolTip(
            "When on, Play wraps back to the first frame instead of"
            " stopping at the last one"
        )
        self._loop_button.setStyleSheet(_LOOP_BUTTON_STYLE)
        self._loop_button.toggled.connect(self._on_loop_toggled)

        self._timecode_label = QLabel()
        self._timecode_label.setStyleSheet(_TIMECODE_LABEL_STYLE)
        self._timecode_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight
        )

        transport_row = QWidget()
        transport_row_layout = QHBoxLayout(transport_row)
        transport_row_layout.setContentsMargins(8, 0, 8, 8)
        transport_row_layout.addWidget(step_back_button)
        transport_row_layout.addWidget(self._play_button)
        transport_row_layout.addWidget(step_forward_button)
        transport_row_layout.addWidget(self._loop_button)
        transport_row_layout.addStretch(1)
        transport_row_layout.addWidget(self._timecode_label)

        bottom_bar = QWidget()
        bottom_bar_layout = QVBoxLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(0, 0, 0, 0)
        bottom_bar_layout.setSpacing(2)
        bottom_bar_layout.addWidget(scrub_row)
        bottom_bar_layout.addWidget(transport_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(top_bar)
        layout.addWidget(self._image_label, 1)
        layout.addWidget(bottom_bar)

    def _load_current_frame(self) -> None:
        """Read the current frame's real image from disk and repaint.

        Falls back to a plain "No Image" label for an unreadable/missing
        file -- the same non-crashing fallback pattern
        ProjectBrowserWidget/FrameThumbnail already use for a missing
        thumbnail -- rather than a broken image or an exception.
        """
        if not self._frames:
            self._current_pixmap = None
            self._image_label.setStyleSheet(_PLACEHOLDER_LABEL_STYLE)
            self._image_label.setText("No frames to preview")
            self._position_label.setText("")
            self._timecode_label.setText("")
            self._rescale_current_pixmap()
            return

        frame = self._frames[self._index]
        pixmap = QPixmap(str(self._project_path / frame.file))

        if pixmap.isNull():
            self._current_pixmap = None
            self._image_label.setStyleSheet(_PLACEHOLDER_LABEL_STYLE)
            self._image_label.setText("No Image")
        else:
            self._current_pixmap = pixmap
            self._image_label.setStyleSheet("")

        self._position_label.setText(
            f"Frame {frame.number}  ({self._index + 1} of {len(self._frames)})"
        )
        self._timecode_label.setText(format_timecode(self._index, self._fps))
        self._sync_scrub_bar()
        self._rescale_current_pixmap()

    def _sync_scrub_bar(self) -> None:
        """Move the scrub bar's handle to match `_index`.

        Called after every change to `_index`, regardless of what
        triggered it (Left/Right, the scrub bar's own drag, Play, the
        Step buttons, or the initial start_index) -- setValue() doesn't
        emit sliderMoved (only an actual drag does), so this never feeds
        back into _on_scrub_bar_moved() and re-navigate. Kept as its own
        method, called from the same place _position_label gets updated,
        so the label and the scrub bar can never drift out of sync with
        each other.
        """
        self._scrub_bar.setValue(self._index)

    def _scrub_bar_tooltip_text(self, index: int) -> str:
        """Format the "Frame N  HH:MM:SS:FF" tooltip _SeekSlider shows
        while hovering/dragging over `index`.

        Passed into _SeekSlider as a callback (see its __init__ docstring
        for why) rather than that class reaching into `_frames`/`_fps`
        directly. Returns "" for an out-of-range index (e.g. the slider
        is disabled with zero frames, or a hover lands a pixel past the
        last valid position) so _SeekSlider's "falsy means show nothing"
        contract is satisfied instead of raising or showing a bogus
        frame.
        """
        if not self._frames or not (0 <= index < len(self._frames)):
            return ""
        frame = self._frames[index]
        return f"Frame {frame.number}  {format_timecode(index, self._fps)}"

    def _rescale_current_pixmap(self) -> None:
        """Re-scale the currently loaded pixmap to fit the image label.

        Rescales the already-loaded pixmap rather than re-reading the
        file from disk, so window resizes stay cheap. Deliberately does
        NOT call setPixmap() at all when there's no pixmap to show --
        QLabel treats pixmap/text as mutually exclusive, so even a null
        QPixmap would wipe out whatever placeholder text
        _load_current_frame() just set.
        """
        if self._current_pixmap is None:
            return
        scaled = self._current_pixmap.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def go_to_index(self, index: int) -> None:
        """Move the preview to `index` if in range; otherwise no-op.

        Public (not `_go_to`) so tests can drive navigation directly,
        matching how Timeline.go_to_index is itself tested directly.
        Deliberately does not wrap or clamp past the ends -- stepping
        past the first/last frame simply does nothing, same as
        Timeline.next_frame/previous_frame's own boundary behavior.

        Does NOT stop Play on its own -- _advance_playback() calls this
        every tick, so pausing here would make Play immediately pause
        itself. Callers driven by the user (arrow keys, the scrub bar,
        the Step buttons) stop playback themselves first; see
        _pause_playback()'s docstring.
        """
        if not self._frames:
            return
        if 0 <= index < len(self._frames):
            self._index = index
            self._load_current_frame()

    def _on_scrub_bar_moved(self, index: int) -> None:
        """Handle a user drag of the scrub bar.

        Stops Play first -- a manual scrub while playing would otherwise
        fight with the timer's own next tick, which would then jump the
        handle again a moment later. Matches the same
        pause-before-manual-navigation the Step buttons and arrow keys
        use; see _pause_playback().
        """
        self._pause_playback()
        self.go_to_index(index)

    def _step_back(self) -> None:
        """Step Back button: pause Play, then move one frame earlier."""
        self._pause_playback()
        self.go_to_index(self._index - 1)

    def _step_forward(self) -> None:
        """Step Forward button: pause Play, then move one frame later."""
        self._pause_playback()
        self.go_to_index(self._index + 1)

    def _on_loop_toggled(self, checked: bool) -> None:
        """Track Loop's on/off state for _advance_playback() to read.

        Loop is just a flag Play consults at the end of the sequence --
        toggling it while Play is already running takes effect on the
        very next tick, same as flipping Feature 7's own loop setting
        mid-playback (PlaybackController._advance() rereads its shared
        settings object every tick for the identical reason). Toggling
        Loop never starts or stops Play itself.
        """
        self._loop = checked

    def _on_play_toggled(self, checked: bool) -> None:
        """React to the Play/Pause button's checked state changing,
        whether the user clicked it or Space toggled it programmatically.
        """
        if checked:
            self._start_playback()
        else:
            self._stop_timer_and_reset_button_text()

    def _start_playback(self) -> None:
        """Start the local QTimer advancing one frame per tick.

        No-op with fewer than two frames -- there's nothing to play
        through, matching why the Play button is disabled in that case
        to begin with (see _build_ui()). One frame advance per
        `1000 / fps` milliseconds, i.e. real-time playback at the
        project's own fps, with no separate speed control -- this
        dialog is a preview, not Feature 7's full transport.
        """
        if len(self._frames) < 2:
            return
        self._play_button.setText("\u23f8 Pause")  # pause glyph
        self._timer.start(round(1000 / self._fps))

    def _pause_playback(self) -> None:
        """Stop the timer and un-press the Play button, without
        recursing back through _on_play_toggled().

        setChecked() would itself emit `toggled` and re-enter
        _on_play_toggled(), which is harmless here (it would just call
        _stop_timer_and_reset_button_text() a second time) but is
        needless -- blockSignals() keeps this a plain, single-purpose
        "make Play agree that we're paused" call, used by every manual-
        navigation path (arrow keys, the scrub bar, the Step buttons)
        before it moves _index itself.
        """
        self._timer.stop()
        self._play_button.setText("\u25b6 Play")  # play glyph
        self._play_button.blockSignals(True)
        self._play_button.setChecked(False)
        self._play_button.blockSignals(False)

    def _stop_timer_and_reset_button_text(self) -> None:
        """Stop the timer and restore the Play button's label.

        Split out from _pause_playback() because that method also
        un-checks the button (for callers that are telling Play it's
        paused from the outside); this one is called FROM the button's
        own toggled(False) signal, where the button is already
        unchecked, so re-touching setChecked() here would be redundant
        (harmless, since it's already false, but redundant).
        """
        self._timer.stop()
        self._play_button.setText("\u25b6 Play")  # play glyph

    def _advance_playback(self) -> None:
        """One QTimer tick: advance to the next frame, or handle
        end-of-sequence.

        At the last frame: loops back to frame 0 if Loop is on,
        otherwise stops here and leaves the preview parked on the last
        frame with Play back to its unpressed state. This deliberately
        does NOT reset the playhead back to frame 0 the way
        PlaybackController._advance() does for the main Timeline --
        that reset exists there so the *real* playhead is immediately
        ready to record/play again; this dialog is a read-only preview
        with no recording concern, so leaving it sitting on the frame
        the user was just looking at (rather than snapping back to the
        start) is the less surprising behavior for a "watch it,
        specifically the ending" browsing action.
        """
        if not self._frames:
            self._pause_playback()
            return

        at_last_frame = self._index >= len(self._frames) - 1
        if at_last_frame:
            if self._loop:
                self.go_to_index(0)
            else:
                self._pause_playback()
            return

        self.go_to_index(self._index + 1)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Left/Right steps through frames for browsing; Space toggles
        Play/Pause; Escape closes.
        """
        if event.key() == Qt.Key.Key_Left:
            self._pause_playback()
            self.go_to_index(self._index - 1)
        elif event.key() == Qt.Key.Key_Right:
            self._pause_playback()
            self.go_to_index(self._index + 1)
        elif event.key() == Qt.Key.Key_Space:
            if self._play_button.isEnabled():
                self._play_button.toggle()
        elif event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the preview scaled to fit whenever the dialog resizes."""
        super().resizeEvent(event)
        self._rescale_current_pixmap()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop the local playback timer when the dialog closes.

        Closing (via Escape or Close) doesn't otherwise touch the timer
        -- without this, a QTimer left running on a hidden-but-not-yet-
        garbage-collected QDialog would keep firing _advance_playback()
        against a widget the user can no longer see.
        """
        self._timer.stop()
        super().closeEvent(event)

"""Main application window for FrameLabs."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from framelabs.capture.commands import (
    DeleteFrameCommand,
    DuplicateFrameCommand,
    ReplaceFrameCommand,
    SetFrameNotesCommand,
    ToggleFrameMarkerCommand,
)
from framelabs.core.config import Config, parse_shortcut
from framelabs.core.event_bus import EventBus
from framelabs.core.undo_manager import UndoManager
from framelabs.project.project import Project
from framelabs.timeline.onion_skin import OnionSkinSettings
from framelabs.timeline.playback import PlaybackSettings
from framelabs.timeline.timeline import Timeline
from framelabs.ui.camera_controller import CameraController
from framelabs.ui.capture_controller import CaptureController
from framelabs.ui.inspector_panel import InspectorPanel
from framelabs.ui.live_view_controller import LiveViewController
from framelabs.ui.live_view_widget import LiveViewWidget
from framelabs.ui.new_project_dialog import NewProjectDialog
from framelabs.ui.onion_skin_controller import OnionSkinController
from framelabs.ui.playback_controller import PlaybackController
from framelabs.ui.project_browser_widget import ProjectBrowserWidget
from framelabs.ui.project_controller import ProjectController
from framelabs.ui.timeline_widget import (
    FrameActionBar,
    PlaybackControls,
    TimelineWidget,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """FrameLabs' main window shell."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle("FrameLabs")
        self.resize(1280, 800)
        self.project: Project | None = None
        self.timeline: Timeline | None = None
        self.onion_settings = OnionSkinSettings()
        self.playback_settings = PlaybackSettings()
        self.event_bus = EventBus()
        # Feature 12. Constructed the same self-contained way as EventBus/
        # UndoManager above -- no other module needs shared access to
        # Config yet, so there's no reason to move construction up into
        # app/main.py until something else actually needs it.
        self.config = Config()
        # Feature 9. Duplicate/Delete/Marker/Notes commands run
        # synchronously on the main thread (see _duplicate_frame's
        # docstring) -- known, flagged simplification, not an oversight.
        # ReplaceFrameCommand is the one exception: its do() triggers a
        # real camera capture, so it runs on CaptureController's worker
        # thread instead (see _replace_frame's docstring).
        self.undo_manager = UndoManager()
        # Set True as the very first thing closeEvent() does. Guards
        # _refresh_onion_skin() against firing once worker-thread teardown
        # has started -- see closeEvent()'s docstring for the full
        # explanation of the shutdown race this prevents.
        self._shutting_down = False
        self._create_actions()
        self._build_menu_bar()
        self._build_central_panes()
        self._start_camera_controller()
        self._start_capture_controller()
        self._start_project_controller()
        self._start_live_view_controller()
        self._start_onion_skin_controller()
        self._start_playback_controller()
        self._wire_playback_controls()
        self._wire_timeline_widget()
        self._wire_frame_action_bar()
        self._wire_project_browser()

    def _create_actions(self) -> None:
        """Create the shared QActions used by the menu bar."""
        self.new_action = QAction("New Project", self)
        self.new_action.triggered.connect(self._on_new_project)

        self.open_action = QAction("Open Project", self)
        self.open_action.triggered.connect(self._on_open_project)

        self.save_action = QAction("Save Project", self)
        self.save_action.setShortcuts(self._shortcuts("save"))
        self.save_action.triggered.connect(self._on_save_project)

        self.capture_action = QAction("Capture", self)
        self.capture_action.setShortcuts(self._shortcuts("capture"))
        self.capture_action.triggered.connect(self._on_capture)

        # Feature 12. Every shortcut below is read from Config's
        # "keyboard_shortcuts" setting via self._shortcuts() rather than
        # hardcoded -- see that method's docstring further down.
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcuts(self._shortcuts("undo"))
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self._on_undo)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts(self._shortcuts("redo"))
        self.redo_action.setEnabled(False)
        self.redo_action.triggered.connect(self._on_redo)

        # Feature 5. Temporary Edit-menu home for Duplicate Frame, from
        # before FrameActionBar/the right-click menu existed. Left in
        # place deliberately -- now arguably redundant with the action
        # bar's Duplicate button, but removing a working shortcut/menu
        # entry is a UI call for Chris, not something to drop silently.
        self.duplicate_frame_action = QAction("Duplicate Frame", self)
        self.duplicate_frame_action.setShortcuts(self._shortcuts("duplicate_frame"))
        self.duplicate_frame_action.triggered.connect(self._on_duplicate_frame)

        self.play_action = QAction("Play", self)
        self.play_action.setShortcuts(self._shortcuts("play_pause"))
        self.play_action.triggered.connect(self._on_toggle_play)

        self.onion_action = QAction("Onion", self)
        self.onion_action.setCheckable(True)
        self.onion_action.setShortcuts(self._shortcuts("toggle_onion_skin"))
        self.onion_action.triggered.connect(self._on_toggle_onion_skin)

        self.safe_areas_action = QAction("Safe Areas", self)
        self.safe_areas_action.setCheckable(True)
        self.safe_areas_action.triggered.connect(self._on_toggle_safe_areas)

        self.camera_action = QAction("Rescan", self)
        self.camera_action.triggered.connect(self._on_rescan_camera)

        self.export_action = QAction("Export", self)
        self.export_action.triggered.connect(lambda: logger.info("Export clicked"))

        self.blender_action = QAction("Open in Blender", self)
        self.blender_action.setShortcuts(self._shortcuts("open_in_blender"))
        self.blender_action.triggered.connect(
            lambda: logger.info("Open in Blender clicked")
        )

        self.previous_frame_action = QAction("Previous Frame", self)
        self.previous_frame_action.setShortcuts(self._shortcuts("previous_frame"))
        self.previous_frame_action.triggered.connect(self._on_previous_frame)

        self.next_frame_action = QAction("Next Frame", self)
        self.next_frame_action.setShortcuts(self._shortcuts("next_frame"))
        self.next_frame_action.triggered.connect(self._on_next_frame)

        # Per Feature 12, Left/Right have no menu home -- unlike every other
        # shortcut above, which gets its shortcut "for free" by being added
        # to a menu in _build_menu_bar(). A QAction not added to any
        # menu/toolbar has no widget to inherit a shortcut context from, so
        # addAction() registers it directly on the window itself, keeping
        # the shortcut live with no visible menu entry.
        self.addAction(self.previous_frame_action)
        self.addAction(self.next_frame_action)

    def _shortcuts(self, action_name: str) -> list[QKeySequence]:
        """Look up the configured QKeySequence(s) for a named action.

        Reads the raw string(s) for `action_name` out of Config's
        "keyboard_shortcuts" setting via the Qt-free parse_shortcut()
        helper (core/config.py), then wraps each resulting key string in a
        real QKeySequence -- this method is the one place in the app that
        touches Qt for shortcut parsing, so parse_shortcut() itself stays
        unit-testable with no GUI setup at all. Returns an empty list (no
        shortcut assigned) if action_name isn't present in Config, rather
        than raising -- a missing/misconfigured entry should degrade to
        "no shortcut" for that one action, not crash startup.
        """
        raw = self.config.get("keyboard_shortcuts", {}).get(action_name, "")
        return [QKeySequence(key) for key in parse_shortcut(raw)]

    def _build_menu_bar(self) -> None:
        """Construct the top menu bar, using the shared actions."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        # Temporary home for Duplicate Frame -- see _create_actions().
        edit_menu.addAction(self.duplicate_frame_action)

        capture_menu = menu_bar.addMenu("&Capture")
        capture_menu.addAction(self.capture_action)
        capture_menu.addAction(self.onion_action)
        capture_menu.addAction(self.safe_areas_action)

        playback_menu = menu_bar.addMenu("&Playback")
        playback_menu.addAction(self.play_action)

        camera_menu = menu_bar.addMenu("&Camera")
        camera_menu.addAction(self.camera_action)

        blender_menu = menu_bar.addMenu("&Blender")
        blender_menu.addAction(self.blender_action)
        blender_menu.addAction(self.export_action)

    def _build_central_panes(self) -> None:
        """Construct the full central area: the three-pane splitter on top,
        with the Timeline strip, the per-frame action bar, and Playback
        controls stacked below it.
        """
        self.project_browser_widget = ProjectBrowserWidget()
        self.live_view_widget = LiveViewWidget()
        self.inspector_panel = InspectorPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.project_browser_widget)
        splitter.addWidget(self.live_view_widget)
        splitter.addWidget(self.inspector_panel)

        # Live Camera View gets most of the space; side panes stay narrower.
        # setSizes() controls the *initial* pixel widths -- QSplitter sizes
        # panes by each widget's size hint otherwise, which is wrong here
        # since "Inspector" and "Project Browser" are different text lengths.
        splitter.setSizes([250, 780, 250])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        self.timeline_widget = TimelineWidget()
        self.frame_action_bar = FrameActionBar()
        # Chris's "click-only" choice (session 13): the bar's controls are
        # hidden by default, and only ever shown by _on_frame_selected()
        # after an explicit thumbnail left-click. Uses set_bar_visible(),
        # not a plain setVisible() on the widget -- see that method's
        # docstring for why toggling the whole widget shifted Live View's
        # size.
        self.frame_action_bar.set_bar_visible(False)
        self.playback_controls = PlaybackControls()

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(splitter, 1)
        central_layout.addWidget(self.timeline_widget)
        central_layout.addWidget(self.frame_action_bar)
        central_layout.addWidget(self.playback_controls)

        self.setCentralWidget(central_widget)

    def _start_camera_controller(self) -> None:
        """Create the camera worker thread and wire its signals to the UI.

        Per the Developer Handbook's "UI Never Blocks" rule, all real
        camera work (device probing via OpenCV) happens on this dedicated
        thread, never on the main/UI thread. See camera_controller.py's
        module docstring for the full threading contract.
        """
        self._camera_thread = QThread(self)
        self.camera_controller = CameraController(self.event_bus)
        self.camera_controller.moveToThread(self._camera_thread)

        self._camera_thread.started.connect(self.camera_controller.start_scanning)
        self.camera_controller.camera_connecting.connect(self._on_camera_connecting)
        self.camera_controller.camera_connected.connect(self._on_camera_connected)
        self.camera_controller.camera_disconnected.connect(self._on_camera_disconnected)
        self.camera_controller.no_camera_found.connect(self._on_no_camera_found)

        self._camera_thread.start()

    def _start_capture_controller(self) -> None:
        """Create the capture worker thread and wire its signals to the UI.

        Deliberately a SEPARATE thread from the camera-scanning thread
        (not reusing self._camera_thread) -- a capture in progress and a
        background camera-availability poll happening simultaneously on
        the same thread could contend with each other. Shares the SAME
        CameraManager instance camera_controller already owns, so capture
        (and Replace, per Feature 5) triggers the actual connected camera.
        """
        self._capture_thread = QThread(self)
        self.capture_controller = CaptureController(
            self.event_bus, self.camera_controller.camera_manager
        )
        self.capture_controller.moveToThread(self._capture_thread)

        self.capture_controller.capture_succeeded.connect(self._on_capture_succeeded)
        self.capture_controller.capture_failed.connect(self._on_capture_failed)
        self.capture_controller.disk_full.connect(self._on_disk_full)
        self.capture_controller.replace_succeeded.connect(self._on_replace_succeeded)
        self.capture_controller.replace_failed.connect(self._on_replace_failed)

        self._capture_thread.start()

    def _start_project_controller(self) -> None:
        """Create the project save/load worker thread and wire its signals.

        Deliberately a THIRD separate thread, distinct from both the
        camera and capture threads -- Save/Open can be triggered at any
        time and shouldn't contend with either an in-progress capture or
        a background camera scan.
        """
        self._project_thread = QThread(self)
        self.project_controller = ProjectController(self.event_bus)
        self.project_controller.moveToThread(self._project_thread)

        self.project_controller.save_succeeded.connect(self._on_save_succeeded)
        self.project_controller.save_failed.connect(self._on_save_failed)
        self.project_controller.load_succeeded.connect(self._on_load_succeeded)
        self.project_controller.load_failed.connect(self._on_load_failed)

        self._project_thread.start()

    def _start_live_view_controller(self) -> None:
        """Create the live-view worker thread and wire its signal to the UI.

        A FOURTH separate thread -- same reasoning as the other three,
        preview polling runs at up to ~30 times a second and shouldn't
        contend with camera scanning, capture, or project save/load.
        Shares the SAME CameraManager instance camera_controller owns, so
        it reflects whatever camera is actually connected.

        histogram_ready is connected the same direct way as frame_ready --
        both are Qt Signals originating on this controller's worker
        thread, so Qt's queued-connection machinery already marshals each
        call safely onto the receiving widget's own (main) thread. No
        additional indirection is needed for either.
        """
        self._live_view_thread = QThread(self)
        self.live_view_controller = LiveViewController(
            self.event_bus, self.camera_controller.camera_manager
        )
        self.live_view_controller.moveToThread(self._live_view_thread)

        self._live_view_thread.started.connect(self.live_view_controller.start)
        self.live_view_controller.frame_ready.connect(self.live_view_widget.show_frame)
        self.live_view_controller.histogram_ready.connect(
            self.inspector_panel.histogram_widget.update_histogram
        )

        self._live_view_thread.start()

    def _start_onion_skin_controller(self) -> None:
        """Create the onion skin worker thread and wire its signal to the UI.

        A FIFTH separate thread -- onion skin refreshes read a handful of
        frame files off disk (see onion_skin_controller.py), which per the
        Handbook's "UI Never Blocks" rule must not run on the main thread,
        and shouldn't contend with camera scanning, capture, live preview,
        or project save/load either.
        """
        self._onion_skin_thread = QThread(self)
        self.onion_skin_controller = OnionSkinController()
        self.onion_skin_controller.moveToThread(self._onion_skin_thread)

        self.onion_skin_controller.frames_ready.connect(
            self.live_view_widget.set_onion_layers
        )

        self._onion_skin_thread.start()

    def _start_playback_controller(self) -> None:
        """Create the playback worker thread and wire its signals to the UI.

        A SIXTH separate thread -- playback runs continuously while active
        and reads a frame image off disk on every tick (see
        playback_controller.py's module docstring), so it shouldn't contend
        with camera scanning, capture, live preview, onion skin refreshes,
        or project save/load.
        """
        self._playback_thread = QThread(self)
        self.playback_controller = PlaybackController()
        self.playback_controller.moveToThread(self._playback_thread)

        self.playback_controller.frame_ready.connect(self.live_view_widget.show_frame)
        self.playback_controller.playhead_advanced.connect(
            self._on_playback_playhead_advanced
        )
        self.playback_controller.playback_finished.connect(self._on_playback_finished)

        self._playback_thread.start()

    def _wire_playback_controls(self) -> None:
        """Connect the PlaybackControls widget to real playback state.

        PlaybackControls itself holds no logic (see its own docstring) --
        MainWindow owns self.playback_settings and drives
        PlaybackController directly from these raw widget signals.
        """
        self.playback_controls.play_button.clicked.connect(self._on_toggle_play)
        self.playback_controls.loop_button.toggled.connect(self._on_loop_toggled)
        self.playback_controls.speed_combo.currentIndexChanged.connect(
            self._on_speed_changed
        )

    def _wire_timeline_widget(self) -> None:
        """Connect the TimelineWidget to real timeline state.

        TimelineWidget holds no Timeline/Project of its own (see its own
        docstring) -- it only emits frame_selected with a raw index when a
        thumbnail is clicked, and frame_context_menu_requested with a raw
        index + global position on right-click. MainWindow owns
        self.timeline and is responsible for translating an index into
        either an actual playhead move (Timeline.go_to_index()) or the
        real Frame it refers to (self.timeline.frames[index]).
        """
        self.timeline_widget.frame_selected.connect(self._on_frame_selected)
        self.timeline_widget.frame_context_menu_requested.connect(
            self._on_frame_context_menu_requested
        )

    def _wire_frame_action_bar(self) -> None:
        """Connect FrameActionBar's controls to real per-frame actions.

        FrameActionBar holds no Project/Timeline/Frame of its own (see its
        own docstring) -- every handler here reads whichever frame is
        currently selected (self.timeline.current_frame) at the moment the
        control is used, rather than trusting a value captured earlier.
        """
        self.frame_action_bar.delete_button.clicked.connect(self._on_delete_frame)
        self.frame_action_bar.replace_button.clicked.connect(self._on_replace_frame)
        self.frame_action_bar.duplicate_button.clicked.connect(self._on_duplicate_frame)
        self.frame_action_bar.marker_button.clicked.connect(self._on_toggle_marker)
        self.frame_action_bar.notes_edit.editingFinished.connect(self._on_notes_edited)

    def _wire_project_browser(self) -> None:
        """Connect the Project Browser's frame_selected to the same shared
        handler TimelineWidget uses.

        ProjectBrowserWidget holds no Project/Timeline of its own (see its
        own docstring), and emits frame_selected with the same raw
        Project.frames/Timeline.frames index TimelineWidget.frame_selected
        already uses -- so double-clicking a frame in the browser tree
        goes through the exact same _on_frame_selected() path a Timeline
        thumbnail click does, per the hand-off's "one shared set of
        handler methods taking a raw identifier" convention.
        """
        self.project_browser_widget.frame_selected.connect(self._on_frame_selected)

    def _on_frame_selected(self, index: int) -> None:
        """React to a thumbnail click in the Timeline strip.

        No-op if there's no active project/timeline yet -- same guard
        pattern as _refresh_onion_skin(); TimelineWidget shouldn't be able
        to emit a click with no timeline behind it, but this keeps the
        handler safe regardless. Moves the playhead to the clicked frame's
        index, then refreshes Onion Skin, the Timeline strip's selection
        border, and the action bar so it reflects the newly selected frame.

        This is the ONLY place that reveals the frame action bar --
        _refresh_frame_action_bar() itself always hides it (see that
        method's docstring), so showing it here, right after that call, is
        what makes a left-click on a thumbnail the sole way to bring the
        bar up, per Chris's "click-only" choice.
        """
        if self.timeline is None:
            return
        self.timeline.go_to_index(index)
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()
        self.frame_action_bar.set_bar_visible(True)

    def _on_frame_context_menu_requested(self, index: int, global_pos) -> None:
        """Show Feature 5's right-click menu for a timeline thumbnail.

        Right-clicking a frame that isn't currently selected first moves
        the playhead to it (same as a left-click would), so the selection
        border reflects the frame the menu is about to act on. The frame
        action bar stays hidden through this, though -- per Chris's
        "click-only" choice, right-clicking is a deliberately separate
        access path to these same actions, not another way to reveal the
        action bar (see _refresh_frame_action_bar()'s docstring).
        """
        if self.timeline is None:
            return
        self.timeline.go_to_index(index)
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

        frame = self.timeline.frames[index]

        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        replace_action = menu.addAction("Replace")
        duplicate_action = menu.addAction("Duplicate")
        marker_action = menu.addAction(
            "Remove Marker" if frame.marker else "Add Marker"
        )
        chosen = menu.exec(global_pos)

        if chosen is delete_action:
            self._delete_frame(frame.number)
        elif chosen is replace_action:
            self._replace_frame(frame.number)
        elif chosen is duplicate_action:
            self._duplicate_frame(frame.number)
        elif chosen is marker_action:
            self._toggle_marker(frame.number)

    def _refresh_timeline_widget(self) -> None:
        """Rebuild the Timeline strip to match the current project/timeline.

        Rebuilds every thumbnail from scratch (disk read + QPixmap scale
        per frame) -- only call this when the frame list itself has
        changed (new project, opened project, capture succeeded, delete,
        replace, duplicate, undo, redo). For a playhead-only move, call
        _move_timeline_playhead() instead, which is much cheaper and does
        no disk I/O -- critical during playback, which can tick many times
        per second. No-op for the Timeline strip itself if there's no
        active project/timeline yet -- same guard pattern as
        _refresh_onion_skin(). Thumbnails live in project_path/"thumbnails",
        per the project folder layout established in Feature 1 and
        project.py's Project docstring.

        Also refreshes the Project Browser tree (backlog item #3) via
        ProjectBrowserWidget.set_project(), since its Frames/Notes/Exports
        branches change on exactly the same events the Timeline strip
        does. Called unconditionally, even when self.project is None,
        since set_project() handles that case itself (shows a "No project
        open" placeholder row) -- unlike the Timeline strip, the browser
        has a real, correct empty state to fall back to rather than
        nothing to do.
        """
        self.project_browser_widget.set_project(self.project)
        if self.project is None or self.timeline is None:
            return
        thumbnails_dir = self.project.project_path / "thumbnails"
        self.timeline_widget.refresh(
            self.timeline.frames, thumbnails_dir, self.timeline.current_index
        )

    def _move_timeline_playhead(self) -> None:
        """Move the Timeline strip's selection border to match the current
        playhead, without rebuilding any thumbnails.

        No-op if there's no active project/timeline yet -- same guard
        pattern as _refresh_onion_skin(). Use this (not
        _refresh_timeline_widget()) for every playhead-only change: arrow
        keys, playback ticks, and thumbnail clicks. None of these change
        the frame list, so rebuilding every thumbnail on each call would
        mean repeated disk reads for no reason -- at playback speed this
        was enough to visibly freeze the UI, which is exactly what the
        Developer Handbook's "UI Never Blocks" principle rules out.
        """
        if self.project is None or self.timeline is None:
            return
        self.timeline_widget.set_current_index(self.timeline.current_index)

    def _refresh_frame_action_bar(self) -> None:
        """Sync FrameActionBar's controls to whichever frame is now current,
        and hide the bar.

        No active project/timeline, or an empty timeline, both correctly
        resolve to Timeline.current_frame being None -- FrameActionBar's
        own set_current_frame(None) already disables and clears every
        control for exactly that case (see its docstring), so no separate
        guard is needed here.

        Hiding the bar here (not just syncing its fields) is deliberate:
        per Chris's "click-only" choice, the bar should disappear the
        instant anything OTHER than an explicit thumbnail left-click moves
        the current frame -- arrow keys, a new capture, undo/redo,
        playback, right-click, even the bar's own Delete/Replace/
        Duplicate/Marker/Notes controls (they all route through the same
        shared handlers as the menu/shortcut paths, with no clean way to
        tell "the bar's own button" apart from "Ctrl+D" once inside those
        handlers -- see _duplicate_frame()/_delete_frame()'s docstrings).
        _on_frame_selected() is the ONLY place that re-shows it, right
        after calling this method, which is what makes "hide by default"
        here safe rather than self-defeating.
        """
        current_frame = self.timeline.current_frame if self.timeline else None
        self.frame_action_bar.set_current_frame(current_frame)
        self.frame_action_bar.set_bar_visible(False)

    def _refresh_onion_skin(self) -> None:
        """Ask the onion skin worker thread to reload overlay frames.

        No-op if there's no active project/timeline yet, OR if the window
        is currently shutting down (self._shutting_down) -- see
        closeEvent()'s docstring for the exact race this second guard
        closes. Emits a signal rather than calling the controller
        directly, since it lives on a different thread -- Qt automatically
        queues this call onto that thread.
        """
        if self._shutting_down or self.timeline is None:
            return
        self.onion_skin_controller.refresh_requested.emit(
            self.timeline, self.onion_settings
        )

    def _on_toggle_onion_skin(self, checked: bool) -> None:
        """Turn Onion Skin on/off and refresh the overlay to match."""
        self.onion_settings.enabled = checked
        logger.info("Onion Skin %s", "enabled" if checked else "disabled")
        self._refresh_onion_skin()

    def _on_toggle_safe_areas(self, checked: bool) -> None:
        """Turn the Safe Area guides on/off.

        Unlike Onion Skin, this needs no worker-thread signal or refresh
        call -- the guides are pure UI geometry that live_view_widget
        already recomputes for whatever frame is currently on screen (see
        LiveViewWidget._update_safe_area_geometry), so toggling visibility
        is a direct, same-thread call: live_view_widget is never
        moveToThread()'d, and this handler itself runs on the main thread
        (menu actions always fire there), so no cross-thread indirection
        is needed here.
        """
        self.live_view_widget.set_safe_areas_visible(checked)
        logger.info("Safe Areas %s", "enabled" if checked else "disabled")

    def _on_toggle_play(self) -> None:
        """Start or stop playback, per Feature 7.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_capture() and _on_save_project().
        """
        if self.project is None or self.timeline is None:
            logger.warning("Play requested with no active project; ignoring")
            return
        if self.playback_settings.is_playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        """Begin playback from the current playhead position.

        Pauses Live View polling first -- see LiveViewController's module
        docstring for why both PlaybackController and LiveViewController
        driving the same LiveViewWidget.show_frame() slot at once causes a
        visible strobe between the live camera feed and whatever frame
        Playback just set. Resumed in _reset_playback_ui(), which runs on
        every path playback can stop (user-stopped or reached the end).
        """
        self.live_view_controller.pause_requested.emit()
        self.playback_settings.is_playing = True
        self.playback_controls.play_button.setText("Pause")
        self.playback_controller.start_requested.emit(
            self.timeline, self.playback_settings
        )
        logger.info("Playback start requested")

    def _stop_playback(self) -> None:
        """Stop playback because the user asked to -- as opposed to
        PlaybackController stopping itself at the end of the sequence with
        Loop off, which goes through _on_playback_finished instead.
        """
        self.playback_controller.stop_requested.emit()
        self._reset_playback_ui()
        logger.info("Playback stop requested")

    def _on_playback_finished(self) -> None:
        """React to PlaybackController stopping itself (reached the end of
        the sequence with Loop off) -- un-press Play so the button reflects
        reality instead of staying stuck on "Pause" with nothing playing.
        """
        logger.info("Playback finished")
        self._reset_playback_ui()

    def _reset_playback_ui(self) -> None:
        """Reset the Play button back to its stopped state.

        Resumes Live View polling, mirroring the pause in
        _start_playback() -- runs on every path playback can stop
        (_stop_playback()'s user-initiated stop, and
        _on_playback_finished()'s reached-the-end stop), so the live feed
        always comes back regardless of how playback ended.
        """
        self.playback_settings.is_playing = False
        self.playback_controls.play_button.setText("Play")
        self.live_view_controller.resume_requested.emit()

    def _on_playback_playhead_advanced(self) -> None:
        """Keep Onion Skin, the Timeline strip, and the action bar in sync
        while Playback moves the same Timeline.current_index they all read
        from.

        Without this, Onion Skin, the Timeline strip's selection border,
        and the action bar would only ever refresh on capture or a manual
        click -- once Play starts moving the playhead on its own, all
        three would go stale and stop matching the frame actually on
        screen. The refresh helpers already no-op safely if disabled/empty
        or if the window is shutting down, so this is safe to call
        unconditionally on every tick.
        """
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

    def _on_previous_frame(self) -> None:
        """Step the playhead back one frame, per Feature 12's Left Arrow.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_capture()/_on_toggle_play(). Refreshes Onion
        Skin, the Timeline strip, and the action bar afterward since the
        playhead moved, the same way _on_playback_playhead_advanced() does.
        """
        if self.timeline is None:
            logger.warning("Previous frame requested with no active project; ignoring")
            return
        self.timeline.previous_frame()
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

    def _on_next_frame(self) -> None:
        """Step the playhead forward one frame, per Feature 12's Right Arrow.

        Same guard and refresh calls as _on_previous_frame().
        """
        if self.timeline is None:
            logger.warning("Next frame requested with no active project; ignoring")
            return
        self.timeline.next_frame()
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

    def _on_duplicate_frame(self) -> None:
        """Duplicate the currently-selected frame -- Edit menu / Ctrl+D /
        action bar Duplicate button all land here.

        No-op with a log line if there's no active project or no frame
        selected -- same guard pattern as _on_capture().
        """
        if self.project is None or self.timeline is None:
            logger.warning("Duplicate Frame requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Duplicate Frame requested with no frame selected; ignoring")
            return
        self._duplicate_frame(frame.number)

    def _duplicate_frame(self, frame_number: int) -> None:
        """Duplicate `frame_number`, undoably, and select the new duplicate.

        Runs DuplicateFrameCommand.do() synchronously on the main thread
        rather than on a worker thread the way capture/replace do -- a
        known, deliberately flagged simplification (see hand-off), not an
        oversight; duplicate_frame() is a same-project file copy, cheap
        enough in practice that this hasn't been worth the extra
        worker-thread plumbing yet, but should move to one if real-world
        frame sizes make it noticeable.

        Moves the playhead to the new duplicate, matching how
        _on_capture_succeeded() always selects the newest frame after a
        capture -- a duplicate is a new frame the user just asked for, so
        it should be the one now on screen, the same way a fresh capture
        is. Shared by the Edit menu/Ctrl+D, the action bar's Duplicate
        button, and the right-click menu's Duplicate entry.
        """
        command = DuplicateFrameCommand(self.project, self.event_bus, frame_number)
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self.timeline.go_to_index(len(self.timeline) - 1)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_delete_frame(self) -> None:
        """Delete the currently-selected frame -- action bar Delete button."""
        if self.project is None or self.timeline is None:
            logger.warning("Delete Frame requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Delete Frame requested with no frame selected; ignoring")
            return
        self._delete_frame(frame.number)

    def _delete_frame(self, frame_number: int) -> None:
        """Confirm, then delete `frame_number`, undoably.

        Shows Feature 5's exact confirmation dialog ("Delete Frame N? /
        Undo Available") before doing anything -- deletion is destructive
        enough (real files removed from disk) to warrant confirmation even
        though it's undoable. Runs DeleteFrameCommand.do() synchronously
        on the main thread, same reasoning as _duplicate_frame() -- a
        delete is just file removal, no camera involved. Shared by the
        action bar's Delete button and the right-click menu's Delete entry.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Delete Frame")
        box.setText(f"Delete Frame {frame_number}?")
        box.setInformativeText("Undo Available")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        command = DeleteFrameCommand(self.project, self.event_bus, frame_number)
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self.timeline.go_to_index(self.timeline.current_index)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_replace_frame(self) -> None:
        """Replace the currently-selected frame -- action bar Replace button."""
        if self.project is None or self.timeline is None:
            logger.warning("Replace Frame requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Replace Frame requested with no frame selected; ignoring")
            return
        self._replace_frame(frame.number)

    def _replace_frame(self, frame_number: int) -> None:
        """Trigger a real camera capture to replace `frame_number`'s image.

        Unlike Duplicate/Delete, ReplaceFrameCommand.do() triggers a real
        camera capture (see capture_service.replace_frame), so per the
        Developer Handbook's "UI Never Blocks" rule it can't run
        synchronously here -- it's handed to CaptureController's worker
        thread instead. Recorded on UndoManager only in
        _on_replace_succeeded(), once the capture has actually completed;
        a failed/disk-full replace never reaches the undo stack, since
        nothing to undo would exist. Shared by the action bar's Replace
        button and the right-click menu's Replace entry.
        """
        command = ReplaceFrameCommand(
            self.project,
            self.camera_controller.camera_manager,
            self.event_bus,
            frame_number,
        )
        self.capture_controller.replace_requested.emit(command)
        logger.info("Replace requested for frame %d", frame_number)

    def _on_replace_succeeded(self, command: ReplaceFrameCommand) -> None:
        """React to a successful Replace, run on the capture worker thread.

        Records the already-completed command via execute_already_done()
        rather than execute(), since do() already ran on the worker thread
        -- see UndoManager.execute_already_done()'s docstring for why
        calling do() a second time here would be wrong.
        """
        logger.info("Replace succeeded: %s", command.description)
        self.undo_manager.execute_already_done(command)
        self._update_undo_redo_actions()
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_replace_failed(self, message: str) -> None:
        """Show a "Replace Failed" dialog. Reuses Feature 4's Capture
        Failed presentation, since replace_frame shares capture_frame's
        exact trigger/write pipeline and can fail for the same reasons.
        """
        logger.error("Replace failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Replace Failed")
        box.setText("Replace Failed")
        box.setInformativeText(message)
        box.exec()

    def _on_toggle_marker(self) -> None:
        """Toggle the marker on the currently-selected frame -- action bar
        Marker button.
        """
        if self.project is None or self.timeline is None:
            logger.warning("Toggle Marker requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Toggle Marker requested with no frame selected; ignoring")
            return
        self._toggle_marker(frame.number)

    def _toggle_marker(self, frame_number: int) -> None:
        """Toggle `frame_number`'s marker, undoably.

        Only refreshes the Timeline strip's marker border and the action
        bar -- no onion skin refresh, since a marker is purely a Timeline
        annotation with no effect on onion skin's overlay frames.
        """
        command = ToggleFrameMarkerCommand(self.project, self.event_bus, frame_number)
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_notes_edited(self) -> None:
        """Save the action bar's Notes field to the currently-selected frame.

        Only executes a command if the text actually changed -- notes_edit
        fires editingFinished on every focus-out, not just real edits, and
        pushing a no-op SetFrameNotesCommand onto the undo stack for an
        unchanged value would make Undo do nothing visible, which is
        confusing regardless of being technically correct.
        """
        if self.project is None or self.timeline is None:
            return
        frame = self.timeline.current_frame
        if frame is None:
            return
        new_notes = self.frame_action_bar.notes_edit.text()
        if new_notes == frame.notes:
            return
        command = SetFrameNotesCommand(
            self.project, self.event_bus, frame.number, new_notes
        )
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()

    def _on_undo(self) -> None:
        """Undo the most recently executed command, per Feature 9.

        The undone command may have changed which frames exist (e.g.
        undoing a duplicate removes the frame it created), so this
        rebuilds the Timeline strip in full via _refresh_timeline_widget()
        rather than the cheaper _move_timeline_playhead() -- same
        reasoning as _on_capture_succeeded(). go_to_index() re-clamps the
        playhead first in case the frame list just got shorter than the
        current index.
        """
        if self.timeline is None:
            logger.warning("Undo requested with no active project; ignoring")
            return
        if self.undo_manager.undo():
            self.timeline.go_to_index(self.timeline.current_index)
            self._update_undo_redo_actions()
            self._refresh_onion_skin()
            self._refresh_timeline_widget()
            self._refresh_frame_action_bar()

    def _on_redo(self) -> None:
        """Redo the most recently undone command, per Feature 9.

        Same rebuild-in-full reasoning as _on_undo(). Note that a redone
        ReplaceFrameCommand does NOT re-trigger the camera (see its
        do()'s docstring), so this can safely run synchronously here even
        though the original Replace ran on the capture worker thread.
        """
        if self.timeline is None:
            logger.warning("Redo requested with no active project; ignoring")
            return
        if self.undo_manager.redo():
            self.timeline.go_to_index(self.timeline.current_index)
            self._update_undo_redo_actions()
            self._refresh_onion_skin()
            self._refresh_timeline_widget()
            self._refresh_frame_action_bar()

    def _update_undo_redo_actions(self) -> None:
        """Enable/disable the Undo and Redo menu entries to match real state.

        Called after every execute/undo/redo so the Edit menu never offers
        an Undo/Redo that would actually be a no-op.
        """
        self.undo_action.setEnabled(self.undo_manager.can_undo())
        self.redo_action.setEnabled(self.undo_manager.can_redo())

    def _on_loop_toggled(self, checked: bool) -> None:
        """Update Loop live.

        PlaybackController re-reads settings.loop from this same shared
        PlaybackSettings object on every tick (see its _advance()
        docstring), so this takes effect immediately, even mid-playback.
        """
        self.playback_settings.loop = checked
        logger.info("Loop %s", "enabled" if checked else "disabled")

    def _on_speed_changed(self, index: int) -> None:
        """Update playback speed live -- same live-update mechanism as Loop."""
        percent = self.playback_controls.speed_combo.itemData(index)
        self.playback_settings.speed_percent = percent
        logger.info("Playback speed set to %d%%", percent)

    def _on_new_project(self) -> None:
        """Open the New Project dialog and adopt the created project.

        Per Feature 1's acceptance criteria, the window title reflects the
        new project's name once creation succeeds. If the user cancels the
        dialog, nothing changes. A fresh Timeline is created over the new
        project's frames at the same time -- Timeline holds a live
        reference to project.frames, so no further sync is needed as
        captures happen. The Timeline strip and action bar are refreshed
        here too, so a brand-new (empty) project correctly clears out
        whatever a previously-open project may have left displayed.
        """
        dialog = NewProjectDialog(self)
        if dialog.exec():
            self.project = dialog.project
            self.timeline = Timeline(self.project)
            self.undo_manager.clear()
            self._update_undo_redo_actions()
            self.setWindowTitle(f"FrameLabs — {self.project.name}")
            logger.info("Project created: %s", self.project.name)
            self._refresh_onion_skin()
            self._refresh_timeline_widget()
            self._refresh_frame_action_bar()

    def _on_open_project(self) -> None:
        """Open a folder picker and request a load on the worker thread.

        A project IS a folder (containing project.ffproj at its top
        level), so this picks the project folder itself -- not a parent
        folder, unlike New Project's Browse.
        """
        chosen = QFileDialog.getExistingDirectory(self, "Open Project")
        if not chosen:
            return
        self.project_controller.load_requested.emit(Path(chosen))

    def _on_load_succeeded(self, project: Project, missing_files: list) -> None:
        """React to a successful load.

        Per Feature 1's edge case, missing frame images don't block
        loading -- if any were found missing, show the warning dialog
        with Continue/Locate Missing Files/Cancel before adopting the
        project. Otherwise adopt immediately.
        """
        if missing_files:
            self._show_missing_frames_dialog(project, missing_files)
        else:
            self._adopt_project(project)

    def _on_load_failed(self, message: str) -> None:
        """Show a "Could Not Open Project" dialog.

        Covers a missing/corrupt project.ffproj or an unsupported version
        -- the user needs to see this, not just find it in a log.
        """
        logger.error("Load failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Could Not Open Project")
        box.setText("Could Not Open Project")
        box.setInformativeText(message)
        box.exec()

    def _adopt_project(self, project: Project) -> None:
        """Make project the active project and reflect it in the UI.

        A fresh Timeline is created over the opened project's frames at
        the same time -- see _on_new_project for why this needs no
        further manual sync. The Timeline strip and action bar are
        refreshed here too, so opening a project immediately shows its
        real frame thumbnails rather than whatever was left over from a
        previous project. undo_manager.clear() runs here for the same
        reason it runs in _on_new_project: every held Command references
        the previous Project object, so undoing one after switching
        projects would silently act on the wrong project's files.
        """
        self.project = project
        self.timeline = Timeline(project)
        self.undo_manager.clear()
        self._update_undo_redo_actions()
        self.setWindowTitle(f"FrameLabs — {project.name}")
        logger.info("Project opened: %s", project.name)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _show_missing_frames_dialog(
        self, project: Project, missing_files: list
    ) -> None:
        """Show Feature 1's "N frames are missing" dialog.

        Continue adopts the project as-is. Locate Missing Files opens the
        project's images/ folder in the system file explorer so the user
        can manually replace the missing files, then re-shows this same
        dialog -- opening the folder doesn't itself resolve anything, the
        user still needs to explicitly Continue or Cancel afterward.
        Cancel leaves the current project (if any) untouched.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Missing Frames")
        box.setText(f"{len(missing_files)} frames are missing.")
        continue_button = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        locate_button = box.addButton(
            "Locate Missing Files", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is continue_button:
            self._adopt_project(project)
        elif clicked is locate_button:
            images_dir = project.project_path / "images"
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(images_dir)))
            self._show_missing_frames_dialog(project, missing_files)
        # Cancel: no-op, dialog just closes.

    def _on_save_project(self) -> None:
        """Request a save on the worker thread.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_capture().
        """
        if self.project is None:
            logger.warning("Save requested with no active project; ignoring")
            return
        self.project_controller.save_requested.emit(self.project)

    def _on_save_succeeded(self) -> None:
        """React to a successful save. Log-only -- no visible confirmation
        needed for a routine save; a failed save gets a dialog instead
        since that's the case the user actually needs to act on.
        """
        logger.info("Project saved: %s", self.project.name if self.project else "?")

    def _on_save_failed(self, message: str) -> None:
        """Show a "Save Failed" dialog. A failed save risks losing work,
        so this is surfaced visibly rather than left as a log line.
        """
        logger.error("Save failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Save Failed")
        box.setText("Save Failed")
        box.setInformativeText(message)
        box.exec()

    def _on_capture(self) -> None:
        """Request a capture on the worker thread.

        No-op with a log line if there's no active project yet -- this is
        a placeholder guard; a real "no project open" state (e.g. graying
        out the Capture action) belongs to a later UI pass, not this one.
        """
        if self.project is None:
            logger.warning("Capture requested with no active project; ignoring")
            return
        self.capture_controller.capture_requested.emit(self.project)

    def _on_capture_succeeded(self, frame_number: int) -> None:
        """React to a successful capture.

        Advances the Timeline's playhead to the newly captured frame (the
        latest one) before refreshing Onion Skin -- otherwise the playhead
        stays stuck wherever it was, and frames_before_current() would not
        reflect the frame just captured. This remains correct now that
        Play also exists: capture always means "the new frame is now
        current," regardless of where Play last left the playhead. The
        Timeline strip and action bar are refreshed last so the
        newly-captured thumbnail appears with its selection border in the
        same place the playhead just moved to.
        """
        logger.info("Capture succeeded: frame %d", frame_number)
        if self.timeline is not None:
            self.timeline.go_to_index(len(self.timeline) - 1)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_capture_failed(self, message: str) -> None:
        """Show Feature 4's "Capture Failed" dialog, with a Retry option.

        Clicking Retry re-runs _on_capture() against the same
        self.project used by the failed attempt -- capture_frame() only
        requires a valid project_path, so repeating the same request is
        always safe. Declining just dismisses the dialog; the failed
        attempt already left nothing partial on disk (per Feature 4's
        acceptance criteria).
        """
        logger.error("Capture failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Capture Failed")
        box.setText("Capture Failed")
        box.setInformativeText(message)
        retry_button = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is retry_button:
            self._on_capture()

    def _on_disk_full(self, message: str) -> None:
        """Show Feature 4's "Disk Full" dialog.

        Acknowledge-only, no Retry -- per the Feature Spec, a disk-full
        capture is aborted rather than retryable; the project remains
        usable, but disk space needs to be freed before capturing again.
        Shared by both Capture and Replace, per capture_controller.py's
        single disk_full signal.
        """
        logger.error("Disk full: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Disk Full")
        box.setText("Capture Aborted")
        box.setInformativeText(message)
        box.exec()

    def _on_rescan_camera(self) -> None:
        """Ask the camera worker thread to run an immediate scan.

        Emits a signal rather than calling the controller directly, since
        the controller lives on a different thread — Qt automatically
        queues this call onto that thread. See camera_controller.py.
        """
        self.camera_controller.rescan_requested.emit()

    def _on_camera_connecting(self) -> None:
        """Reflect an in-progress scan in the Inspector's Camera field."""
        self.inspector_panel.set_camera_status("Scanning...")

    def _on_camera_connected(self, display_name: str) -> None:
        """Reflect a successful camera connection in the Inspector."""
        self.inspector_panel.set_camera_status(f"{display_name} Connected")

    def _on_camera_disconnected(self) -> None:
        """Reflect a camera disconnect in the Inspector."""
        self.inspector_panel.clear_camera_status()

    def _on_no_camera_found(self) -> None:
        """Reflect a completed scan that found nothing, in the Inspector."""
        self.inspector_panel.clear_camera_status()

    def closeEvent(self, event) -> None:
        """Shut all six worker threads down cleanly before closing.

        Sets self._shutting_down = True FIRST, before touching any thread.
        This closes a real race: PlaybackController.playhead_advanced is a
        queued cross-thread connection to _on_playback_playhead_advanced()
        on THIS (main) thread. If Play is still running (e.g. Loop
        enabled) when the window closes, one more tick can be emitted
        before playback's own thread is told to stop further down this
        method -- but Qt doesn't actually deliver that queued call until
        the main thread's event loop resumes processing events, which
        only happens AFTER this entire method returns (QThread.wait()
        blocks the calling/main thread without pumping its event queue).
        By the time that queued call is finally delivered,
        onion_skin_controller has already been deleted -- its thread is
        shut down earlier in this method, before playback's -- so
        _refresh_onion_skin() emitting on it raised RuntimeError: Signal
        source has been deleted. self._shutting_down, checked at the top
        of _refresh_onion_skin(), makes that eventual call a safe no-op
        instead, regardless of exactly when it's delivered relative to
        thread teardown order -- so this fix doesn't depend on getting
        that ordering exactly right.

        Without this, Qt logs a "QThread destroyed while running" warning
        and the thread is torn down abruptly rather than exiting its event
        loop normally. deleteLater() is queued onto each thread's own
        event loop via its finished signal, so each controller is cleaned
        up on the thread it actually belongs to.
        """
        self._shutting_down = True

        self._camera_thread.finished.connect(self.camera_controller.deleteLater)
        self._camera_thread.quit()
        self._camera_thread.wait(2000)

        self._capture_thread.finished.connect(self.capture_controller.deleteLater)
        self._capture_thread.quit()
        self._capture_thread.wait(2000)

        self._project_thread.finished.connect(self.project_controller.deleteLater)
        self._project_thread.quit()
        self._project_thread.wait(2000)

        self._live_view_thread.finished.connect(self.live_view_controller.deleteLater)
        self._live_view_thread.quit()
        self._live_view_thread.wait(2000)

        self._onion_skin_thread.finished.connect(self.onion_skin_controller.deleteLater)
        self._onion_skin_thread.quit()
        self._onion_skin_thread.wait(2000)

        self._playback_thread.finished.connect(self.playback_controller.deleteLater)
        self._playback_thread.quit()
        self._playback_thread.wait(2000)

        super().closeEvent(event)

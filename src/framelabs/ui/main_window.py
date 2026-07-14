"""Main application window for FrameLabs."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from framelabs.core.event_bus import EventBus
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
from framelabs.ui.project_controller import ProjectController
from framelabs.ui.timeline_widget import PlaybackControls, TimelineStrip

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

    def _create_actions(self) -> None:
        """Create the shared QActions used by the menu bar."""
        self.new_action = QAction("New Project", self)
        self.new_action.triggered.connect(self._on_new_project)

        self.open_action = QAction("Open Project", self)
        self.open_action.triggered.connect(self._on_open_project)

        self.save_action = QAction("Save Project", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self._on_save_project)

        self.capture_action = QAction("Capture", self)
        self.capture_action.setShortcut(QKeySequence(Qt.Key.Key_Space))
        self.capture_action.triggered.connect(self._on_capture)

        self.play_action = QAction("Play", self)
        self.play_action.triggered.connect(self._on_toggle_play)

        self.onion_action = QAction("Onion", self)
        self.onion_action.setCheckable(True)
        self.onion_action.setShortcut(QKeySequence(Qt.Key.Key_O))
        self.onion_action.triggered.connect(self._on_toggle_onion_skin)

        self.camera_action = QAction("Rescan", self)
        self.camera_action.triggered.connect(self._on_rescan_camera)

        self.export_action = QAction("Export", self)
        self.export_action.triggered.connect(lambda: logger.info("Export clicked"))

        self.blender_action = QAction("Open in Blender", self)
        self.blender_action.triggered.connect(
            lambda: logger.info("Open in Blender clicked")
        )

    def _build_menu_bar(self) -> None:
        """Construct the top menu bar, using the shared actions."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)

        menu_bar.addMenu("&Edit")

        capture_menu = menu_bar.addMenu("&Capture")
        capture_menu.addAction(self.capture_action)
        capture_menu.addAction(self.onion_action)

        playback_menu = menu_bar.addMenu("&Playback")
        playback_menu.addAction(self.play_action)

        camera_menu = menu_bar.addMenu("&Camera")
        camera_menu.addAction(self.camera_action)

        blender_menu = menu_bar.addMenu("&Blender")
        blender_menu.addAction(self.blender_action)
        blender_menu.addAction(self.export_action)

    def _build_central_panes(self) -> None:
        """Construct the full central area: the three-pane splitter on top,
        with the Timeline strip and Playback controls stacked below it.
        """
        self.project_browser_placeholder = self._make_placeholder("Project Browser")
        self.live_view_widget = LiveViewWidget()
        self.inspector_panel = InspectorPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.project_browser_placeholder)
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

        self.timeline_strip = TimelineStrip()
        self.playback_controls = PlaybackControls()

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(splitter, 1)
        central_layout.addWidget(self.timeline_strip)
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
        triggers the actual connected camera.
        """
        self._capture_thread = QThread(self)
        self.capture_controller = CaptureController(
            self.event_bus, self.camera_controller.camera_manager
        )
        self.capture_controller.moveToThread(self._capture_thread)

        self.capture_controller.capture_succeeded.connect(self._on_capture_succeeded)
        self.capture_controller.capture_failed.connect(self._on_capture_failed)
        self.capture_controller.disk_full.connect(self._on_disk_full)

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
        """
        self._live_view_thread = QThread(self)
        self.live_view_controller = LiveViewController(
            self.event_bus, self.camera_controller.camera_manager
        )
        self.live_view_controller.moveToThread(self._live_view_thread)

        self._live_view_thread.started.connect(self.live_view_controller.start)
        self.live_view_controller.frame_ready.connect(self.live_view_widget.show_frame)

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
        """Begin playback from the current playhead position."""
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
        """Reset the Play button back to its stopped state."""
        self.playback_settings.is_playing = False
        self.playback_controls.play_button.setText("Play")

    def _on_playback_playhead_advanced(self) -> None:
        """Keep Onion Skin in sync while Playback moves the same
        Timeline.current_index Onion Skin reads from.

        Without this, Onion Skin only ever refreshes on capture -- once
        Play starts moving the playhead on its own, the "before" ghosted
        frames would go stale and stop matching the frame actually on
        screen. _refresh_onion_skin() already no-ops safely if Onion Skin
        is currently disabled (OnionSkinController just emits empty
        layers) OR if the window is shutting down, so this is safe to call
        unconditionally on every tick.
        """
        self._refresh_onion_skin()

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
        captures happen.
        """
        dialog = NewProjectDialog(self)
        if dialog.exec():
            self.project = dialog.project
            self.timeline = Timeline(self.project)
            self.setWindowTitle(f"FrameLabs — {self.project.name}")
            logger.info("Project created: %s", self.project.name)
            self._refresh_onion_skin()

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
        further manual sync.
        """
        self.project = project
        self.timeline = Timeline(project)
        self.setWindowTitle(f"FrameLabs — {project.name}")
        logger.info("Project opened: %s", project.name)
        self._refresh_onion_skin()

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
        current," regardless of where Play last left the playhead.
        A visible "frame captured" indicator (thumbnail appearing in the
        Timeline strip) belongs to the real Timeline UI built in Phase 6,
        not bolted onto this pass.
        """
        logger.info("Capture succeeded: frame %d", frame_number)
        if self.timeline is not None:
            self.timeline.go_to_index(len(self.timeline) - 1)
        self._refresh_onion_skin()

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

    @staticmethod
    def _make_placeholder(label_text: str) -> QLabel:
        """Build a labeled placeholder widget for a not-yet-implemented pane."""
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid gray;")
        return label

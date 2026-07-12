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
from framelabs.ui.camera_controller import CameraController
from framelabs.ui.capture_controller import CaptureController
from framelabs.ui.inspector_panel import InspectorPanel
from framelabs.ui.live_view_controller import LiveViewController
from framelabs.ui.live_view_widget import LiveViewWidget
from framelabs.ui.new_project_dialog import NewProjectDialog
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
        self.event_bus = EventBus()
        self._create_actions()
        self._build_menu_bar()
        self._build_central_panes()
        self._start_camera_controller()
        self._start_capture_controller()
        self._start_project_controller()
        self._start_live_view_controller()

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
        self.play_action.triggered.connect(lambda: logger.info("Play/Pause clicked"))

        self.onion_action = QAction("Onion", self)
        self.onion_action.triggered.connect(lambda: logger.info("Onion Skin toggled"))

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

    def _on_new_project(self) -> None:
        """Open the New Project dialog and adopt the created project.

        Per Feature 1's acceptance criteria, the window title reflects the
        new project's name once creation succeeds. If the user cancels the
        dialog, nothing changes.
        """
        dialog = NewProjectDialog(self)
        if dialog.exec():
            self.project = dialog.project
            self.setWindowTitle(f"FrameLabs — {self.project.name}")
            logger.info("Project created: %s", self.project.name)

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
        """Make project the active project and reflect it in the UI."""
        self.project = project
        self.setWindowTitle(f"FrameLabs — {project.name}")
        logger.info("Project opened: %s", project.name)

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

        Log-only for now -- a visible "frame captured" indicator (thumbnail
        appearing in the Timeline strip) belongs to the real Timeline UI
        built in Phase 6, not bolted onto this pass.
        """
        logger.info("Capture succeeded: frame %d", frame_number)

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
        """Shut all four worker threads down cleanly before closing.

        Without this, Qt logs a "QThread destroyed while running" warning
        and the thread is torn down abruptly rather than exiting its event
        loop normally. deleteLater() is queued onto each thread's own
        event loop via its finished signal, so each controller is cleaned
        up on the thread it actually belongs to.
        """
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

        super().closeEvent(event)

    @staticmethod
    def _make_placeholder(label_text: str) -> QLabel:
        """Build a labeled placeholder widget for a not-yet-implemented pane."""
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid gray;")
        return label

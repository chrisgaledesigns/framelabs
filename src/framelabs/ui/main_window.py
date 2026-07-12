"""Main application window for FrameLabs."""

import logging

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from framelabs.core.event_bus import EventBus
from framelabs.project.project import Project
from framelabs.ui.camera_controller import CameraController
from framelabs.ui.inspector_panel import InspectorPanel
from framelabs.ui.new_project_dialog import NewProjectDialog
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

    def _create_actions(self) -> None:
        """Create the shared QActions used by the menu bar."""
        self.new_action = QAction("New Project", self)
        self.new_action.triggered.connect(self._on_new_project)

        self.open_action = QAction("Open Project", self)
        self.open_action.triggered.connect(lambda: logger.info("Open Project clicked"))

        self.save_action = QAction("Save Project", self)
        self.save_action.triggered.connect(lambda: logger.info("Save Project clicked"))

        self.capture_action = QAction("Capture", self)
        self.capture_action.triggered.connect(lambda: logger.info("Capture clicked"))

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
        self.live_view_placeholder = self._make_placeholder("Live Camera View")
        self.inspector_panel = InspectorPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.project_browser_placeholder)
        splitter.addWidget(self.live_view_placeholder)
        splitter.addWidget(self.inspector_panel)

        # Live Camera View gets most of the space; side panes stay narrower.
        # setSizes() controls the *initial* pixel widths — QSplitter sizes
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
        """Shut the camera worker thread down cleanly before closing.

        Without this, Qt logs a "QThread destroyed while running" warning
        and the thread is torn down abruptly rather than exiting its event
        loop normally. deleteLater() is queued onto the thread's own event
        loop via its finished signal, so the controller (and its QTimer)
        are cleaned up on the thread they actually belong to, not
        whichever thread happens to be running when Python garbage
        collects them.
        """
        self._camera_thread.finished.connect(self.camera_controller.deleteLater)
        self._camera_thread.quit()
        self._camera_thread.wait(2000)
        super().closeEvent(event)

    @staticmethod
    def _make_placeholder(label_text: str) -> QLabel:
        """Build a labeled placeholder widget for a not-yet-implemented pane."""
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid gray;")
        return label

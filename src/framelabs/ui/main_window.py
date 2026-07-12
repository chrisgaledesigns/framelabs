"""Main application window for FrameLabs."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter

from framelabs.ui.inspector_panel import InspectorPanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """FrameLabs' main window shell."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle("FrameLabs")
        self.resize(1280, 800)
        self._create_actions()
        self._build_menu_bar()
        self._build_central_panes()

    def _create_actions(self) -> None:
        """Create the shared QActions used by the menu bar."""
        self.new_action = QAction("New Project", self)
        self.new_action.triggered.connect(lambda: logger.info("New Project clicked"))

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

        self.camera_action = QAction("Camera", self)
        self.camera_action.triggered.connect(lambda: logger.info("Camera clicked"))

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
        """Construct the three-pane splitter: Project Browser | Live Camera
        View | Inspector.
        """
        self.project_browser_placeholder = self._make_placeholder("Project Browser")
        self.live_view_placeholder = self._make_placeholder("Live Camera View")
        self.inspector_placeholder = InspectorPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.project_browser_placeholder)
        splitter.addWidget(self.live_view_placeholder)
        splitter.addWidget(self.inspector_placeholder)

        # Live Camera View gets most of the space; side panes stay narrower.
        # setSizes() controls the *initial* pixel widths — QSplitter sizes
        # panes by each widget's size hint otherwise, which is wrong here
        # since "Inspector" and "Project Browser" are different text lengths.
        splitter.setSizes([250, 780, 250])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        self.setCentralWidget(splitter)

    @staticmethod
    def _make_placeholder(label_text: str) -> QLabel:
        """Build a labeled placeholder widget for a not-yet-implemented pane."""
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid gray;")
        return label

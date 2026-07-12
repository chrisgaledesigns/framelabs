"""Main application window for FrameLabs."""

import logging

from PySide6.QtWidgets import QMainWindow

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """FrameLabs' main window shell."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle("FrameLabs")
        self.resize(1280, 800)
        self._build_menu_bar()

    def _build_menu_bar(self) -> None:
        """Construct the top menu bar and its stub actions."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction("New Project", lambda: logger.info("New Project clicked"))
        file_menu.addAction("Open Project", lambda: logger.info("Open Project clicked"))
        file_menu.addAction("Save Project", lambda: logger.info("Save Project clicked"))

        menu_bar.addMenu("&Edit")

        capture_menu = menu_bar.addMenu("&Capture")
        capture_menu.addAction("Capture", lambda: logger.info("Capture clicked"))
        capture_menu.addAction(
            "Toggle Onion Skin", lambda: logger.info("Onion Skin toggled")
        )

        playback_menu = menu_bar.addMenu("&Playback")
        playback_menu.addAction("Play/Pause", lambda: logger.info("Play/Pause clicked"))

        menu_bar.addMenu("&Camera")

        blender_menu = menu_bar.addMenu("&Blender")
        blender_menu.addAction(
            "Open in Blender", lambda: logger.info("Open in Blender clicked")
        )
        blender_menu.addAction("Export", lambda: logger.info("Export clicked"))

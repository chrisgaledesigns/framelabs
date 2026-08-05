"""Startup splash screen for FrameLabs.

Shown for the brief window between the app process starting and the
Welcome dialog appearing. Plugin discovery/loading is the one startup
step slow enough (arbitrary third-party plugin code) to be worth
reassuring the user something is happening, rather than leaving the OS
showing nothing while Python imports run.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSplashScreen

from framelabs.ui.branding import branded_pixmap
from framelabs.ui.theme import ACCENT

SPLASH_WIDTH = 560
SPLASH_HEIGHT = 320

# Bottom-center placement for the status line, in the app's own accent
# color (theme.ACCENT) rather than QSplashScreen's default message
# color, which assumes a light background and would be unreadable here.
_MESSAGE_ALIGNMENT = Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
_MESSAGE_COLOR = QColor(ACCENT)


class FrameLabsSplashScreen(QSplashScreen):
    """The logo-on-dark splash screen shown while the app starts up."""

    def __init__(self) -> None:
        pixmap = branded_pixmap(SPLASH_WIDTH, SPLASH_HEIGHT, logo_scale=0.7)
        super().__init__(pixmap)
        # Frameless + always-on-top: a splash screen with a title bar,
        # or one that can get buried behind other windows the moment
        # focus shifts, defeats the point of showing one at all.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

    def show_status(self, message: str) -> None:
        """Update the status line along the bottom of the splash.

        Callers should follow this with QApplication.processEvents()
        (there's no event loop running yet at the point this is used
        in app/main.py), or the new text won't actually repaint.
        """
        self.showMessage(message, _MESSAGE_ALIGNMENT, _MESSAGE_COLOR)

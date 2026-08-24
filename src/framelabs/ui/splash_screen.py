"""Startup splash screen for FrameLabs.

Shown for the brief window between the app process starting and the
Welcome dialog appearing. Plugin discovery/loading is the one startup
step slow enough (arbitrary third-party plugin code) to be worth
reassuring the user something is happening, rather than leaving the OS
showing nothing while Python imports run.

Visually mirrors StartupDialog's hero banner (same photo, via
branding.find_hero_image() -- both screens share one asset rather than
each carrying their own) with the logo and version badge overlaid on
it, plus a solid message bar below the photo for the status line,
rather than text floating directly on top of the image.
"""

from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen

from framelabs.ui.branding import current_version_text, find_hero_image, hero_banner_pixmap
from framelabs.ui.theme import ACCENT, BG_WINDOW

SPLASH_WIDTH = 560
SPLASH_HEIGHT = 320

# The solid bar along the bottom the status line sits in, separate
# from the photo above it -- matches the mockup's layout (a dark strip
# under the image) rather than text floating directly on the photo.
MESSAGE_BAR_HEIGHT = 50
_HERO_HEIGHT = SPLASH_HEIGHT - MESSAGE_BAR_HEIGHT

# Bottom-center placement for the status line, in the app's own accent
# color (theme.ACCENT) rather than QSplashScreen's default message
# color, which assumes a light background and would be unreadable here.
_MESSAGE_ALIGNMENT = Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
_MESSAGE_COLOR = QColor(ACCENT)

# Tongue-in-cheek stand-ins for real status text. There's nothing
# meaningful to report at either of the two points main.py updates the
# splash (plugin loading, workspace prep are both fast/synchronous), so
# rather than generic "Loading..." text, the status line shows one of
# these at random -- each idiom about hasty/reckless action is a wink
# at the fact that the app is, in fact, starting up in a hurry.
IDIOMS = [
    "beating around the bush...",
    "opening a can of worms...",
    "counting your chickens before they've hatched...",
    "putting the cart before the horse...",
    "barking up the wrong tree...",
    "jumping the gun...",
    "biting off more than you can chew...",
    "walking on thin ice...",
    "digging yourself into a hole...",
    "throwing fuel on the fire...",
]


def _build_splash_pixmap() -> QPixmap:
    """Hero photo on top, a solid BG_WINDOW message bar below it.

    hero_banner_pixmap() already handles the photo/fallback-gradient,
    scrim, logo, and version badge -- this just stacks that on top of
    a bit of extra solid-color height for show_status()'s text to sit
    in, rather than reimplementing any of that compositing here.
    """
    hero = hero_banner_pixmap(
        SPLASH_WIDTH,
        _HERO_HEIGHT,
        image_path=find_hero_image(),
        version_text=current_version_text(),
    )

    canvas = QPixmap(SPLASH_WIDTH, SPLASH_HEIGHT)
    canvas.fill(QColor(BG_WINDOW))
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, hero)
    painter.end()
    return canvas


class FrameLabsSplashScreen(QSplashScreen):
    """The hero-photo splash screen shown while the app starts up."""

    def __init__(self) -> None:
        super().__init__(_build_splash_pixmap())
        # Frameless + always-on-top: a splash screen with a title bar,
        # or one that can get buried behind other windows the moment
        # focus shifts, defeats the point of showing one at all.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self._last_idiom: str | None = None

    def show_status(self, message: str) -> None:
        """Update the status line along the bottom of the splash.

        Callers should follow this with QApplication.processEvents()
        (there's no event loop running yet at the point this is used
        in app/main.py), or the new text won't actually repaint.
        """
        self.showMessage(message, _MESSAGE_ALIGNMENT, _MESSAGE_COLOR)

    def show_random_status(self) -> None:
        """Show a random idiom from IDIOMS as the status line.

        Picks from every idiom except whichever was shown last, so two
        consecutive calls (main.py makes exactly two) can't land on the
        same line twice in a row. Same processEvents() caveat as
        show_status() applies.
        """
        choices = [idiom for idiom in IDIOMS if idiom != self._last_idiom]
        message = random.choice(choices)
        self._last_idiom = message
        self.show_status(message)

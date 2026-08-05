"""Shared branding helpers for FrameLabs' pre-launch screens.

The Splash Screen and the startup Welcome dialog both need the same
"logo on a dark card" treatment: Logo_Horizontal.png's "FRAME" wordmark
is rendered in pure opaque white, invisible against a light background
by design, so both screens render it over a dark background rather
than the OS's default (usually light) widget background.

Uses theme.BG_WINDOW rather than its own hardcoded color, so these
pre-launch screens automatically stay in sync with the rest of the
app's palette (theme.py) instead of drifting from it over time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from framelabs.ui.theme import BG_WINDOW

BACKGROUND_COLOR = QColor(BG_WINDOW)

# resources/ is a sibling package of ui/, not this module's own
# package, so it's addressed relative to this file rather than via a
# hardcoded absolute path.
_LOGO_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "Logo_Horizontal.png"
)


def branded_pixmap(width: int, height: int, logo_scale: float = 0.6) -> QPixmap:
    """Render Logo_Horizontal.png centered on a BACKGROUND_COLOR card.

    Args:
        width: Card width in pixels.
        height: Card height in pixels.
        logo_scale: Fraction of the card's width the logo should occupy.
    """
    canvas = QPixmap(width, height)
    canvas.fill(BACKGROUND_COLOR)

    logo = QPixmap(str(_LOGO_PATH))
    if logo.isNull():
        # Missing/unreadable logo file shouldn't crash startup -- fall
        # back to a plain dark card rather than raising.
        return canvas

    scaled_logo = logo.scaledToWidth(
        int(width * logo_scale), Qt.TransformationMode.SmoothTransformation
    )

    painter = QPainter(canvas)
    x = (width - scaled_logo.width()) // 2
    y = (height - scaled_logo.height()) // 2
    painter.drawPixmap(x, y, scaled_logo)
    painter.end()

    return canvas

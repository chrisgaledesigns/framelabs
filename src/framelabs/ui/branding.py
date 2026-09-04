"""Shared branding helpers for FrameLabs' pre-launch screens.

The Splash Screen and the startup Welcome dialog both need the same
"hero photo with the logo overlaid" treatment -- and, per hero images
just being production stills, the exact same photo. find_hero_image()
resolves that one shared file; both screens call it independently
rather than one screen owning the asset, so neither has to reach into
the other's module.

Uses theme.BG_WINDOW rather than its own hardcoded color, so these
pre-launch screens automatically stay in sync with the rest of the
app's palette (theme.py) instead of drifting from it over time.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

from framelabs.ui.theme import ACCENT_YELLOW, BG_PANEL_RAISED, BG_WINDOW

BACKGROUND_COLOR = QColor(BG_WINDOW)

# resources/ is a sibling package of ui/, not this module's own
# package, so it's addressed relative to this file rather than via a
# hardcoded absolute path.
_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
_LOGO_PATH = _RESOURCES_DIR / "Logo_Horizontal.png"

# Candidate filenames for StartupDialog's hero photo, checked in order.
# There's no bundled default -- whichever of these the user drops into
# resources/ (a behind-the-scenes still, a puppet close-up, whatever)
# is picked up automatically. See find_hero_image()'s docstring.
_HERO_IMAGE_CANDIDATES = (
    "StartupHero.jpg",
    "StartupHero.jpeg",
    "StartupHero.png",
)


def find_hero_image() -> Path | None:
    """Return the first hero-photo candidate that exists, or None.

    Shared by StartupDialog and the splash screen -- both use whatever
    production still the user drops into resources/ as
    StartupHero.{jpg,jpeg,png}, so the app's two pre-launch screens
    always show the same photo rather than two different ones. Until
    one's added, callers fall back to a plain gradient card.
    """
    for name in _HERO_IMAGE_CANDIDATES:
        candidate = _RESOURCES_DIR / name
        if candidate.is_file():
            return candidate
    return None


def current_version_text() -> str:
    """ "version X.Y.Z" from the installed package, or "" if unresolvable.

    Reads the real installed version rather than hardcoding a number
    that would silently go stale after the next release. Shared by
    StartupDialog and the splash screen so the two never disagree.
    """
    try:
        return f"version {version('framelabs')}"
    except PackageNotFoundError:
        return ""


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


def _cover_scaled(image: QPixmap, width: int, height: int) -> QPixmap:
    """Scale+center-crop image to exactly fill width x height (CSS 'cover')."""
    scaled = image.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (scaled.width() - width) // 2
    y = (scaled.height() - height) // 2
    return scaled.copy(QRect(x, y, width, height))


def hero_banner_pixmap(
    width: int,
    height: int,
    image_path: Path | None = None,
    version_text: str | None = None,
    logo_scale: float = 0.34,
) -> QPixmap:
    """Full-bleed photo banner for StartupDialog, logo overlaid bottom-left.

    Renders `image_path` (typically find_hero_image()'s result) cover-
    cropped to width x height, with a bottom gradient scrim so the
    logo and version badge stay legible over a busy photo, then draws
    Logo_Horizontal.png bottom-left and, if given, `version_text`
    top-right in ACCENT_YELLOW.

    If `image_path` is None or fails to load, falls back to a plain
    BG_PANEL_RAISED -> BG_WINDOW gradient card instead of a photo, so
    the dialog still looks intentional before a hero image is added.
    """
    canvas = QPixmap(width, height)

    photo = QPixmap(str(image_path)) if image_path is not None else QPixmap()
    if not photo.isNull():
        canvas = _cover_scaled(photo, width, height)
    else:
        canvas.fill(BACKGROUND_COLOR)
        fallback = QLinearGradient(0, 0, 0, height)
        fallback.setColorAt(0.0, QColor(BG_PANEL_RAISED))
        fallback.setColorAt(1.0, QColor(BG_WINDOW))
        painter = QPainter(canvas)
        painter.fillRect(QRectF(0, 0, width, height), fallback)
        painter.end()

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Bottom scrim: transparent -> near-opaque BG_WINDOW, so logo/
    # version text reads cleanly regardless of what's under them.
    scrim_top = QColor(BG_WINDOW)
    scrim_top.setAlpha(0)
    scrim_bottom = QColor(BG_WINDOW)
    scrim_bottom.setAlpha(235)
    scrim = QLinearGradient(0, height * 0.45, 0, height)
    scrim.setColorAt(0.0, scrim_top)
    scrim.setColorAt(1.0, scrim_bottom)
    painter.fillRect(QRectF(0, height * 0.45, width, height * 0.55), scrim)

    logo = QPixmap(str(_LOGO_PATH))
    padding = max(16, int(width * 0.025))
    if not logo.isNull():
        scaled_logo = logo.scaledToWidth(
            int(width * logo_scale), Qt.TransformationMode.SmoothTransformation
        )
        logo_x = padding
        logo_y = height - padding - scaled_logo.height()
        painter.drawPixmap(logo_x, logo_y, scaled_logo)

    if version_text:
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(ACCENT_YELLOW))
        text_rect = QRect(0, padding, width - padding, 20)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            version_text,
        )

    painter.end()
    return canvas

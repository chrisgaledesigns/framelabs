"""Tests for FrameLabsSplashScreen in ui/splash_screen.py.

A real QSplashScreen is built, using the real hero_banner_pixmap() /
find_hero_image() (already covered by test_branding.py) since there's
nothing worth mocking here -- this class's whole job is a couple of
window-flag calls and a styled showMessage() wrapper.
"""

from PySide6.QtCore import Qt

from framelabs.ui.splash_screen import (
    IDIOMS,
    SPLASH_HEIGHT,
    SPLASH_WIDTH,
    FrameLabsSplashScreen,
)


def test_init_builds_pixmap_at_configured_size():
    """The splash's pixmap should be sized per the module's
    SPLASH_WIDTH/SPLASH_HEIGHT constants."""
    splash = FrameLabsSplashScreen()

    pixmap = splash.pixmap()
    assert pixmap.width() == SPLASH_WIDTH
    assert pixmap.height() == SPLASH_HEIGHT


def test_init_sets_frameless_and_always_on_top_flags():
    """A splash screen with a title bar, or one that can get buried
    behind other windows, defeats the point -- both flags should be
    set."""
    splash = FrameLabsSplashScreen()

    flags = splash.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint) is True
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True


def test_show_status_does_not_raise():
    """show_status() should update the message line without error, even
    though (per its own docstring) no event loop is running yet at the
    point app/main.py actually calls this."""
    splash = FrameLabsSplashScreen()

    splash.show_status("Loading plugins...")  # should not raise


def test_show_random_status_picks_from_idioms():
    """show_random_status() should always land on one of IDIOMS."""
    splash = FrameLabsSplashScreen()

    for _ in range(20):
        splash.show_random_status()
        assert splash._last_idiom in IDIOMS


def test_show_random_status_never_repeats_back_to_back():
    """main.py calls this twice in a row; the two picks should never be
    the same idiom, so the status line visibly changes both times."""
    splash = FrameLabsSplashScreen()

    for _ in range(50):
        splash.show_random_status()
        previous = splash._last_idiom
        splash.show_random_status()
        assert splash._last_idiom != previous

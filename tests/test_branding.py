"""Tests for ui/branding.py: branded_pixmap() (splash screen) and
find_hero_image()/hero_banner_pixmap() (startup Welcome dialog).
"""

from framelabs.ui.branding import branded_pixmap, find_hero_image, hero_banner_pixmap


def test_branded_pixmap_has_requested_size(qtbot):
    pixmap = branded_pixmap(400, 200)
    assert pixmap.width() == 400
    assert pixmap.height() == 200


def test_branded_pixmap_is_not_null(qtbot):
    """Confirms Logo_Horizontal.png actually loads from the packaged
    resources path -- a null pixmap here would mean every pre-launch
    screen silently degraded to a blank dark card."""
    pixmap = branded_pixmap(400, 200)
    assert not pixmap.isNull()


def test_find_hero_image_finds_shipped_startup_hero(qtbot):
    """StartupHero.png now ships in resources/ (added with the splash
    screen work), so find_hero_image() should resolve to a real,
    existing path rather than None."""
    result = find_hero_image()
    assert result is not None
    assert result.exists()
    assert result.name == "StartupHero.png"


def test_hero_banner_pixmap_has_requested_size_without_an_image(qtbot):
    """No hero photo on disk -> gradient fallback, but still exactly
    the requested size so StartupDialog's layout doesn't jump around
    once a real photo is added later."""
    pixmap = hero_banner_pixmap(600, 300, image_path=None)
    assert pixmap.width() == 600
    assert pixmap.height() == 300
    assert not pixmap.isNull()


def test_hero_banner_pixmap_handles_missing_file_path(qtbot, tmp_path):
    """A path that doesn't exist on disk should fall back gracefully,
    same as image_path=None, rather than raising."""
    missing = tmp_path / "does-not-exist.jpg"
    pixmap = hero_banner_pixmap(600, 300, image_path=missing)
    assert pixmap.width() == 600
    assert pixmap.height() == 300
    assert not pixmap.isNull()


def test_hero_banner_pixmap_with_version_text_does_not_raise(qtbot):
    pixmap = hero_banner_pixmap(600, 300, image_path=None, version_text="version 0.1.0")
    assert not pixmap.isNull()

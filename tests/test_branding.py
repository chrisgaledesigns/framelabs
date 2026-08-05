"""Tests for ui/branding.py's branded_pixmap(), shared by the splash
screen and the startup Welcome dialog.
"""

from framelabs.ui.branding import branded_pixmap


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

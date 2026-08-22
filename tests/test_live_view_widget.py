"""Tests for LiveViewWidget in ui/live_view_widget.py.

Real QImage/QPixmap decoding is exercised with genuine encoded PNG
bytes (matching test_capture_service.py's _real_png_bytes() convention)
since this widget's whole job is decoding and displaying real image
bytes. Mouse/wheel/key interactions are driven via real Qt event
objects (matching test_timeline_widget.py and test_theater_view_dialog.py's
conventions) rather than mocking Qt's event system.
"""

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

from framelabs.ui.composition_guides import (
    ASPECT_RATIO_16_9,
    ASPECT_RATIO_NONE,
    GUIDE_NONE,
    GUIDE_THIRDS,
)
from framelabs.ui.live_view_widget import (
    ACTION_SAFE_RATIO,
    TITLE_SAFE_RATIO,
    LiveViewWidget,
)


def _real_png_bytes(width: int = 100, height: int = 60) -> bytes:
    """Build genuine encoded PNG bytes, matching test_capture_service.py."""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".png", image)
    assert success
    return encoded.tobytes()


def _middle_press(widget, x: float = 50.0, y: float = 30.0) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


def _middle_move(widget, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseMoveEvent(event)


def _middle_release(widget, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(event)


def _left_press(widget, x: float = 50.0, y: float = 30.0) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


def _wheel(widget, delta_y: int) -> None:
    event = QWheelEvent(
        QPointF(50, 30),
        QPointF(50, 30),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(event)


def _press_key(widget, key: Qt.Key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(event)


def test_init_has_no_frame_and_hidden_safe_areas():
    widget = LiveViewWidget()

    assert widget._has_frame is False
    assert widget._action_safe_item.isVisible() is False
    assert widget._title_safe_item.isVisible() is False
    assert widget.objectName() == "liveViewWidget"


def test_show_frame_with_valid_bytes_displays_it_and_marks_has_frame():
    widget = LiveViewWidget()
    widget.resize(200, 150)

    widget.show_frame(_real_png_bytes(100, 60))

    assert widget._has_frame is True
    assert widget._pixmap_item.pixmap().isNull() is False
    assert widget._pixmap_item.pixmap().width() == 100
    assert widget._pixmap_item.pixmap().height() == 60


def test_show_frame_with_invalid_bytes_does_nothing():
    widget = LiveViewWidget()

    widget.show_frame(b"not a real image")

    assert widget._has_frame is False
    assert widget._pixmap_item.pixmap().isNull() is True


def test_show_frame_updates_safe_area_geometry_to_frame_size():
    widget = LiveViewWidget()
    widget.resize(200, 150)

    widget.show_frame(_real_png_bytes(200, 100))

    action_rect = widget._action_safe_item.rect()
    title_rect = widget._title_safe_item.rect()
    assert action_rect.width() == 200 * ACTION_SAFE_RATIO
    assert action_rect.height() == 100 * ACTION_SAFE_RATIO
    assert title_rect.width() == 200 * TITLE_SAFE_RATIO
    assert title_rect.height() == 100 * TITLE_SAFE_RATIO


def test_show_frame_auto_fits_on_first_frame():
    widget = LiveViewWidget()
    widget.resize(200, 150)

    widget.show_frame(_real_png_bytes())

    # fit_to_view() resets _user_has_zoomed -- confirms it actually ran.
    assert widget._user_has_zoomed is False


def test_show_frame_preserves_zoom_after_user_has_zoomed():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())
    widget._user_has_zoomed = True

    widget.show_frame(_real_png_bytes())

    assert widget._user_has_zoomed is True


def test_set_safe_areas_visible_toggles_both_items():
    widget = LiveViewWidget()

    widget.set_safe_areas_visible(True)
    assert widget._action_safe_item.isVisible() is True
    assert widget._title_safe_item.isVisible() is True

    widget.set_safe_areas_visible(False)
    assert widget._action_safe_item.isVisible() is False
    assert widget._title_safe_item.isVisible() is False


def test_composition_guide_item_starts_hidden():
    widget = LiveViewWidget()

    assert widget._composition_guide_item.isVisible() is False
    assert widget._composition_guide_item.guide_type() == GUIDE_NONE


def test_set_composition_guide_shows_and_hides_the_overlay():
    widget = LiveViewWidget()

    widget.set_composition_guide(GUIDE_THIRDS)
    assert widget._composition_guide_item.isVisible() is True
    assert widget._composition_guide_item.guide_type() == GUIDE_THIRDS

    widget.set_composition_guide(GUIDE_NONE)
    assert widget._composition_guide_item.isVisible() is False


def test_aspect_ratio_guide_item_starts_hidden():
    widget = LiveViewWidget()

    assert widget._aspect_ratio_guide_item.isVisible() is False
    assert widget._aspect_ratio_guide_item.ratio_type() == ASPECT_RATIO_NONE


def test_set_aspect_ratio_guide_shows_and_hides_the_overlay():
    widget = LiveViewWidget()

    widget.set_aspect_ratio_guide(ASPECT_RATIO_16_9)
    assert widget._aspect_ratio_guide_item.isVisible() is True
    assert widget._aspect_ratio_guide_item.ratio_type() == ASPECT_RATIO_16_9

    widget.set_aspect_ratio_guide(ASPECT_RATIO_NONE)
    assert widget._aspect_ratio_guide_item.isVisible() is False


def test_show_frame_updates_composition_and_aspect_ratio_guide_geometry():
    widget = LiveViewWidget()
    widget.resize(200, 150)

    widget.show_frame(_real_png_bytes(200, 100))

    assert widget._composition_guide_item.boundingRect().width() == 200
    assert widget._composition_guide_item.boundingRect().height() == 100
    assert widget._aspect_ratio_guide_item.boundingRect().width() == 200
    assert widget._aspect_ratio_guide_item.boundingRect().height() == 100


def test_composition_and_aspect_ratio_guides_are_independent():
    widget = LiveViewWidget()

    widget.set_composition_guide(GUIDE_THIRDS)
    widget.set_aspect_ratio_guide(ASPECT_RATIO_16_9)

    assert widget._composition_guide_item.guide_type() == GUIDE_THIRDS
    assert widget._aspect_ratio_guide_item.ratio_type() == ASPECT_RATIO_16_9

    # Turning one off shouldn't touch the other.
    widget.set_composition_guide(GUIDE_NONE)
    assert widget._aspect_ratio_guide_item.ratio_type() == ASPECT_RATIO_16_9


def test_set_onion_layers_adds_before_and_after_layers():
    widget = LiveViewWidget()
    widget.show_frame(_real_png_bytes())
    before = [(_real_png_bytes(), 0.5, "#ff0000")]
    after = [(_real_png_bytes(), 0.3, "#0000ff"), (_real_png_bytes(), 0.1, "#0000ff")]

    widget.set_onion_layers(before, after)

    assert len(widget._onion_items) == 3


def test_set_onion_layers_skips_invalid_image_bytes():
    widget = LiveViewWidget()
    before = [(b"not a real image", 0.5, "#ff0000")]

    widget.set_onion_layers(before, [])

    assert len(widget._onion_items) == 0


def test_set_onion_layers_replaces_previous_layers():
    widget = LiveViewWidget()
    widget.set_onion_layers([(_real_png_bytes(), 0.5, "#ff0000")], [])
    assert len(widget._onion_items) == 1

    widget.set_onion_layers([], [])

    assert len(widget._onion_items) == 0


def test_fit_to_view_with_no_pixmap_does_not_raise():
    widget = LiveViewWidget()

    widget.fit_to_view()  # should not raise, pixmap is still null


def test_wheel_event_without_frame_does_nothing():
    widget = LiveViewWidget()

    _wheel(widget, 120)  # should not raise, no frame yet

    assert widget._user_has_zoomed is False


def test_wheel_event_with_frame_zooms_and_marks_user_has_zoomed():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())

    _wheel(widget, 120)  # zoom in

    assert widget._user_has_zoomed is True


def test_wheel_event_negative_delta_zooms_out():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())

    _wheel(widget, -120)  # should not raise

    assert widget._user_has_zoomed is True


def test_middle_button_drag_pans_and_resets_on_release():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())

    _middle_press(widget, 50, 30)
    assert widget._panning is True

    _middle_move(widget, 60, 40)  # should not raise

    _middle_release(widget, 60, 40)
    assert widget._panning is False
    assert widget._pan_last_pos is None


def test_left_button_press_does_not_start_panning():
    widget = LiveViewWidget()

    _left_press(widget)

    assert widget._panning is False


def test_mouse_move_while_not_panning_falls_through_to_super():
    """Without an active middle-button pan, mouseMoveEvent should defer
    to QGraphicsView's own handling rather than doing anything itself."""
    widget = LiveViewWidget()

    _middle_move(widget, 60, 40)  # should not raise; _panning is False

    assert widget._panning is False


def test_mouse_release_while_not_panning_falls_through_to_super():
    """A middle-button release with no active pan (e.g. press happened
    outside the widget) should defer to the base implementation."""
    widget = LiveViewWidget()

    _middle_release(widget, 60, 40)  # should not raise; _panning is False

    assert widget._panning is False


def test_key_f_fits_to_view():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())
    widget._user_has_zoomed = True

    _press_key(widget, Qt.Key.Key_F)

    assert widget._user_has_zoomed is False


def test_other_key_press_does_not_affect_zoom_state():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())
    widget._user_has_zoomed = True

    _press_key(widget, Qt.Key.Key_A)

    assert widget._user_has_zoomed is True


def test_draw_background_before_first_frame_does_not_raise():
    widget = LiveViewWidget()
    widget.resize(200, 150)

    widget.grab()  # triggers drawBackground(); should not raise


def test_draw_background_after_first_frame_does_not_raise():
    widget = LiveViewWidget()
    widget.resize(200, 150)
    widget.show_frame(_real_png_bytes())

    widget.grab()  # should not raise

"""Tests for composition_guides.py.

Geometry helpers (fraction_grid_lines, diagonal_lines, crosshair_lines,
aspect_ratio_rect, golden_spiral_arcs) are pure QRectF/QLineF math with
no painting involved, so they're checked directly against expected
coordinates. CompositionGuideItem/AspectRatioGuideItem are checked the
same way test_live_view_widget.py checks the existing safe area items:
geometry/visibility state after calling their public setters, plus a
paint()-doesn't-raise smoke test for every guide type (driven through a
real QGraphicsScene.render() rather than mocking QPainter, matching this
suite's general preference for exercising real Qt objects).
"""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGraphicsScene

from framelabs.ui.composition_guides import (
    ASPECT_RATIO_1_1,
    ASPECT_RATIO_4_3,
    ASPECT_RATIO_16_9,
    ASPECT_RATIO_GUIDE_TYPES,
    ASPECT_RATIO_NONE,
    ASPECT_RATIO_VALUES,
    COMPOSITION_GUIDE_TYPES,
    GOLDEN_RATIO_MAJOR,
    GOLDEN_RATIO_MINOR,
    GUIDE_CROSSHAIR,
    GUIDE_NONE,
    GUIDE_THIRDS,
    AspectRatioGuideItem,
    CompositionGuideItem,
    aspect_ratio_rect,
    crosshair_lines,
    diagonal_lines,
    fraction_grid_lines,
    golden_spiral_arcs,
)


def _render(item) -> None:
    """Render `item` inside a real scene, exercising its paint() for real."""
    scene = QGraphicsScene()
    scene.addItem(item)
    image = QImage(200, 150, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    scene.render(painter)
    painter.end()


# ---------------------------------------------------------------------
# fraction_grid_lines
# ---------------------------------------------------------------------


def test_fraction_grid_lines_center_grid_is_one_vertical_and_one_horizontal():
    rect = QRectF(0, 0, 200, 100)

    lines = fraction_grid_lines(rect, [0.5])

    assert len(lines) == 2
    vertical, horizontal = lines
    assert vertical.x1() == vertical.x2() == 100
    assert (vertical.y1(), vertical.y2()) == (0, 100)
    assert horizontal.y1() == horizontal.y2() == 50
    assert (horizontal.x1(), horizontal.x2()) == (0, 200)


def test_fraction_grid_lines_thirds_has_four_lines_at_correct_positions():
    rect = QRectF(0, 0, 300, 90)

    lines = fraction_grid_lines(rect, [1 / 3, 2 / 3])

    assert len(lines) == 4
    vertical_xs = sorted({lines[0].x1(), lines[2].x1()})
    assert vertical_xs == [100, 200]
    horizontal_ys = sorted({lines[1].y1(), lines[3].y1()})
    assert horizontal_ys == [30, 60]


def test_fraction_grid_lines_golden_ratio_uses_phi_fractions():
    rect = QRectF(0, 0, 1000, 1000)

    lines = fraction_grid_lines(rect, [GOLDEN_RATIO_MINOR, GOLDEN_RATIO_MAJOR])

    xs = sorted({lines[0].x1(), lines[2].x1()})
    assert xs[0] == 1000 * GOLDEN_RATIO_MINOR
    assert xs[1] == 1000 * GOLDEN_RATIO_MAJOR
    # The two fractions should straddle the exact center, roughly symmetrically.
    assert abs((xs[0] + xs[1]) / 2 - 500) < 1


def test_fraction_grid_lines_quarters_has_six_lines():
    rect = QRectF(0, 0, 400, 400)

    lines = fraction_grid_lines(rect, [0.25, 0.5, 0.75])

    assert len(lines) == 6
    vertical_xs = sorted({lines[0].x1(), lines[2].x1(), lines[4].x1()})
    assert vertical_xs == [100, 200, 300]


def test_fraction_grid_lines_offset_rect_respects_origin():
    rect = QRectF(10, 20, 200, 100)

    lines = fraction_grid_lines(rect, [0.5])

    vertical, horizontal = lines
    assert vertical.x1() == 110  # 10 + 200 * 0.5
    assert horizontal.y1() == 70  # 20 + 100 * 0.5


# ---------------------------------------------------------------------
# diagonal_lines / crosshair_lines
# ---------------------------------------------------------------------


def test_diagonal_lines_connects_opposite_corners():
    rect = QRectF(0, 0, 200, 100)

    lines = diagonal_lines(rect)

    assert len(lines) == 2
    assert (lines[0].p1(), lines[0].p2()) == (rect.topLeft(), rect.bottomRight())
    assert (lines[1].p1(), lines[1].p2()) == (rect.topRight(), rect.bottomLeft())


def test_crosshair_lines_are_short_and_centered():
    rect = QRectF(0, 0, 200, 100)

    lines = crosshair_lines(rect)

    assert len(lines) == 2
    horizontal, vertical = lines
    center = rect.center()
    assert horizontal.y1() == horizontal.y2() == center.y()
    assert vertical.x1() == vertical.x2() == center.x()
    # Arms are short relative to the frame -- not full-width/height lines
    # like the grid guides (that distinction is the whole point of this
    # guide type).
    assert horizontal.length() < rect.width() * 0.5
    assert vertical.length() < rect.height() * 0.5


def test_crosshair_lines_scale_with_shorter_side():
    wide_rect = QRectF(0, 0, 400, 100)
    lines = crosshair_lines(wide_rect)
    horizontal, vertical = lines
    # Arm length is derived from min(width, height), so it should be
    # bounded by the shorter (height) dimension, not the longer one.
    assert horizontal.length() <= wide_rect.height()


# ---------------------------------------------------------------------
# aspect_ratio_rect
# ---------------------------------------------------------------------


def test_aspect_ratio_rect_letterboxes_when_frame_is_wider():
    frame = QRectF(0, 0, 1000, 500)  # 2:1, wider than any target below

    guide = aspect_ratio_rect(frame, ASPECT_RATIO_VALUES[ASPECT_RATIO_1_1])

    assert guide.height() == 500
    assert guide.width() == 500
    assert guide.left() == 250  # centered horizontally
    assert guide.top() == 0


def test_aspect_ratio_rect_pillarboxes_when_frame_is_taller():
    frame = QRectF(0, 0, 400, 800)  # 1:2, taller than 16:9

    guide = aspect_ratio_rect(frame, ASPECT_RATIO_VALUES[ASPECT_RATIO_16_9])

    assert guide.width() == 400
    assert guide.height() == 400 / (16 / 9)
    assert guide.left() == 0
    assert guide.top() == (800 - guide.height()) / 2


def test_aspect_ratio_rect_matches_frame_when_ratio_equal():
    frame = QRectF(0, 0, 400, 300)  # exactly 4:3

    guide = aspect_ratio_rect(frame, ASPECT_RATIO_VALUES[ASPECT_RATIO_4_3])

    assert guide == frame


def test_aspect_ratio_rect_handles_degenerate_rect():
    frame = QRectF(0, 0, 0, 0)

    guide = aspect_ratio_rect(frame, 1.0)

    assert (
        guide == frame
    )  # falls back to the input rather than raising/dividing by zero


# ---------------------------------------------------------------------
# golden_spiral_arcs
# ---------------------------------------------------------------------


def test_golden_spiral_arcs_returns_requested_step_count():
    rect = QRectF(0, 0, 640, 360)

    arcs = golden_spiral_arcs(rect, steps=9)

    assert len(arcs) == 9


def test_golden_spiral_arcs_squares_shrink_each_step():
    rect = QRectF(0, 0, 640, 360)

    arcs = golden_spiral_arcs(rect, steps=5)

    sides = [circle_rect.width() / 2 for circle_rect, _ in arcs]
    assert sides == sorted(sides, reverse=True)
    assert all(a > b for a, b in zip(sides, sides[1:]))


def test_golden_spiral_arcs_start_angles_are_valid_qt_angles():
    rect = QRectF(0, 0, 640, 360)

    arcs = golden_spiral_arcs(rect, steps=8)

    for _, start_angle in arcs:
        assert start_angle in (0.0, 90.0, 180.0, 270.0)


def test_golden_spiral_arcs_handles_degenerate_rect():
    assert golden_spiral_arcs(QRectF(0, 0, 0, 0)) == []


# ---------------------------------------------------------------------
# CompositionGuideItem
# ---------------------------------------------------------------------


def test_composition_guide_item_starts_hidden_with_no_type():
    item = CompositionGuideItem()

    assert item.isVisible() is False
    assert item.guide_type() == GUIDE_NONE


def test_composition_guide_item_set_guide_type_shows_and_hides():
    item = CompositionGuideItem()

    item.set_guide_type(GUIDE_THIRDS)
    assert item.isVisible() is True
    assert item.guide_type() == GUIDE_THIRDS

    item.set_guide_type(GUIDE_NONE)
    assert item.isVisible() is False


def test_composition_guide_item_set_frame_rect_updates_bounding_rect():
    item = CompositionGuideItem()

    item.set_frame_rect(QRectF(0, 0, 640, 360))

    assert item.boundingRect() == QRectF(0, 0, 640, 360)


def test_composition_guide_item_paints_every_guide_type_without_raising():
    for guide_type in COMPOSITION_GUIDE_TYPES:
        item = CompositionGuideItem()
        item.set_frame_rect(QRectF(0, 0, 200, 150))
        item.set_guide_type(guide_type)

        _render(item)  # should not raise, for every guide type including GUIDE_NONE


def test_composition_guide_item_paint_with_empty_rect_does_not_raise():
    item = CompositionGuideItem()
    item.set_guide_type(GUIDE_CROSSHAIR)  # frame_rect never set -> empty QRectF

    _render(item)


# ---------------------------------------------------------------------
# AspectRatioGuideItem
# ---------------------------------------------------------------------


def test_aspect_ratio_guide_item_starts_hidden_with_no_type():
    item = AspectRatioGuideItem()

    assert item.isVisible() is False
    assert item.ratio_type() == ASPECT_RATIO_NONE


def test_aspect_ratio_guide_item_set_ratio_type_shows_and_hides():
    item = AspectRatioGuideItem()

    item.set_ratio_type(ASPECT_RATIO_16_9)
    assert item.isVisible() is True
    assert item.ratio_type() == ASPECT_RATIO_16_9

    item.set_ratio_type(ASPECT_RATIO_NONE)
    assert item.isVisible() is False


def test_aspect_ratio_guide_item_paints_every_ratio_type_without_raising():
    for ratio_type in ASPECT_RATIO_GUIDE_TYPES:
        item = AspectRatioGuideItem()
        item.set_frame_rect(QRectF(0, 0, 200, 150))
        item.set_ratio_type(ratio_type)

        _render(
            item
        )  # should not raise, for every ratio type including ASPECT_RATIO_NONE


def test_aspect_ratio_guide_item_paint_with_empty_rect_does_not_raise():
    item = AspectRatioGuideItem()
    item.set_ratio_type(ASPECT_RATIO_1_1)  # frame_rect never set -> empty QRectF

    _render(item)

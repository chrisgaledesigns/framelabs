"""Composition guide overlays for Live View.

Adds two independent, selectable overlay families on top of the Live
View frame, alongside the existing Safe Area guides in
live_view_widget.py:

- Composition guides (COMPOSITION_GUIDE_TYPES): full-frame grid/line/
  point overlays -- Center Grid, Thirds, Golden Ratio (Phi Grid), Golden
  Spiral, Quarters Grid (4x4), Diagonal Grid, and Crosshair / Center
  Point. Only one is shown at a time (or none, GUIDE_NONE).
- Aspect ratio guides (ASPECT_RATIO_GUIDE_TYPES): a single centered
  letterboxed/pillarboxed rectangle previewing a target aspect ratio's
  crop within the current frame -- 1:1, 4:3, 3:2, 16:9, 2.35:1. Also
  only one shown at a time (or none, ASPECT_RATIO_NONE), and fully
  independent of whichever composition guide (if any) is also showing.

Each family is its own QGraphicsItem subclass (CompositionGuideItem,
AspectRatioGuideItem) so LiveViewWidget can add one instance of each
straight into its QGraphicsScene, the same way it already adds the Safe
Area QGraphicsRectItems -- see LiveViewWidget's docstring for the shared
zValue-stacking approach these items slot into.

The actual line/rect/arc geometry for each guide type is exposed as
plain functions returning QLineF lists or QRectF/tuples -- no QPainter
involved -- so the geometry itself is unit-testable without constructing
a QGraphicsItem, a QPainter, or a QApplication.
"""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsItem

# Golden ratio (phi) and the two grid-line fractions derived from it --
# shared by the Golden Ratio (Phi Grid) composition guide and the Golden
# Spiral, which is built from the same proportions.
PHI = 1.618033988749895
GOLDEN_RATIO_MINOR = 1 / (PHI * PHI)  # ~0.382
GOLDEN_RATIO_MAJOR = 1 / PHI  # ~0.618

GUIDE_NONE = "none"
GUIDE_CENTER_GRID = "center_grid"
GUIDE_THIRDS = "thirds"
GUIDE_GOLDEN_RATIO = "golden_ratio"
GUIDE_GOLDEN_SPIRAL = "golden_spiral"
GUIDE_QUARTERS = "quarters"
GUIDE_DIAGONAL = "diagonal"
GUIDE_CROSSHAIR = "crosshair"

# Display-ordered -- matches the order these appear in the Guides menu.
COMPOSITION_GUIDE_TYPES = (
    GUIDE_NONE,
    GUIDE_CENTER_GRID,
    GUIDE_THIRDS,
    GUIDE_GOLDEN_RATIO,
    GUIDE_GOLDEN_SPIRAL,
    GUIDE_QUARTERS,
    GUIDE_DIAGONAL,
    GUIDE_CROSSHAIR,
)

COMPOSITION_GUIDE_LABELS = {
    GUIDE_NONE: "None",
    GUIDE_CENTER_GRID: "Center Grid",
    GUIDE_THIRDS: "Thirds",
    GUIDE_GOLDEN_RATIO: "Golden Ratio (Phi Grid)",
    GUIDE_GOLDEN_SPIRAL: "Golden Spiral",
    GUIDE_QUARTERS: "Quarters Grid (4x4)",
    GUIDE_DIAGONAL: "Diagonal Grid",
    GUIDE_CROSSHAIR: "Crosshair / Center Point",
}

ASPECT_RATIO_NONE = "none"
ASPECT_RATIO_1_1 = "1:1"
ASPECT_RATIO_4_3 = "4:3"
ASPECT_RATIO_3_2 = "3:2"
ASPECT_RATIO_16_9 = "16:9"
ASPECT_RATIO_2_35_1 = "2.35:1"

ASPECT_RATIO_GUIDE_TYPES = (
    ASPECT_RATIO_NONE,
    ASPECT_RATIO_1_1,
    ASPECT_RATIO_4_3,
    ASPECT_RATIO_3_2,
    ASPECT_RATIO_16_9,
    ASPECT_RATIO_2_35_1,
)

ASPECT_RATIO_LABELS = {
    ASPECT_RATIO_NONE: "None",
    ASPECT_RATIO_1_1: "1:1 (Square)",
    ASPECT_RATIO_4_3: "4:3 (Academy/Standard)",
    ASPECT_RATIO_3_2: "3:2",
    ASPECT_RATIO_16_9: "16:9 (Widescreen/HD)",
    ASPECT_RATIO_2_35_1: "2.35:1 (Cinemascope)",
}

# Target width/height ratio for each aspect ratio guide.
ASPECT_RATIO_VALUES = {
    ASPECT_RATIO_1_1: 1.0,
    ASPECT_RATIO_4_3: 4 / 3,
    ASPECT_RATIO_3_2: 3 / 2,
    ASPECT_RATIO_16_9: 16 / 9,
    ASPECT_RATIO_2_35_1: 2.35,
}

# Composition guides use a neutral, semi-transparent white so they read
# clearly over any footage without implying a pass/fail judgement the
# way the safe area guides' yellow/red does.
GUIDE_COLOR = QColor(255, 255, 255, 160)
ASPECT_RATIO_GUIDE_COLOR = QColor(0, 220, 255, 200)

# Each crosshair arm's length, as a fraction of the frame's shorter side.
CROSSHAIR_ARM_RATIO = 0.05
CROSSHAIR_DOT_RADIUS = 3.0

# Nested squares for the Golden Spiral -- each is ~0.618x the previous,
# so by 9 steps the remaining square is already sub-pixel at any normal
# frame resolution and further steps would be invisible.
GOLDEN_SPIRAL_STEPS = 9


def fraction_grid_lines(rect: QRectF, fractions: list[float]) -> list[QLineF]:
    """Return one full-height vertical + one full-width horizontal line
    at each given fraction of rect's width/height.

    Shared by every fixed-fraction grid guide -- Center Grid ([0.5]),
    Thirds ([1/3, 2/3]), Golden Ratio ([GOLDEN_RATIO_MINOR,
    GOLDEN_RATIO_MAJOR]), and Quarters Grid ([0.25, 0.5, 0.75]) are all
    "grid lines at fixed fractions of the frame", differing only in
    which fractions.
    """
    lines: list[QLineF] = []
    for fraction in fractions:
        x = rect.left() + rect.width() * fraction
        lines.append(QLineF(x, rect.top(), x, rect.bottom()))
        y = rect.top() + rect.height() * fraction
        lines.append(QLineF(rect.left(), y, rect.right(), y))
    return lines


def diagonal_lines(rect: QRectF) -> list[QLineF]:
    """Return both corner-to-corner diagonals of rect."""
    return [
        QLineF(rect.topLeft(), rect.bottomRight()),
        QLineF(rect.topRight(), rect.bottomLeft()),
    ]


def crosshair_lines(rect: QRectF) -> list[QLineF]:
    """Return the two short arms of a crosshair centered on rect.

    Deliberately short (CROSSHAIR_ARM_RATIO of the shorter side) rather
    than full-frame lines -- this guide marks the exact center point,
    not a dividing line, which is also what distinguishes it from
    Center Grid.
    """
    center = rect.center()
    arm = min(rect.width(), rect.height()) * CROSSHAIR_ARM_RATIO
    return [
        QLineF(center.x() - arm, center.y(), center.x() + arm, center.y()),
        QLineF(center.x(), center.y() - arm, center.x(), center.y() + arm),
    ]


def aspect_ratio_rect(rect: QRectF, target_ratio: float) -> QRectF:
    """Return the largest target_ratio (width/height) rectangle centered in rect.

    Letterboxes (leaves top/bottom margin) when rect is relatively taller
    than target_ratio, and pillarboxes (leaves left/right margin) when
    rect is relatively wider -- whichever keeps the guide rectangle
    fully inside rect at the correct proportions.
    """
    width, height = rect.width(), rect.height()
    if height <= 0 or width <= 0:
        return QRectF(rect)
    if width / height > target_ratio:
        new_height = height
        new_width = height * target_ratio
    else:
        new_width = width
        new_height = width / target_ratio
    x = rect.left() + (width - new_width) / 2
    y = rect.top() + (height - new_height) / 2
    return QRectF(x, y, new_width, new_height)


def golden_spiral_arcs(
    rect: QRectF, steps: int = GOLDEN_SPIRAL_STEPS
) -> list[tuple[QRectF, float]]:
    """Return (circle_bounding_rect, start_angle_degrees) pairs tracing a golden spiral.

    Each pair describes one 90-degree quarter-circle arc -- draw it with
    `painter.drawArc(circle_rect, start_angle * 16, 90 * 16)` (Qt's
    drawArc takes angles in 1/16ths of a degree). Built by the classic
    golden-rectangle construction: peel a square off the rectangle's
    leading edge (cycling left/top/right/bottom), leaving a smaller
    golden rectangle behind, and repeat. Each square's arc is a quarter
    of the circle of radius `side` centered on whichever of that
    square's corners is shared with the *next* square in the sequence --
    that shared-corner choice is what makes consecutive arcs meet end to
    end into one continuous spiral rather than four disconnected curves.

    The spiral is fitted to the largest golden-ratio (phi:1) rectangle
    that fits centered in `rect`, rather than to `rect` directly --  the
    construction only looks like a proper spiral at true golden
    proportions, and `rect` (the live frame) is usually a different
    aspect ratio.
    """
    if rect.width() <= 0 or rect.height() <= 0:
        return []

    if rect.width() / rect.height() > PHI:
        golden_width = rect.height() * PHI
        golden_height = rect.height()
    else:
        golden_width = rect.width()
        golden_height = rect.width() / PHI
    golden_left = rect.left() + (rect.width() - golden_width) / 2
    golden_top = rect.top() + (rect.height() - golden_height) / 2
    remaining = QRectF(golden_left, golden_top, golden_width, golden_height)

    # Which corner of the peeled square connects to the next square in
    # the cycle, and that corner's drawArc start angle -- Qt's
    # convention is 0=east/3-o'clock, 90=north, positive=counter-
    # clockwise, so the 90-degree quadrant "inside" a square measured
    # from a given corner starts at: TL->270, TR->180, BL->0, BR->90.
    peel_corners = {"left": "BR", "top": "BL", "right": "TL", "bottom": "TR"}
    corner_start_angle = {"TL": 270.0, "TR": 180.0, "BL": 0.0, "BR": 90.0}
    peel_cycle = ("left", "top", "right", "bottom")

    arcs: list[tuple[QRectF, float]] = []
    for step in range(steps):
        side = min(remaining.width(), remaining.height())
        if side < 1:
            break
        peel = peel_cycle[step % len(peel_cycle)]

        if peel == "left":
            square = QRectF(remaining.left(), remaining.top(), side, side)
            remaining = QRectF(
                remaining.left() + side,
                remaining.top(),
                remaining.width() - side,
                remaining.height(),
            )
        elif peel == "top":
            square = QRectF(remaining.left(), remaining.top(), remaining.width(), side)
            remaining = QRectF(
                remaining.left(),
                remaining.top() + side,
                remaining.width(),
                remaining.height() - side,
            )
        elif peel == "right":
            square = QRectF(remaining.right() - side, remaining.top(), side, side)
            remaining = QRectF(
                remaining.left(),
                remaining.top(),
                remaining.width() - side,
                remaining.height(),
            )
        else:  # "bottom"
            square = QRectF(
                remaining.left(), remaining.bottom() - side, remaining.width(), side
            )
            remaining = QRectF(
                remaining.left(),
                remaining.top(),
                remaining.width(),
                remaining.height() - side,
            )

        corner = peel_corners[peel]
        corner_point = {
            "TL": square.topLeft(),
            "TR": square.topRight(),
            "BL": square.bottomLeft(),
            "BR": square.bottomRight(),
        }[corner]
        circle_rect = QRectF(
            corner_point.x() - side, corner_point.y() - side, side * 2, side * 2
        )
        arcs.append((circle_rect, corner_start_angle[corner]))

    return arcs


class CompositionGuideItem(QGraphicsItem):
    """A single-guide composition overlay: draws whichever guide type
    (COMPOSITION_GUIDE_TYPES) is currently selected, or nothing at all.

    Sized to the current frame via set_frame_rect(), the same pattern
    LiveViewWidget already uses for its safe area QGraphicsRectItems --
    see that widget's _update_safe_area_geometry() docstring.
    """

    def __init__(self) -> None:
        """Build the item, initially empty, hidden, and showing GUIDE_NONE."""
        super().__init__()
        self._rect = QRectF()
        self._guide_type = GUIDE_NONE
        self.setVisible(False)

    def set_frame_rect(self, rect: QRectF) -> None:
        """Resize the guide to match the current frame's geometry."""
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self.update()

    def set_guide_type(self, guide_type: str) -> None:
        """Switch to a different guide type (or GUIDE_NONE to hide it).

        Visibility follows the guide type directly -- GUIDE_NONE hides
        the item, anything else shows it -- so callers don't need a
        separate visibility toggle alongside this one.
        """
        self._guide_type = guide_type
        self.setVisible(guide_type != GUIDE_NONE)
        self.update()

    def guide_type(self) -> str:
        """Return the currently selected guide type."""
        return self._guide_type

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None) -> None:
        """Draw the currently selected guide type's geometry, if any."""
        if self._guide_type == GUIDE_NONE or self._rect.isEmpty():
            return

        pen = QPen(GUIDE_COLOR)
        pen.setWidth(1)
        pen.setCosmetic(True)
        painter.setPen(pen)

        if self._guide_type == GUIDE_CENTER_GRID:
            painter.drawLines(fraction_grid_lines(self._rect, [0.5]))
        elif self._guide_type == GUIDE_THIRDS:
            painter.drawLines(fraction_grid_lines(self._rect, [1 / 3, 2 / 3]))
        elif self._guide_type == GUIDE_GOLDEN_RATIO:
            painter.drawLines(
                fraction_grid_lines(
                    self._rect, [GOLDEN_RATIO_MINOR, GOLDEN_RATIO_MAJOR]
                )
            )
        elif self._guide_type == GUIDE_QUARTERS:
            painter.drawLines(fraction_grid_lines(self._rect, [0.25, 0.5, 0.75]))
        elif self._guide_type == GUIDE_DIAGONAL:
            painter.drawLines(diagonal_lines(self._rect))
        elif self._guide_type == GUIDE_CROSSHAIR:
            painter.drawLines(crosshair_lines(self._rect))
            center = self._rect.center()
            painter.drawEllipse(center, CROSSHAIR_DOT_RADIUS, CROSSHAIR_DOT_RADIUS)
        elif self._guide_type == GUIDE_GOLDEN_SPIRAL:
            for circle_rect, start_angle in golden_spiral_arcs(self._rect):
                painter.drawArc(circle_rect, int(start_angle * 16), 90 * 16)


class AspectRatioGuideItem(QGraphicsItem):
    """A single aspect-ratio crop guide overlay: a centered rectangle
    previewing the selected target ratio (ASPECT_RATIO_GUIDE_TYPES)
    within the current frame, or nothing at all.

    Sized to the current frame via set_frame_rect(), same pattern as
    CompositionGuideItem above.
    """

    def __init__(self) -> None:
        """Build the item, initially empty, hidden, and showing ASPECT_RATIO_NONE."""
        super().__init__()
        self._rect = QRectF()
        self._ratio_type = ASPECT_RATIO_NONE
        self.setVisible(False)

    def set_frame_rect(self, rect: QRectF) -> None:
        """Resize the guide to match the current frame's geometry."""
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self.update()

    def set_ratio_type(self, ratio_type: str) -> None:
        """Switch to a different target ratio (or ASPECT_RATIO_NONE to hide it)."""
        self._ratio_type = ratio_type
        self.setVisible(ratio_type != ASPECT_RATIO_NONE)
        self.update()

    def ratio_type(self) -> str:
        """Return the currently selected aspect ratio type."""
        return self._ratio_type

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None) -> None:
        """Draw the selected target ratio's centered crop rectangle, if any."""
        if self._ratio_type == ASPECT_RATIO_NONE or self._rect.isEmpty():
            return
        target_ratio = ASPECT_RATIO_VALUES[self._ratio_type]
        pen = QPen(ASPECT_RATIO_GUIDE_COLOR)
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(aspect_ratio_rect(self._rect, target_ratio))

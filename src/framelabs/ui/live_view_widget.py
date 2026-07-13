"""Live camera view widget for Feature 3.

Displays whatever frame it's given -- either a live camera preview frame
(from LiveViewController) or a specific saved frame during Play/Onion Skin
-- through a single shared rendering surface. Onion skin overlays (Feature
6) are additional pixmap items in the same scene, stacked ABOVE the current
frame via zValue, each rendered at partial opacity so the current frame
remains visible beneath the ghosted layers -- the current frame's own
pixmap is fully opaque, so an onion layer stacked below it would be
entirely hidden regardless of its own opacity. Remaining overlays (safe
areas, histogram) are still to come as later layers on top of this core
display.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsColorizeEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)

# Feature Spec Feature 3: "Mouse wheel" zoom, scaled per notch.
ZOOM_FACTOR_PER_STEP = 1.15

# The current frame is the base layer -- every onion skin layer renders
# above it (positive zValue, see _add_onion_layers) at partial opacity, so
# the current frame stays visible underneath the ghosted layers.
CURRENT_FRAME_Z_VALUE = 0.0


class LiveViewWidget(QGraphicsView):
    """Displays a live or saved frame with zoom, pan, fit-to-view, and
    Onion Skin overlays.

    Zoom: mouse wheel, centered on the cursor.
    Pan: middle mouse button drag.
    Fit: F key, or automatically whenever a new frame arrives -- unless
        the user has manually zoomed since the last fit, in which case
        their zoom/pan is preserved across new frames until they press F
        again.
    """

    def __init__(self) -> None:
        """Build the view, its scene, and the (initially empty) pixmap item."""
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setZValue(CURRENT_FRAME_Z_VALUE)
        self._scene.addItem(self._pixmap_item)

        self._onion_items: list[QGraphicsPixmapItem] = []

        self._has_frame = False
        self._user_has_zoomed = False
        self._panning = False
        self._pan_last_pos = None

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor(30, 30, 30))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def show_frame(self, image_bytes: bytes) -> None:
        """Decode and display a new frame.

        Args:
            image_bytes: Encoded image bytes (JPEG or PNG) -- either a live
                preview frame from LiveViewController, or the raw bytes of
                a saved frame's file read from disk.
        """
        image = QImage.fromData(image_bytes)
        if image.isNull():
            return

        pixmap = QPixmap.fromImage(image)
        self._pixmap_item.setPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))

        was_first_frame = not self._has_frame
        self._has_frame = True

        if was_first_frame or not self._user_has_zoomed:
            self.fit_to_view()

    def set_onion_layers(
        self, before_layers: list[tuple[bytes, float, str]], after_layers: list
    ) -> None:
        """Replace the onion skin overlay with a new set of frame layers.

        Args:
            before_layers: (image_bytes, opacity, tint_hex) tuples for
                frames before the current one, nearest-first -- the same
                shape OnionSkinController.frames_ready emits.
            after_layers: Same shape, for frames after the current one.

        Each layer is drawn at (0, 0) in scene coordinates, on the
        assumption that every captured frame in a project shares the same
        resolution -- true for real capture, since Resolution is fixed at
        project creation. Stacking is controlled by zValue: every onion
        layer sits ABOVE the current frame (CURRENT_FRAME_Z_VALUE), so its
        partial opacity lets the current frame show through -- stacking
        it below the current frame's opaque pixmap would hide it entirely,
        regardless of its own opacity. Among onion layers themselves, the
        nearest frame on each side sits closest to the current frame's
        zValue, with further frames stacked progressively above that.
        """
        self._clear_onion_layers()
        self._add_onion_layers(before_layers)
        self._add_onion_layers(after_layers)

    def _add_onion_layers(self, layers: list[tuple[bytes, float, str]]) -> None:
        """Add one side's onion layers (already nearest-first) to the scene."""
        for distance, (image_bytes, opacity, tint_hex) in enumerate(layers, start=1):
            image = QImage.fromData(image_bytes)
            if image.isNull():
                continue

            item = QGraphicsPixmapItem(QPixmap.fromImage(image))
            item.setPos(0, 0)
            item.setOpacity(opacity)
            # Every onion layer renders above the current frame
            # (CURRENT_FRAME_Z_VALUE), so it's actually visible through its
            # own partial opacity. Nearer frames sit closest to the
            # current frame's zValue; further frames stack progressively
            # above that.
            item.setZValue(CURRENT_FRAME_Z_VALUE + distance)

            effect = QGraphicsColorizeEffect()
            effect.setColor(QColor(tint_hex))
            effect.setStrength(1.0)
            item.setGraphicsEffect(effect)

            self._scene.addItem(item)
            self._onion_items.append(item)

    def _clear_onion_layers(self) -> None:
        """Remove and discard every currently-shown onion skin layer."""
        for item in self._onion_items:
            self._scene.removeItem(item)
        self._onion_items.clear()

    def fit_to_view(self) -> None:
        """Scale and center the current frame to fill the viewport.

        Resets the "user has zoomed" flag, so subsequent new frames go
        back to auto-fitting until the user zooms again.
        """
        if self._pixmap_item.pixmap().isNull():
            return
        self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._user_has_zoomed = False

    def wheelEvent(self, event) -> None:
        """Zoom in/out around the cursor position."""
        if not self._has_frame:
            return
        factor = (
            ZOOM_FACTOR_PER_STEP
            if event.angleDelta().y() > 0
            else 1 / ZOOM_FACTOR_PER_STEP
        )
        self.scale(factor, factor)
        self._user_has_zoomed = True

    def mousePressEvent(self, event) -> None:
        """Begin a manual pan on middle-button press."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Continue a manual pan while the middle button is held."""
        if self._panning and self._pan_last_pos is not None:
            delta = event.position() - self._pan_last_pos
            self._pan_last_pos = event.position()
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - int(delta.x()))
            v_bar.setValue(v_bar.value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """End a manual pan on middle-button release."""
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self._pan_last_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        """F key: fit the current frame to the view."""
        if event.key() == Qt.Key.Key_F:
            self.fit_to_view()
            event.accept()
            return
        super().keyPressEvent(event)

    def drawBackground(self, painter, rect) -> None:
        """Draw a "No Camera" placeholder until the first frame arrives."""
        super().drawBackground(painter, rect)
        if self._has_frame:
            return
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(150, 150, 150))
        painter.drawText(
            self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, "No Camera"
        )
        painter.restore()

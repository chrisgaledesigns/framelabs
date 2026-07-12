"""Live camera view widget for Feature 3.

Displays whatever frame it's given -- either a live camera preview frame
(from LiveViewController) or a specific saved frame during Play/Onion Skin
-- through a single shared rendering surface. Overlays (safe areas,
histogram, onion skin) are added as later layers on top of this core
display; this module owns only the base image display, zoom, pan, and fit.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

# Feature Spec Feature 3: "Mouse wheel" zoom, scaled per notch.
ZOOM_FACTOR_PER_STEP = 1.15


class LiveViewWidget(QGraphicsView):
    """Displays a live or saved frame with zoom, pan, and fit-to-view.

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
        self._scene.addItem(self._pixmap_item)

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

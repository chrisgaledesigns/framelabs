"""Live luminance histogram strip for the Inspector panel.

Pure display widget -- receives a pre-computed 256-bin normalized
luminance histogram (see image_processing/histogram.py) via
update_histogram() and paints it as a bar strip. Knows nothing about
cameras, threads, or the event bus; InspectorPanel owns wiring this to
LiveViewController's histogram_ready signal.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

# Industry-standard look for a camera histogram: a dark strip with a
# light fill, similar to Lightroom/Photoshop/most camera manufacturers'
# in-body histogram displays. A deliberate visual default -- flagged to
# Chris directly rather than assumed silently; easy to adjust later.
BACKGROUND_COLOR = QColor("#1e1e1e")
BAR_COLOR = QColor("#d8d8d8")
MIN_HEIGHT = 80


class HistogramWidget(QWidget):
    """Paints a live-updating luminance histogram as a strip of bars."""

    def __init__(self) -> None:
        """Build the widget with no histogram data yet."""
        super().__init__()
        self._histogram: np.ndarray | None = None
        self.setMinimumHeight(MIN_HEIGHT)

    def sizeHint(self) -> QSize:
        """Suggest a reasonable default size for layouts."""
        return QSize(200, MIN_HEIGHT)

    def update_histogram(self, histogram: np.ndarray) -> None:
        """Store the latest histogram and trigger a repaint.

        Called from LiveViewController.histogram_ready, delivered safely
        onto this widget's own (main) thread by Qt's queued-connection
        machinery, since the signal originates on the live-view worker
        thread.
        """
        self._histogram = histogram
        self.update()

    def paintEvent(self, event) -> None:
        """Draw the histogram as vertical bars scaled to the tallest bin.

        Scaling to the current frame's own tallest bin (rather than a
        fixed 0-1 range) is deliberate -- a real photo's luminance values
        cluster into a handful of bins, so an absolute scale would render
        as a nearly flat, unreadable line. This matches how camera and
        photo-editor histograms conventionally display: shape, not
        absolute magnitude, is what the user reads off it.
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND_COLOR)

        if self._histogram is None or self._histogram.size == 0:
            painter.end()
            return

        peak = float(self._histogram.max())
        if peak <= 0:
            painter.end()
            return

        width = self.width()
        height = self.height()
        bin_count = self._histogram.size
        bar_width = width / bin_count

        painter.setPen(Qt.NoPen)
        painter.setBrush(BAR_COLOR)

        for i, value in enumerate(self._histogram):
            bar_height = (float(value) / peak) * height
            x = i * bar_width
            y = height - bar_height
            painter.drawRect(
                int(x), int(y), max(1, int(bar_width) + 1), int(bar_height)
            )

        painter.end()

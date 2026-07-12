"""Timeline and playback control widgets for the main window.

Placeholder only — no real Timeline data model exists yet (that's Phase 6).
This gives the main window's bottom section its final shape so the full
Phase 5 skeleton is visible, without pretending there's real frame data or
working playback yet.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class TimelineStrip(QWidget):
    """Placeholder for the frame-thumbnail timeline strip."""

    def __init__(self) -> None:
        """Build the timeline strip placeholder."""
        super().__init__()
        self.setFixedHeight(100)
        self.setStyleSheet("border: 1px solid gray;")

        layout = QHBoxLayout(self)
        label = QLabel("Timeline")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class PlaybackControls(QWidget):
    """Placeholder playback control bar (Play/Pause/Loop/speed)."""

    def __init__(self) -> None:
        """Build the playback controls bar."""
        super().__init__()
        self.setFixedHeight(50)
        self.setStyleSheet("border: 1px solid gray;")

        layout = QHBoxLayout(self)

        self.play_button = QPushButton("Play")
        self.loop_button = QPushButton("Loop")
        self.loop_button.setCheckable(True)

        layout.addWidget(self.play_button)
        layout.addWidget(self.loop_button)
        layout.addStretch()

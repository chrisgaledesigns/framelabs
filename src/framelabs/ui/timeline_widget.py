"""Timeline and playback control widgets for the main window.

TimelineStrip remains a placeholder -- the real frame-thumbnail Timeline UI
is Phase 6 work. PlaybackControls now exposes real, wired widgets for
Feature 7, Playback -- Play/Pause, Loop, and a speed selector -- driven
externally by MainWindow against the real PlaybackController and
PlaybackSettings.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from framelabs.timeline.playback import PLAYBACK_SPEEDS


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
    """Playback control bar for Feature 7: Play/Pause, Loop, speed.

    This widget only exposes raw controls -- it holds no PlaybackSettings
    or PlaybackController of its own. MainWindow reads and writes
    self.play_button, self.loop_button, and self.speed_combo directly and
    owns all the real playback wiring, consistent with how the rest of the
    UI layer stays "dumb" per the Developer Handbook (UI calls
    services/controllers, never owns application behavior itself).
    """

    def __init__(self) -> None:
        """Build the playback controls bar."""
        super().__init__()
        self.setFixedHeight(50)
        self.setStyleSheet("border: 1px solid gray;")

        layout = QHBoxLayout(self)

        self.play_button = QPushButton("Play")
        self.loop_button = QPushButton("Loop")
        self.loop_button.setCheckable(True)

        self.speed_combo = QComboBox()
        for speed in PLAYBACK_SPEEDS:
            self.speed_combo.addItem(f"{speed}%", userData=speed)
        # PLAYBACK_SPEEDS is (25, 50, 100, 200) -- default to 100%.
        self.speed_combo.setCurrentIndex(PLAYBACK_SPEEDS.index(100))

        layout.addWidget(self.play_button)
        layout.addWidget(self.loop_button)
        layout.addWidget(self.speed_combo)
        layout.addStretch()

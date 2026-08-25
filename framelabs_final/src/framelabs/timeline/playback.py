"""Playback settings for FrameLabs' Feature 7, Playback.

Pure data/logic module, per the Developer Handbook -- no Qt/UI code and no
timer logic. The actual QTimer-driven playback loop lives in
ui/playback_controller.py; this module only defines what playback *means*:
whether it's running, at what speed, and whether it loops.
"""

from __future__ import annotations

from dataclasses import dataclass

# Feature Spec Feature 7's four supported playback speeds, as percentages
# of the project's native FPS.
PLAYBACK_SPEEDS = (25, 50, 100, 200)


@dataclass
class PlaybackSettings:
    """User-adjustable settings for Feature 7, Playback.

    Attributes:
        is_playing: Whether playback is currently running.
        speed_percent: Playback speed as a percentage of the project's
            native FPS -- one of PLAYBACK_SPEEDS (25, 50, 100, 200).
        loop: Whether playback wraps back to the first frame after
            reaching the last one, instead of stopping there.
    """

    is_playing: bool = False
    speed_percent: int = 100
    loop: bool = False

    def interval_ms(self, project_fps: int) -> int:
        """Return the QTimer interval, in milliseconds, for one frame step
        at the current speed.

        Args:
            project_fps: The project's native frames-per-second.

        Returns:
            Milliseconds between frame advances. E.g. at 12 fps and 100%
            speed, ~83ms; at 200% speed, ~42ms (twice as fast); at 25%
            speed, ~333ms (quarter as fast).

        Raises:
            ValueError: If project_fps is not positive.
        """
        if project_fps <= 0:
            raise ValueError("project_fps must be > 0")
        base_interval = 1000.0 / project_fps
        return round(base_interval * (100.0 / self.speed_percent))

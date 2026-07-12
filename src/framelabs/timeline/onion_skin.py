"""Onion Skin settings and opacity falloff logic for FrameLabs.

Pure data/logic module, per the Developer Handbook -- no file I/O and no
Qt/UI code. Reading frame image bytes off disk belongs to a dedicated UI
controller (background thread); the actual overlay rendering belongs to
ui/live_view_widget.py. This module only defines what onion skin *means*:
how many frames on each side, at what opacity, tinted what color.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OnionSkinSettings:
    """User-adjustable settings for Feature 6, Onion Skin.

    Attributes:
        enabled: Whether onion skin overlays are currently shown.
        opacity: Base opacity (0.0-1.0) for the nearest frame on each side.
            Falls off toward zero for frames further away -- see
            opacity_for_distance().
        previous_count: How many frames before the current one to overlay.
        next_count: How many frames after the current one to overlay.
        previous_tint: Hex color (e.g. "#3399ff") tinting previous frames.
        next_tint: Hex color tinting next frames.
    """

    enabled: bool = False
    opacity: float = 0.35
    previous_count: int = 2
    next_count: int = 1
    previous_tint: str = "#3399ff"
    next_tint: str = "#ff3333"

    def opacity_for_distance(self, distance: int) -> float:
        """Return the effective opacity for a frame `distance` steps away.

        distance=1 is the nearest frame (rendered at the full `opacity`);
        each step further away halves it -- e.g. opacity=0.4 gives
        0.4, 0.2, 0.1, ... This keeps nearer frames most visible, matching
        Feature 6's opacity-falloff requirement, without a separate
        falloff setting to tune.

        Args:
            distance: 1-indexed distance from the current frame.

        Returns:
            The opacity to render that frame at.

        Raises:
            ValueError: If distance is less than 1.
        """
        if distance < 1:
            raise ValueError("distance must be >= 1")
        return self.opacity * (0.5 ** (distance - 1))

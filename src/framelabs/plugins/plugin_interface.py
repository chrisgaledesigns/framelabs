"""Plugin interface all FrameLabs plugins must implement.

Every plugin implements the same interface -- same convention as
CameraInterface (see Developer Handbook's Camera Rules) -- so
PluginManager never needs to know anything about a specific plugin's
internals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PluginBase(ABC):
    """Base class every FrameLabs plugin must subclass exactly once."""

    #: Human-readable name shown in logs. Subclasses should override.
    name: str = "Unnamed Plugin"

    @abstractmethod
    def activate(self) -> None:
        """Run the plugin's startup logic.

        Raise any exception to signal failure -- PluginManager catches it,
        disables this plugin, and continues loading/running the rest of
        the application, per the Handbook's Plugin System rule.
        """

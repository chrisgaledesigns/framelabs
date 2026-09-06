"""Concrete Command subclasses for the Composite workspace's layer stack.

Per core/command.py's own module docstring, concrete commands live
alongside the state they wrap, not in core/ itself.

Only structural changes to the stack -- adding, removing, reordering a
layer -- go through undo/redo here. Per-layer opacity/blend-mode/
visibility tweaks are applied directly by CompositeWorkspace's caller
(main_window.py) without a Command, the same way dragging a volume slider
elsewhere in the app doesn't produce one undo entry per pixel of drag --
see main_window.py's _apply_composite_layer_edit() docstring for that
reasoning. Every entry here is drawn from Project.overlays (never copies
a new file), so unlike AddAssetCommand/RemoveAssetCommand in
asset_commands.py, no on-disk backup is ever needed for undo: the
overlay file itself is untouched either way.

Every command here follows the standard mutate -> save -> publish order
(see the Developer Handbook / this project's hand-off conventions),
publishing COMPOSITE_LAYER_ADDED, COMPOSITE_LAYER_REMOVED, or
COMPOSITE_LAYERS_REORDERED on both do() and the appropriate inverse on
undo() -- e.g. RemoveCompositeLayerCommand.undo() publishes
COMPOSITE_LAYER_ADDED, mirroring RemoveAssetCommand.undo()'s own
AUDIO_ADDED/REFERENCE_ADDED/OVERLAY_ADDED pattern in asset_commands.py.
Nothing subscribes to these yet as of this writing, but publishing them
now keeps this module consistent with every other command in the
codebase rather than being a silent, undocumented exception.

SetWorkingRangeCommand is a different shape from the three layer-stack
commands above -- it doesn't touch composite_layers at all, it sets
Project.working_range (the Composite workspace's NLA-style strip
editor's in/out trim). It lives here rather than in a new module because
it's driven by the same Composite workspace UI and follows the identical
mutate -> save -> publish -> undo pattern, publishing
WORKING_RANGE_CHANGED. Per this feature's own design (see the project
hand-off), trimming is always non-destructive: no Frame is ever removed
or altered, only the shared Project.working_range value changes, which
both the Composite workspace's strip editor and the Capture tab's
TimelineWidget read from the same Project to decide what to render as
out-of-range.
"""

from __future__ import annotations

import logging

from framelabs.core.command import Command
from framelabs.core.event_bus import EventBus
from framelabs.project.project import CompositeLayer, Project
from framelabs.project.serializer import ProjectSerializer

logger = logging.getLogger(__name__)


class AddCompositeLayerCommand(Command):
    """Append a new layer to the top of the Composite workspace's stack."""

    def __init__(self, project: Project, event_bus: EventBus, source: str) -> None:
        """Prepare to add a layer drawing from `source`.

        Args:
            project: The active project.
            event_bus: The event bus to publish COMPOSITE_LAYER_ADDED /
                COMPOSITE_LAYER_REMOVED on, matching every other
                project-mutating command's do()/undo() -- see
                asset_commands.py for the same pattern.
            source: Relative path of an existing Project.overlays entry,
                e.g. "overlays/vignette.png".
        """
        self._project = project
        self._event_bus = event_bus
        self._layer = CompositeLayer(source=source)

    @property
    def description(self) -> str:
        return f"Add Composite Layer {self._layer.source}"

    def do(self) -> None:
        self._project.composite_layers.append(self._layer)
        ProjectSerializer.save(self._project)
        self._event_bus.publish("COMPOSITE_LAYER_ADDED", {"source": self._layer.source})

    def undo(self) -> None:
        self._project.composite_layers.remove(self._layer)
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "COMPOSITE_LAYER_REMOVED", {"source": self._layer.source}
        )


class RemoveCompositeLayerCommand(Command):
    """Remove a layer from the Composite workspace's stack.

    Backs up the layer's settings (opacity/blend_mode/visible), not just
    its source path, so undo restores exactly what was removed rather
    than a freshly-defaulted layer at the same source.
    """

    def __init__(self, project: Project, event_bus: EventBus, index: int) -> None:
        """Prepare to remove the layer currently at `index`.

        Args:
            project: The active project.
            event_bus: The event bus to publish COMPOSITE_LAYER_REMOVED /
                COMPOSITE_LAYER_ADDED on, matching AddCompositeLayerCommand.
            index: Position of the layer to remove within
                project.composite_layers at the time this command is
                constructed. Captured immediately (not re-looked-up in
                do()) since the caller determines it from the same list
                state this command will act on.
        """
        self._project = project
        self._event_bus = event_bus
        self._index = index
        self._removed_layer: CompositeLayer | None = None

    @property
    def description(self) -> str:
        source = (
            self._removed_layer.source
            if self._removed_layer is not None
            else self._project.composite_layers[self._index].source
        )
        return f"Remove Composite Layer {source}"

    def do(self) -> None:
        if self._removed_layer is None:
            self._removed_layer = self._project.composite_layers[self._index]
        self._project.composite_layers.pop(self._index)
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "COMPOSITE_LAYER_REMOVED", {"source": self._removed_layer.source}
        )

    def undo(self) -> None:
        """Reinsert the removed layer at its original index.

        Raises:
            RuntimeError: If called before do() has ever run.
        """
        if self._removed_layer is None:
            raise RuntimeError(
                "RemoveCompositeLayerCommand.undo() called before do() "
                "-- nothing to undo yet."
            )
        self._project.composite_layers.insert(self._index, self._removed_layer)
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "COMPOSITE_LAYER_ADDED", {"source": self._removed_layer.source}
        )


class ReorderCompositeLayerCommand(Command):
    """Move one layer from `old_index` to `new_index` within the stack.

    Used by CompositeWorkspace's up/down reorder buttons -- one command
    per press, matching ReorderFramesCommand's granularity in
    capture/commands.py rather than the drag-and-drop continuous-position
    granularity TimelineWidget uses for frames.
    """

    def __init__(
        self, project: Project, event_bus: EventBus, old_index: int, new_index: int
    ) -> None:
        self._project = project
        self._event_bus = event_bus
        self._old_index = old_index
        self._new_index = new_index

    @property
    def description(self) -> str:
        return f"Reorder Composite Layer {self._old_index} -> {self._new_index}"

    def do(self) -> None:
        layers = self._project.composite_layers
        layer = layers.pop(self._old_index)
        layers.insert(self._new_index, layer)
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "COMPOSITE_LAYERS_REORDERED",
            {"old_index": self._old_index, "new_index": self._new_index},
        )

    def undo(self) -> None:
        layers = self._project.composite_layers
        layer = layers.pop(self._new_index)
        layers.insert(self._old_index, layer)
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "COMPOSITE_LAYERS_REORDERED",
            {"old_index": self._new_index, "new_index": self._old_index},
        )


class SetWorkingRangeCommand(Command):
    """Set the Composite workspace's NLA-style strip trim (in/out points).

    Non-destructive: only Project.working_range changes. No Frame is ever
    removed, reordered, or otherwise touched, and no on-disk backup is
    needed for undo since nothing irreplaceable is ever at risk -- undo
    just restores the previous (start, end) tuple (or None, if the strip
    was untrimmed before this command ran).
    """

    def __init__(
        self,
        project: Project,
        event_bus: EventBus,
        new_range: tuple[int, int] | None,
    ) -> None:
        """Prepare to set the working range to `new_range`.

        Args:
            project: The active project.
            event_bus: The event bus to publish WORKING_RANGE_CHANGED on,
                matching every other project-mutating command's
                do()/undo().
            new_range: The (start_frame, end_frame) inclusive range to
                trim to, by Frame.number, or None to clear the trim and
                mark the whole sequence in-range again.

        Raises:
            ValueError: If new_range is given but start_frame is greater
                than end_frame -- caught here, before do() ever runs,
                rather than left to produce a backwards/empty range.
        """
        if new_range is not None and new_range[0] > new_range[1]:
            raise ValueError(
                f"working_range start ({new_range[0]}) cannot be greater "
                f"than end ({new_range[1]})"
            )
        self._project = project
        self._event_bus = event_bus
        self._new_range = new_range
        self._old_range = project.working_range

    @property
    def description(self) -> str:
        if self._new_range is None:
            return "Clear Composite Working Range"
        return f"Set Composite Working Range {self._new_range[0]}-{self._new_range[1]}"

    def do(self) -> None:
        self._project.working_range = self._new_range
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "WORKING_RANGE_CHANGED", {"working_range": self._new_range}
        )

    def undo(self) -> None:
        self._project.working_range = self._old_range
        ProjectSerializer.save(self._project)
        self._event_bus.publish(
            "WORKING_RANGE_CHANGED", {"working_range": self._old_range}
        )

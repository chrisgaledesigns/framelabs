"""Concrete Command subclasses for the Composite workspace's layer stack.

Per core/command.py's own module docstring, concrete commands live
alongside the state they wrap, not in core/ itself.

Only structural changes to the stack -- adding, removing, reordering a
layer -- go through undo/redo here. Per-layer opacity/blend-mode/
visibility tweaks are applied directly by CompositeWorkspace's caller
(main_window.py) without a Command, the same way dragging a volume slider
elsewhere in the app doesn't produce one undo entry per pixel of drag --
see main_window.py's _on_composite_layer_changed() docstring for that
reasoning. Every entry here is drawn from Project.overlays (never copies
a new file), so unlike AddAssetCommand/RemoveAssetCommand in
asset_commands.py, no on-disk backup is ever needed for undo: the
overlay file itself is untouched either way.
"""

from __future__ import annotations

import logging

from framelabs.core.command import Command
from framelabs.project.project import CompositeLayer, Project
from framelabs.project.serializer import ProjectSerializer

logger = logging.getLogger(__name__)


class AddCompositeLayerCommand(Command):
    """Append a new layer to the top of the Composite workspace's stack."""

    def __init__(self, project: Project, source: str) -> None:
        """Prepare to add a layer drawing from `source`.

        Args:
            project: The active project.
            source: Relative path of an existing Project.overlays entry,
                e.g. "overlays/vignette.png".
        """
        self._project = project
        self._layer = CompositeLayer(source=source)

    @property
    def description(self) -> str:
        return f"Add Composite Layer {self._layer.source}"

    def do(self) -> None:
        self._project.composite_layers.append(self._layer)
        ProjectSerializer.save(self._project)

    def undo(self) -> None:
        self._project.composite_layers.remove(self._layer)
        ProjectSerializer.save(self._project)


class RemoveCompositeLayerCommand(Command):
    """Remove a layer from the Composite workspace's stack.

    Backs up the layer's settings (opacity/blend_mode/visible), not just
    its source path, so undo restores exactly what was removed rather
    than a freshly-defaulted layer at the same source.
    """

    def __init__(self, project: Project, index: int) -> None:
        """Prepare to remove the layer currently at `index`.

        Args:
            project: The active project.
            index: Position of the layer to remove within
                project.composite_layers at the time this command is
                constructed. Captured immediately (not re-looked-up in
                do()) since the caller determines it from the same list
                state this command will act on.
        """
        self._project = project
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


class ReorderCompositeLayerCommand(Command):
    """Move one layer from `old_index` to `new_index` within the stack.

    Used by CompositeWorkspace's up/down reorder buttons -- one command
    per press, matching ReorderFramesCommand's granularity in
    capture/commands.py rather than the drag-and-drop continuous-position
    granularity TimelineWidget uses for frames.
    """

    def __init__(self, project: Project, old_index: int, new_index: int) -> None:
        self._project = project
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

    def undo(self) -> None:
        layers = self._project.composite_layers
        layer = layers.pop(self._new_index)
        layers.insert(self._old_index, layer)
        ProjectSerializer.save(self._project)

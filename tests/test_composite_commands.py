"""Tests for framelabs.project.composite_commands."""

import pytest

from framelabs.core.event_bus import EventBus
from framelabs.core.undo_manager import UndoManager
from framelabs.project.composite_commands import (
    AddCompositeLayerCommand,
    RemoveCompositeLayerCommand,
    ReorderCompositeLayerCommand,
)
from framelabs.project.creator import create_new_project


def _make_project(tmp_path):
    project = create_new_project(
        name="Test Project", parent_dir=tmp_path, fps=12, resolution=(1920, 1080)
    )
    # Layers always reference an existing overlay entry -- populate a few
    # so commands under test have real sources to point at.
    project.overlays = [
        "overlays/vignette.png",
        "overlays/grain.png",
        "overlays/wash.png",
    ]
    return project


# ---------------------------------------------------------------------------
# AddCompositeLayerCommand
# ---------------------------------------------------------------------------


def test_add_composite_layer_command_do_appends_layer(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()

    command = AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png")
    command.do()

    assert len(project.composite_layers) == 1
    assert project.composite_layers[0].source == "overlays/vignette.png"


def test_add_composite_layer_command_appends_to_top_of_stack(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()

    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()

    assert [layer.source for layer in project.composite_layers] == [
        "overlays/vignette.png",
        "overlays/grain.png",
    ]


def test_add_composite_layer_command_undo_removes_it(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    command = AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png")
    command.do()

    command.undo()

    assert project.composite_layers == []


def test_add_composite_layer_command_redo_readds_it(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    command = AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png")
    command.do()
    command.undo()

    command.do()

    assert len(project.composite_layers) == 1
    assert project.composite_layers[0].source == "overlays/vignette.png"


def test_add_composite_layer_command_description(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    command = AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png")
    assert command.description == "Add Composite Layer overlays/vignette.png"


def test_add_composite_layer_command_new_layer_has_default_settings(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()

    layer = project.composite_layers[0]
    assert layer.opacity == pytest.approx(1.0)
    assert layer.visible is True


def test_add_composite_layer_command_do_publishes_composite_layer_added(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    received = []
    event_bus.subscribe("COMPOSITE_LAYER_ADDED", received.append)

    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()

    assert received == [{"source": "overlays/vignette.png"}]


def test_add_composite_layer_command_undo_publishes_composite_layer_removed(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    command = AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png")
    command.do()
    received = []
    event_bus.subscribe("COMPOSITE_LAYER_REMOVED", received.append)

    command.undo()

    assert received == [{"source": "overlays/vignette.png"}]


# ---------------------------------------------------------------------------
# RemoveCompositeLayerCommand
# ---------------------------------------------------------------------------


def test_remove_composite_layer_command_do_removes_at_index(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()

    RemoveCompositeLayerCommand(project, event_bus, 0).do()

    assert [layer.source for layer in project.composite_layers] == [
        "overlays/grain.png"
    ]


def test_remove_composite_layer_command_undo_restores_at_original_index(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/wash.png").do()

    command = RemoveCompositeLayerCommand(project, event_bus, 1)
    command.do()
    command.undo()

    assert [layer.source for layer in project.composite_layers] == [
        "overlays/vignette.png",
        "overlays/grain.png",
        "overlays/wash.png",
    ]


def test_remove_composite_layer_command_undo_restores_exact_settings(tmp_path):
    """Undo must restore the removed layer's opacity/blend_mode/visible,
    not a freshly-defaulted layer at the same source."""
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    layer = project.composite_layers[0]
    layer.opacity = 0.4
    layer.blend_mode = "multiply"
    layer.visible = False

    command = RemoveCompositeLayerCommand(project, event_bus, 0)
    command.do()
    command.undo()

    restored = project.composite_layers[0]
    assert restored.opacity == pytest.approx(0.4)
    assert restored.blend_mode == "multiply"
    assert restored.visible is False


def test_remove_composite_layer_command_undo_before_do_raises(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()

    command = RemoveCompositeLayerCommand(project, event_bus, 0)

    with pytest.raises(RuntimeError):
        command.undo()


def test_remove_composite_layer_command_description_before_do(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()

    command = RemoveCompositeLayerCommand(project, event_bus, 0)

    assert command.description == "Remove Composite Layer overlays/vignette.png"


def test_remove_composite_layer_command_description_after_do(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    command = RemoveCompositeLayerCommand(project, event_bus, 0)
    command.do()

    assert command.description == "Remove Composite Layer overlays/vignette.png"


def test_remove_composite_layer_command_do_publishes_composite_layer_removed(
    tmp_path,
):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    received = []
    event_bus.subscribe("COMPOSITE_LAYER_REMOVED", received.append)

    RemoveCompositeLayerCommand(project, event_bus, 0).do()

    assert received == [{"source": "overlays/vignette.png"}]


def test_remove_composite_layer_command_undo_publishes_composite_layer_added(
    tmp_path,
):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    command = RemoveCompositeLayerCommand(project, event_bus, 0)
    command.do()
    received = []
    event_bus.subscribe("COMPOSITE_LAYER_ADDED", received.append)

    command.undo()

    assert received == [{"source": "overlays/vignette.png"}]


# ---------------------------------------------------------------------------
# ReorderCompositeLayerCommand
# ---------------------------------------------------------------------------


def test_reorder_composite_layer_command_do_moves_layer(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/wash.png").do()

    ReorderCompositeLayerCommand(project, event_bus, 0, 2).do()

    assert [layer.source for layer in project.composite_layers] == [
        "overlays/grain.png",
        "overlays/wash.png",
        "overlays/vignette.png",
    ]


def test_reorder_composite_layer_command_undo_restores_original_order(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/wash.png").do()

    command = ReorderCompositeLayerCommand(project, event_bus, 0, 2)
    command.do()
    command.undo()

    assert [layer.source for layer in project.composite_layers] == [
        "overlays/vignette.png",
        "overlays/grain.png",
        "overlays/wash.png",
    ]


def test_reorder_composite_layer_command_description(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()

    command = ReorderCompositeLayerCommand(project, event_bus, 0, 1)

    assert command.description == "Reorder Composite Layer 0 -> 1"


def test_reorder_composite_layer_command_do_publishes_composite_layers_reordered(
    tmp_path,
):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()
    received = []
    event_bus.subscribe("COMPOSITE_LAYERS_REORDERED", received.append)

    ReorderCompositeLayerCommand(project, event_bus, 0, 1).do()

    assert received == [{"old_index": 0, "new_index": 1}]


def test_reorder_composite_layer_command_undo_publishes_inverse_indices(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png").do()
    AddCompositeLayerCommand(project, event_bus, "overlays/grain.png").do()
    command = ReorderCompositeLayerCommand(project, event_bus, 0, 1)
    command.do()
    received = []
    event_bus.subscribe("COMPOSITE_LAYERS_REORDERED", received.append)

    command.undo()

    assert received == [{"old_index": 1, "new_index": 0}]


# ---------------------------------------------------------------------------
# Full cycle through the real UndoManager
# ---------------------------------------------------------------------------


def test_add_reorder_remove_via_undo_manager_full_cycle(tmp_path):
    project = _make_project(tmp_path)
    event_bus = EventBus()
    manager = UndoManager()

    manager.execute(
        AddCompositeLayerCommand(project, event_bus, "overlays/vignette.png")
    )
    manager.execute(AddCompositeLayerCommand(project, event_bus, "overlays/grain.png"))
    assert [layer.source for layer in project.composite_layers] == [
        "overlays/vignette.png",
        "overlays/grain.png",
    ]

    manager.execute(ReorderCompositeLayerCommand(project, event_bus, 0, 1))
    assert [layer.source for layer in project.composite_layers] == [
        "overlays/grain.png",
        "overlays/vignette.png",
    ]

    manager.execute(RemoveCompositeLayerCommand(project, event_bus, 0))
    assert [layer.source for layer in project.composite_layers] == [
        "overlays/vignette.png",
    ]
    assert manager.can_undo() is True

    manager.undo()  # undo remove
    assert [layer.source for layer in project.composite_layers] == [
        "overlays/grain.png",
        "overlays/vignette.png",
    ]

    manager.undo()  # undo reorder
    assert [layer.source for layer in project.composite_layers] == [
        "overlays/vignette.png",
        "overlays/grain.png",
    ]

    assert manager.can_redo() is True
    manager.redo()  # redo reorder
    assert [layer.source for layer in project.composite_layers] == [
        "overlays/grain.png",
        "overlays/vignette.png",
    ]

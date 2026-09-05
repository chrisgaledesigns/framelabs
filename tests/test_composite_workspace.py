"""Tests for framelabs.ui.composite_workspace.CompositeWorkspace.

Uses real Project/CompositeLayer objects, matching this repo's existing
convention of testing real behavior rather than mocking the thing being
tested (see test_project_browser_widget.py).
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from framelabs.project.project import CompositeLayer, Project
from framelabs.ui.composite_workspace import CompositeWorkspace


def _make_project(
    tmp_path: Path, layers: list[CompositeLayer] | None = None
) -> Project:
    project_path = tmp_path / "MyFilm"
    project_path.mkdir()
    return Project(
        version=4,
        name="MyFilm",
        fps=12,
        resolution=(1920, 1080),
        camera_model=None,
        camera_lens=None,
        frames=[],
        overlays=["overlays/vignette.png", "overlays/grain.png"],
        composite_layers=layers or [],
        project_path=project_path,
    )


# ---------------------------------------------------------------------------
# No project / empty states
# ---------------------------------------------------------------------------


def test_no_project_shows_no_project_open_message(qtbot):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)

    assert widget.preview_label.text() == "No project open"


def test_no_project_disables_add_layer_button(qtbot):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)

    assert widget.add_layer_button.isEnabled() is False


def test_project_with_no_overlays_disables_add_layer_with_tooltip(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path)
    project.overlays = []

    widget.set_project(project)

    assert widget.add_layer_button.isEnabled() is False
    assert widget.add_layer_button.toolTip() != ""


def test_project_with_overlays_enables_add_layer_with_no_tooltip(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path)

    widget.set_project(project)

    assert widget.add_layer_button.isEnabled() is True
    assert widget.add_layer_button.toolTip() == ""


def test_overlay_combo_populated_from_project_overlays(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path)

    widget.set_project(project)

    assert widget.overlay_combo.count() == 2
    assert widget.overlay_combo.itemData(0) == "overlays/vignette.png"
    assert widget.overlay_combo.itemData(1) == "overlays/grain.png"


# ---------------------------------------------------------------------------
# Layer list population and reversed display order
# ---------------------------------------------------------------------------


def test_layer_list_shows_layers_in_reversed_order(qtbot, tmp_path):
    """List row 0 is the top of the stack (last element) -- see this
    module's own docstring for why the display is reversed from
    Project.composite_layers' bottom-to-top storage order."""
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [
        CompositeLayer(source="overlays/vignette.png"),
        CompositeLayer(source="overlays/grain.png"),
    ]
    project = _make_project(tmp_path, layers)

    widget.set_project(project)

    assert widget.layer_list.count() == 2
    assert widget.layer_list.item(0).text() == "grain.png"
    assert widget.layer_list.item(1).text() == "vignette.png"


def test_layer_list_checkbox_reflects_visibility(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [
        CompositeLayer(source="overlays/vignette.png", visible=True),
        CompositeLayer(source="overlays/grain.png", visible=False),
    ]
    project = _make_project(tmp_path, layers)

    widget.set_project(project)

    # Row 0 == grain.png (visible=False), row 1 == vignette.png (visible=True)
    assert widget.layer_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert widget.layer_list.item(1).checkState() == Qt.CheckState.Checked


def test_settings_group_disabled_when_no_layer_selected(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path, [CompositeLayer(source="overlays/vignette.png")])

    widget.set_project(project)

    assert widget._settings_group.isEnabled() is False


# ---------------------------------------------------------------------------
# Row <-> layer-index conversion (the one place the reversal happens)
# ---------------------------------------------------------------------------


def test_list_row_to_layer_index_reverses_correctly(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [
        CompositeLayer(source="overlays/a.png"),
        CompositeLayer(source="overlays/b.png"),
        CompositeLayer(source="overlays/c.png"),
    ]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)

    # 3 layers: row 0 (top of list) -> index 2 (last in storage list)
    assert widget._list_row_to_layer_index(0) == 2
    assert widget._list_row_to_layer_index(1) == 1
    assert widget._list_row_to_layer_index(2) == 0


# ---------------------------------------------------------------------------
# Signals: add / remove / reorder
# ---------------------------------------------------------------------------


def test_add_layer_button_emits_add_layer_requested_with_combo_source(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    project = _make_project(tmp_path)
    widget.set_project(project)
    widget.overlay_combo.setCurrentIndex(1)  # overlays/grain.png

    with qtbot.waitSignal(widget.add_layer_requested, timeout=1000) as blocker:
        widget.add_layer_button.click()

    assert blocker.args == ["overlays/grain.png"]


def test_remove_layer_button_emits_remove_layer_requested_with_correct_index(
    qtbot, tmp_path
):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [
        CompositeLayer(source="overlays/vignette.png"),
        CompositeLayer(source="overlays/grain.png"),
    ]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)
    widget.layer_list.setCurrentRow(0)  # row 0 == grain.png == index 1

    with qtbot.waitSignal(widget.remove_layer_requested, timeout=1000) as blocker:
        widget.remove_layer_button.click()

    assert blocker.args == [1]


def test_move_up_emits_move_layer_requested_toward_top_of_stack(qtbot, tmp_path):
    """'Up' in the list (toward the front) means a *higher* index in
    composite_layers, since the list is displayed reversed."""
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [
        CompositeLayer(source="overlays/vignette.png"),
        CompositeLayer(source="overlays/grain.png"),
    ]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)
    widget.layer_list.setCurrentRow(1)  # row 1 == vignette.png == index 0

    with qtbot.waitSignal(widget.move_layer_requested, timeout=1000) as blocker:
        widget.move_up_button.click()

    assert blocker.args == [0, 1]


def test_move_down_at_bottom_of_stack_does_not_emit(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [CompositeLayer(source="overlays/vignette.png")]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)
    widget.layer_list.setCurrentRow(0)  # only layer, index 0 -- already at bottom

    with qtbot.assertNotEmitted(widget.move_layer_requested):
        widget.move_down_button.click()


def test_move_up_at_top_of_stack_does_not_emit(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [CompositeLayer(source="overlays/vignette.png")]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)
    widget.layer_list.setCurrentRow(0)

    with qtbot.assertNotEmitted(widget.move_layer_requested):
        widget.move_up_button.click()


# ---------------------------------------------------------------------------
# Signals: visibility / opacity / blend mode
# ---------------------------------------------------------------------------


def test_toggling_checkbox_emits_layer_visibility_toggled(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [CompositeLayer(source="overlays/vignette.png", visible=True)]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)

    item = widget.layer_list.item(0)

    with qtbot.waitSignal(widget.layer_visibility_toggled, timeout=1000) as blocker:
        item.setCheckState(Qt.CheckState.Unchecked)

    assert blocker.args == [0, False]


def test_selecting_layer_populates_opacity_and_blend_mode_controls(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [
        CompositeLayer(
            source="overlays/vignette.png", opacity=0.4, blend_mode="multiply"
        )
    ]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)

    widget.layer_list.setCurrentRow(0)

    assert widget._settings_group.isEnabled() is True
    assert widget.opacity_spin.value() == 40.0
    assert widget.blend_mode_combo.currentData() == "multiply"


def test_changing_opacity_spin_emits_layer_opacity_changed(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [CompositeLayer(source="overlays/vignette.png", opacity=1.0)]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)
    widget.layer_list.setCurrentRow(0)

    with qtbot.waitSignal(widget.layer_opacity_changed, timeout=1000) as blocker:
        widget.opacity_spin.setValue(60.0)

    assert blocker.args == [0, 0.6]


def test_changing_blend_mode_combo_emits_layer_blend_mode_changed(qtbot, tmp_path):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [CompositeLayer(source="overlays/vignette.png", blend_mode="normal")]
    project = _make_project(tmp_path, layers)
    widget.set_project(project)
    widget.layer_list.setCurrentRow(0)

    with qtbot.waitSignal(widget.layer_blend_mode_changed, timeout=1000) as blocker:
        widget.blend_mode_combo.setCurrentIndex(
            widget.blend_mode_combo.findData("screen")
        )

    assert blocker.args == [0, "screen"]


def test_refreshing_layer_list_does_not_spuriously_emit_visibility_toggled(
    qtbot, tmp_path
):
    """Guards the `_refreshing` flag: rebuilding the list on set_project()
    must not be misread as the user editing a layer."""
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)
    layers = [CompositeLayer(source="overlays/vignette.png", visible=True)]
    project = _make_project(tmp_path, layers)

    with qtbot.assertNotEmitted(widget.layer_visibility_toggled):
        widget.set_project(project)


# ---------------------------------------------------------------------------
# set_preview_pixmap
# ---------------------------------------------------------------------------


def test_set_preview_pixmap_none_shows_message(qtbot):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)

    widget.set_preview_pixmap(None, message="Capture at least one frame first")

    assert widget.preview_label.text() == "Capture at least one frame first"


def test_set_preview_pixmap_with_real_pixmap_clears_message(qtbot):
    widget = CompositeWorkspace()
    qtbot.addWidget(widget)

    pixmap = QPixmap(10, 10)
    pixmap.fill()

    widget.set_preview_pixmap(pixmap)

    assert widget.preview_label.text() == ""
    assert not widget.preview_label.pixmap().isNull()

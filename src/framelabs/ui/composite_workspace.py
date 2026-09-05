"""Composite workspace page for FrameLabs.

A third page alongside the editor and ExportPage, reached via
WorkspaceTabBar's "Composite" tab. Holds the layer-stack UI for
Project.composite_layers -- a project-wide effects stack (vignettes,
color washes, rough backgrounds) blended over every frame, per
CompositeLayer's own docstring in project/project.py.

Same "dumb widget, MainWindow owns behavior" split as ExportPage: this
page holds no Project of its own beyond what's needed to populate the
layer list and the "add from overlay" picker. MainWindow calls
set_project() every time the page is shown, recomputes the composited
preview via image_processing/compositor.py, and calls set_preview_pixmap()
-- this page never touches pixel data itself.

The layer list's top row is the top of the composite stack (the last
thing blended on, drawn frontmost) -- opposite of Project.composite_
layers' own bottom-to-top storage order, since that's how every layer
panel outside FrameLabs (Photoshop, Krita, DaVinci's own Fusion page)
reads. _list_row_to_layer_index()/_layer_index_to_list_row() are the one
place that reversal happens; everything else in this file thinks in
list-row terms only.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from framelabs.image_processing.compositor import BLEND_MODES
from framelabs.project.project import CompositeLayer, Project

_PREVIEW_MIN_WIDTH = 480
_PREVIEW_MIN_HEIGHT = 320

# Display label per blend mode, in BLEND_MODES' own order -- built once
# here rather than duplicating the mode list in _build_ui().
_BLEND_MODE_LABELS = {
    "normal": "Normal",
    "multiply": "Multiply",
    "screen": "Screen",
    "overlay": "Overlay",
    "add": "Add",
}


class CompositeWorkspace(QWidget):
    """Composite workspace: preview on the left, layer stack on the right."""

    # str is a project-relative overlay path, e.g. "overlays/vignette.png"
    add_layer_requested = Signal(str)
    remove_layer_requested = Signal(int)  # composite_layers index
    # old_index, new_index -- both in composite_layers terms already
    move_layer_requested = Signal(int, int)
    layer_visibility_toggled = Signal(int, bool)
    layer_opacity_changed = Signal(int, float)
    layer_blend_mode_changed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("compositeWorkspace")
        self._project: Project | None = None
        # Set while _refresh_layer_list() rebuilds the list/form so its
        # own itemChanged/valueChanged signals don't get reinterpreted
        # as the user editing a layer and re-emitted as bogus requests.
        self._refreshing = False
        self._build_ui()
        self.set_project(None)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(16)

        title_label = QLabel("COMPOSITE")
        title_label.setObjectName("panelTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title_label)

        body = QHBoxLayout()
        body.setSpacing(24)
        body.addLayout(self._build_preview_column(), 3)
        body.addLayout(self._build_layer_column(), 2)
        root.addLayout(body, 1)

    def _build_preview_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(10)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("compositePreview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(_PREVIEW_MIN_WIDTH, _PREVIEW_MIN_HEIGHT)
        self.preview_label.setFrameShape(QFrame.Shape.Box)
        self.preview_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        column.addWidget(self.preview_label, 1)

        return column

    def _build_layer_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(10)

        # "Add from Overlay" -- layers only ever draw from an existing
        # Project.overlays entry (see CompositeLayer's docstring), so
        # this is a picker over what's already in the project rather
        # than a file-browse dialog.
        add_row = QHBoxLayout()
        self.overlay_combo = QComboBox()
        self.add_layer_button = QPushButton("Add Layer")
        self.add_layer_button.clicked.connect(self._on_add_clicked)
        add_row.addWidget(self.overlay_combo, 1)
        add_row.addWidget(self.add_layer_button)
        column.addLayout(add_row)

        self.layer_list = QListWidget()
        self.layer_list.setObjectName("compositeLayerList")
        self.layer_list.itemChanged.connect(self._on_item_changed)
        self.layer_list.currentRowChanged.connect(self._on_current_row_changed)
        column.addWidget(self.layer_list, 1)

        reorder_row = QHBoxLayout()
        self.move_up_button = QPushButton("Move Up")
        self.move_down_button = QPushButton("Move Down")
        self.remove_layer_button = QPushButton("Remove Layer")
        self.move_up_button.clicked.connect(self._on_move_up_clicked)
        self.move_down_button.clicked.connect(self._on_move_down_clicked)
        self.remove_layer_button.clicked.connect(self._on_remove_clicked)
        reorder_row.addWidget(self.move_up_button)
        reorder_row.addWidget(self.move_down_button)
        reorder_row.addWidget(self.remove_layer_button)
        column.addLayout(reorder_row)

        settings_group = QGroupBox("Selected Layer")
        settings_layout = QFormLayout(settings_group)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.0, 100.0)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.valueChanged.connect(self._on_opacity_changed)
        settings_layout.addRow("Opacity:", self.opacity_spin)

        self.blend_mode_combo = QComboBox()
        for mode in BLEND_MODES:
            self.blend_mode_combo.addItem(_BLEND_MODE_LABELS[mode], userData=mode)
        self.blend_mode_combo.currentIndexChanged.connect(self._on_blend_mode_changed)
        settings_layout.addRow("Blend Mode:", self.blend_mode_combo)

        column.addWidget(settings_group)
        self._settings_group = settings_group
        self._settings_group.setEnabled(False)

        return column

    # -- selection/index helpers --------------------------------------

    def _list_row_to_layer_index(self, row: int) -> int:
        """List row 0 is the top of the stack (last element); see this
        module's docstring for why the list is shown reversed."""
        count = self.layer_list.count()
        return count - 1 - row

    def _current_layer_index(self) -> int | None:
        row = self.layer_list.currentRow()
        if row < 0:
            return None
        return self._list_row_to_layer_index(row)

    # -- user-interaction handlers --------------------------------------

    def _on_add_clicked(self) -> None:
        source = self.overlay_combo.currentData()
        if source:
            self.add_layer_requested.emit(source)

    def _on_remove_clicked(self) -> None:
        index = self._current_layer_index()
        if index is not None:
            self.remove_layer_requested.emit(index)

    def _on_move_up_clicked(self) -> None:
        # "Up" in the list (toward the top/front of the stack) means a
        # *higher* index in composite_layers, since the list is reversed.
        index = self._current_layer_index()
        if index is not None and index < self.layer_list.count() - 1:
            self.move_layer_requested.emit(index, index + 1)

    def _on_move_down_clicked(self) -> None:
        index = self._current_layer_index()
        if index is not None and index > 0:
            self.move_layer_requested.emit(index, index - 1)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._refreshing:
            return
        row = self.layer_list.row(item)
        index = self._list_row_to_layer_index(row)
        visible = item.checkState() == Qt.CheckState.Checked
        self.layer_visibility_toggled.emit(index, visible)

    def _on_current_row_changed(self, row: int) -> None:
        if self._refreshing:
            return
        index = self._current_layer_index()
        if index is None or self._project is None:
            self._settings_group.setEnabled(False)
            return
        layer = self._project.composite_layers[index]
        self._settings_group.setEnabled(True)
        self._refreshing = True
        self.opacity_spin.setValue(layer.opacity * 100.0)
        mode_row = self.blend_mode_combo.findData(layer.blend_mode)
        self.blend_mode_combo.setCurrentIndex(max(mode_row, 0))
        self._refreshing = False

    def _on_opacity_changed(self, value: float) -> None:
        if self._refreshing:
            return
        index = self._current_layer_index()
        if index is not None:
            self.layer_opacity_changed.emit(index, value / 100.0)

    def _on_blend_mode_changed(self, _combo_index: int) -> None:
        if self._refreshing:
            return
        index = self._current_layer_index()
        if index is not None:
            mode = self.blend_mode_combo.currentData()
            self.layer_blend_mode_changed.emit(index, mode)

    # -- MainWindow-facing API -------------------------------------------

    def set_project(self, project: Project | None) -> None:
        """Refresh the page against `project`. Called once at
        construction and again every time MainWindow switches to this
        page, mirroring ExportPage.set_project().

        Sets an initial "no project open" preview placeholder here --
        MainWindow's _refresh_composite_preview() overwrites it with
        either the real composited preview or a more specific reason
        (no frames captured yet, etc.) right after, but this page
        should never sit on a blank box in between, e.g. while a project
        is being loaded.
        """
        self._project = project
        self._refresh_overlay_combo(project)
        self._refresh_layer_list(project)
        if project is None:
            self.set_preview_pixmap(None, message="No project open")

    def _refresh_overlay_combo(self, project: Project | None) -> None:
        self.overlay_combo.clear()
        if project is None:
            self.add_layer_button.setEnabled(False)
            self.add_layer_button.setToolTip("")
            return
        for overlay_path in project.overlays:
            label = overlay_path.rsplit("/", 1)[-1]
            self.overlay_combo.addItem(label, userData=overlay_path)
        has_overlays = bool(project.overlays)
        self.add_layer_button.setEnabled(has_overlays)
        # Explains the disabled state instead of leaving it looking
        # broken -- a composite layer always draws from an existing
        # Overlay asset (see CompositeLayer's docstring in project.py),
        # so there's nothing to add until at least one overlay exists.
        self.add_layer_button.setToolTip(
            "" if has_overlays else "Add an Overlay in Project Browser first"
        )

    def _refresh_layer_list(self, project: Project | None) -> None:
        self._refreshing = True
        self.layer_list.clear()
        if project is not None:
            for layer in reversed(project.composite_layers):
                self._add_list_item(layer)
        self._refreshing = False
        self._settings_group.setEnabled(False)

    def _add_list_item(self, layer: CompositeLayer) -> None:
        label = layer.source.rsplit("/", 1)[-1]
        item = QListWidgetItem(label)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
        )
        self.layer_list.addItem(item)

    def set_preview_pixmap(
        self, pixmap: QPixmap | None, message: str = "No preview available"
    ) -> None:
        """Show the already-composited preview MainWindow computed via
        image_processing/compositor.py. This page never composites
        anything itself -- see this module's docstring.

        Args:
            pixmap: The composited frame, or None if there's nothing to
                show yet.
            message: Shown in place of a pixmap when `pixmap` is None --
                MainWindow passes a specific reason ("Capture a frame
                first", "Add an overlay first", ...) rather than this
                generic default, so an empty preview always explains
                itself instead of just sitting blank (the bug this
                parameter exists to fix -- a fresh project with no
                frames/overlays yet used to leave this box looking
                broken rather than merely empty).
        """
        if pixmap is None or pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(message)
            return
        self.preview_label.setText("")
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

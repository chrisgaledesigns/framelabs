"""Project Settings dialog for FrameLabs.

Lets the user edit an already-created project's metadata -- name, FPS,
resolution, and camera info -- from the Edit menu, without going through
Save/Open. Mirrors NewProjectDialog's form (same fields, same
QFormLayout/QDialogButtonBox shape) since both are just "collect this
handful of project fields," but this dialog edits an existing Project
in place instead of calling create_new_project().
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from framelabs.project.project import Project


class ProjectSettingsDialog(QDialog):
    """Dialog for viewing and editing an existing project's settings.

    Unlike NewProjectDialog (which builds a brand-new Project),
    this dialog is handed an already-active Project and, on Ok,
    writes the edited values directly back onto that same instance --
    Project is a plain mutable dataclass, so there's no separate
    "apply" step for the caller to get wrong. Callers should only treat
    the project as updated after exec() returns QDialog.Accepted;
    nothing is written back on Cancel.
    """

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        """Build the dialog's form, pre-filled from `project`'s current
        values.

        Args:
            project: The active project to edit. Kept as a reference
                (not copied) so _on_save can write straight back into
                it once the new values pass validation.
        """
        super().__init__(parent)
        self.setWindowTitle("Project Settings")
        self._project = project
        self._build_form()

    def _build_form(self) -> None:
        """Build the dialog's form fields, pre-filled from self._project."""
        self.name_edit = QLineEdit(self._project.name)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(self._project.fps)

        width, height = self._project.resolution
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 10000)
        self.width_spin.setValue(width)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 10000)
        self.height_spin.setValue(height)

        resolution_row = QWidget()
        resolution_layout = QHBoxLayout(resolution_row)
        resolution_layout.setContentsMargins(0, 0, 0, 0)
        resolution_layout.addWidget(self.width_spin)
        resolution_layout.addSpacing(8)
        resolution_layout.addWidget(self.height_spin)

        # camera_model/camera_lens are optional (str | None) on Project --
        # an empty field round-trips back to None rather than "", so a
        # project with no camera info recorded stays that way instead of
        # picking up a stray empty string. See _on_save().
        self.camera_model_edit = QLineEdit(self._project.camera_model or "")
        self.camera_model_edit.setPlaceholderText("e.g. Canon EOS R5")

        self.camera_lens_edit = QLineEdit(self._project.camera_lens or "")
        self.camera_lens_edit.setPlaceholderText("e.g. 50mm f/1.8")

        form = QFormLayout()
        form.addRow("Project Name:", self.name_edit)
        form.addRow("FPS:", self.fps_spin)
        form.addRow("Resolution (W x H):", resolution_row)
        form.addRow("Camera Model:", self.camera_model_edit)
        form.addRow("Camera Lens:", self.camera_lens_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        """Validate inputs, write them onto self._project, and close.

        Does not close the dialog on failure, matching
        NewProjectDialog's _on_create -- so the user can fix the name
        and try again without losing anything else they've already
        changed.
        """
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Enter a project name.")
            return

        self._project.name = name
        self._project.fps = self.fps_spin.value()
        self._project.resolution = (self.width_spin.value(), self.height_spin.value())
        self._project.camera_model = self.camera_model_edit.text().strip() or None
        self._project.camera_lens = self.camera_lens_edit.text().strip() or None

        self.accept()

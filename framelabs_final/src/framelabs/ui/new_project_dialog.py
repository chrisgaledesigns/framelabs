"""New Project dialog for FrameLabs.

Implements Feature 1's "Create Project" user flow: choose a project name,
choose a parent folder, choose FPS, choose resolution, then Create. On a
successful create, calls the real (already-tested) `create_new_project()`
rather than reimplementing any project-creation logic here.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from framelabs.project.creator import ProjectCreationError, create_new_project
from framelabs.project.project import Project


class NewProjectDialog(QDialog):
    """Dialog for collecting New Project details and creating the project.

    On successful creation, the created `Project` is available as
    `self.project`. Callers should only read `self.project` after `exec()`
    returns `QDialog.Accepted`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the dialog and build its form."""
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.project: Project | None = None
        self._build_form()

    def _build_form(self) -> None:
        """Build the dialog's form fields, in Feature 1's flow order."""
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Robot Walk Cycle")

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("No folder chosen")

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse)

        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(browse_button)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(12)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 10000)
        self.width_spin.setValue(1920)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 10000)
        self.height_spin.setValue(1080)

        resolution_row = QWidget()
        resolution_layout = QHBoxLayout(resolution_row)
        resolution_layout.setContentsMargins(0, 0, 0, 0)
        resolution_layout.addWidget(self.width_spin)
        resolution_layout.addSpacing(8)
        resolution_layout.addWidget(self.height_spin)

        form = QFormLayout()
        form.addRow("Project Name:", self.name_edit)
        form.addRow("Folder:", folder_row)
        form.addRow("FPS:", self.fps_spin)
        form.addRow("Resolution (W x H):", resolution_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        buttons.accepted.connect(self._on_create)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        """Open a folder picker and store the chosen parent directory."""
        chosen = QFileDialog.getExistingDirectory(self, "Choose Parent Folder")
        if chosen:
            self.folder_edit.setText(chosen)

    def _on_create(self) -> None:
        """Validate inputs, create the project, and close on success.

        Does not close the dialog on failure, so the user can fix the
        offending field(s) and try again without re-entering everything.
        """
        name = self.name_edit.text().strip()
        folder_text = self.folder_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Missing Name", "Enter a project name.")
            return

        if not folder_text:
            QMessageBox.warning(self, "Missing Folder", "Choose a parent folder.")
            return

        parent_dir = Path(folder_text)
        fps = self.fps_spin.value()
        resolution = (self.width_spin.value(), self.height_spin.value())

        try:
            self.project = create_new_project(
                name=name,
                parent_dir=parent_dir,
                fps=fps,
                resolution=resolution,
            )
        except ProjectCreationError as exc:
            QMessageBox.critical(self, "Could Not Create Project", str(exc))
            return

        self.accept()

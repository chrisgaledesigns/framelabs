"""Startup "Welcome to FrameLabs" project-picker dialog.

Shown after the splash screen and before MainWindow exists at all --
lets the user create a new project, browse to an existing one, or
reopen a recent one, before the app's main window ever appears.
Project creation is delegated to the existing NewProjectDialog rather
than reimplementing any of its validation/creation logic here. No
dialog-specific styling is applied here -- app/main.py's app-wide
theme.STYLESHEET (QDialog, QPushButton, QListWidget, ...) already
covers it.

Layout: a full-bleed hero photo banner (see branding.hero_banner_pixmap)
with the logo and version badge overlaid on it, Recent Projects below
that, and New/Open/Open Selected along the bottom -- no separate Quit
button, since the dialog's own close box / Esc already reject() it the
same way a Quit button would.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from framelabs.core.config import Config
from framelabs.project.project import Project
from framelabs.ui.branding import (
    current_version_text,
    find_hero_image,
    hero_banner_pixmap,
)
from framelabs.ui.new_project_dialog import NewProjectDialog

HERO_WIDTH = 600
HERO_HEIGHT = 300

# Recent Projects hugs its actual item count instead of reserving a
# fixed block of space -- a couple of entries shouldn't leave a wall
# of empty dark panel between the list and the buttons below it. Caps
# out at MAX_VISIBLE_RECENT_ROWS tall and scrolls beyond that, so a
# long history doesn't grow the dialog unboundedly instead.
MAX_VISIBLE_RECENT_ROWS = 5


class StartupDialog(QDialog):
    """Pre-launch dialog offering New Project / Open Project / Recent.

    On `Accepted`, exactly one of `new_project` or `chosen_path` is
    set: `new_project` for a project already created here (via
    NewProjectDialog), `chosen_path` for a project folder to hand to
    `MainWindow.open_project_at()` -- picked via Browse or from Recent
    Projects. Callers should check `new_project` first, since it's the
    more specific outcome of the two. On `Rejected` (Quit, Escape, or
    closing the window), neither is set and the caller should exit
    without ever constructing MainWindow.
    """

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to FrameLabs")
        self.setMinimumWidth(HERO_WIDTH)
        self._config = config
        self.new_project: Project | None = None
        self.chosen_path: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        layout.setSpacing(12)

        hero = QLabel()
        hero.setPixmap(
            hero_banner_pixmap(
                HERO_WIDTH,
                HERO_HEIGHT,
                image_path=find_hero_image(),
                version_text=current_version_text(),
            )
        )
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hero)

        recent_label = QLabel("Recent Projects")
        recent_label.setContentsMargins(16, 4, 16, 0)
        layout.addWidget(recent_label)

        self._recent_list = QListWidget()
        self._recent_list.itemDoubleClicked.connect(self._on_recent_item_chosen)
        self._recent_list.itemSelectionChanged.connect(
            self._update_open_selected_enabled
        )
        self._populate_recent_projects()
        self._size_recent_list_to_content()

        recent_row = QHBoxLayout()
        recent_row.setContentsMargins(16, 0, 16, 0)
        recent_row.addWidget(self._recent_list)
        layout.addLayout(recent_row)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(16, 0, 16, 0)
        bottom_row.setSpacing(8)

        self._open_selected_button = QPushButton("Open Selected")
        self._open_selected_button.setEnabled(False)
        self._open_selected_button.clicked.connect(self._on_open_selected)
        bottom_row.addWidget(self._open_selected_button)
        bottom_row.addStretch()

        new_button = QPushButton("New Project...")
        new_button.setMinimumHeight(36)
        new_button.setDefault(True)
        new_button.clicked.connect(self._on_new_project)
        bottom_row.addWidget(new_button)

        open_button = QPushButton("Open Project...")
        open_button.setMinimumHeight(36)
        open_button.clicked.connect(self._on_open_project)
        bottom_row.addWidget(open_button)

        layout.addLayout(bottom_row)

    def _size_recent_list_to_content(self) -> None:
        """Fix the list's height to its actual row count (capped).

        Called once, right after populating -- this list's contents
        never change afterward, so a one-time fixed height (rather
        than a fixed minimum reserving space no matter the count) is
        enough to keep it hugging 1-2 real entries as tightly as it
        hugs the single "No recent projects yet" placeholder.
        """
        count = max(self._recent_list.count(), 1)
        visible_rows = min(count, MAX_VISIBLE_RECENT_ROWS)
        row_height = self._recent_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self._recent_list.fontMetrics().height() + 12
        frame = 2 * self._recent_list.frameWidth()
        self._recent_list.setFixedHeight(row_height * visible_rows + frame + 4)

    def _populate_recent_projects(self) -> None:
        """Fill the Recent Projects list from Config.

        Stale entries (folder deleted/moved) have already been dropped
        by Config.get_recent_projects() itself, so anything returned
        here is safe to offer.
        """
        recents = self._config.get_recent_projects()
        if not recents:
            placeholder = QListWidgetItem("No recent projects yet")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(placeholder)
            return

        for entry in recents:
            item = QListWidgetItem(f"{entry['name']}   —   {entry['path']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            self._recent_list.addItem(item)

    def _update_open_selected_enabled(self) -> None:
        """Only enable Open Selected for a real entry, not the placeholder."""
        selected = self._recent_list.selectedItems()
        has_valid_selection = bool(selected) and (
            selected[0].data(Qt.ItemDataRole.UserRole) is not None
        )
        self._open_selected_button.setEnabled(has_valid_selection)

    def _on_new_project(self) -> None:
        """Delegate to the existing NewProjectDialog, then accept on success."""
        dialog = NewProjectDialog(self)
        if dialog.exec():
            self.new_project = dialog.project
            self.accept()

    def _on_open_project(self) -> None:
        """Folder picker for an existing project, same as File > Open Project."""
        chosen = QFileDialog.getExistingDirectory(self, "Open Project")
        if chosen:
            self.chosen_path = Path(chosen)
            self.accept()

    def _on_open_selected(self) -> None:
        selected = self._recent_list.selectedItems()
        if selected:
            self._on_recent_item_chosen(selected[0])

    def _on_recent_item_chosen(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if path_str:
            self.chosen_path = Path(path_str)
            self.accept()

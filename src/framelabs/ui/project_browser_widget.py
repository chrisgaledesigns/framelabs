"""Project Browser panel widget — backlog item #3.

Real per-project navigation panel, following the Project Vision PDF's Main
Window Layout wireframe (Frames / Audio / References / Overlays / Notes /
Exports / Plugins), but scoped down per Chris's explicit choice: only the
three sections with a real, working data source behind them are shown --
Frames (a real thumbnail grid, reading the same project_path/thumbnails
files TimelineWidget already reads), Notes (frames with real note text
attached, per Feature 5), and Exports (a real scan of the project's
on-disk exports/ folder, per Feature 1's project layout). Audio,
References, Overlays, and Plugins have no project-level data model or
folder yet, so showing them now would just be four permanently-empty
sections masquerading as finished features -- they'll be added to this
widget once each of those features is actually built, not before.

Frames renders as a real thumbnail grid (QListWidget in IconMode), not a
text list, per Chris's explicit choice after seeing the first version --
this is why Frames uses a different widget type than Notes/Exports below
it, rather than one shared tree. Notes and Exports stay as simple text
lists: Notes needs to show note content, and Exports needs to show
filenames, neither of which benefits from a thumbnail grid.

Like TimelineWidget and InspectorPanel, this widget holds no Project of its
own -- MainWindow calls set_project() whenever the underlying project
changes.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from framelabs.project.project import Project

# QListWidgetItem data slot used to stash a Frame item's position in
# Project.frames / Timeline.frames -- the same "raw index" contract
# TimelineWidget.frame_selected already uses, so MainWindow can route both
# through the one shared _on_frame_selected() handler (per the hand-off's
# "one shared set of handler methods taking a raw identifier" convention).
_FRAME_INDEX_ROLE = Qt.ItemDataRole.UserRole

# Grid tile size for the Frames thumbnail grid. Deliberately smaller than
# TimelineWidget's THUMBNAIL_DISPLAY_HEIGHT (100px) -- this panel lives in
# the narrow side splitter (main_window.py's setSizes() gives it ~250px),
# so tiles need to be small enough that more than one fits per row.
FRAME_TILE_SIZE = 72


class ProjectBrowserWidget(QWidget):
    """Real per-project navigation panel: Frames grid / Notes / Exports.

    See module docstring for why only these three sections exist today,
    and why Frames alone uses a thumbnail grid rather than a text list.
    """

    # Raw index into Project.frames / Timeline.frames, exactly matching
    # TimelineWidget.frame_selected's contract.
    frame_selected = Signal(int)

    def __init__(self) -> None:
        """Build the panel's three sections (initially empty/hidden)."""
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._no_project_label = QLabel("No project open")
        self._no_project_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._no_project_label)

        self._frames_header = self._make_header("Frames")
        layout.addWidget(self._frames_header)

        self._frames_grid = QListWidget()
        self._frames_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._frames_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._frames_grid.setMovement(QListWidget.Movement.Static)
        self._frames_grid.setIconSize(QSize(FRAME_TILE_SIZE, FRAME_TILE_SIZE))
        self._frames_grid.setSpacing(4)
        self._frames_grid.itemDoubleClicked.connect(
            self._on_indexed_item_double_clicked
        )
        layout.addWidget(self._frames_grid, 2)

        self._notes_header = self._make_header("Notes")
        layout.addWidget(self._notes_header)

        self._notes_list = QListWidget()
        self._notes_list.itemDoubleClicked.connect(self._on_indexed_item_double_clicked)
        layout.addWidget(self._notes_list, 1)

        self._exports_header = self._make_header("Exports")
        layout.addWidget(self._exports_header)

        self._exports_list = QListWidget()
        layout.addWidget(self._exports_list, 1)

        self._show_no_project()

    @staticmethod
    def _make_header(text: str) -> QLabel:
        """Build a small bold section header label."""
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold;")
        return label

    def _section_widgets(self) -> tuple[QWidget, ...]:
        """All section headers/lists, for the show/hide-together toggle
        between the "No project open" state and a real project's sections.
        """
        return (
            self._frames_header,
            self._frames_grid,
            self._notes_header,
            self._notes_list,
            self._exports_header,
            self._exports_list,
        )

    def _show_no_project(self) -> None:
        """Show only the placeholder row; hide every real section."""
        self._no_project_label.setVisible(True)
        for widget in self._section_widgets():
            widget.setVisible(False)
        self._frames_grid.clear()
        self._notes_list.clear()
        self._exports_list.clear()

    def set_project(self, project: Project | None) -> None:
        """Rebuild the panel to match `project`'s current frames/notes/exports.

        Call this from the same places MainWindow calls
        _refresh_timeline_widget() -- new project, opened project, capture,
        delete, replace, duplicate, undo, redo -- so the panel never shows
        stale frame data. Safe to call with `project=None` (no active
        project yet), which shows a single placeholder row instead of three
        empty sections.
        """
        self._frames_grid.clear()
        self._notes_list.clear()
        self._exports_list.clear()

        if project is None:
            self._show_no_project()
            return

        self._no_project_label.setVisible(False)
        for widget in self._section_widgets():
            widget.setVisible(True)

        self._build_frames_grid(project)
        self._build_notes_list(project)
        self._build_exports_list(project)

    @staticmethod
    def _ordered_frames(project: Project) -> list:
        """Frames sorted by frame number, matching Timeline.frames exactly.

        MainWindow's _on_frame_selected() resolves the index this widget
        emits via self.timeline.frames[index] -- Timeline.frames always
        returns project.frames sorted by frame number (see its
        docstring), not insertion order. Reading project.frames directly
        here would silently emit indices into the wrong list the moment
        a project's frames aren't already stored in number order, so this
        mirrors that same sort rather than assuming it's unnecessary.
        """
        return sorted(project.frames, key=lambda f: f.number)

    def _build_frames_grid(self, project: Project) -> None:
        """Fill the Frames grid with one real thumbnail tile per frame.

        Reads thumbnails from project_path/thumbnails/{number:06d}.jpg --
        the exact same file, naming convention, and QPixmap-loading
        approach as TimelineWidget.FrameThumbnail, so a frame that has a
        real thumbnail on disk always shows it here too. A frame with no
        readable thumbnail file falls back to a plain numbered tile with
        no icon, the grid equivalent of FrameThumbnail's "No Thumbnail"
        text fallback, rather than a broken image.
        """
        thumbnails_dir = (
            project.project_path / "thumbnails"
            if project.project_path is not None
            else None
        )
        for index, frame in enumerate(self._ordered_frames(project)):
            item = QListWidgetItem(str(frame.number))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setData(_FRAME_INDEX_ROLE, index)

            if thumbnails_dir is not None:
                thumbnail_path = thumbnails_dir / f"{frame.number:06d}.jpg"
                pixmap = QPixmap(str(thumbnail_path))
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        FRAME_TILE_SIZE,
                        FRAME_TILE_SIZE,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    item.setIcon(QIcon(pixmap))

            self._frames_grid.addItem(item)

    def _build_notes_list(self, project: Project) -> None:
        """Fill the Notes list with only frames that have real note text.

        Per Feature 5, notes are optional and stored directly on Frame --
        there's no separate notes data source, so this is a filtered view
        of the same ordered frame list _build_frames_grid() reads, not a
        distinct model.
        """
        for index, frame in enumerate(self._ordered_frames(project)):
            if not frame.notes.strip():
                continue
            summary = frame.notes.strip().splitlines()[0][:40]
            item = QListWidgetItem(f"Frame {frame.number}: {summary}")
            item.setData(_FRAME_INDEX_ROLE, index)
            self._notes_list.addItem(item)

    def _build_exports_list(self, project: Project) -> None:
        """Fill the Exports list with real files in project_path/exports.

        A genuine disk scan, not a stub -- Feature 10 (Blender Export)
        hasn't landed yet, so this will legitimately stay empty until it
        does and starts writing real files there. The folder itself is
        always created up front by create_new_project() per Feature 1's
        project layout, but its absence is handled the same as "empty"
        rather than as an error, so nothing here can crash a project that
        otherwise opens fine.
        """
        if project.project_path is None:
            return
        exports_dir = project.project_path / "exports"
        if not exports_dir.is_dir():
            return
        for path in sorted(exports_dir.iterdir()):
            if path.is_file():
                self._exports_list.addItem(QListWidgetItem(path.name))

    def _on_indexed_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Emit frame_selected if a real Frame/Notes row was double-clicked.

        Shared by both the Frames grid and the Notes list, since both
        carry the same _FRAME_INDEX_ROLE data. Double-click, not
        single-click, deliberately -- unlike TimelineWidget's
        single-click-to-select thumbnails, this panel is browsed by
        scrolling/scanning as much as it's used for navigation, so a
        single click here shouldn't risk moving the playhead by accident
        while Chris is just looking around.
        """
        index = item.data(_FRAME_INDEX_ROLE)
        if index is not None:
            self.frame_selected.emit(index)

"""Project Browser panel widget — backlog item #3.

Real per-project navigation panel: Frames grid / Audio / References /
Overlays / Notes / Exports, following the Project Vision PDF's Main
Window Layout wireframe. Plugins is still withheld -- no project-level
data model or folder for it yet, so it isn't shown here at all (adding a
placeholder entry with no real behavior behind it was deliberately
skipped per Chris's explicit choice).

Every section header is a real clickable accordion toggle (_SectionHeader
below), not just a label -- clicking it expands/collapses that section's
content, per Chris's explicit feedback that six always-expanded sections
stacked in the narrow side splitter looked cluttered. Only Frames starts
expanded when a project opens; every other section starts collapsed,
also per Chris's explicit choice -- Frames is the one section almost
always relevant, the rest are opened on demand. Collapse state persists
across set_project() calls within the same widget instance (switching
projects doesn't reset a section a user deliberately expanded), and is
NOT saved anywhere (a fresh ProjectBrowserWidget always starts with only
Frames expanded).

Frames renders as a real thumbnail grid (QListWidget in IconMode), not a
text list, per Chris's explicit choice after seeing the first version --
this is why Frames uses a different widget type than the text-list
sections below it, rather than one shared tree. Notes, Exports, and
Audio/References/Overlays stay as simple text lists: none of them
benefit from a thumbnail-sized icon (a filename doesn't, and audio files
have no meaningful thumbnail at all).

Audio, References, and Overlays are structurally identical (one list
attribute on Project, one matching subfolder), so they share one generic
build/signal implementation, the same reasoning project/asset_service.py
itself uses.

Like TimelineWidget and InspectorPanel, this widget holds no Project of
its own -- MainWindow calls set_project() whenever the underlying project
changes.

Each section also supports right-click actions, not just browsing --
Chris's explicit feedback after the first version was that the panel was
"just a media browser but you can't really do anything with it." This
widget itself only reports WHAT was right-clicked (raw frame index for
Frames/Notes, filename for Exports, project-relative path for
Audio/References/Overlays) and WHERE, exactly the same "widget reports,
MainWindow decides" split TimelineWidget already established for its own
right-click menu -- MainWindow owns the actual QMenu contents and the
resulting actions in every case:

- Frames grid: emits frame_context_menu_requested(index, global_pos),
  the exact same signal shape as TimelineWidget's, so MainWindow can wire
  it straight into its existing _on_frame_context_menu_requested handler
  with zero new menu logic -- Delete/Replace/Duplicate/Marker, identical
  to the Timeline strip's own right-click menu.
- Notes list: emits note_context_menu_requested(index, global_pos) --
  MainWindow shows Jump to Frame / Edit Note / Clear Note.
- Exports list: emits export_context_menu_requested(filename, global_pos)
  -- MainWindow shows Open File / Open Containing Folder / Delete Export.
- Audio/References/Overlays lists: right-click on an EXISTING tracked
  item emits {kind}_item_context_menu_requested(relative_path, global_pos)
  -- MainWindow shows Open File / Open Containing Folder / Remove from
  Project. Right-click on EMPTY space in one of these three lists instead
  emits {kind}_add_requested(global_pos) -- since these sections start
  genuinely empty and there's no other "Add" UI anywhere yet, right-click
  on empty space is the only way to import a new file into them.

Double-click has two DIFFERENT meanings depending on which section is
double-clicked, per Chris's explicit follow-up choice (session 15):
- Notes list: double-click still emits frame_selected(index) -- jumps the
  Timeline playhead to that frame, exactly as before, same as a Timeline
  strip thumbnail click.
- Frames grid: double-click now emits a SEPARATE signal,
  frame_preview_requested(index), which opens a movable/resizable Theater
  View preview window (see ui/theater_view_dialog.py) instead. This is
  deliberately
  NOT routed through frame_selected -- per Chris's explicit choice,
  previewing a frame in Theater View must not move the Timeline's
  playhead or reveal the frame action bar, unlike every other
  click/double-click path in this app. Right-click on the Frames grid is
  unaffected -- it still emits frame_context_menu_requested as above.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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

# QListWidgetItem data slot used to stash an Audio/References/Overlays
# item's project-relative path (e.g. "audio/scratch_track.wav"), the
# string MainWindow needs to open/remove the real file. Uses the same
# UserRole enum value as _FRAME_INDEX_ROLE -- each QListWidgetItem's data
# is independent, so reusing the role number across different lists is
# safe and matches how _FRAME_INDEX_ROLE itself is already reused across
# the Frames grid and Notes list above.
_ASSET_PATH_ROLE = Qt.ItemDataRole.UserRole

# Grid tile size for the Frames thumbnail grid. Deliberately smaller than
# TimelineWidget's THUMBNAIL_DISPLAY_HEIGHT (100px) -- this panel lives in
# the narrow side splitter (main_window.py's setSizes() gives it ~250px),
# so tiles need to be small enough that more than one fits per row.
FRAME_TILE_SIZE = 72

# The three asset kinds sharing one generic list-section implementation,
# in display order. Matches Project.audio/references/overlays' attribute
# names directly, so getattr(project, kind) always resolves correctly.
_ASSET_KINDS = ("audio", "references", "overlays")

# Every collapsible section, in display order top to bottom. Matches the
# keys used in _section_headers/_section_content below.
_SECTION_KEYS = ("frames", "audio", "references", "overlays", "notes", "exports")

# Only Frames starts expanded -- see module docstring for why.
_INITIALLY_EXPANDED = {"frames"}


class _SectionHeader(QPushButton):
    """A clickable, collapsible section header showing an expand/collapse
    chevron next to its title.

    A real QPushButton (flat, borderless, checkable) rather than a plain
    QLabel, so clicking anywhere on the header toggles it -- checked
    state IS the expanded/collapsed state, read via isChecked().
    """

    def __init__(self, title: str) -> None:
        """Build the header, initially collapsed. Caller sets the real
        initial state via set_expanded() afterward."""
        super().__init__()
        self._title = title
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { text-align: left; font-weight: bold; "
            "border: none; padding: 4px 2px; }"
        )
        self.toggled.connect(self._update_text)
        self._update_text()

    def _update_text(self) -> None:
        """Redraw the label with the chevron matching the current state."""
        chevron = "\u25be" if self.isChecked() else "\u25b8"
        self.setText(f"{chevron} {self._title}")

    def set_expanded(self, expanded: bool) -> None:
        """Set expanded/collapsed state without requiring a real click."""
        self.setChecked(expanded)


class ProjectBrowserWidget(QWidget):
    """Real per-project navigation panel: Frames grid / Audio / References
    / Overlays / Notes / Exports, each a collapsible accordion section.

    See module docstring for why Frames alone uses a thumbnail grid rather
    than a text list, why Audio/References/Overlays share one generic
    implementation instead of three near-copies, and why sections are
    collapsible with only Frames expanded by default.
    """

    # Raw index into Project.frames / Timeline.frames, exactly matching
    # TimelineWidget.frame_selected's contract.
    frame_selected = Signal(int)

    # Same (index, global_pos) shape as TimelineWidget.frame_context_menu_
    # requested -- lets MainWindow wire this directly into its existing
    # handler for the Frames grid with no new menu logic.
    frame_context_menu_requested = Signal(int, QPoint)

    # Raw index into Project.frames/Timeline.frames of a Frames-grid tile
    # that was double-clicked, requesting a read-only Theater View preview.
    # Deliberately a SEPARATE signal from frame_selected (see module
    # docstring) -- MainWindow must not route this through
    # _on_frame_selected, since previewing a frame must not move the
    # Timeline's playhead.
    frame_preview_requested = Signal(int)

    # Same raw-index contract as frame_selected, for the Notes list.
    note_context_menu_requested = Signal(int, QPoint)

    # Exports has no frame index to report -- just which file was
    # right-clicked, by name (matches _build_exports_list's item text).
    export_context_menu_requested = Signal(str, QPoint)

    # Audio/References/Overlays: right-click on EMPTY space in that
    # section's list, requesting a new file be imported. global_pos is
    # where MainWindow should show the "Add <Kind> File..." menu.
    audio_add_requested = Signal(QPoint)
    references_add_requested = Signal(QPoint)
    overlays_add_requested = Signal(QPoint)

    # Audio/References/Overlays: right-click on an EXISTING tracked item.
    # Carries the item's project-relative path string (not a raw index --
    # MainWindow needs the real path to open/remove the file, and these
    # lists have no separate index-based lookup the way Frames/Notes do).
    audio_item_context_menu_requested = Signal(str, QPoint)
    references_item_context_menu_requested = Signal(str, QPoint)
    overlays_item_context_menu_requested = Signal(str, QPoint)

    def __init__(self) -> None:
        """Build the panel's sections (initially empty/hidden)."""
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._no_project_label = QLabel("No project open")
        self._no_project_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._no_project_label)

        self._frames_header = _SectionHeader("Frames")
        layout.addWidget(self._frames_header)
        self._frames_grid = QListWidget()
        self._frames_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._frames_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._frames_grid.setMovement(QListWidget.Movement.Static)
        self._frames_grid.setIconSize(QSize(FRAME_TILE_SIZE, FRAME_TILE_SIZE))
        self._frames_grid.setSpacing(4)
        self._frames_grid.itemDoubleClicked.connect(
            self._on_frames_grid_item_double_clicked
        )
        self._frames_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frames_grid.customContextMenuRequested.connect(
            self._on_frames_grid_context_menu_requested
        )
        layout.addWidget(self._frames_grid, 2)

        # Audio/References/Overlays: one QListWidget per kind, built
        # generically since all three are structurally identical. Stored
        # in a dict keyed by kind so the generic handlers below can look
        # up "which list, which signals" from a single kind string.
        self._asset_headers: dict[str, _SectionHeader] = {}
        self._asset_lists: dict[str, QListWidget] = {}
        for kind in _ASSET_KINDS:
            header = _SectionHeader(kind.capitalize())
            layout.addWidget(header)
            self._asset_headers[kind] = header

            list_widget = QListWidget()
            list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(
                partial(self._on_asset_list_context_menu_requested, kind)
            )
            layout.addWidget(list_widget, 1)
            self._asset_lists[kind] = list_widget

        self._notes_header = _SectionHeader("Notes")
        layout.addWidget(self._notes_header)
        self._notes_list = QListWidget()
        self._notes_list.itemDoubleClicked.connect(self._on_indexed_item_double_clicked)
        self._notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._notes_list.customContextMenuRequested.connect(
            self._on_notes_list_context_menu_requested
        )
        layout.addWidget(self._notes_list, 1)

        self._exports_header = _SectionHeader("Exports")
        layout.addWidget(self._exports_header)
        self._exports_list = QListWidget()
        self._exports_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._exports_list.customContextMenuRequested.connect(
            self._on_exports_list_context_menu_requested
        )
        layout.addWidget(self._exports_list, 1)

        # Unified key -> (header, content) mapping, used by the generic
        # collapse/expand logic and the "no project" show/hide toggle,
        # rather than repeating six near-identical if/elif blocks.
        self._section_headers: dict[str, _SectionHeader] = {
            "frames": self._frames_header,
            "audio": self._asset_headers["audio"],
            "references": self._asset_headers["references"],
            "overlays": self._asset_headers["overlays"],
            "notes": self._notes_header,
            "exports": self._exports_header,
        }
        self._section_content: dict[str, QWidget] = {
            "frames": self._frames_grid,
            "audio": self._asset_lists["audio"],
            "references": self._asset_lists["references"],
            "overlays": self._asset_lists["overlays"],
            "notes": self._notes_list,
            "exports": self._exports_list,
        }

        for key in _SECTION_KEYS:
            header = self._section_headers[key]
            header.set_expanded(key in _INITIALLY_EXPANDED)
            header.toggled.connect(partial(self._on_section_toggled, key))

        self._show_no_project()

    def _section_widgets(self) -> tuple[QWidget, ...]:
        """All section headers/content widgets, for the show/hide-together
        toggle between the "No project open" state and a real project's
        sections."""
        widgets: tuple[QWidget, ...] = ()
        for key in _SECTION_KEYS:
            widgets += (self._section_headers[key], self._section_content[key])
        return widgets

    def _show_no_project(self) -> None:
        """Show only the placeholder row; hide every real section."""
        self._no_project_label.setVisible(True)
        for widget in self._section_widgets():
            widget.setVisible(False)
        self._frames_grid.clear()
        for kind in _ASSET_KINDS:
            self._asset_lists[kind].clear()
        self._notes_list.clear()
        self._exports_list.clear()

    def set_project(self, project: Project | None) -> None:
        """Rebuild the panel to match `project`'s current state.

        Call this from the same places MainWindow calls
        _refresh_timeline_widget() -- new project, opened project, capture,
        delete, replace, duplicate, undo, redo, and any asset add/remove --
        so the panel never shows stale data. Safe to call with
        `project=None` (no active project yet), which shows a single
        placeholder row instead of every section.

        Each section's collapsed/expanded state is preserved across this
        call -- switching projects (or refreshing the current one) doesn't
        reset a section the user deliberately expanded or collapsed.
        """
        self._frames_grid.clear()
        for kind in _ASSET_KINDS:
            self._asset_lists[kind].clear()
        self._notes_list.clear()
        self._exports_list.clear()

        if project is None:
            self._show_no_project()
            return

        self._no_project_label.setVisible(False)
        for key in _SECTION_KEYS:
            self._section_headers[key].setVisible(True)
            self._section_content[key].setVisible(
                self._section_headers[key].isChecked()
            )

        self._build_frames_grid(project)
        for kind in _ASSET_KINDS:
            self._build_asset_list(kind, project)
        self._build_notes_list(project)
        self._build_exports_list(project)

    def _on_section_toggled(self, key: str, expanded: bool) -> None:
        """Show/hide a section's content when its header is clicked.

        No-op while no project is open -- all sections are hidden
        together via _show_no_project() regardless of collapse state, so
        toggling a header before a project loads shouldn't make content
        visible against the placeholder state.
        """
        if self._no_project_label.isVisible():
            return
        self._section_content[key].setVisible(expanded)

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

    def _build_asset_list(self, kind: str, project: Project) -> None:
        """Fill one Audio/References/Overlays list from Project.{kind}.

        Displays just the filename (not the full "audio/name.ext" project-
        relative path) for readability, since every item in a given
        section is already known to live in that section's subfolder --
        the full relative path is stashed on the item via _ASSET_PATH_ROLE
        for MainWindow's right-click handling to use.
        """
        list_widget = self._asset_lists[kind]
        for relative_path in getattr(project, kind):
            filename = relative_path.rsplit("/", 1)[-1]
            item = QListWidgetItem(filename)
            item.setData(_ASSET_PATH_ROLE, relative_path)
            list_widget.addItem(item)

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
        """Fill the Exports list with real files AND folders in
        project_path/exports.

        A genuine disk scan, not a stub. Files are the video/GIF exports
        from export_service.export_video()/export_gif(); folders are the
        image-sequence exports from export_service.export_image_sequence()
        (each one a self-contained numbered-frame folder, not a single
        file). Folders are suffixed with "/" for display only -- Path
        normalizes away a trailing slash, so
        _on_exports_list_context_menu_requested()'s emitted filename still
        resolves to the right path with no special-casing needed there.
        The exports/ folder itself is always created up front by
        create_new_project() per Feature 1's project layout, but its
        absence is handled the same as "empty" rather than as an error,
        so nothing here can crash a project that otherwise opens fine.
        """
        if project.project_path is None:
            return
        exports_dir = project.project_path / "exports"
        if not exports_dir.is_dir():
            return
        for path in sorted(exports_dir.iterdir()):
            if path.is_dir():
                self._exports_list.addItem(QListWidgetItem(f"{path.name}/"))
            elif path.is_file():
                self._exports_list.addItem(QListWidgetItem(path.name))

    def _on_indexed_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Emit frame_selected if a real Notes row was double-clicked.

        Used by the Notes list only (see module docstring for why the
        Frames grid uses a separate handler/signal as of session 15).
        Double-click, not single-click, deliberately -- unlike
        TimelineWidget's single-click-to-select thumbnails, this panel is
        browsed by scrolling/scanning as much as it's used for
        navigation, so a single click here shouldn't risk moving the
        playhead by accident while Chris is just looking around.
        """
        index = item.data(_FRAME_INDEX_ROLE)
        if index is not None:
            self.frame_selected.emit(index)

    def _on_frames_grid_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Emit frame_preview_requested for a double-clicked Frames tile.

        Deliberately distinct from _on_indexed_item_double_clicked (see
        module docstring): opening the Theater View preview must not move
        the Timeline's playhead, unlike double-clicking a Notes row or a
        Timeline strip thumbnail.
        """
        index = item.data(_FRAME_INDEX_ROLE)
        if index is not None:
            self.frame_preview_requested.emit(index)

    def _on_frames_grid_context_menu_requested(self, pos: QPoint) -> None:
        """Emit frame_context_menu_requested for the tile under `pos`.

        Same (index, global_pos) shape as TimelineWidget's own signal --
        see the module docstring for why this lets MainWindow reuse its
        existing handler as-is.
        """
        item = self._frames_grid.itemAt(pos)
        if item is None:
            return
        index = item.data(_FRAME_INDEX_ROLE)
        if index is None:
            return
        global_pos = self._frames_grid.viewport().mapToGlobal(pos)
        self.frame_context_menu_requested.emit(index, global_pos)

    def _on_asset_list_context_menu_requested(self, kind: str, pos: QPoint) -> None:
        """Emit the right add/item-context signal for `kind`'s list.

        Right-click on EMPTY space (no item under `pos`) emits
        {kind}_add_requested(global_pos) -- the only way to import a new
        file into a section that starts genuinely empty. Right-click on
        an EXISTING item emits {kind}_item_context_menu_requested(
        relative_path, global_pos) instead, carrying the item's stashed
        project-relative path.
        """
        list_widget = self._asset_lists[kind]
        global_pos = list_widget.viewport().mapToGlobal(pos)
        item = list_widget.itemAt(pos)

        add_signal = getattr(self, f"{kind}_add_requested")
        item_signal = getattr(self, f"{kind}_item_context_menu_requested")

        if item is None:
            add_signal.emit(global_pos)
            return

        relative_path = item.data(_ASSET_PATH_ROLE)
        if relative_path is None:
            return
        item_signal.emit(relative_path, global_pos)

    def _on_notes_list_context_menu_requested(self, pos: QPoint) -> None:
        """Emit note_context_menu_requested for the row under `pos`."""
        item = self._notes_list.itemAt(pos)
        if item is None:
            return
        index = item.data(_FRAME_INDEX_ROLE)
        if index is None:
            return
        global_pos = self._notes_list.viewport().mapToGlobal(pos)
        self.note_context_menu_requested.emit(index, global_pos)

    def _on_exports_list_context_menu_requested(self, pos: QPoint) -> None:
        """Emit export_context_menu_requested for the file under `pos`.

        Reports the filename (the item's own display text, set directly
        from Path.name in _build_exports_list) rather than a stashed data
        role, since Exports has no frame index to carry.
        """
        item = self._exports_list.itemAt(pos)
        if item is None:
            return
        global_pos = self._exports_list.viewport().mapToGlobal(pos)
        self.export_context_menu_requested.emit(item.text(), global_pos)

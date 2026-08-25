"""Project Browser panel widget — backlog item #3.

Real per-project navigation panel: Frames grid / Audio / References /
Overlays / Notes / Exports, following the Project Vision PDF's Main
Window Layout wireframe. Plugins is still withheld -- no project-level
data model or folder for it yet, so it isn't shown here at all (adding a
placeholder entry with no real behavior behind it was deliberately
skipped per Chris's explicit choice).

Every section header is a real clickable tab button (_SectionHeader
below), not a plain label -- clicking one switches which section's
content is shown below the tab row, per Chris's explicit feedback that
six always-expanded sections stacked in the narrow side splitter looked
cluttered, and that the original vertical accordion still wasted most
of the panel's height on collapsed headers instead of giving Frames
(the section almost always relevant) the full remaining space. The six
headers sit in one horizontal row instead, each toggling visibility of
its own content area below; an exclusive QButtonGroup (_section_button_
group) enforces that exactly one is ever checked, so switching tabs
always shows exactly one section's content, filling the panel's full
height, rather than stacking multiple expanded sections. Frames starts
active when a project opens (_DEFAULT_ACTIVE_SECTION). The active tab
persists across set_project() calls within the same widget instance
(switching projects doesn't reset which tab a user was viewing), and is
NOT saved anywhere (a fresh ProjectBrowserWidget always starts on
Frames).

Only four of the six sections -- Frames, Audio, Notes, Exports -- get a
visible tab button in that row, matching Chris's mockup exactly.
References and Overlays instead live behind a trailing overflow
("burger", \u2630) button at the end of the row: clicking it opens a menu
listing References and Overlays, and picking either just checks that
section's own (still-real, still in _section_button_group, just never
added to the tab row's layout) _SectionHeader -- see
_on_overflow_action_triggered(). That reuses every bit of the exclusive-
group/_on_section_toggled machinery the four visible tabs already use,
so References/Overlays behave identically to a "real" tab once selected;
the only thing that's different is how you get there. Because neither
header is ever shown, the overflow button itself doubles as their tab
in the row -- see _update_overflow_button_state() for how it borrows the
active section's name and a checked/accent look whenever References or
Overlays is the one currently showing.

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
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
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

# Grid tile size for the Frames thumbnail grid, per Chris's mockup: a
# landscape (not square) tile close to the captured frame's own aspect,
# sized so three columns comfortably fit the panel's default width
# (main_window.py's setSizes() gives Project Browser ~300px). Kept as two
# constants -- rather than one square FRAME_TILE_SIZE like before -- since
# a square icon box would letterbox every landscape thumbnail instead of
# filling the tile the way the mockup shows.
FRAME_TILE_WIDTH = 80
FRAME_TILE_HEIGHT = 50

# Kept for backward compatibility with callers that just want "a tile
# dimension" (e.g. requesting a QPixmap off a QIcon at a single size) --
# equal to the tile's width, the larger of the two dimensions.
FRAME_TILE_SIZE = FRAME_TILE_WIDTH

# The three asset kinds sharing one generic list-section implementation,
# in display order. Matches Project.audio/references/overlays' attribute
# names directly, so getattr(project, kind) always resolves correctly.
_ASSET_KINDS = ("audio", "references", "overlays")

# Every section this panel knows about. Matches the keys used in
# _section_headers/_section_content below. Order here drives nothing
# visual by itself -- see _TAB_SECTION_KEYS/_OVERFLOW_SECTION_KEYS below
# for the order/grouping that actually reaches the screen.
_SECTION_KEYS = ("frames", "audio", "references", "overlays", "notes", "exports")

# The sections shown as real tab buttons in the horizontal tab row, per
# Chris's mockup -- References and Overlays are deliberately left off
# this row (see _OVERFLOW_SECTION_KEYS) so the row itself matches the
# four-tab mockup exactly instead of all six sections competing for the
# same narrow strip.
_TAB_SECTION_KEYS = ("frames", "audio", "notes", "exports")

# The sections tucked behind the tab row's overflow ("burger") button
# instead of getting their own tab button. References and Overlays are
# used far less often than Frames/Audio/Notes/Exports, and Chris's
# mockup only shows four tabs, so these two move into the overflow menu
# rather than crowding the row -- selecting either from that menu still
# activates the exact same header/content pair used for the other four,
# via _on_overflow_action_triggered().
_OVERFLOW_SECTION_KEYS = ("references", "overlays")

# The section shown by default when a project opens -- see module
# docstring for why Frames specifically.
_DEFAULT_ACTIVE_SECTION = "frames"


def _fill_tile(pixmap: QPixmap) -> QPixmap:
    """Scale+crop `pixmap` to exactly FRAME_TILE_WIDTH x FRAME_TILE_HEIGHT.

    Matches the mockup, where every thumbnail fills its tile edge-to-edge
    with no letterboxing -- KeepAspectRatio (the old behavior) would
    shrink a landscape frame to fit inside the box and leave bars on the
    two remaining sides instead. KeepAspectRatioByExpanding fills the box
    but overshoots one dimension, so the overshoot is center-cropped away
    afterward; the result is always exactly tile-sized, so QIcon never
    has to re-scale it again when the grid asks for FRAME_TILE_WIDTH x
    FRAME_TILE_HEIGHT at paint time.
    """
    scaled = pixmap.scaled(
        FRAME_TILE_WIDTH,
        FRAME_TILE_HEIGHT,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - FRAME_TILE_WIDTH) // 2)
    y = max(0, (scaled.height() - FRAME_TILE_HEIGHT) // 2)
    return scaled.copy(x, y, FRAME_TILE_WIDTH, FRAME_TILE_HEIGHT)


class _SectionHeader(QPushButton):
    """A clickable tab button showing an expand/collapse-style chevron
    next to its title, matching the active/inactive state.

    A real QPushButton (flat, borderless, checkable) rather than a plain
    QLabel, so clicking anywhere on the tab activates it -- checked
    state IS "this tab is the active one", read via isChecked(). Callers
    add every _SectionHeader instance to one exclusive QButtonGroup (see
    ProjectBrowserWidget.__init__), which is what actually enforces
    "exactly one active at a time" -- this class itself has no opinion
    on the other tabs.
    """

    def __init__(self, title: str) -> None:
        """Build the tab, initially inactive. Caller sets the real
        initial state via set_expanded() afterward."""
        super().__init__()
        self._title = title
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { text-align: left; font-weight: 600; "
            "font-size: 12px; border: none; padding: 6px 8px; }"
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
    / Overlays / Notes / Exports, shown one at a time behind a tab strip.

    See module docstring for why Frames alone uses a thumbnail grid rather
    than a text list, why Audio/References/Overlays share one generic
    implementation instead of three near-copies, and why the tabs are
    mutually exclusive with only Frames active by default.
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
        """Build the panel's tab strip and per-section content (initially
        empty/hidden)."""
        super().__init__()
        self.setObjectName("projectBrowserWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._no_project_label = QLabel("No project open")
        self._no_project_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._no_project_label)

        self._frames_header = _SectionHeader("Frames")
        self._frames_grid = QListWidget()
        self._frames_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._frames_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._frames_grid.setMovement(QListWidget.Movement.Static)
        self._frames_grid.setIconSize(QSize(FRAME_TILE_WIDTH, FRAME_TILE_HEIGHT))
        self._frames_grid.setSpacing(4)
        self._frames_grid.itemDoubleClicked.connect(
            self._on_frames_grid_item_double_clicked
        )
        self._frames_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._frames_grid.customContextMenuRequested.connect(
            self._on_frames_grid_context_menu_requested
        )

        # Audio/References/Overlays: one QListWidget per kind, built
        # generically since all three are structurally identical. Stored
        # in a dict keyed by kind so the generic handlers below can look
        # up "which list, which signals" from a single kind string.
        self._asset_headers: dict[str, _SectionHeader] = {}
        self._asset_lists: dict[str, QListWidget] = {}
        for kind in _ASSET_KINDS:
            self._asset_headers[kind] = _SectionHeader(kind.capitalize())

            list_widget = QListWidget()
            list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(
                partial(self._on_asset_list_context_menu_requested, kind)
            )
            self._asset_lists[kind] = list_widget

        self._notes_header = _SectionHeader("Notes")
        self._notes_list = QListWidget()
        self._notes_list.itemDoubleClicked.connect(self._on_indexed_item_double_clicked)
        self._notes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._notes_list.customContextMenuRequested.connect(
            self._on_notes_list_context_menu_requested
        )

        self._exports_header = _SectionHeader("Exports")
        self._exports_list = QListWidget()
        self._exports_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._exports_list.customContextMenuRequested.connect(
            self._on_exports_list_context_menu_requested
        )

        # Unified key -> (header, content) mapping, used by the generic
        # tab-switch logic and the "no project" show/hide toggle, rather
        # than repeating six near-identical if/elif blocks.
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

        # One horizontal row of tabs, per Chris's explicit choice that
        # the old vertical accordion wasted height on collapsed headers
        # -- see module docstring. An exclusive QButtonGroup is what
        # actually enforces "exactly one active at a time" (verified:
        # unlike an accordion's independent toggles, an exclusive group
        # refuses to let its sole checked button be unchecked directly,
        # so there's no extra guard code needed here for a "collapse the
        # last open tab" case that the tab strip shouldn't allow anyway).
        self._section_button_group = QButtonGroup(self)
        self._section_button_group.setExclusive(True)
        for key in _SECTION_KEYS:
            self._section_button_group.addButton(self._section_headers[key])

        # References/Overlays keep their _SectionHeader (they still need
        # one to stay in the exclusive button group and to drive
        # _on_section_toggled exactly like every other section), but that
        # header never joins the tab row layout -- explicitly reparenting
        # it to this widget (rather than a layout) keeps it a normal
        # hidden child instead of an orphaned top-level window, and it
        # stays hidden permanently; see _on_overflow_action_triggered.
        for key in _OVERFLOW_SECTION_KEYS:
            header = self._section_headers[key]
            header.setParent(self)
            header.hide()

        # The overflow ("burger") button: everything NOT in the four-tab
        # mockup lives behind this one menu instead of its own tab, per
        # Chris's explicit choice to keep the tab row matching the
        # mockup exactly rather than fitting all six sections across it.
        self._overflow_button = QPushButton("\u2630")
        self._overflow_button.setObjectName("projectBrowserOverflowButton")
        self._overflow_button.setFlat(True)
        self._overflow_button.setCheckable(True)
        self._overflow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._overflow_button.setToolTip("More sections (References, Overlays)")
        overflow_menu = QMenu(self._overflow_button)
        for key in _OVERFLOW_SECTION_KEYS:
            action = overflow_menu.addAction(self._section_headers[key]._title)
            action.triggered.connect(partial(self._on_overflow_action_triggered, key))
        self._overflow_button.setMenu(overflow_menu)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(2)
        for key in _TAB_SECTION_KEYS:
            tab_row.addWidget(self._section_headers[key])
        tab_row.addStretch(1)
        tab_row.addWidget(self._overflow_button)
        layout.addLayout(tab_row)

        # Content widgets all share the same row in the layout below the
        # tab strip -- only the active tab's content is ever visible, so
        # whichever one that is expands to fill the panel's full
        # remaining height (stretch=1 on all of them, since exactly one
        # is visible at a time regardless of the others' stretch).
        for key in _SECTION_KEYS:
            layout.addWidget(self._section_content[key], 1)

        for key in _SECTION_KEYS:
            header = self._section_headers[key]
            header.set_expanded(key == _DEFAULT_ACTIVE_SECTION)
            header.toggled.connect(partial(self._on_section_toggled, key))
            header.toggled.connect(self._update_overflow_button_state)

        self._update_overflow_button_state()
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
        self._overflow_button.setVisible(False)
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

        Each tab's active/inactive state is preserved across this call --
        switching projects (or refreshing the current one) doesn't reset
        which tab a user was viewing.
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
        self._overflow_button.setVisible(True)
        for key in _SECTION_KEYS:
            # References/Overlays' headers stay permanently hidden (see
            # __init__) -- only the four tab-row sections get a visible
            # header button; the overflow menu is how References/Overlays
            # get activated instead.
            if key in _TAB_SECTION_KEYS:
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
        """Show/hide a section's content when its tab is (de)activated.

        No-op while no project is open -- all sections are hidden
        together via _show_no_project() regardless of active-tab state,
        so switching tabs before a project loads shouldn't make content
        visible against the placeholder state.
        """
        if self._no_project_label.isVisible():
            return
        self._section_content[key].setVisible(expanded)

    def _on_overflow_action_triggered(self, key: str) -> None:
        """Activate References or Overlays from the overflow menu.

        Just checks that section's (permanently hidden) header -- the
        exclusive _section_button_group then deactivates whichever tab
        was previously checked, and the header's own toggled signal
        drives _on_section_toggled exactly as if a visible tab had been
        clicked. No separate show/hide logic needed here.
        """
        self._section_headers[key].setChecked(True)

    def _update_overflow_button_state(self) -> None:
        """Keep the burger button's checked look and label in sync with
        whichever section is actually active.

        Runs on every header's toggled signal (see __init__): if the
        newly-active section is one of the overflow ones, the burger
        button itself becomes the visual stand-in for "the active tab"
        (checked, labeled with that section's name) since neither
        References' nor Overlays' own header is ever shown in the row.
        Otherwise the burger button just reads as an untoggled, generic
        "more sections" affordance.
        """
        active_overflow_key = next(
            (
                key
                for key in _OVERFLOW_SECTION_KEYS
                if self._section_headers[key].isChecked()
            ),
            None,
        )
        self._overflow_button.setChecked(active_overflow_key is not None)
        if active_overflow_key is not None:
            title = self._section_headers[active_overflow_key]._title
            self._overflow_button.setText(f"\u2630 {title}")
        else:
            self._overflow_button.setText("\u2630")

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
                    item.setIcon(QIcon(_fill_tile(pixmap)))
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

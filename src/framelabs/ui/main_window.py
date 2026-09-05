"""Main application window for FrameLabs."""

import logging
import shutil
from functools import partial
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QImage,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from framelabs.capture.commands import (
    DeleteFrameCommand,
    DuplicateFrameCommand,
    ReorderFramesCommand,
    ReplaceFrameCommand,
    SetFrameNotesCommand,
    ToggleFrameMarkerCommand,
)
from framelabs.core.config import Config, parse_shortcut
from framelabs.core.event_bus import EventBus
from framelabs.core.undo_manager import UndoManager
from framelabs.export.export_service import ExportProgress, ExportRequest, ExportResult
from framelabs.image_processing import compositor
from framelabs.project.asset_commands import AddAssetCommand, RemoveAssetCommand
from framelabs.project.asset_service import AssetServiceError
from framelabs.project.autosave import has_recoverable_autosave
from framelabs.project.composite_commands import (
    AddCompositeLayerCommand,
    RemoveCompositeLayerCommand,
    ReorderCompositeLayerCommand,
)
from framelabs.project.project import Project
from framelabs.project.serializer import ProjectSerializer
from framelabs.timeline.onion_skin import OnionSkinSettings
from framelabs.timeline.playback import PlaybackSettings
from framelabs.timeline.timeline import Timeline
from framelabs.ui.autosave_controller import AutosaveController
from framelabs.ui.blender_controller import BlenderBridgeController
from framelabs.ui.blender_sync_controller import BlenderSyncController
from framelabs.ui.camera_controller import CameraController
from framelabs.ui.capture_controller import CaptureController
from framelabs.ui.composite_workspace import CompositeWorkspace
from framelabs.ui.composition_guides import (
    ASPECT_RATIO_GUIDE_TYPES,
    ASPECT_RATIO_LABELS,
    ASPECT_RATIO_NONE,
    COMPOSITION_GUIDE_LABELS,
    COMPOSITION_GUIDE_TYPES,
    GUIDE_NONE,
)
from framelabs.ui.export_controller import ExportController
from framelabs.ui.export_page import ExportPage
from framelabs.ui.inspector_panel import InspectorPanel
from framelabs.ui.live_view_controller import LiveViewController
from framelabs.ui.live_view_widget import LiveViewWidget
from framelabs.ui.new_project_dialog import NewProjectDialog
from framelabs.ui.onion_skin_controller import OnionSkinController
from framelabs.ui.playback_controller import PlaybackController
from framelabs.ui.project_browser_widget import ProjectBrowserWidget
from framelabs.ui.project_controller import ProjectController
from framelabs.ui.project_settings_dialog import ProjectSettingsDialog
from framelabs.ui.theater_view_dialog import TheaterViewDialog
from framelabs.ui.timecode_widget import TimecodeWidget
from framelabs.ui.timeline_widget import (
    FrameActionBar,
    PlaybackControls,
    TimelineWidget,
)
from framelabs.ui.workspace_tab_bar import (
    COMPOSITE,
    EDIT,
    EXPORT,
    WorkspaceTabBar,
)

logger = logging.getLogger(__name__)

# Feature 8: "Every: 30 seconds AND after every capture." Lives here
# (not in autosave_controller.py) because the timer itself lives on the
# main thread -- see _start_autosave_controller()'s docstring.
AUTOSAVE_INTERVAL_MS = 30000

# Human-readable label per ExportProgress.format_key, for the export
# progress dialog. Keys match export_service.ExportResult's keys exactly.
_EXPORT_FORMAT_LABELS = {
    "video": "Rendering video",
    "image_sequence": "Copying image sequence",
    "gif": "Encoding GIF",
}


def _numpy_rgb_to_pixmap(array: np.ndarray) -> QPixmap:
    """Convert a composited (H, W, 3) uint8 RGB array into a QPixmap.

    The one numpy<->Qt conversion point in this file -- everything
    upstream of this call (image_processing/compositor.py) stays Qt-free
    and unit-testable, per that module's own docstring; this function is
    what lets its output actually reach CompositeWorkspace's QLabel.

    QImage does not copy the buffer it's constructed from, so `array`
    must stay alive at least as long as the QImage does -- `.copy()`
    here forces that copy up front rather than risking `array` (a local
    in _refresh_composite_preview()) being garbage-collected out from
    under a QImage that still thinks it owns that memory.
    """
    height, width, _channels = array.shape
    image = QImage(
        array.tobytes(), width, height, width * 3, QImage.Format.Format_RGB888
    )
    return QPixmap.fromImage(image.copy())


def _titled_pane(title: str, content: QWidget) -> QWidget:
    """Wrap `content` in a plain container with a small caption label
    above it, so each of the main window's panes (Project Browser, Live
    View, Inspector, Timeline) is visibly labeled.

    A wrapper QWidget rather than editing each pane's own __init__,
    since LiveViewWidget is a QGraphicsView and TimelineWidget is a
    QScrollArea -- neither has a layout of its own to drop a label into
    without restructuring the widget itself. Wrapping at the call site
    keeps every pane's existing class untouched.
    """
    title_label = QLabel(title.upper())
    title_label.setObjectName("panelTitle")

    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(title_label)
    layout.addWidget(content, 1)
    return container


class MainWindow(QMainWindow):
    """FrameLabs' main window shell."""

    def __init__(self, config: Config | None = None) -> None:
        """Initialize the main window.

        Args:
            config: Shared Config instance. app/main.py constructs one
                up front and passes it in so the startup Welcome
                dialog's Recent Projects list and MainWindow's own
                recent-projects writes (see _adopt_project) operate on
                the exact same config.json, instead of MainWindow
                silently reloading a second copy from disk here. Falls
                back to constructing its own when omitted, so
                MainWindow remains usable standalone (e.g. from tests).
        """
        super().__init__()
        self.setWindowTitle("FrameLabs")
        self.resize(1280, 800)
        self.project: Project | None = None
        self.timeline: Timeline | None = None
        self.onion_settings = OnionSkinSettings()
        self.playback_settings = PlaybackSettings()
        self.event_bus = EventBus()
        # Feature 12. Also shared with BlenderBridgeController, which
        # persists a located Blender executable path here (see
        # _start_blender_controller()).
        self.config = config if config is not None else Config()
        # Feature 9. Duplicate/Delete/Marker/Notes commands run
        # synchronously on the main thread (see _duplicate_frame's
        # docstring) -- known, flagged simplification, not an oversight.
        # ReplaceFrameCommand is the one exception: its do() triggers a
        # real camera capture, so it runs on CaptureController's worker
        # thread instead (see _replace_frame's docstring).
        self.undo_manager = UndoManager()
        # Set True as the very first thing closeEvent() does. Guards
        # _refresh_onion_skin() against firing once worker-thread teardown
        # has started -- see closeEvent()'s docstring for the full
        # explanation of the shutdown race this prevents.
        self._shutting_down = False
        # Live only while a video/sequence/GIF export is running -- see
        # _on_export_render()/_on_export_progress()/_close_export_progress().
        self._export_progress_dialog: QProgressDialog | None = None
        self._create_actions()
        self._build_menu_bar()
        self._build_central_panes()
        self._start_camera_controller()
        self._start_capture_controller()
        self._start_project_controller()
        self._start_live_view_controller()
        self._start_onion_skin_controller()
        self._start_playback_controller()
        self._start_autosave_controller()
        self._start_export_controller()
        self._start_blender_controller()
        self._start_blender_sync_controller()
        self._wire_playback_controls()
        self._wire_timeline_widget()
        self._wire_frame_action_bar()
        self._wire_project_browser()

    def _create_actions(self) -> None:
        """Create the shared QActions used by the menu bar."""
        self.new_action = QAction("New Project", self)
        self.new_action.triggered.connect(self._on_new_project)

        self.open_action = QAction("Open Project", self)
        self.open_action.triggered.connect(self._on_open_project)

        self.save_action = QAction("Save Project", self)
        self.save_action.setShortcuts(self._shortcuts("save"))
        self.save_action.triggered.connect(self._on_save_project)

        self.capture_action = QAction("Capture", self)
        self.capture_action.setShortcuts(self._shortcuts("capture"))
        self.capture_action.triggered.connect(self._on_capture)

        # Feature 12. Every shortcut below is read from Config's
        # "keyboard_shortcuts" setting via self._shortcuts() rather than
        # hardcoded -- see that method's docstring further down.
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcuts(self._shortcuts("undo"))
        self.undo_action.setEnabled(False)
        self.undo_action.triggered.connect(self._on_undo)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts(self._shortcuts("redo"))
        self.redo_action.setEnabled(False)
        self.redo_action.triggered.connect(self._on_redo)

        # Feature 5. Temporary Edit-menu home for Duplicate Frame, from
        # before FrameActionBar/the right-click menu existed. Left in
        # place deliberately -- now arguably redundant with the action
        # bar's Duplicate button, but removing a working shortcut/menu
        # entry is a UI call for Chris, not something to drop silently.
        self.duplicate_frame_action = QAction("Duplicate Frame", self)
        self.duplicate_frame_action.setShortcuts(self._shortcuts("duplicate_frame"))
        self.duplicate_frame_action.triggered.connect(self._on_duplicate_frame)

        # Feature 12/Feature 5. Same shared no-arg handler already used by
        # the action bar's Delete button and the right-click menu's Delete
        # entry (see _on_delete_frame()'s docstring) -- this just gives it
        # a keyboard shortcut too, read from Config like every other
        # shortcut here.
        self.delete_frame_action = QAction("Delete Frame", self)
        self.delete_frame_action.setShortcuts(self._shortcuts("delete_frame"))
        self.delete_frame_action.triggered.connect(self._on_delete_frame)

        # Edit menu: name/FPS/resolution/camera info for the active
        # project. Guarded (no-op with a log line) rather than
        # proactively disabled when there's no active project yet --
        # same pattern as save_action/duplicate_frame_action above,
        # not a special case.
        self.project_settings_action = QAction("Project Settings...", self)
        self.project_settings_action.triggered.connect(self._on_project_settings)

        self.play_action = QAction("Play", self)
        self.play_action.setShortcuts(self._shortcuts("play_pause"))
        self.play_action.triggered.connect(self._on_toggle_play)

        # Feature 7 follow-up: a menu-driven way into Theater View that
        # doesn't require double-clicking a specific tile in the Project
        # Browser's Frames grid first. Opens on the Timeline's current
        # playhead frame -- see _on_open_theater_view()'s docstring for why
        # that's still safe under Chris's "must not move the playhead"
        # rule for this dialog.
        self.theater_view_action = QAction("Theater View...", self)
        self.theater_view_action.setShortcuts(self._shortcuts("theater_view"))
        self.theater_view_action.triggered.connect(self._on_open_theater_view)

        self.onion_action = QAction("Onion", self)
        self.onion_action.setCheckable(True)
        self.onion_action.setShortcuts(self._shortcuts("toggle_onion_skin"))
        self.onion_action.triggered.connect(self._on_toggle_onion_skin)

        self.safe_areas_action = QAction("Safe Areas", self)
        self.safe_areas_action.setCheckable(True)
        self.safe_areas_action.triggered.connect(self._on_toggle_safe_areas)

        # Composition guide overlays (Center Grid, Thirds, Golden Ratio,
        # etc.) -- mutually exclusive via QActionGroup, since
        # LiveViewWidget only ever shows one at a time. "None" is a real
        # entry in the group (not a separate toggle) so the group always
        # has exactly one checked action, matching
        # composition_guides.COMPOSITION_GUIDE_TYPES exactly.
        self.composition_guide_actions: dict[str, QAction] = {}
        self.composition_guide_group = QActionGroup(self)
        self.composition_guide_group.setExclusive(True)
        for guide_type in COMPOSITION_GUIDE_TYPES:
            action = QAction(COMPOSITION_GUIDE_LABELS[guide_type], self)
            action.setCheckable(True)
            action.setChecked(guide_type == GUIDE_NONE)
            action.triggered.connect(
                partial(self._on_composition_guide_selected, guide_type)
            )
            self.composition_guide_group.addAction(action)
            self.composition_guide_actions[guide_type] = action

        # Aspect ratio crop guides (1:1, 4:3, 16:9, etc.) -- same
        # mutually-exclusive-group-with-a-real-"None"-entry pattern as
        # composition guides above, and fully independent of it: both
        # groups can have a real selection active at once.
        self.aspect_ratio_guide_actions: dict[str, QAction] = {}
        self.aspect_ratio_guide_group = QActionGroup(self)
        self.aspect_ratio_guide_group.setExclusive(True)
        for ratio_type in ASPECT_RATIO_GUIDE_TYPES:
            action = QAction(ASPECT_RATIO_LABELS[ratio_type], self)
            action.setCheckable(True)
            action.setChecked(ratio_type == ASPECT_RATIO_NONE)
            action.triggered.connect(
                partial(self._on_aspect_ratio_guide_selected, ratio_type)
            )
            self.aspect_ratio_guide_group.addAction(action)
            self.aspect_ratio_guide_actions[ratio_type] = action

        self.camera_action = QAction("Rescan", self)
        self.camera_action.triggered.connect(self._on_rescan_camera)

        # "Export .blend" -- headless manifest -> script -> Blender
        # (--background) pipeline that saves a shareable .blend with no
        # interactive window, e.g. for handing a scene to a collaborator
        # who'll open it themselves. Distinct from export_render_action
        # below (video/image-sequence/GIF), and from blender_action
        # (interactive "Open in Blender").
        self.export_action = QAction("Export .blend...", self)
        self.export_action.triggered.connect(self._on_export_blend)

        self.export_render_action = QAction("Export...", self)
        self.export_render_action.setShortcuts(self._shortcuts("export"))
        self.export_render_action.triggered.connect(self._on_show_export_page)

        # Starts disabled, same reasoning as PlaybackControls' Export
        # button (see that widget's __init__) -- there's nothing to
        # composite before a project is open. Re-enabled in
        # _adopt_project().
        self.composite_workspace_action = QAction("Composite Workspace", self)
        self.composite_workspace_action.setEnabled(False)
        self.composite_workspace_action.triggered.connect(
            self._on_show_composite_workspace
        )

        self.blender_action = QAction("Open in Blender", self)
        self.blender_action.setShortcuts(self._shortcuts("open_in_blender"))
        self.blender_action.triggered.connect(self._on_open_in_blender)

        # Feature 11: only meaningful once "Open in Blender" has been
        # run this session -- see _on_toggle_live_blender_sync(). Starts
        # unchecked and disabled; re-enabled the moment a Blender bridge
        # launch succeeds (_on_blender_bridge_succeeded()).
        self.live_sync_action = QAction("Live Blender Sync", self)
        self.live_sync_action.setCheckable(True)
        self.live_sync_action.setEnabled(False)
        self.live_sync_action.triggered.connect(self._on_toggle_live_blender_sync)

        self.previous_frame_action = QAction("Previous Frame", self)
        self.previous_frame_action.setShortcuts(self._shortcuts("previous_frame"))
        self.previous_frame_action.triggered.connect(self._on_previous_frame)

        self.next_frame_action = QAction("Next Frame", self)
        self.next_frame_action.setShortcuts(self._shortcuts("next_frame"))
        self.next_frame_action.triggered.connect(self._on_next_frame)

        # Per Feature 12, Left/Right have no menu home -- unlike every other
        # shortcut above, which gets its shortcut "for free" by being added
        # to a menu in _build_menu_bar(). A QAction not added to any
        # menu/toolbar has no widget to inherit a shortcut context from, so
        # addAction() registers it directly on the window itself, keeping
        # the shortcut live with no visible menu entry.
        self.addAction(self.previous_frame_action)
        self.addAction(self.next_frame_action)

    def _shortcuts(self, action_name: str) -> list[QKeySequence]:
        """Look up the configured QKeySequence(s) for a named action.

        Reads the raw string(s) for `action_name` out of Config's
        "keyboard_shortcuts" setting via the Qt-free parse_shortcut()
        helper (core/config.py), then wraps each resulting key string in a
        real QKeySequence -- this method is the one place in the app that
        touches Qt for shortcut parsing, so parse_shortcut() itself stays
        unit-testable with no GUI setup at all. Returns an empty list (no
        shortcut assigned) if action_name isn't present in Config, rather
        than raising -- a missing/misconfigured entry should degrade to
        "no shortcut" for that one action, not crash startup.
        """
        raw = self.config.get("keyboard_shortcuts", {}).get(action_name, "")
        return [QKeySequence(key) for key in parse_shortcut(raw)]

    def _build_menu_bar(self) -> None:
        """Construct the top menu bar, using the shared actions."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        # Temporary home for Duplicate Frame -- see _create_actions().
        edit_menu.addAction(self.duplicate_frame_action)
        edit_menu.addAction(self.delete_frame_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.project_settings_action)

        capture_menu = menu_bar.addMenu("&Capture")
        capture_menu.addAction(self.capture_action)
        capture_menu.addAction(self.onion_action)

        guides_menu = menu_bar.addMenu("&Guides")
        guides_menu.addAction(self.safe_areas_action)
        guides_menu.addSeparator()
        composition_menu = guides_menu.addMenu("Composition Guide")
        for guide_type in COMPOSITION_GUIDE_TYPES:
            composition_menu.addAction(self.composition_guide_actions[guide_type])
            if guide_type == GUIDE_NONE:
                composition_menu.addSeparator()
        aspect_ratio_menu = guides_menu.addMenu("Aspect Ratio Guide")
        for ratio_type in ASPECT_RATIO_GUIDE_TYPES:
            aspect_ratio_menu.addAction(self.aspect_ratio_guide_actions[ratio_type])
            if ratio_type == ASPECT_RATIO_NONE:
                aspect_ratio_menu.addSeparator()

        playback_menu = menu_bar.addMenu("&Playback")
        playback_menu.addAction(self.play_action)
        playback_menu.addSeparator()
        playback_menu.addAction(self.theater_view_action)

        camera_menu = menu_bar.addMenu("&Camera")
        camera_menu.addAction(self.camera_action)

        composite_menu = menu_bar.addMenu("Co&mposite")
        composite_menu.addAction(self.composite_workspace_action)

        export_menu = menu_bar.addMenu("&Export")
        export_menu.addAction(self.export_render_action)
        export_menu.addSeparator()
        export_menu.addAction(self.blender_action)
        export_menu.addAction(self.export_action)
        export_menu.addAction(self.live_sync_action)

    def _build_central_panes(self) -> None:
        """Construct the full central area: the three-pane splitter on top,
        with the Timeline strip, the per-frame action bar, and Playback
        controls stacked below it -- all as one page of a QStackedWidget,
        with the Export page (reached via the Export button in Playback
        Controls' bottom-right corner, or the Export menu action) and the
        Composite workspace (reached via WorkspaceTabBar or the Composite
        menu action) as the other two pages. A real page switch rather
        than a dialog popup, per Chris's explicit choice -- see
        export_page.py's module docstring.

        WorkspaceTabBar sits *outside* the QStackedWidget, pinned to the
        very bottom of the window, so it's visible no matter which page
        is showing -- see workspace_tab_bar.py's module docstring for why
        that's what makes it a DaVinci-style workspace switcher rather
        than just a third way to reach the Export page.
        """
        self.project_browser_widget = ProjectBrowserWidget()
        self.live_view_widget = LiveViewWidget()
        self.inspector_panel = InspectorPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(13)
        splitter.addWidget(_titled_pane("Project Browser", self.project_browser_widget))
        splitter.addWidget(_titled_pane("Live View", self.live_view_widget))
        splitter.addWidget(_titled_pane("Inspector", self.inspector_panel))

        # Live Camera View gets most of the space and stays centered; the
        # two side panes are kept equal in width so Live View isn't pushed
        # off-center. setSizes() controls the *initial* pixel widths --
        # QSplitter sizes panes by each widget's size hint otherwise, which
        # is wrong here since "Inspector" and "Project Browser" are
        # different text lengths.
        splitter.setSizes([275, 730, 275])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

        self.timeline_widget = TimelineWidget()
        self.frame_action_bar = FrameActionBar()
        # Chris's "click-only" choice (session 13): the bar's controls are
        # hidden by default, and only ever shown by _on_frame_selected()
        # after an explicit thumbnail left-click. Uses set_bar_visible(),
        # not a plain setVisible() on the widget -- see that method's
        # docstring for why toggling the whole widget shifted Live View's
        # size.
        self.frame_action_bar.set_bar_visible(False)
        self.playback_controls = PlaybackControls()
        self.timecode_widget = TimecodeWidget()

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(12, 12, 12, 0)
        central_layout.setSpacing(10)
        central_layout.addWidget(splitter, 1)
        # Centered as one unit (not stretched full-width) directly below
        # Live View and above the Timeline strip, per Chris's explicit
        # placement -- AlignHCenter here is what actually centers it;
        # the widget itself just sizes to its own content (see
        # TimecodeWidget's docstring).
        central_layout.addWidget(self.timecode_widget, 0, Qt.AlignmentFlag.AlignHCenter)
        central_layout.addWidget(_titled_pane("Timeline", self.timeline_widget))
        central_layout.addWidget(self.frame_action_bar)
        central_layout.addWidget(self.playback_controls)

        self.export_page = ExportPage()
        self.export_page.back_requested.connect(self._on_export_page_back)
        self.export_page.export_requested.connect(self._on_export_page_export_requested)
        self.export_page.open_in_blender_requested.connect(self._on_open_in_blender)

        self.composite_workspace = CompositeWorkspace()
        self.composite_workspace.add_layer_requested.connect(
            self._on_composite_add_layer_requested
        )
        self.composite_workspace.remove_layer_requested.connect(
            self._on_composite_remove_layer_requested
        )
        self.composite_workspace.move_layer_requested.connect(
            self._on_composite_move_layer_requested
        )
        self.composite_workspace.layer_visibility_toggled.connect(
            self._on_composite_layer_visibility_toggled
        )
        self.composite_workspace.layer_opacity_changed.connect(
            self._on_composite_layer_opacity_changed
        )
        self.composite_workspace.layer_blend_mode_changed.connect(
            self._on_composite_layer_blend_mode_changed
        )

        self._editor_page = central_widget
        self._central_stack = QStackedWidget()
        self._central_stack.addWidget(self._editor_page)
        self._central_stack.addWidget(self.composite_workspace)
        self._central_stack.addWidget(self.export_page)

        # Maps each WorkspaceTabBar id to the page it shows, so
        # _on_workspace_selected() is a one-line lookup instead of an
        # if/elif chain that has to stay in sync with the tab bar's own
        # id list by hand.
        self._workspace_pages = {
            EDIT: self._editor_page,
            COMPOSITE: self.composite_workspace,
            EXPORT: self.export_page,
        }

        self.workspace_tab_bar = WorkspaceTabBar()
        self.workspace_tab_bar.workspace_selected.connect(self._on_workspace_selected)

        outer_widget = QWidget()
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self._central_stack, 1)
        outer_layout.addWidget(self.workspace_tab_bar)
        self.setCentralWidget(outer_widget)

    def _start_camera_controller(self) -> None:
        """Create the camera worker thread and wire its signals to the UI.

        Per the Developer Handbook's "UI Never Blocks" rule, all real
        camera work (device probing via OpenCV) happens on this dedicated
        thread, never on the main/UI thread. See camera_controller.py's
        module docstring for the full threading contract.
        """
        self._camera_thread = QThread(self)
        self.camera_controller = CameraController(self.event_bus)
        self.camera_controller.moveToThread(self._camera_thread)

        self._camera_thread.started.connect(self.camera_controller.start_scanning)
        self.camera_controller.camera_connecting.connect(self._on_camera_connecting)
        self.camera_controller.camera_connected.connect(self._on_camera_connected)
        self.camera_controller.camera_disconnected.connect(self._on_camera_disconnected)
        self.camera_controller.no_camera_found.connect(self._on_no_camera_found)

        self.inspector_panel.iso_changed.connect(
            self.camera_controller.iso_change_requested.emit
        )
        self.inspector_panel.shutter_changed.connect(
            self.camera_controller.shutter_change_requested.emit
        )
        self.inspector_panel.aperture_changed.connect(
            self.camera_controller.aperture_change_requested.emit
        )

        self._camera_thread.start()

    def _start_capture_controller(self) -> None:
        """Create the capture worker thread and wire its signals to the UI.

        Deliberately a SEPARATE thread from the camera-scanning thread
        (not reusing self._camera_thread) -- a capture in progress and a
        background camera-availability poll happening simultaneously on
        the same thread could contend with each other. Shares the SAME
        CameraManager instance camera_controller already owns, so capture
        (and Replace, per Feature 5) triggers the actual connected camera.
        """
        self._capture_thread = QThread(self)
        self.capture_controller = CaptureController(
            self.event_bus, self.camera_controller.camera_manager
        )
        self.capture_controller.moveToThread(self._capture_thread)

        self.capture_controller.capture_succeeded.connect(self._on_capture_succeeded)
        self.capture_controller.capture_failed.connect(self._on_capture_failed)
        self.capture_controller.disk_full.connect(self._on_disk_full)
        self.capture_controller.camera_lost.connect(self._on_camera_lost)
        self.capture_controller.replace_succeeded.connect(self._on_replace_succeeded)
        self.capture_controller.replace_failed.connect(self._on_replace_failed)
        self.capture_controller.replace_camera_lost.connect(
            self._on_replace_camera_lost
        )

        self._capture_thread.start()

    def _start_project_controller(self) -> None:
        """Create the project save/load worker thread and wire its signals.

        Deliberately a THIRD separate thread, distinct from both the
        camera and capture threads -- Save/Open can be triggered at any
        time and shouldn't contend with either an in-progress capture or
        a background camera scan.
        """
        self._project_thread = QThread(self)
        self.project_controller = ProjectController(self.event_bus)
        self.project_controller.moveToThread(self._project_thread)

        self.project_controller.save_succeeded.connect(self._on_save_succeeded)
        self.project_controller.save_failed.connect(self._on_save_failed)
        self.project_controller.load_succeeded.connect(self._on_load_succeeded)
        self.project_controller.load_failed.connect(self._on_load_failed)

        self._project_thread.start()

    def _start_live_view_controller(self) -> None:
        """Create the live-view worker thread and wire its signal to the UI.

        A FOURTH separate thread -- same reasoning as the other three,
        preview polling runs at up to ~30 times a second and shouldn't
        contend with camera scanning, capture, or project save/load.
        Shares the SAME CameraManager instance camera_controller owns, so
        it reflects whatever camera is actually connected.

        histogram_ready is connected the same direct way as frame_ready --
        both are Qt Signals originating on this controller's worker
        thread, so Qt's queued-connection machinery already marshals each
        call safely onto the receiving widget's own (main) thread. No
        additional indirection is needed for either.
        """
        self._live_view_thread = QThread(self)
        self.live_view_controller = LiveViewController(
            self.event_bus, self.camera_controller.camera_manager
        )
        self.live_view_controller.moveToThread(self._live_view_thread)

        self._live_view_thread.started.connect(self.live_view_controller.start)
        self.live_view_controller.frame_ready.connect(self.live_view_widget.show_frame)
        self.live_view_controller.histogram_ready.connect(
            self.inspector_panel.histogram_widget.update_histogram
        )

        self._live_view_thread.start()

    def _start_onion_skin_controller(self) -> None:
        """Create the onion skin worker thread and wire its signal to the UI.

        A FIFTH separate thread -- onion skin refreshes read a handful of
        frame files off disk (see onion_skin_controller.py), which per the
        Handbook's "UI Never Blocks" rule must not run on the main thread,
        and shouldn't contend with camera scanning, capture, live preview,
        or project save/load either.
        """
        self._onion_skin_thread = QThread(self)
        self.onion_skin_controller = OnionSkinController()
        self.onion_skin_controller.moveToThread(self._onion_skin_thread)

        self.onion_skin_controller.frames_ready.connect(
            self.live_view_widget.set_onion_layers
        )

        self._onion_skin_thread.start()

    def _start_playback_controller(self) -> None:
        """Create the playback worker thread and wire its signals to the UI.

        A SIXTH separate thread -- playback runs continuously while active
        and reads a frame image off disk on every tick (see
        playback_controller.py's module docstring), so it shouldn't contend
        with camera scanning, capture, live preview, onion skin refreshes,
        or project save/load.
        """
        self._playback_thread = QThread(self)
        self.playback_controller = PlaybackController()
        self.playback_controller.moveToThread(self._playback_thread)

        self.playback_controller.frame_ready.connect(self.live_view_widget.show_frame)
        self.playback_controller.playhead_advanced.connect(
            self._on_playback_playhead_advanced
        )
        self.playback_controller.playback_finished.connect(self._on_playback_finished)

        self._playback_thread.start()

    def _start_autosave_controller(self) -> None:
        """Create the autosave worker thread and wire its signals.

        A SEVENTH separate thread -- see autosave_controller.py's module
        docstring for why an autosave write shouldn't contend with any of
        the other six.

        The 30-second periodic timer itself lives on the MAIN thread
        (self._autosave_timer below), NOT this worker thread -- unlike
        CameraController.start_scanning()'s timer, this one's callback
        does no real work of its own (just a None/shutdown check and a
        signal emit, see _on_autosave_timer_tick()), so there's no "UI
        Never Blocks" reason to create it on the worker thread, and
        keeping it on the main thread means it can read self.project
        directly rather than needing a separately-tracked, cross-thread
        -synced copy of it (same "carry the Project on the signal itself"
        reasoning as capture_controller.py's capture_requested).
        """
        self._autosave_thread = QThread(self)
        self.autosave_controller = AutosaveController()
        self.autosave_controller.moveToThread(self._autosave_thread)

        self.autosave_controller.autosave_succeeded.connect(self._on_autosave_succeeded)
        self.autosave_controller.autosave_failed.connect(self._on_autosave_failed)

        self._autosave_thread.start()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._on_autosave_timer_tick)
        self._autosave_timer.start()

    def _start_export_controller(self) -> None:
        """Create the export worker thread and wire its signals.

        An EIGHTH separate thread -- rendering a full project to
        video/GIF, or copying every frame into an image sequence, can
        take real time on a long project and shouldn't contend with any
        of the other seven.
        """
        self._export_thread = QThread(self)
        self.export_controller = ExportController(self.event_bus)
        self.export_controller.moveToThread(self._export_thread)

        self.export_controller.export_succeeded.connect(self._on_export_succeeded)
        self.export_controller.export_failed.connect(self._on_export_failed)
        self.export_controller.export_progress.connect(self._on_export_progress)

        self._export_thread.start()

    def _start_blender_controller(self) -> None:
        """Create the Blender bridge worker thread and wire its signals.

        A NINTH separate thread -- building the manifest/scene script and
        launching a real Blender process shouldn't contend with any of
        the other eight, same "UI Never Blocks" reasoning as every other
        _start_x_controller() method above. (Feature 11's Live Blender
        Sync is a further, TENTH thread of its own -- see
        _start_blender_sync_controller().)
        """
        self._blender_thread = QThread(self)
        self.blender_controller = BlenderBridgeController(self.config)
        self.blender_controller.moveToThread(self._blender_thread)

        self.blender_controller.bridge_succeeded.connect(
            self._on_blender_bridge_succeeded
        )
        self.blender_controller.bridge_failed.connect(self._on_blender_bridge_failed)
        self.blender_controller.executable_not_found.connect(
            self._on_blender_executable_not_found
        )
        self.blender_controller.already_running.connect(
            self._on_blender_already_running
        )
        self.blender_controller.blend_export_succeeded.connect(
            self._on_blend_export_succeeded
        )
        self.blender_controller.blend_export_failed.connect(
            self._on_blend_export_failed
        )
        self.blender_controller.blend_export_executable_not_found.connect(
            self._on_blend_export_executable_not_found
        )

        self._blender_thread.start()

    def _start_blender_sync_controller(self) -> None:
        """Create Feature 11's Live Blender Sync worker thread and wire
        its signals.

        A TENTH separate thread, deliberately distinct from
        BlenderBridgeController's own -- see
        blender_sync_controller.py's module docstring for why a slow
        per-frame sync send must never contend with (or be contended by)
        an "Open in Blender"/"Export .blend" launch.
        """
        self._blender_sync_thread = QThread(self)
        self.blender_sync_controller = BlenderSyncController()
        self.blender_sync_controller.moveToThread(self._blender_sync_thread)

        self.blender_sync_controller.sync_connected.connect(
            self._on_live_sync_connected
        )
        self.blender_sync_controller.sync_disconnected.connect(
            self._on_live_sync_disconnected
        )
        self.blender_sync_controller.sync_connect_failed.connect(
            self._on_live_sync_connect_failed
        )

        self._blender_sync_thread.start()

    def _on_autosave_timer_tick(self) -> None:
        """Fire one periodic autosave, per Feature 8's "every 30 seconds".

        No-op if no project is open yet -- same guard pattern as
        _on_capture() and _on_save_project(). Also no-op once shutdown has
        started, same self._shutting_down guard closeEvent()'s own
        docstring explains for _refresh_onion_skin() -- without it, a tick
        landing between "closeEvent sets _shutting_down" and "the autosave
        thread is actually torn down" would emit onto a worker thread
        that's already been told to quit.
        """
        if self._shutting_down or self.project is None:
            return
        self.autosave_controller.autosave_requested.emit(self.project)

    def _on_autosave_succeeded(self, autosave_path: str) -> None:
        """Log-only. Feature 8: "Autosave should be silent." """
        logger.info("Autosave written: %s", autosave_path)

    def _on_autosave_failed(self, message: str) -> None:
        """Log-only, deliberately no dialog.

        Feature 8: "Autosave should be silent... Never interrupt
        capture." Unlike ProjectController's save_failed (an explicit
        Ctrl+S the user is actively waiting on), a failed background
        .autosave/ snapshot must not interrupt the user -- project.ffproj
        itself is kept current independently by capture_service's own
        synchronous save after every capture/delete/replace/duplicate/
        notes/marker change, so a failed autosave snapshot never puts
        real project data at risk on its own.
        """
        logger.error("Autosave failed: %s", message)

    def _wire_playback_controls(self) -> None:
        """Connect the PlaybackControls widget to real playback state.

        PlaybackControls itself holds no logic (see its own docstring) --
        MainWindow owns self.playback_settings and drives
        PlaybackController directly from these raw widget signals.
        """
        self.playback_controls.play_button.clicked.connect(self._on_toggle_play)
        self.playback_controls.loop_button.toggled.connect(self._on_loop_toggled)
        self.playback_controls.speed_combo.currentIndexChanged.connect(
            self._on_speed_changed
        )
        self.playback_controls.export_button.clicked.connect(self._on_show_export_page)

    def _wire_timeline_widget(self) -> None:
        """Connect the TimelineWidget to real timeline state.

        TimelineWidget holds no Timeline/Project of its own (see its own
        docstring) -- it only emits frame_selected with a raw index when a
        thumbnail is clicked, and frame_context_menu_requested with a raw
        index + global position on right-click. MainWindow owns
        self.timeline and is responsible for translating an index into
        either an actual playhead move (Timeline.go_to_index()) or the
        real Frame it refers to (self.timeline.frames[index]).
        """
        self.timeline_widget.frame_selected.connect(self._on_frame_selected)
        self.timeline_widget.frame_context_menu_requested.connect(
            self._on_frame_context_menu_requested
        )
        self.timeline_widget.frames_reorder_requested.connect(
            self._on_frames_reorder_requested
        )

    def _wire_frame_action_bar(self) -> None:
        """Connect FrameActionBar's controls to real per-frame actions.

        FrameActionBar holds no Project/Timeline/Frame of its own (see its
        own docstring) -- every handler here reads whichever frame is
        currently selected (self.timeline.current_frame) at the moment the
        control is used, rather than trusting a value captured earlier.
        """
        self.frame_action_bar.delete_button.clicked.connect(self._on_delete_frame)
        self.frame_action_bar.replace_button.clicked.connect(self._on_replace_frame)
        self.frame_action_bar.duplicate_button.clicked.connect(self._on_duplicate_frame)
        self.frame_action_bar.marker_button.clicked.connect(self._on_toggle_marker)
        self.frame_action_bar.notes_edit.editingFinished.connect(self._on_notes_edited)

    def _wire_project_browser(self) -> None:
        """Connect the Project Browser's signals to their handlers.

        ProjectBrowserWidget holds no Project/Timeline of its own (see its
        own docstring), and emits frame_selected with the same raw
        Project.frames/Timeline.frames index TimelineWidget.frame_selected
        already uses -- so double-clicking a frame in the browser tree
        goes through the exact same _on_frame_selected() path a Timeline
        thumbnail click does, per the hand-off's "one shared set of
        handler methods taking a raw identifier" convention.

        The Frames grid's right-click menu reuses
        _on_frame_context_menu_requested directly, with zero new logic --
        ProjectBrowserWidget.frame_context_menu_requested emits the exact
        same (index, global_pos) shape TimelineWidget's own signal does,
        so right-clicking a frame in the browser shows the identical
        Delete/Replace/Duplicate/Marker menu right-clicking it in the
        Timeline strip does. Notes and Exports get their own handlers,
        since they offer a different set of actions.

        Double-clicking a Frames grid tile is deliberately NOT wired to
        frame_selected/_on_frame_selected -- it emits a separate
        frame_preview_requested signal instead (see
        ProjectBrowserWidget's module docstring), routed to
        _on_frame_preview_requested below, per Chris's explicit choice
        that opening the Theater View preview must not move the
        Timeline's playhead or reveal the frame action bar.
        """
        self.project_browser_widget.frame_selected.connect(self._on_frame_selected)
        self.project_browser_widget.frame_context_menu_requested.connect(
            self._on_frame_context_menu_requested
        )
        self.project_browser_widget.note_context_menu_requested.connect(
            self._on_project_browser_note_context_menu_requested
        )
        self.project_browser_widget.export_context_menu_requested.connect(
            self._on_project_browser_export_context_menu_requested
        )
        self.project_browser_widget.frame_preview_requested.connect(
            self._on_frame_preview_requested
        )

        # Audio/References/Overlays: one add_requested and one item_
        # context_menu_requested signal per kind, wired generically via
        # functools.partial binding each to its own kind string, rather
        # than three near-identical handler methods -- same reasoning
        # ProjectBrowserWidget/asset_service.py already use.
        for kind in ("audio", "references", "overlays"):
            getattr(self.project_browser_widget, f"{kind}_add_requested").connect(
                partial(self._on_asset_add_requested, kind)
            )
            getattr(
                self.project_browser_widget, f"{kind}_item_context_menu_requested"
            ).connect(partial(self._on_asset_item_context_menu_requested, kind))

    def _on_frame_selected(self, index: int) -> None:
        """React to a thumbnail click in the Timeline strip.

        No-op if there's no active project/timeline yet -- same guard
        pattern as _refresh_onion_skin(); TimelineWidget shouldn't be able
        to emit a click with no timeline behind it, but this keeps the
        handler safe regardless. Moves the playhead to the clicked frame's
        index, then refreshes Onion Skin, the Timeline strip's selection
        border, and the action bar so it reflects the newly selected frame.

        This is the ONLY place that reveals the frame action bar --
        _refresh_frame_action_bar() itself always hides it (see that
        method's docstring), so showing it here, right after that call, is
        what makes a left-click on a thumbnail the sole way to bring the
        bar up, per Chris's "click-only" choice.
        """
        if self.timeline is None:
            return
        self.timeline.go_to_index(index)
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()
        self.frame_action_bar.set_bar_visible(True)

    def _on_frames_reorder_requested(
        self, frame_numbers: list[int], insert_before: int | None
    ) -> None:
        """React to TimelineWidget's Shift/Ctrl+click multi-select + drag-
        to-reorder gesture (backlog item #2).

        `frame_numbers` and `insert_before` are exactly what
        ReorderFramesCommand/reorder_frames() expect -- TimelineWidget
        resolves screen position to these before emitting, since only it
        knows each thumbnail's on-screen geometry; MainWindow never learns
        pixel coordinates, only frame identities, same "dumb widget,
        MainWindow owns behavior" split every other TimelineWidget signal
        already follows.

        No-op (with a log line) if there's no active project/timeline, or
        if the drag ended without a valid drop target -- TimelineWidget
        can't emit this signal in the first place unless a reorder-drag
        actually started, but both guards stay for the same defensive
        reasons every other handler in this file has them.

        Tracks the playhead across the reorder by the current Frame
        object's identity, not its number -- reorder_frames() may well
        change the current frame's own number if it was part of the
        moved block or displaced by it, so re-finding it by number
        afterward could land on the wrong frame (or a stale one).
        list.index() on the same object is safe here even though its
        fields just changed, since it's being compared against itself.
        """
        if self.project is None or self.timeline is None:
            logger.warning("Frame reorder requested with no active project; ignoring")
            return
        if not frame_numbers:
            return

        current_frame_obj = self.timeline.current_frame

        command = ReorderFramesCommand(
            self.project, self.event_bus, frame_numbers, insert_before
        )
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()

        if current_frame_obj is not None:
            try:
                new_index = self.timeline.frames.index(current_frame_obj)
            except ValueError:
                pass
            else:
                self.timeline.go_to_index(new_index)

        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_frame_preview_requested(self, index: int) -> None:
        """Open a movable/resizable Theater View preview for frame `index`.

        Deliberately does NOT call self.timeline.go_to_index() or
        _on_frame_selected() -- per Chris's explicit choice, previewing a
        frame from the Project Browser's Frames grid must not move the
        Timeline's playhead or reveal the frame action bar, unlike every
        other click/double-click path in this file. `index` is into
        self.timeline.frames (the same ordered list
        ProjectBrowserWidget's own _ordered_frames() mirrors), so it's
        passed straight through unmodified. Modal (`exec()`), so the
        dialog owns input focus for its own Left/Right/Escape browsing
        until closed, then control returns here with no other state
        touched in between.
        """
        if self.project is None or self.timeline is None:
            return
        dialog = TheaterViewDialog(
            self.project.project_path,
            self.timeline.frames,
            index,
            fps=self.project.fps,
            parent=self,
        )
        dialog.exec()

    def _on_open_theater_view(self) -> None:
        """React to Playback menu > Theater View... -- open the same
        TheaterViewDialog the Project Browser's frame-tile double-click
        uses, starting on whatever frame the Timeline's playhead is
        currently sitting on.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_toggle_play(). Reading
        self.timeline.current_index here only picks the dialog's
        *starting* frame; exactly like _on_frame_preview_requested(), the
        dialog then owns its own local browsing position from that point
        on and never writes back to Timeline.current_index, so this menu
        entry is just a second door into the identical read-only preview
        -- it doesn't relax Chris's "must not move the playhead" rule for
        this dialog, it just picks a different starting frame than a
        Frames-grid double-click would.
        """
        if self.project is None or self.timeline is None:
            logger.warning("Theater View requested with no active project; ignoring")
            return
        dialog = TheaterViewDialog(
            self.project.project_path,
            self.timeline.frames,
            self.timeline.current_index,
            fps=self.project.fps,
            parent=self,
        )
        dialog.exec()

    def _on_frame_context_menu_requested(self, index: int, global_pos) -> None:
        """Show Feature 5's right-click menu for a timeline thumbnail.

        Right-clicking a frame that isn't currently selected first moves
        the playhead to it (same as a left-click would), so the selection
        border reflects the frame the menu is about to act on. The frame
        action bar stays hidden through this, though -- per Chris's
        "click-only" choice, right-clicking is a deliberately separate
        access path to these same actions, not another way to reveal the
        action bar (see _refresh_frame_action_bar()'s docstring).
        """
        if self.timeline is None:
            return
        self.timeline.go_to_index(index)
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

        frame = self.timeline.frames[index]

        menu = QMenu(self)
        delete_action = menu.addAction("Delete")
        replace_action = menu.addAction("Replace")
        duplicate_action = menu.addAction("Duplicate")
        marker_action = menu.addAction(
            "Remove Marker" if frame.marker else "Add Marker"
        )
        chosen = menu.exec(global_pos)

        if chosen is delete_action:
            self._delete_frame(frame.number)
        elif chosen is replace_action:
            self._replace_frame(frame.number)
        elif chosen is duplicate_action:
            self._duplicate_frame(frame.number)
        elif chosen is marker_action:
            self._toggle_marker(frame.number)

    def _on_project_browser_note_context_menu_requested(
        self, index: int, global_pos
    ) -> None:
        """Show the Project Browser Notes list's right-click menu.

        Jump to Frame: navigates only, same as a double-click on the same
        row -- routed through the shared _on_frame_selected() path.
        Edit Note: navigates AND gives keyboard focus to the action bar's
        Notes field with its text selected, ready to type over -- the
        fastest path from "I see a note I want to change" to actually
        changing it. Clear Note: a direct SetFrameNotesCommand to "",
        deliberately without navigating away first, since clearing a note
        while browsing several frames' notes shouldn't interrupt browsing
        by also jumping the Timeline playhead.
        """
        if self.timeline is None:
            return
        frame = self.timeline.frames[index]

        menu = QMenu(self)
        jump_action = menu.addAction("Jump to Frame")
        edit_action = menu.addAction("Edit Note")
        clear_action = menu.addAction("Clear Note")
        clear_action.setEnabled(bool(frame.notes.strip()))
        chosen = menu.exec(global_pos)

        if chosen is jump_action:
            self._on_frame_selected(index)
        elif chosen is edit_action:
            self._on_frame_selected(index)
            self.frame_action_bar.notes_edit.setFocus()
            self.frame_action_bar.notes_edit.selectAll()
        elif chosen is clear_action:
            self._clear_frame_notes(frame.number)

    def _on_frames_reorder_requested(
        self, frame_numbers: list[int], insert_before: int | None
    ) -> None:
        """Reorder dragged frame(s) -- TimelineWidget's Shift/Ctrl+click
        multi-select plus drag-to-reorder (backlog item #2).

        `insert_before` is a frame number (insert before that frame) or
        None (move to the end), exactly as ReorderFramesCommand/
        reorder_frames expect -- TimelineWidget resolves screen position
        to this before emitting, since only it knows each thumbnail's
        on-screen geometry.

        Tracks the playhead by the current Frame *object* rather than its
        number, since reordering renumbers frames -- list.index() on the
        same object instance still finds it correctly no matter what its
        .number field was renamed to.
        """
        if self.project is None or self.timeline is None:
            logger.warning("Frame reorder requested with no active project; ignoring")
            return
        if not frame_numbers:
            return

        current_frame_obj = self.timeline.current_frame

        command = ReorderFramesCommand(
            self.project, self.event_bus, frame_numbers, insert_before
        )
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()

        if current_frame_obj is not None:
            try:
                self.timeline.go_to_index(self.timeline.frames.index(current_frame_obj))
            except ValueError:
                pass

        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _clear_frame_notes(self, frame_number: int) -> None:
        """Set frame_number's notes to "" via an undoable command.

        Shared logic behind the Notes list's Clear Note action -- kept as
        its own method (rather than inlined in the menu handler above) in
        case another entry point needs to clear a note the same way in
        the future, matching how _delete_frame()/_replace_frame()/
        _duplicate_frame() are already split from their _on_* callers.
        """
        if self.project is None:
            return
        command = SetFrameNotesCommand(self.project, self.event_bus, frame_number, "")
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self._refresh_timeline_widget()
        if self.timeline is not None and self.timeline.current_frame is not None:
            if self.timeline.current_frame.number == frame_number:
                self.frame_action_bar.notes_edit.setText("")

    def _on_project_browser_export_context_menu_requested(
        self, filename: str, global_pos
    ) -> None:
        """Show the Project Browser Exports list's right-click menu.

        Open File launches the export with the OS's default handler for
        its type (e.g. the system video player for a rendered clip).
        Open Containing Folder opens project_path/exports itself, the
        same QDesktopServices.openUrl() pattern _show_missing_frames_
        dialog() already uses for "Locate Missing Files" -- there's no
        cross-platform way to open a folder with one specific file
        pre-selected, so this opens the folder and leaves finding the
        file to the user, same tradeoff as that existing call site.
        Delete Export removes the file from disk after confirmation.
        Exports are regenerated output, not source data (the Feature 10
        exporter that will eventually populate this folder can always
        produce the file again), so this is a plain confirm-then-delete
        with no undo -- unlike Delete Frame, which protects irreplaceable
        captured images.
        """
        if self.project is None or self.project.project_path is None:
            return
        exports_dir = self.project.project_path / "exports"
        file_path = exports_dir / filename

        menu = QMenu(self)
        open_action = menu.addAction("Open File")
        open_folder_action = menu.addAction("Open Containing Folder")
        delete_action = menu.addAction("Delete Export")
        chosen = menu.exec(global_pos)

        if chosen is open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path)))
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(exports_dir)))
        elif chosen is delete_action:
            self._delete_export(file_path)

    def _delete_export(self, file_path: Path) -> None:
        """Confirm, then permanently delete an export from disk.

        Handles both single-file exports (video/GIF) and the
        image-sequence exports' folders -- export_image_sequence() writes
        a whole numbered-frame folder, not one file, so this removes it
        with shutil.rmtree() rather than Path.unlink(), which only works
        on files. No undo either way -- see
        _on_project_browser_export_context_menu_requested's docstring for
        why that's the deliberate choice for exports specifically, unlike
        every frame-destroying action in this file.
        """
        confirm = QMessageBox.question(
            self,
            "Delete Export",
            f'Delete "{file_path.name}"? This cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()
        except OSError as exc:
            logger.error("Failed to delete export %s: %s", file_path, exc)
            QMessageBox.warning(
                self, "Delete Failed", f"Could not delete {file_path.name}."
            )
            return
        logger.info("Export deleted: %s", file_path)
        self.project_browser_widget.set_project(self.project)

    def _on_workspace_selected(self, workspace_id: str) -> None:
        """Switch the central stack to `workspace_id`'s page and keep
        WorkspaceTabBar's highlighted tab in sync.

        This is the single place any workspace switch goes through --
        WorkspaceTabBar's own clicks, the Export/Composite menu actions,
        Playback Controls' Export button, and ExportPage's Back button
        all funnel through here (via the thin wrapper methods below)
        rather than each calling _central_stack.setCurrentWidget()
        directly, so the tab bar can never drift out of sync with
        whichever page is actually on screen.

        Args:
            workspace_id: One of workspace_tab_bar.EDIT, .COMPOSITE,
                .EXPORT.
        """
        if workspace_id == EXPORT:
            self.export_page.set_project(self.project)
        elif workspace_id == COMPOSITE:
            self.composite_workspace.set_project(self.project)
            self._refresh_composite_preview()

        self._central_stack.setCurrentWidget(self._workspace_pages[workspace_id])
        self.workspace_tab_bar.set_current_workspace(workspace_id)

    def _on_show_export_page(self) -> None:
        """Show the Export page. Reached from the Export button in the
        bottom-right corner of Playback Controls, or the "Export..."
        menu action -- both funnel through _on_workspace_selected() so
        the page is never shown stale and the tab bar stays in sync.
        """
        self._on_workspace_selected(EXPORT)

    def _on_show_composite_workspace(self) -> None:
        """Show the Composite workspace. Reached from the Composite menu
        action (WorkspaceTabBar's own tab click goes straight to
        _on_workspace_selected() instead)."""
        self._on_workspace_selected(COMPOSITE)

    def _on_export_page_back(self) -> None:
        """Return to the editor from the Export page's Back button."""
        self._on_workspace_selected(EDIT)

    # -- Composite workspace ---------------------------------------------

    def _on_composite_add_layer_requested(self, source: str) -> None:
        """Handle CompositeWorkspace's "Add Layer" button.

        A single discrete action, so it goes through UndoManager like
        every other structural project edit -- see composite_commands.py's
        module docstring for why opacity/blend-mode/visibility tweaks
        below do not.
        """
        if self.project is None:
            return
        command = AddCompositeLayerCommand(self.project, self.event_bus, source)
        self.undo_manager.execute(command)
        self.composite_workspace.set_project(self.project)
        self._refresh_composite_preview()

    def _on_composite_remove_layer_requested(self, index: int) -> None:
        if self.project is None:
            return
        command = RemoveCompositeLayerCommand(self.project, self.event_bus, index)
        self.undo_manager.execute(command)
        self.composite_workspace.set_project(self.project)
        self._refresh_composite_preview()

    def _on_composite_move_layer_requested(
        self, old_index: int, new_index: int
    ) -> None:
        if self.project is None:
            return
        command = ReorderCompositeLayerCommand(
            self.project, self.event_bus, old_index, new_index
        )
        self.undo_manager.execute(command)
        self.composite_workspace.set_project(self.project)
        self._refresh_composite_preview()

    def _on_composite_layer_visibility_toggled(self, index: int, visible: bool) -> None:
        self._apply_composite_layer_edit(index, visible=visible)

    def _on_composite_layer_opacity_changed(self, index: int, opacity: float) -> None:
        self._apply_composite_layer_edit(index, opacity=opacity)

    def _on_composite_layer_blend_mode_changed(
        self, index: int, blend_mode: str
    ) -> None:
        self._apply_composite_layer_edit(index, blend_mode=blend_mode)

    def _apply_composite_layer_edit(
        self,
        index: int,
        *,
        opacity: float | None = None,
        blend_mode: str | None = None,
        visible: bool | None = None,
    ) -> None:
        """Mutate one CompositeLayer's field directly and re-save.

        Deliberately not a Command: an opacity spinner or blend-mode
        dropdown fires this once per intermediate value while the user
        is still adjusting it, and a project already treats "no undo
        entry per slider tick" as normal (e.g. GIF fps in ExportPage
        isn't undoable either) -- see composite_commands.py's module
        docstring. What *is* undoable is adding/removing/reordering the
        layer itself, which these three signals never do. Still
        publishes COMPOSITE_LAYER_UPDATED after saving, though, matching
        every other mutate-then-save path in the app -- the "no Command"
        exception here is specifically about undo granularity, not about
        skipping the EventBus notification too.
        """
        if self.project is None or not (
            0 <= index < len(self.project.composite_layers)
        ):
            return
        layer = self.project.composite_layers[index]
        if opacity is not None:
            layer.opacity = opacity
        if blend_mode is not None:
            layer.blend_mode = blend_mode
        if visible is not None:
            layer.visible = visible
        ProjectSerializer.save(self.project)
        self.event_bus.publish("COMPOSITE_LAYER_UPDATED", {"index": index})
        self._refresh_composite_preview()

    def _refresh_composite_preview(self) -> None:
        """Recompute the Composite workspace's preview pixmap from
        scratch and hand it to composite_workspace.set_preview_pixmap().

        Loads the same "last captured frame" thumbnail ExportPage
        previews from (see that page's _refresh_preview() docstring for
        the thumbnails/{number:06d}.jpg convention this reuses), then
        blends every visible composite_layers entry over it via
        image_processing/compositor.py -- the one place in this file
        pixel data crosses from disk into that Qt-free module and back
        out again as a QPixmap.

        A no-op if the Composite workspace isn't the page currently on
        screen -- no sense spending the compositing work on a page
        nobody can see. Every other "nothing to show yet" case (no
        project, no frames captured, thumbnail missing) sets a specific
        placeholder message via set_preview_pixmap() instead of leaving
        the box blank with no explanation.
        """
        if self._central_stack.currentWidget() is not self.composite_workspace:
            return
        if self.project is None:
            self.composite_workspace.set_preview_pixmap(None, message="No project open")
            return
        if self.project.project_path is None or not self.project.frames:
            self.composite_workspace.set_preview_pixmap(
                None, message="Capture at least one frame first"
            )
            return

        thumbnail_path = (
            self.project.project_path
            / "thumbnails"
            / f"{self.project.frames[-1].number:06d}.jpg"
        )
        if not thumbnail_path.exists():
            self.composite_workspace.set_preview_pixmap(
                None, message="Preview unavailable"
            )
            return

        try:
            base_frame = np.array(Image.open(thumbnail_path).convert("RGB"))
            height, width = base_frame.shape[:2]

            layers: list[tuple[np.ndarray, float, str]] = []
            for layer in self.project.composite_layers:
                if not layer.visible:
                    continue
                layer_path = self.project.project_path / layer.source
                if not layer_path.exists():
                    continue
                layer_image = Image.open(layer_path).convert("RGB")
                if layer_image.size != (width, height):
                    # Overlays are arbitrary user images, not guaranteed
                    # to already match the project's capture resolution
                    # -- resize to fit rather than raising, so a
                    # slightly-mismatched overlay still previews instead
                    # of blanking the whole page.
                    layer_image = layer_image.resize((width, height))
                layers.append((np.array(layer_image), layer.opacity, layer.blend_mode))

            composited = compositor.composite_frame(base_frame, layers)
        except (OSError, compositor.CompositorError) as exc:
            logger.error("Composite preview failed: %s", exc)
            self.composite_workspace.set_preview_pixmap(
                None, message="Preview unavailable"
            )
            return

        self.composite_workspace.set_preview_pixmap(_numpy_rgb_to_pixmap(composited))

    def _on_export_page_export_requested(self, request: ExportRequest) -> None:
        """Fire only the formats checked on the Export page, on
        ExportController's worker thread -- see that module's
        docstring for why exports run off the main thread.

        The page itself keeps its own Export button disabled until at
        least one format is checked, so this is only ever reached with
        something real to run. Disables that same button for the
        export's duration so a second click can't overlap one already
        in progress; re-enabled in both _on_export_succeeded() and
        _on_export_failed(). Also shows a real progress dialog, updated
        by _on_export_progress() as ExportController re-emits
        export_all()'s per-frame progress -- no Cancel button, since
        export_service has no mid-export cancellation to hook it up to.
        """
        if self.project is None or self.project.project_path is None:
            return
        self.export_page.set_export_in_progress(True)

        self._export_progress_dialog = QProgressDialog(
            "Starting export...", "", 0, 100, self
        )
        self._export_progress_dialog.setWindowTitle("Exporting")
        self._export_progress_dialog.setCancelButton(None)
        self._export_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress_dialog.setMinimumDuration(0)
        self._export_progress_dialog.setValue(0)

        self.export_controller.export_requested.emit(request)

    def _on_export_progress(self, progress: ExportProgress) -> None:
        """Update the export progress dialog from ExportController's
        re-emitted ExportProgress. No-op if the dialog was already
        closed (e.g. a stray late signal after _close_export_progress()
        already ran) -- see _on_export_render()'s docstring."""
        if self._export_progress_dialog is None:
            return
        label = _EXPORT_FORMAT_LABELS.get(progress.format_key, progress.format_key)
        percent = int(progress.current / progress.total * 100) if progress.total else 0
        self._export_progress_dialog.setLabelText(
            f"{label}: {progress.current}/{progress.total} frames"
        )
        self._export_progress_dialog.setValue(percent)

    def _close_export_progress(self) -> None:
        """Close and release the export progress dialog, if one is
        showing. Shared by _on_export_succeeded() and
        _on_export_failed() -- every path out of an export needs this,
        successful or not."""
        if self._export_progress_dialog is not None:
            self._export_progress_dialog.close()
            self._export_progress_dialog = None

    def _on_export_succeeded(self, result: ExportResult) -> None:
        """Report the finished export, refreshing the Exports list either
        way -- a partial success (see export_all()'s docstring) still
        writes real files that belong there."""
        self.export_page.set_export_in_progress(False)
        self._close_export_progress()
        if self.project is not None:
            self.project_browser_widget.set_project(self.project)

        if not result.failed:
            QMessageBox.information(
                self,
                "Export Complete",
                "Exported: " + ", ".join(sorted(result.succeeded)),
            )
            return

        lines = [f"{key}: {message}" for key, message in result.failed.items()]
        QMessageBox.warning(
            self,
            "Export Partially Failed",
            "Succeeded: "
            + (", ".join(sorted(result.succeeded)) or "none")
            + "\n\nFailed:\n"
            + "\n".join(lines),
        )

    def _on_export_failed(self, message: str) -> None:
        """Report a total export failure (e.g. no frames to export)."""
        self.export_page.set_export_in_progress(False)
        self._close_export_progress()
        QMessageBox.warning(self, "Export Failed", message)

    def _on_open_in_blender(self) -> None:
        """Feature 10: kick off the full manifest -> script -> launch
        pipeline on BlenderBridgeController's worker thread.

        Disables the menu action -- and, since "Open in Blender" now
        also lives as a button on the Export page (see that module's
        docstring), that button too -- for the duration, re-enabled in
        every one of the controller's four possible outcomes
        (succeeded/failed/executable-not-found/already-running).
        """
        if self.project is None or self.project.project_path is None:
            return
        self.blender_action.setEnabled(False)
        self.export_page.set_blender_action_in_progress(True)
        self.blender_controller.bridge_requested.emit(self.project)

    def _on_blender_bridge_succeeded(self, blend_output_path: str) -> None:
        """Blender was launched successfully and told to save its scene
        to blend_output_path. Blender opens its own window directly --
        this app has no further "Open Scene" step of its own to perform,
        so this is log-only plus re-enabling the action, deliberately no
        dialog (would just be an extra click in front of the Blender
        window that's already opening).

        Also the point Feature 11's Live Blender Sync becomes available:
        live_sync_action is enabled here (having started disabled, per
        its own comment in _create_actions()), and if it was already
        checked from an earlier launch -- e.g. the user picked "Open
        New Instance" after already_running -- reconnects to the fresh
        listener automatically, since the old connection (if any) now
        points at a Blender window that's no longer the current one.
        """
        self.blender_action.setEnabled(True)
        self.export_page.set_blender_action_in_progress(False)
        logger.info("Blender launched, scene will be saved to %s", blend_output_path)
        self.live_sync_action.setEnabled(True)
        if self.live_sync_action.isChecked() and self.project is not None:
            self.blender_sync_controller.connect_requested.emit(self.project)

    def _on_blender_bridge_failed(self, message: str) -> None:
        """Report a Blender bridge failure that isn't the specific
        "no executable found" case (see _on_blender_executable_not_found
        for that one)."""
        self.blender_action.setEnabled(True)
        self.export_page.set_blender_action_in_progress(False)
        QMessageBox.warning(self, "Open in Blender Failed", message)

    def _on_blender_executable_not_found(self) -> None:
        """Feature Spec's named failure case: prompt for "Locate Blender
        Executable" and remember the choice, rather than just showing a
        plain error like _on_blender_bridge_failed() does.

        Deliberately does not automatically retry the bridge after a
        path is chosen -- the project/frame data that prompted this
        attempt is not re-sent, keeping this handler simple. The user
        clicks "Open in Blender" again once a real executable is
        remembered.
        """
        self.blender_action.setEnabled(True)
        self.export_page.set_blender_action_in_progress(False)
        file_path, _ = QFileDialog.getOpenFileName(self, "Locate Blender Executable")
        if not file_path:
            return
        self.blender_controller.locate_executable_requested.emit(file_path)
        QMessageBox.information(
            self,
            "Blender Executable Remembered",
            'Click "Open in Blender" again to continue.',
        )

    def _on_blender_already_running(self) -> None:
        """Feature Spec's named failure case: a FrameLabs-launched
        Blender instance from earlier this session is still running.
        Offers the spec's "Reuse Existing Blender" / "Open New Instance"
        choice instead of silently launching a second process.

        "Reuse" (and Cancel) leave the existing window untouched -- see
        BlenderLauncher.launch()'s docstring for why FrameLabs cannot
        actually inject the new scene into it, only choose not to open
        a second one. "Open New Instance" re-sends the current project
        on force_new_instance_requested, which skips the running-instance
        check entirely.
        """
        self.blender_action.setEnabled(True)
        self.export_page.set_blender_action_in_progress(False)
        box = QMessageBox(self)
        box.setWindowTitle("Blender Already Running")
        box.setText(
            "A Blender window opened by FrameLabs is already running.\n\n"
            "Reusing it leaves that window alone -- FrameLabs can't send "
            "the new scene into an already-open Blender. Opening a new "
            "instance starts a second Blender window with this project's "
            "scene."
        )
        reuse_button = box.addButton(
            "Reuse Existing Blender", QMessageBox.ButtonRole.AcceptRole
        )
        new_instance_button = box.addButton(
            "Open New Instance", QMessageBox.ButtonRole.DestructiveRole
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(reuse_button)
        box.exec()

        if box.clickedButton() is new_instance_button:
            self.blender_action.setEnabled(False)
            self.export_page.set_blender_action_in_progress(True)
            self.blender_controller.force_new_instance_requested.emit(self.project)
        # Reuse or Cancel: leave the existing Blender window alone, no
        # further action needed.

    def _on_export_blend(self) -> None:
        """ "Export .blend": the same manifest -> script pipeline as
        "Open in Blender", but run headlessly via
        BlenderBridgeController.export_blend_requested -- writes a
        shareable .blend with no interactive window, e.g. for handing
        the scene to a collaborator to open themselves.

        Disables the menu action for the duration, same pattern as
        _on_open_in_blender() -- re-enabled in every one of the three
        possible outcomes (succeeded/failed/executable-not-found) below.
        No already-running guard here: unlike an interactive launch, a
        background export is a short-lived process with no window left
        open afterwards for a later click to collide with.
        """
        if self.project is None or self.project.project_path is None:
            return
        self.export_action.setEnabled(False)
        self.blender_controller.export_blend_requested.emit(self.project)

    def _on_blend_export_succeeded(self, blend_output_path: str) -> None:
        """ "Export .blend" finished and the file was written -- unlike
        the interactive bridge (no dialog, since Blender's own window is
        already opening), this path has nothing else visible to the user
        yet, so a confirmation with the real path is worth showing."""
        self.export_action.setEnabled(True)
        if self.project is not None:
            self.project_browser_widget.set_project(self.project)
        QMessageBox.information(
            self,
            "Blend Exported",
            f"Scene saved to:\n{blend_output_path}",
        )

    def _on_blend_export_failed(self, message: str) -> None:
        """Report an "Export .blend" failure that isn't the specific
        "no executable found" case (see
        _on_blend_export_executable_not_found for that one)."""
        self.export_action.setEnabled(True)
        QMessageBox.warning(self, "Export .blend Failed", message)

    def _on_blend_export_executable_not_found(self) -> None:
        """Feature Spec's named failure case, for the "Export .blend"
        path specifically -- same prompt-and-remember pattern as
        _on_blender_executable_not_found(), kept separate only so the
        follow-up message names the right action to click again."""
        self.export_action.setEnabled(True)
        file_path, _ = QFileDialog.getOpenFileName(self, "Locate Blender Executable")
        if not file_path:
            return
        self.blender_controller.locate_executable_requested.emit(file_path)
        QMessageBox.information(
            self,
            "Blender Executable Remembered",
            'Click "Export .blend..." again to continue.',
        )

    def _on_toggle_live_blender_sync(self, checked: bool) -> None:
        """Feature 11: turn per-capture forwarding to Blender on or off.

        Only ever reachable once live_sync_action has been enabled by
        _on_blender_bridge_succeeded() -- "Open in Blender" must have
        launched successfully at least once this session, since there
        is otherwise no listener anywhere to connect to. Checking the
        box asks BlenderSyncController to connect (or reconnect, if a
        previous connection had since dropped); unchecking it
        disconnects outright rather than merely gating future sends, so
        no connection is left open in the background for no reason.
        """
        if checked:
            if self.project is None or self.project.project_path is None:
                self.live_sync_action.setChecked(False)
                return
            self.blender_sync_controller.connect_requested.emit(self.project)
        else:
            self.blender_sync_controller.disconnect_requested.emit()

    def _on_live_sync_connected(self) -> None:
        """Live Blender Sync is now connected to the launched Blender's
        listener. Log-only plus reflecting the real state in the
        checkbox -- no dialog, matching _on_blender_bridge_succeeded()'s
        own "don't interrupt with a popup" reasoning.
        """
        logger.info("Live Blender Sync connected")
        self.live_sync_action.setChecked(True)

    def _on_live_sync_disconnected(self) -> None:
        """The live-sync connection ended, whether by explicit user
        request (unchecking the box) or because a send failed (e.g. the
        user closed the Blender window mid-session) -- either way,
        reflect "not connected" in the checkbox so it never shows
        checked while nothing is actually listening.
        """
        logger.info("Live Blender Sync disconnected")
        self.live_sync_action.setChecked(False)

    def _on_live_sync_connect_failed(self, message: str) -> None:
        """Connecting to Blender's live-sync listener failed outright
        (e.g. discover_port() timed out). Unlike a mid-session
        disconnect, this is surfaced with a dialog -- the user just
        took an explicit action (checking the box) that visibly didn't
        do what it promised, unlike a background send failure.
        """
        logger.error("Live Blender Sync connect failed: %s", message)
        self.live_sync_action.setChecked(False)
        QMessageBox.warning(self, "Live Blender Sync Failed", message)

    _ASSET_FILE_FILTERS = {
        "audio": "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a)",
        "references": "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)",
        "overlays": "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)",
    }

    def _on_asset_add_requested(self, kind: str, global_pos) -> None:
        """Show "Add <Kind> File...", then run AddAssetCommand.

        Triggered by right-click on empty space in one of the Audio/
        References/Overlays lists -- the only way to import a new file
        into a section that starts genuinely empty, since there's no
        other "Add" UI anywhere yet (see ProjectBrowserWidget's module
        docstring). Goes through self.undo_manager like every other
        project-mutating action in this app.
        """
        if self.project is None:
            return

        menu = QMenu(self)
        add_action = menu.addAction(f"Add {kind.capitalize()} File...")
        chosen = menu.exec(global_pos)
        if chosen is not add_action:
            return

        file_filter = self._ASSET_FILE_FILTERS[kind]
        source_file, _ = QFileDialog.getOpenFileName(
            self, f"Add {kind.capitalize()} File", "", file_filter
        )
        if not source_file:
            return

        command = AddAssetCommand(self.project, self.event_bus, kind, Path(source_file))
        try:
            self.undo_manager.execute(command)
        except AssetServiceError as exc:
            logger.error("Failed to add %s asset: %s", kind, exc)
            QMessageBox.warning(self, "Add Failed", str(exc))
            return
        self._update_undo_redo_actions()
        self.project_browser_widget.set_project(self.project)

    def _on_asset_item_context_menu_requested(
        self, kind: str, relative_path: str, global_pos
    ) -> None:
        """Show Open File / Open Containing Folder / Remove from Project
        for an existing tracked Audio/References/Overlays item.

        Same QDesktopServices.openUrl() pattern the Exports menu already
        uses. Remove from Project is undoable (unlike Delete Export) --
        see asset_commands.py's RemoveAssetCommand docstring for why:
        these are user-supplied source files the app can't reproduce on
        its own if removed by mistake.
        """
        if self.project is None or self.project.project_path is None:
            return
        real_path = self.project.project_path / relative_path

        menu = QMenu(self)
        open_action = menu.addAction("Open File")
        open_folder_action = menu.addAction("Open Containing Folder")
        remove_action = menu.addAction("Remove from Project")
        chosen = menu.exec(global_pos)

        if chosen is open_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(real_path)))
        elif chosen is open_folder_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(real_path.parent)))
        elif chosen is remove_action:
            self._remove_asset(kind, relative_path)

    def _remove_asset(self, kind: str, relative_path: str) -> None:
        """Confirm, then run RemoveAssetCommand through self.undo_manager.

        Mirrors _delete_export()'s shape, but undoable -- see
        _on_asset_item_context_menu_requested's docstring for why.
        """
        if self.project is None:
            return
        filename = relative_path.rsplit("/", 1)[-1]
        confirm = QMessageBox.question(
            self,
            "Remove from Project",
            f'Remove "{filename}" from the project?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        command = RemoveAssetCommand(self.project, self.event_bus, kind, relative_path)
        try:
            self.undo_manager.execute(command)
        except AssetServiceError as exc:
            logger.error("Failed to remove %s asset: %s", kind, exc)
            QMessageBox.warning(self, "Remove Failed", str(exc))
            return
        self._update_undo_redo_actions()
        self.project_browser_widget.set_project(self.project)

    def _refresh_timeline_widget(self) -> None:
        """Rebuild the Timeline strip to match the current project/timeline.

        Rebuilds every thumbnail from scratch (disk read + QPixmap scale
        per frame) -- only call this when the frame list itself has
        changed (new project, opened project, capture succeeded, delete,
        replace, duplicate, undo, redo). For a playhead-only move, call
        _move_timeline_playhead() instead, which is much cheaper and does
        no disk I/O -- critical during playback, which can tick many times
        per second. No-op for the Timeline strip itself if there's no
        active project/timeline yet -- same guard pattern as
        _refresh_onion_skin(). Thumbnails live in project_path/"thumbnails",
        per the project folder layout established in Feature 1 and
        project.py's Project docstring.

        Also refreshes the Project Browser tree (backlog item #3) via
        ProjectBrowserWidget.set_project(), since its Frames/Notes/Exports
        branches change on exactly the same events the Timeline strip
        does. Called unconditionally, even when self.project is None,
        since set_project() handles that case itself (shows a "No project
        open" placeholder row) -- unlike the Timeline strip, the browser
        has a real, correct empty state to fall back to rather than
        nothing to do.

        Also refreshes the Timecode readout via _update_timecode_widget()
        -- a frame-list change (capture, delete, undo/redo, ...) can move
        the playhead just as much as an explicit navigation action can,
        so the timecode needs to stay in sync here too, not just from
        _move_timeline_playhead().
        """
        self.project_browser_widget.set_project(self.project)
        if self.project is None or self.timeline is None:
            self.timecode_widget.clear()
            return
        thumbnails_dir = self.project.project_path / "thumbnails"
        self.timeline_widget.refresh(
            self.timeline.frames, thumbnails_dir, self.timeline.current_index
        )
        self._update_timecode_widget()

    def _move_timeline_playhead(self) -> None:
        """Move the Timeline strip's selection border to match the current
        playhead, without rebuilding any thumbnails.

        No-op if there's no active project/timeline yet -- same guard
        pattern as _refresh_onion_skin(). Use this (not
        _refresh_timeline_widget()) for every playhead-only change: arrow
        keys, playback ticks, and thumbnail clicks. None of these change
        the frame list, so rebuilding every thumbnail on each call would
        mean repeated disk reads for no reason -- at playback speed this
        was enough to visibly freeze the UI, which is exactly what the
        Developer Handbook's "UI Never Blocks" principle rules out.
        """
        if self.project is None or self.timeline is None:
            return
        self.timeline_widget.set_current_index(self.timeline.current_index)
        self._update_timecode_widget()

    def _update_timecode_widget(self) -> None:
        """Keep the Timecode readout in sync with the current playhead.

        Called from both _refresh_timeline_widget() (frame list changed)
        and _move_timeline_playhead() (playhead-only move) -- the same
        two call sites that already keep the Timeline strip's own
        selection border in sync, since the timecode needs updating on
        exactly the same events. No-op guard mirrors every other
        Timeline-dependent refresh method here (falls back to
        TimecodeWidget's own empty-state placeholder via clear()).
        """
        if self.project is None or self.timeline is None:
            self.timecode_widget.clear()
            return
        self.timecode_widget.set_state(
            self.timeline.current_index, len(self.timeline), self.project.fps
        )

    def _refresh_frame_action_bar(self) -> None:
        """Sync FrameActionBar's controls to whichever frame is now current,
        and hide the bar.

        No active project/timeline, or an empty timeline, both correctly
        resolve to Timeline.current_frame being None -- FrameActionBar's
        own set_current_frame(None) already disables and clears every
        control for exactly that case (see its docstring), so no separate
        guard is needed here.

        Hiding the bar here (not just syncing its fields) is deliberate:
        per Chris's "click-only" choice, the bar should disappear the
        instant anything OTHER than an explicit thumbnail left-click moves
        the current frame -- arrow keys, a new capture, undo/redo,
        playback, right-click, even the bar's own Delete/Replace/
        Duplicate/Marker/Notes controls (they all route through the same
        shared handlers as the menu/shortcut paths, with no clean way to
        tell "the bar's own button" apart from "Ctrl+D" once inside those
        handlers -- see _duplicate_frame()/_delete_frame()'s docstrings).
        _on_frame_selected() is the ONLY place that re-shows it, right
        after calling this method, which is what makes "hide by default"
        here safe rather than self-defeating.
        """
        current_frame = self.timeline.current_frame if self.timeline else None
        self.frame_action_bar.set_current_frame(current_frame)
        self.frame_action_bar.set_bar_visible(False)

    def _refresh_onion_skin(self) -> None:
        """Ask the onion skin worker thread to reload overlay frames.

        No-op if there's no active project/timeline yet, OR if the window
        is currently shutting down (self._shutting_down) -- see
        closeEvent()'s docstring for the exact race this second guard
        closes. Emits a signal rather than calling the controller
        directly, since it lives on a different thread -- Qt automatically
        queues this call onto that thread.
        """
        if self._shutting_down or self.timeline is None:
            return
        self.onion_skin_controller.refresh_requested.emit(
            self.timeline, self.onion_settings
        )

    def _on_toggle_onion_skin(self, checked: bool) -> None:
        """Turn Onion Skin on/off and refresh the overlay to match."""
        self.onion_settings.enabled = checked
        logger.info("Onion Skin %s", "enabled" if checked else "disabled")
        self._refresh_onion_skin()

    def _on_toggle_safe_areas(self, checked: bool) -> None:
        """Turn the Safe Area guides on/off.

        Unlike Onion Skin, this needs no worker-thread signal or refresh
        call -- the guides are pure UI geometry that live_view_widget
        already recomputes for whatever frame is currently on screen (see
        LiveViewWidget._update_safe_area_geometry), so toggling visibility
        is a direct, same-thread call: live_view_widget is never
        moveToThread()'d, and this handler itself runs on the main thread
        (menu actions always fire there), so no cross-thread indirection
        is needed here.
        """
        self.live_view_widget.set_safe_areas_visible(checked)
        logger.info("Safe Areas %s", "enabled" if checked else "disabled")

    def _on_composition_guide_selected(self, guide_type: str) -> None:
        """Switch the composition guide overlay to `guide_type`.

        Connected once per action in _create_actions() via
        functools.partial, so `guide_type` is which menu entry fired
        this, not which one is currently checked -- QActionGroup already
        guarantees exactly one of composition_guide_actions is checked
        at a time, this just forwards that selection to LiveViewWidget.
        Pure UI geometry like Safe Areas, so (per
        _on_toggle_safe_areas's docstring) no worker-thread refresh is
        needed here either.
        """
        self.live_view_widget.set_composition_guide(guide_type)
        logger.info("Composition Guide set to %s", guide_type)

    def _on_aspect_ratio_guide_selected(self, ratio_type: str) -> None:
        """Switch the aspect ratio crop guide overlay to `ratio_type`.

        Same functools.partial/QActionGroup pattern as
        _on_composition_guide_selected -- see that method's docstring.
        """
        self.live_view_widget.set_aspect_ratio_guide(ratio_type)
        logger.info("Aspect Ratio Guide set to %s", ratio_type)

    def _on_toggle_play(self) -> None:
        """Start or stop playback, per Feature 7.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_capture() and _on_save_project().
        """
        if self.project is None or self.timeline is None:
            logger.warning("Play requested with no active project; ignoring")
            return
        if self.playback_settings.is_playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        """Begin playback from the current playhead position.

        Pauses Live View polling first -- see LiveViewController's module
        docstring for why both PlaybackController and LiveViewController
        driving the same LiveViewWidget.show_frame() slot at once causes a
        visible strobe between the live camera feed and whatever frame
        Playback just set. Resumed in _reset_playback_ui(), which runs on
        every path playback can stop (user-stopped or reached the end).
        """
        self.live_view_controller.pause_requested.emit()
        self.playback_settings.is_playing = True
        self.playback_controls.play_button.setText("Pause")
        self.playback_controller.start_requested.emit(
            self.timeline, self.playback_settings
        )
        logger.info("Playback start requested")

    def _stop_playback(self) -> None:
        """Stop playback because the user asked to -- as opposed to
        PlaybackController stopping itself at the end of the sequence with
        Loop off, which goes through _on_playback_finished instead.
        """
        self.playback_controller.stop_requested.emit()
        self._reset_playback_ui()
        logger.info("Playback stop requested")

    def _on_playback_finished(self) -> None:
        """React to PlaybackController stopping itself (reached the end of
        the sequence with Loop off) -- un-press Play so the button reflects
        reality instead of staying stuck on "Pause" with nothing playing.
        """
        logger.info("Playback finished")
        self._reset_playback_ui()

    def _reset_playback_ui(self) -> None:
        """Reset the Play button back to its stopped state.

        Resumes Live View polling, mirroring the pause in
        _start_playback() -- runs on every path playback can stop
        (_stop_playback()'s user-initiated stop, and
        _on_playback_finished()'s reached-the-end stop), so the live feed
        always comes back regardless of how playback ended.
        """
        self.playback_settings.is_playing = False
        self.playback_controls.play_button.setText("Play")
        self.live_view_controller.resume_requested.emit()

    def _on_playback_playhead_advanced(self) -> None:
        """Keep Onion Skin, the Timeline strip, and the action bar in sync
        while Playback moves the same Timeline.current_index they all read
        from.

        Without this, Onion Skin, the Timeline strip's selection border,
        and the action bar would only ever refresh on capture or a manual
        click -- once Play starts moving the playhead on its own, all
        three would go stale and stop matching the frame actually on
        screen. The refresh helpers already no-op safely if disabled/empty
        or if the window is shutting down, so this is safe to call
        unconditionally on every tick.
        """
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

    def _on_previous_frame(self) -> None:
        """Step the playhead back one frame, per Feature 12's Left Arrow.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_capture()/_on_toggle_play(). Refreshes Onion
        Skin, the Timeline strip, and the action bar afterward since the
        playhead moved, the same way _on_playback_playhead_advanced() does.
        """
        if self.timeline is None:
            logger.warning("Previous frame requested with no active project; ignoring")
            return
        self.timeline.previous_frame()
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

    def _on_next_frame(self) -> None:
        """Step the playhead forward one frame, per Feature 12's Right Arrow.

        Same guard and refresh calls as _on_previous_frame().
        """
        if self.timeline is None:
            logger.warning("Next frame requested with no active project; ignoring")
            return
        self.timeline.next_frame()
        self._refresh_onion_skin()
        self._move_timeline_playhead()
        self._refresh_frame_action_bar()

    def _on_duplicate_frame(self) -> None:
        """Duplicate the currently-selected frame -- Edit menu / Ctrl+D /
        action bar Duplicate button all land here.

        No-op with a log line if there's no active project or no frame
        selected -- same guard pattern as _on_capture().
        """
        if self.project is None or self.timeline is None:
            logger.warning("Duplicate Frame requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Duplicate Frame requested with no frame selected; ignoring")
            return
        self._duplicate_frame(frame.number)

    def _duplicate_frame(self, frame_number: int) -> None:
        """Duplicate `frame_number`, undoably, and select the new duplicate.

        Runs DuplicateFrameCommand.do() synchronously on the main thread
        rather than on a worker thread the way capture/replace do -- a
        known, deliberately flagged simplification (see hand-off), not an
        oversight; duplicate_frame() is a same-project file copy, cheap
        enough in practice that this hasn't been worth the extra
        worker-thread plumbing yet, but should move to one if real-world
        frame sizes make it noticeable.

        Moves the playhead to the new duplicate, matching how
        _on_capture_succeeded() always selects the newest frame after a
        capture -- a duplicate is a new frame the user just asked for, so
        it should be the one now on screen, the same way a fresh capture
        is. Shared by the Edit menu/Ctrl+D, the action bar's Duplicate
        button, and the right-click menu's Duplicate entry.
        """
        command = DuplicateFrameCommand(self.project, self.event_bus, frame_number)
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self.timeline.go_to_index(len(self.timeline) - 1)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_delete_frame(self) -> None:
        """Delete the currently-selected frame -- action bar Delete button."""
        if self.project is None or self.timeline is None:
            logger.warning("Delete Frame requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Delete Frame requested with no frame selected; ignoring")
            return
        self._delete_frame(frame.number)

    def _delete_frame(self, frame_number: int) -> None:
        """Confirm, then delete `frame_number`, undoably.

        Shows Feature 5's exact confirmation dialog ("Delete Frame N? /
        Undo Available") before doing anything -- deletion is destructive
        enough (real files removed from disk) to warrant confirmation even
        though it's undoable. Runs DeleteFrameCommand.do() synchronously
        on the main thread, same reasoning as _duplicate_frame() -- a
        delete is just file removal, no camera involved. Shared by the
        action bar's Delete button and the right-click menu's Delete entry.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Delete Frame")
        box.setText(f"Delete Frame {frame_number}?")
        box.setInformativeText("Undo Available")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        command = DeleteFrameCommand(self.project, self.event_bus, frame_number)
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self.timeline.go_to_index(self.timeline.current_index)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_replace_frame(self) -> None:
        """Replace the currently-selected frame -- action bar Replace button."""
        if self.project is None or self.timeline is None:
            logger.warning("Replace Frame requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Replace Frame requested with no frame selected; ignoring")
            return
        self._replace_frame(frame.number)

    def _replace_frame(self, frame_number: int) -> None:
        """Trigger a real camera capture to replace `frame_number`'s image.

        Unlike Duplicate/Delete, ReplaceFrameCommand.do() triggers a real
        camera capture (see capture_service.replace_frame), so per the
        Developer Handbook's "UI Never Blocks" rule it can't run
        synchronously here -- it's handed to CaptureController's worker
        thread instead. Recorded on UndoManager only in
        _on_replace_succeeded(), once the capture has actually completed;
        a failed/disk-full replace never reaches the undo stack, since
        nothing to undo would exist. Shared by the action bar's Replace
        button and the right-click menu's Replace entry.
        """
        command = ReplaceFrameCommand(
            self.project,
            self.camera_controller.camera_manager,
            self.event_bus,
            frame_number,
        )
        self.capture_controller.replace_requested.emit(command)
        logger.info("Replace requested for frame %d", frame_number)

    def _on_replace_succeeded(self, command: ReplaceFrameCommand) -> None:
        """React to a successful Replace, run on the capture worker thread.

        Records the already-completed command via execute_already_done()
        rather than execute(), since do() already ran on the worker thread
        -- see UndoManager.execute_already_done()'s docstring for why
        calling do() a second time here would be wrong.
        """
        logger.info("Replace succeeded: %s", command.description)
        self.undo_manager.execute_already_done(command)
        self._update_undo_redo_actions()
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_replace_failed(self, message: str) -> None:
        """Show a "Replace Failed" dialog. Reuses Feature 4's Capture
        Failed presentation, since replace_frame shares capture_frame's
        exact trigger/write pipeline and can fail for the same reasons.
        """
        logger.error("Replace failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Replace Failed")
        box.setText("Replace Failed")
        box.setInformativeText(message)
        box.exec()

    def _on_replace_camera_lost(self, message: str, frame_number: int) -> None:
        """Show Feature 2's "Camera Lost" dialog for a disconnect mid-Replace.

        Same shape and button choices as _on_camera_lost above, but
        Retry constructs a FRESH ReplaceFrameCommand for frame_number via
        _replace_frame() rather than reusing the one that just failed --
        see ReplaceFrameCommand.frame_number's docstring for why
        re-running do() on that same command isn't safe.
        """
        logger.error("Camera lost during replace: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Camera Lost")
        box.setText("Camera Lost")
        box.setInformativeText(message)
        reconnect_button = box.addButton("Reconnect", QMessageBox.ButtonRole.ActionRole)
        retry_button = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reconnect_button:
            self._on_rescan_camera()
        elif clicked is retry_button:
            self._replace_frame(frame_number)

    def _on_toggle_marker(self) -> None:
        """Toggle the marker on the currently-selected frame -- action bar
        Marker button.
        """
        if self.project is None or self.timeline is None:
            logger.warning("Toggle Marker requested with no active project; ignoring")
            return
        frame = self.timeline.current_frame
        if frame is None:
            logger.warning("Toggle Marker requested with no frame selected; ignoring")
            return
        self._toggle_marker(frame.number)

    def _toggle_marker(self, frame_number: int) -> None:
        """Toggle `frame_number`'s marker, undoably.

        Only refreshes the Timeline strip's marker border and the action
        bar -- no onion skin refresh, since a marker is purely a Timeline
        annotation with no effect on onion skin's overlay frames.
        """
        command = ToggleFrameMarkerCommand(self.project, self.event_bus, frame_number)
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()

    def _on_notes_edited(self) -> None:
        """Save the action bar's Notes field to the currently-selected frame.

        Only executes a command if the text actually changed -- notes_edit
        fires editingFinished on every focus-out, not just real edits, and
        pushing a no-op SetFrameNotesCommand onto the undo stack for an
        unchanged value would make Undo do nothing visible, which is
        confusing regardless of being technically correct.
        """
        if self.project is None or self.timeline is None:
            return
        frame = self.timeline.current_frame
        if frame is None:
            return
        new_notes = self.frame_action_bar.notes_edit.text()
        if new_notes == frame.notes:
            return
        command = SetFrameNotesCommand(
            self.project, self.event_bus, frame.number, new_notes
        )
        self.undo_manager.execute(command)
        self._update_undo_redo_actions()
        self._refresh_timeline_widget()

    def _on_undo(self) -> None:
        """Undo the most recently executed command, per Feature 9.

        The undone command may have changed which frames exist (e.g.
        undoing a duplicate removes the frame it created), so this
        rebuilds the Timeline strip in full via _refresh_timeline_widget()
        rather than the cheaper _move_timeline_playhead() -- same
        reasoning as _on_capture_succeeded(). go_to_index() re-clamps the
        playhead first in case the frame list just got shorter than the
        current index.
        """
        if self.timeline is None:
            logger.warning("Undo requested with no active project; ignoring")
            return
        if self.undo_manager.undo():
            self.timeline.go_to_index(self.timeline.current_index)
            self._update_undo_redo_actions()
            self._refresh_onion_skin()
            self._refresh_timeline_widget()
            self._refresh_frame_action_bar()

    def _on_redo(self) -> None:
        """Redo the most recently undone command, per Feature 9.

        Same rebuild-in-full reasoning as _on_undo(). Note that a redone
        ReplaceFrameCommand does NOT re-trigger the camera (see its
        do()'s docstring), so this can safely run synchronously here even
        though the original Replace ran on the capture worker thread.
        """
        if self.timeline is None:
            logger.warning("Redo requested with no active project; ignoring")
            return
        if self.undo_manager.redo():
            self.timeline.go_to_index(self.timeline.current_index)
            self._update_undo_redo_actions()
            self._refresh_onion_skin()
            self._refresh_timeline_widget()
            self._refresh_frame_action_bar()

    def _update_undo_redo_actions(self) -> None:
        """Enable/disable the Undo and Redo menu entries to match real state.

        Called after every execute/undo/redo so the Edit menu never offers
        an Undo/Redo that would actually be a no-op.
        """
        self.undo_action.setEnabled(self.undo_manager.can_undo())
        self.redo_action.setEnabled(self.undo_manager.can_redo())

    def _on_loop_toggled(self, checked: bool) -> None:
        """Update Loop live.

        PlaybackController re-reads settings.loop from this same shared
        PlaybackSettings object on every tick (see its _advance()
        docstring), so this takes effect immediately, even mid-playback.
        """
        self.playback_settings.loop = checked
        logger.info("Loop %s", "enabled" if checked else "disabled")

    def _on_speed_changed(self, index: int) -> None:
        """Update playback speed live -- same live-update mechanism as Loop."""
        percent = self.playback_controls.speed_combo.itemData(index)
        self.playback_settings.speed_percent = percent
        logger.info("Playback speed set to %d%%", percent)

    def _on_new_project(self) -> None:
        """Open the New Project dialog and adopt the created project.

        If the user cancels the dialog, nothing changes. See
        open_created_project()/_adopt_project() for what "adopt" does.
        """
        dialog = NewProjectDialog(self)
        if dialog.exec():
            self.open_created_project(dialog.project)

    def open_created_project(self, project: Project) -> None:
        """Adopt a Project that was already created elsewhere.

        Used by _on_new_project (NewProjectDialog run from the File
        menu) and by app/main.py (NewProjectDialog run from the
        startup Welcome dialog, before MainWindow even existed) -- both
        hand MainWindow an already-created Project, so both adopt it
        the same way and log it the same way ("created", not "opened").
        """
        self._adopt_project(project, created=True)

    def _on_open_project(self) -> None:
        """Open a folder picker and hand the chosen path to open_project_at().

        A project IS a folder (containing project.ffproj at its top
        level), so this picks the project folder itself -- not a parent
        folder, unlike New Project's Browse.
        """
        chosen = QFileDialog.getExistingDirectory(self, "Open Project")
        if chosen:
            self.open_project_at(Path(chosen))

    def open_project_at(self, project_path: Path) -> None:
        """Load the project at project_path, handling autosave recovery.

        Shared by _on_open_project (path chosen via a folder picker)
        and app/main.py (path chosen from the startup Welcome dialog's
        own Browse button or its Recent Projects list) -- both need
        the exact same Feature 8 crash-recovery check before handing
        off to ProjectController.

        has_recoverable_autosave() is just two stat() calls, cheap
        enough to run synchronously here rather than round-tripping to
        a worker thread first.
        """
        if has_recoverable_autosave(project_path):
            self._show_recovery_dialog(project_path)
        else:
            self.project_controller.load_requested.emit(project_path)

    def _show_recovery_dialog(self, project_path: Path) -> None:
        """Show Feature 8's "Recovered Project Found" dialog.

        has_recoverable_autosave() already filtered out the common case
        (an autosave folder existing but not newer than project.ffproj),
        so reaching this dialog means the app didn't exit cleanly the
        last time this project was open. Restore loads from the newest
        .autosave/ snapshot instead of project.ffproj; Discard proceeds
        with the normal load, exactly as if no autosave existed --
        neither choice deletes anything, per the Handbook's "if there is
        uncertainty, preserve the data."
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Recovered Project Found")
        box.setText("Recovered Project Found")
        box.setInformativeText(
            "FrameLabs found a more recent autosave for this project than "
            "its last saved file. This usually means the app didn't close "
            "properly last time.\n\nRestore the autosave, or discard it "
            "and open the last saved version instead?"
        )
        restore_button = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        if box.clickedButton() is restore_button:
            logger.info("Restoring project from autosave: %s", project_path)
            self.project_controller.restore_requested.emit(project_path)
        else:
            logger.info("Discarding autosave, opening saved project: %s", project_path)
            self.project_controller.load_requested.emit(project_path)

    def _on_load_succeeded(self, project: Project, missing_files: list) -> None:
        """React to a successful load.

        Per Feature 1's edge case, missing frame images don't block
        loading -- if any were found missing, show the warning dialog
        with Continue/Locate Missing Files/Cancel before adopting the
        project. Otherwise adopt immediately.
        """
        if missing_files:
            self._show_missing_frames_dialog(project, missing_files)
        else:
            self._adopt_project(project)

    def _on_load_failed(self, message: str) -> None:
        """Show a "Could Not Open Project" dialog.

        Covers a missing/corrupt project.ffproj or an unsupported version
        -- the user needs to see this, not just find it in a log.
        """
        logger.error("Load failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Could Not Open Project")
        box.setText("Could Not Open Project")
        box.setInformativeText(message)
        box.exec()

    def _adopt_project(self, project: Project, *, created: bool = False) -> None:
        """Make project the active project and reflect it in the UI.

        The single funnel every path that hands MainWindow a real
        Project converges on: open_created_project() (New Project, from
        either the File menu or the startup Welcome dialog),
        _on_load_succeeded() (Open Project), and the autosave restore
        path (which also emits load_succeeded -- see
        ProjectController's docstring). A fresh Timeline is created
        over the project's frames at the same time -- see
        open_created_project() for why this needs no further manual
        sync. The Timeline strip and action bar are refreshed here too,
        so adopting a project immediately shows its real frame
        thumbnails rather than whatever was left over from a previous
        one. undo_manager.clear() runs here for the same reason: every
        held Command references the previous Project object, so
        undoing one after switching projects would silently act on the
        wrong project's files.

        Also records the project in Config's recent-projects list, so
        it shows up in the startup Welcome dialog next launch. Skipped
        only if project_path is somehow unset -- shouldn't happen in
        practice, since every Project reaching this method has already
        been created on disk or loaded from disk.
        """
        self.project = project
        self.timeline = Timeline(project)
        self.undo_manager.clear()
        self._update_undo_redo_actions()
        self.setWindowTitle(f"FrameLabs — {project.name}")
        logger.info("Project %s: %s", "created" if created else "opened", project.name)
        if project.project_path is not None:
            self.config.add_recent_project(project.project_path, project.name)
            self.config.save()
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()
        # Enables the bottom-right Export button (starts disabled -- see
        # PlaybackControls.__init__ -- since there's nothing to export
        # before a project is open) and refreshes the Export page's own
        # preview/settings in case it's already showing, or gets shown
        # later without another _on_show_export_page() refresh in
        # between (that method also calls set_project(), but a project
        # switch while the Export page happens to already be visible
        # would otherwise leave it showing the previous project).
        self.playback_controls.export_button.setEnabled(True)
        self.export_page.set_project(project)
        # Same reasoning as the Export button/page above, one paragraph
        # up -- starts disabled since composite_workspace_action's
        # QAction has no PlaybackControls-style widget of its own to
        # inherit a disabled look from before a project exists.
        self.composite_workspace_action.setEnabled(True)
        self.composite_workspace.set_project(project)
        # Feature 11: any existing live-sync connection points at the
        # PREVIOUS project's Blender launch (a different project_path,
        # therefore a different port file) -- never valid for whatever
        # project was just adopted, so disconnect and require the user
        # to run "Open in Blender" again for this one, same as if the
        # app had just started.
        self.blender_sync_controller.disconnect_requested.emit()
        self.live_sync_action.setChecked(False)
        self.live_sync_action.setEnabled(False)

    def _show_missing_frames_dialog(
        self, project: Project, missing_files: list
    ) -> None:
        """Show Feature 1's "N frames are missing" dialog.

        Continue adopts the project as-is. Locate Missing Files opens the
        project's images/ folder in the system file explorer so the user
        can manually replace the missing files, then re-shows this same
        dialog -- opening the folder doesn't itself resolve anything, the
        user still needs to explicitly Continue or Cancel afterward.
        Cancel leaves the current project (if any) untouched.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Missing Frames")
        box.setText(f"{len(missing_files)} frames are missing.")
        continue_button = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        locate_button = box.addButton(
            "Locate Missing Files", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is continue_button:
            self._adopt_project(project)
        elif clicked is locate_button:
            images_dir = project.project_path / "images"
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(images_dir)))
            self._show_missing_frames_dialog(project, missing_files)
        # Cancel: no-op, dialog just closes.

    def _on_save_project(self) -> None:
        """Request a save on the worker thread.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_capture().
        """
        if self.project is None:
            logger.warning("Save requested with no active project; ignoring")
            return
        self.project_controller.save_requested.emit(self.project)

    def _on_save_succeeded(self) -> None:
        """React to a successful save. Log-only -- no visible confirmation
        needed for a routine save; a failed save gets a dialog instead
        since that's the case the user actually needs to act on.
        """
        logger.info("Project saved: %s", self.project.name if self.project else "?")

    def _on_save_failed(self, message: str) -> None:
        """Show a "Save Failed" dialog. A failed save risks losing work,
        so this is surfaced visibly rather than left as a log line.
        """
        logger.error("Save failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Save Failed")
        box.setText("Save Failed")
        box.setInformativeText(message)
        box.exec()

    def _on_project_settings(self) -> None:
        """Open the Project Settings dialog for the active project.

        No-op with a log line if there's no active project yet -- same
        guard pattern as _on_save_project(). ProjectSettingsDialog
        writes its edited values directly onto self.project when Ok is
        pressed (see its docstring), so on acceptance this just
        reflects the possible name change in the window title and
        persists the change immediately, the same way any other
        project edit (e.g. Duplicate Frame) gets written to disk --
        rather than silently leaving it only in memory until the next
        manual Save.
        """
        if self.project is None:
            logger.warning(
                "Project Settings requested with no active project; ignoring"
            )
            return
        dialog = ProjectSettingsDialog(self.project, self)
        if dialog.exec():
            self.setWindowTitle(f"FrameLabs — {self.project.name}")
            self.project_controller.save_requested.emit(self.project)

    def _on_capture(self) -> None:
        """Request a capture on the worker thread.

        No-op with a log line if there's no active project yet -- this is
        a placeholder guard; a real "no project open" state (e.g. graying
        out the Capture action) belongs to a later UI pass, not this one.
        """
        if self.project is None:
            logger.warning("Capture requested with no active project; ignoring")
            return
        self.capture_controller.capture_requested.emit(self.project)

    def _on_capture_succeeded(self, frame_number: int) -> None:
        """React to a successful capture.

        Advances the Timeline's playhead to the newly captured frame (the
        latest one) before refreshing Onion Skin -- otherwise the playhead
        stays stuck wherever it was, and frames_before_current() would not
        reflect the frame just captured. This remains correct now that
        Play also exists: capture always means "the new frame is now
        current," regardless of where Play last left the playhead. The
        Timeline strip and action bar are refreshed last so the
        newly-captured thumbnail appears with its selection border in the
        same place the playhead just moved to.
        """
        logger.info("Capture succeeded: frame %d", frame_number)
        if self.timeline is not None:
            self.timeline.go_to_index(len(self.timeline) - 1)
        self._refresh_onion_skin()
        self._refresh_timeline_widget()
        self._refresh_frame_action_bar()
        # Feature 8: "after every capture." project.ffproj itself is
        # already current (capture_service.capture_frame() saves it
        # synchronously) -- this writes the separate .autosave/ snapshot
        # on top of that, per autosave_controller.py's module docstring.
        if self.project is not None:
            self.autosave_controller.autosave_requested.emit(self.project)
        # Feature 11: forward the new frame to Blender, but only if Live
        # Blender Sync is actually on -- see BlenderSyncController's own
        # module docstring for why this is a direct signal emission
        # here rather than an EventBus subscription over on that
        # controller's side.
        if self.live_sync_action.isChecked() and self.project is not None:
            self.blender_sync_controller.frame_sync_requested.emit(
                self.project, frame_number
            )

    def _on_capture_failed(self, message: str) -> None:
        """Show Feature 4's "Capture Failed" dialog, with a Retry option.

        Clicking Retry re-runs _on_capture() against the same
        self.project used by the failed attempt -- capture_frame() only
        requires a valid project_path, so repeating the same request is
        always safe. Declining just dismisses the dialog; the failed
        attempt already left nothing partial on disk (per Feature 4's
        acceptance criteria).
        """
        logger.error("Capture failed: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Capture Failed")
        box.setText("Capture Failed")
        box.setInformativeText(message)
        retry_button = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is retry_button:
            self._on_capture()

    def _on_camera_lost(self, message: str) -> None:
        """Show Feature 2's "Camera Lost" dialog, for a disconnect mid-capture.

        Distinct from _on_capture_failed's generic "Capture Failed"
        dialog -- CaptureController only emits camera_lost once
        CameraManager has confirmed the camera actually disconnected
        (not a transient trigger failure). Per Feature 2's acceptance
        criteria, no partial frame is ever written before this fires, so
        the timeline is left intact and the project stays fully usable no
        matter which button is clicked.

        Reconnect asks the camera-scanning worker thread for an
        immediate rescan (the same request the Inspector's Rescan
        control makes) and then just dismisses -- reconnecting is
        inherently asynchronous, so the user sees the Inspector's camera
        status update once it succeeds and can press Capture again
        themselves. Retry re-runs _on_capture() immediately, for the
        common case where the camera was already physically reconnected
        by the time the user reacts to the dialog.
        """
        logger.error("Camera lost: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Camera Lost")
        box.setText("Camera Lost")
        box.setInformativeText(message)
        reconnect_button = box.addButton("Reconnect", QMessageBox.ButtonRole.ActionRole)
        retry_button = box.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reconnect_button:
            self._on_rescan_camera()
        elif clicked is retry_button:
            self._on_capture()

    def _on_disk_full(self, message: str) -> None:
        """Show Feature 4's "Disk Full" dialog.

        Acknowledge-only, no Retry -- per the Feature Spec, a disk-full
        capture is aborted rather than retryable; the project remains
        usable, but disk space needs to be freed before capturing again.
        Shared by both Capture and Replace, per capture_controller.py's
        single disk_full signal.
        """
        logger.error("Disk full: %s", message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Disk Full")
        box.setText("Capture Aborted")
        box.setInformativeText(message)
        box.exec()

    def _on_rescan_camera(self) -> None:
        """Ask the camera worker thread to run an immediate scan.

        Emits a signal rather than calling the controller directly, since
        the controller lives on a different thread — Qt automatically
        queues this call onto that thread. See camera_controller.py.
        """
        self.camera_controller.rescan_requested.emit()

    def _on_camera_connecting(self) -> None:
        """Reflect an in-progress scan in the Inspector's Camera field."""
        self.inspector_panel.set_camera_status("Scanning...")

    def _on_camera_connected(self, display_name: str, backend_type: str) -> None:
        """Reflect a successful camera connection in the Inspector.

        ISO/Shutter/Aperture only get enabled for a real DSLR ("gphoto"
        backend_type) -- a webcam connection reflects the new status text
        but leaves those controls disabled, since WebcamBackend's
        set_iso/set_shutter/set_aperture are no-ops.
        """
        self.inspector_panel.set_camera_status(f"{display_name} Connected")
        self.inspector_panel.set_dslr_controls_enabled(backend_type == "gphoto")

    def _on_camera_disconnected(self) -> None:
        """Reflect a camera disconnect in the Inspector."""
        self.inspector_panel.clear_camera_status()
        self.inspector_panel.set_dslr_controls_enabled(False)

    def _on_no_camera_found(self) -> None:
        """Reflect a completed scan that found nothing, in the Inspector."""
        self.inspector_panel.clear_camera_status()
        self.inspector_panel.set_dslr_controls_enabled(False)

    def closeEvent(self, event) -> None:
        """Shut all ten worker threads down cleanly before closing.

        Sets self._shutting_down = True FIRST, before touching any thread.
        This closes a real race: PlaybackController.playhead_advanced is a
        queued cross-thread connection to _on_playback_playhead_advanced()
        on THIS (main) thread. If Play is still running (e.g. Loop
        enabled) when the window closes, one more tick can be emitted
        before playback's own thread is told to stop further down this
        method -- but Qt doesn't actually deliver that queued call until
        the main thread's event loop resumes processing events, which
        only happens AFTER this entire method returns (QThread.wait()
        blocks the calling/main thread without pumping its event queue).
        By the time that queued call is finally delivered,
        onion_skin_controller has already been deleted -- its thread is
        shut down earlier in this method, before playback's -- so
        _refresh_onion_skin() emitting on it raised RuntimeError: Signal
        source has been deleted. self._shutting_down, checked at the top
        of _refresh_onion_skin(), makes that eventual call a safe no-op
        instead, regardless of exactly when it's delivered relative to
        thread teardown order -- so this fix doesn't depend on getting
        that ordering exactly right.

        Without this, Qt logs a "QThread destroyed while running" warning
        and the thread is torn down abruptly rather than exiting its event
        loop normally. deleteLater() is queued onto each thread's own
        event loop via its finished signal, so each controller is cleaned
        up on the thread it actually belongs to.
        """
        self._shutting_down = True

        self._camera_thread.finished.connect(self.camera_controller.deleteLater)
        self._camera_thread.quit()
        self._camera_thread.wait(2000)

        self._capture_thread.finished.connect(self.capture_controller.deleteLater)
        self._capture_thread.quit()
        self._capture_thread.wait(2000)

        self._project_thread.finished.connect(self.project_controller.deleteLater)
        self._project_thread.quit()
        self._project_thread.wait(2000)

        self._live_view_thread.finished.connect(self.live_view_controller.deleteLater)
        self._live_view_thread.quit()
        self._live_view_thread.wait(2000)

        self._onion_skin_thread.finished.connect(self.onion_skin_controller.deleteLater)
        self._onion_skin_thread.quit()
        self._onion_skin_thread.wait(2000)

        self._playback_thread.finished.connect(self.playback_controller.deleteLater)
        self._playback_thread.quit()
        self._playback_thread.wait(2000)

        # Stop the timer BEFORE quitting the autosave thread, not after --
        # otherwise a tick landing in that gap could still emit onto a
        # worker thread that's already been told to quit. (The
        # self._shutting_down guard in _on_autosave_timer_tick() is a
        # second, independent layer against the same race, not a
        # substitute for stopping the timer here.)
        self._autosave_timer.stop()
        self._autosave_thread.finished.connect(self.autosave_controller.deleteLater)
        self._autosave_thread.quit()
        self._autosave_thread.wait(2000)

        self._export_thread.finished.connect(self.export_controller.deleteLater)
        self._export_thread.quit()
        self._export_thread.wait(2000)

        self._blender_thread.finished.connect(self.blender_controller.deleteLater)
        self._blender_thread.quit()
        self._blender_thread.wait(2000)

        self._blender_sync_thread.finished.connect(
            self.blender_sync_controller.deleteLater
        )
        self._blender_sync_thread.quit()
        self._blender_sync_thread.wait(2000)

        super().closeEvent(event)

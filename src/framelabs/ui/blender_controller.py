"""Blender bridge worker controller for the UI layer.

Drives Feature 10's full "Open in Blender" pipeline off the main thread,
per the Developer Handbook's "UI Never Blocks" rule -- building the
manifest, writing the scene-generation script, and launching a real OS
process for Blender must never freeze the window, same reasoning as
export_controller.py and the Handbook's own "Blender launch" example.

Same "carry the request on the signal itself" pattern every other
controller in this package uses (autosave_controller.py,
export_controller.py, capture_controller.py) rather than tracking a
separately-synced "current project" reference.

Instances of this class are meant to be moved to their own dedicated
QThread via moveToThread(), separate from every other worker thread --
launching Blender (and the file I/O leading up to it) should never
contend with an in-progress capture, camera scan, live preview, onion
skin refresh, playback tick, project save/load, autosave write, or
export.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from framelabs.blender.exporter import (
    BlenderExportError,
    build_manifest,
    write_manifest,
)
from framelabs.blender.launcher import (
    BlenderExecutableNotFoundError,
    BlenderLauncher,
    BlenderLaunchError,
)
from framelabs.blender.scene_builder import write_scene_script
from framelabs.core.config import Config
from framelabs.project.project import Project

logger = logging.getLogger(__name__)


class BlenderBridgeController(QObject):
    """Drives the "Open in Blender" pipeline on a worker thread for the
    UI: build manifest -> write manifest -> write scene script -> launch
    Blender.

    Meant to be constructed on the main thread, then moved to a QThread
    with moveToThread() before that thread is started. See module
    docstring for the full threading contract.
    """

    bridge_succeeded = Signal(str)  # the .blend path Blender was told to save to
    bridge_failed = Signal(str)
    # Emitted specifically when no Blender executable could be resolved
    # at all -- distinct from bridge_failed so MainWindow can offer
    # "Locate Blender Executable" instead of a plain error dialog, per
    # the Feature Spec's named failure case.
    executable_not_found = Signal()
    # Emitted when a FrameLabs-launched Blender instance from earlier
    # this session is still running -- distinct from bridge_failed so
    # MainWindow can offer the Feature Spec's named "Reuse Existing
    # Blender" / "Open New Instance" choice instead of a plain error.
    # Carries no payload: MainWindow already holds the Project it wants
    # opened and re-sends it on force_new_instance_requested if the user
    # picks "Open New Instance".
    already_running = Signal()

    # Emitted from the main thread with the currently active Project as
    # its payload; connected to _handle_bridge_requested below, which --
    # because this object lives on the worker thread once moved -- Qt
    # automatically delivers via a queued connection.
    bridge_requested = Signal(object)

    # Emitted from the main thread after the user picks a Blender
    # executable via "Locate Blender Executable"; the path is remembered
    # in Config so future sessions never need to ask again.
    locate_executable_requested = Signal(str)

    # Emitted from the main thread after the user explicitly chooses
    # "Open New Instance" in response to already_running -- skips the
    # has_running_instance() check entirely and launches unconditionally,
    # since the user has already been told one is running and chose to
    # open another anyway.
    force_new_instance_requested = Signal(object)

    def __init__(self, config: Config) -> None:
        """Build the controller against the app's shared Config, so a
        located/remembered Blender executable path persists across
        sessions the same way every other setting does.
        """
        super().__init__()
        self._launcher = BlenderLauncher(config)
        self.bridge_requested.connect(self._handle_bridge_requested)
        self.locate_executable_requested.connect(
            self._handle_locate_executable_requested
        )
        self.force_new_instance_requested.connect(
            self._handle_force_new_instance_requested
        )

    def _handle_bridge_requested(self, project: Project) -> None:
        """Run the full manifest -> script -> launch pipeline, unless a
        FrameLabs-launched Blender instance is already running -- per
        the Feature Spec's "Blender already running" case, that prompts
        MainWindow for Reuse/New Instance instead of launching a second
        process silently. Always runs on the worker thread."""
        if self._launcher.has_running_instance():
            logger.info(
                "Blender bridge: a FrameLabs-launched Blender instance is "
                "still running; asking whether to reuse it or open a new one"
            )
            self.already_running.emit()
            return
        self._run_pipeline(project)

    def _handle_force_new_instance_requested(self, project: Project) -> None:
        """User explicitly chose "Open New Instance" after already_running
        was raised. Skips has_running_instance() entirely -- the user has
        already been told one is running and chose to open another
        anyway, so asking again would just be a redundant prompt loop."""
        self._run_pipeline(project)

    def _run_pipeline(self, project: Project) -> None:
        """The actual manifest -> script -> launch pipeline, shared by
        both the normal path and the explicit "Open New Instance" path.
        """
        try:
            manifest = build_manifest(project)
            write_manifest(project)
            script_dir = project.project_path / "cache" / "blender"
            script_path = write_scene_script(manifest, script_dir)
            self._launcher.launch(script_path)
        except BlenderExecutableNotFoundError:
            logger.error("Blender bridge failed: no Blender executable found")
            self.executable_not_found.emit()
        except (BlenderExportError, BlenderLaunchError) as exc:
            logger.error("Blender bridge failed: %s", exc)
            self.bridge_failed.emit(str(exc))
        except Exception as exc:
            # Defense in depth: same reasoning as
            # ExportController._handle_export_requested() -- an
            # unexpected exception here must not vanish silently, or
            # the Blender menu item is left permanently disabled with
            # no dialog ever shown.
            logger.exception("Blender bridge failed with an unexpected error")
            self.bridge_failed.emit(str(exc))
        else:
            logger.info("Blender launched for project: %s", manifest.blend_output_path)
            self.bridge_succeeded.emit(manifest.blend_output_path)

    def _handle_locate_executable_requested(self, path: str) -> None:
        """Remember a user-located Blender executable. Always runs on
        the worker thread, same as _handle_bridge_requested, since it
        touches the same Config/launcher state."""
        try:
            self._launcher.remember_executable(Path(path))
        except BlenderLaunchError as exc:
            logger.error("Failed to remember Blender executable: %s", exc)
            self.bridge_failed.emit(str(exc))

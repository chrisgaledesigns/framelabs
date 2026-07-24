"""Autosave snapshots for FrameLabs projects (Feature 8).

capture_service.py already calls ProjectSerializer.save() synchronously
after every capture/delete/replace/duplicate/notes/marker change, and
ProjectController.save() handles the explicit Ctrl+S path -- so
project.ffproj itself is, in practice, almost always already up to date.

This module is the OTHER half of Feature 8: timestamped snapshots written
into a project's `.autosave/` folder, separate from project.ffproj. They
exist for two reasons the always-up-to-date project.ffproj doesn't cover:

1. A crash or power loss mid-write can leave project.ffproj truncated or
   corrupt on disk. A recent autosave snapshot is the fallback.
2. Not every future mutation is guaranteed to save synchronously (e.g. a
   project-settings edit UI that doesn't exist yet). The 30-second timer
   in ui/autosave_controller.py is a backstop for that.

Per the Developer Handbook's "Never Lose User Data" principle: if there's
uncertainty, preserve the data -- pruning only ever removes autosave
snapshots, never a real captured frame or project.ffproj itself.

This module is pure: no Qt, no threading, real file I/O only. The
30-second timer and "after every capture" trigger live in
ui/autosave_controller.py, which calls into this module off the main
thread, per the handbook's "UI Never Blocks" rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from framelabs.core.logger import get_logger
from framelabs.project.project import Project
from framelabs.project.serializer import PROJECT_FILENAME, ProjectSerializer

logger = get_logger(__name__)

AUTOSAVE_DIR_NAME = ".autosave"
_AUTOSAVE_PREFIX = "autosave_"
_AUTOSAVE_SUFFIX = ".ffproj"

# Feature 8: "Keep: Last 20 autosaves."
MAX_AUTOSAVES = 20


def write_autosave(project: Project) -> Path:
    """Write a timestamped autosave snapshot, then prune old ones.

    Args:
        project: The project to snapshot. Must have project_path set.

    Returns:
        The path of the newly written autosave file.

    Raises:
        ValueError: If project.project_path is None.
    """
    if project.project_path is None:
        raise ValueError("Cannot autosave a project with no project_path set.")

    autosave_dir = project.project_path / AUTOSAVE_DIR_NAME
    autosave_dir.mkdir(exist_ok=True)

    # UTC + microseconds: two autosaves in the same session should never
    # collide on filename, even if triggered back-to-back (e.g. a capture
    # landing in the same instant as a periodic tick).
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    autosave_path = autosave_dir / f"{_AUTOSAVE_PREFIX}{timestamp}{_AUTOSAVE_SUFFIX}"

    ProjectSerializer.save_to_path(project, autosave_path)
    logger.info("Autosave written: %s", autosave_path)

    _prune_old_autosaves(autosave_dir)

    return autosave_path


def find_latest_autosave(project_path: Path) -> Path | None:
    """Return the most recent autosave file for project_path, or None.

    Args:
        project_path: The project's folder.
    """
    autosaves = _list_autosaves(project_path)
    return autosaves[-1] if autosaves else None


def has_recoverable_autosave(project_path: Path) -> bool:
    """Return True if project_path has a genuinely-recoverable autosave.

    "Recoverable" means either project.ffproj itself is missing/corrupt
    (see ProjectLoadError below), or the latest autosave snapshot is
    strictly newer than project.ffproj -- the signal that the app didn't
    exit cleanly the last time this project was open (a clean exit's
    final mutation, or an explicit Save, always leaves project.ffproj at
    least as new as any autosave). Just having a `.autosave/` folder is
    NOT enough on its own -- under normal operation one always exists
    after the first 30 seconds of a session, and prompting Chris to
    "recover" on every single startup would train him to click through
    it without reading it.

    Args:
        project_path: The project's folder.
    """
    latest = find_latest_autosave(project_path)
    if latest is None:
        return False

    main_file = project_path / PROJECT_FILENAME
    if not main_file.exists():
        return True

    try:
        return latest.stat().st_mtime > main_file.stat().st_mtime
    except OSError as exc:
        # Filesystem hiccup reading mtimes shouldn't block opening the
        # project outright -- per "if there is uncertainty, preserve the
        # data", default to offering recovery rather than silently
        # assuming everything is fine.
        logger.warning(
            "Could not compare autosave/project.ffproj timestamps for %s: %s",
            project_path,
            exc,
        )
        return True


def restore_autosave(project_path: Path) -> Project:
    """Load the most recent autosave snapshot as the active Project.

    Args:
        project_path: The project's folder.

    Returns:
        The restored Project, with project_path set to project_path (not
        the autosave snapshot's own location inside .autosave/).

    Raises:
        FileNotFoundError: If no autosave exists for project_path.
        ProjectLoadError: If the latest autosave file itself is
            malformed. (Deliberately not caught here -- if even the
            newest autosave is corrupt, the caller needs to know rather
            than silently falling back further; see module docstring on
            "if there is uncertainty, preserve the data" rather than
            guessing.)
    """
    latest = find_latest_autosave(project_path)
    if latest is None:
        raise FileNotFoundError(f"No autosave found for project: {project_path}")

    project = ProjectSerializer.load_from_path(latest, project_path)
    logger.info("Restored project from autosave: %s", latest)
    return project


def _list_autosaves(project_path: Path) -> list[Path]:
    """Return every autosave file for project_path, oldest first.

    Sorting on filename works because the timestamp format
    (%Y%m%dT%H%M%S%f) is lexicographically ordered the same as
    chronologically -- no need to stat() every file just to order them.
    """
    autosave_dir = project_path / AUTOSAVE_DIR_NAME
    if not autosave_dir.is_dir():
        return []
    return sorted(autosave_dir.glob(f"{_AUTOSAVE_PREFIX}*{_AUTOSAVE_SUFFIX}"))


def _prune_old_autosaves(autosave_dir: Path) -> None:
    """Delete the oldest autosaves beyond MAX_AUTOSAVES, if any.

    A pruning failure (e.g. a locked file on Windows) is logged and
    skipped, not raised -- per the handbook, a failure to delete an OLD
    autosave must never be treated as seriously as a failure affecting a
    real captured frame or the current project.ffproj. Worst case, one
    extra stale file lingers past MAX_AUTOSAVES until the next successful
    prune.
    """
    autosaves = sorted(autosave_dir.glob(f"{_AUTOSAVE_PREFIX}*{_AUTOSAVE_SUFFIX}"))
    excess_count = len(autosaves) - MAX_AUTOSAVES
    if excess_count <= 0:
        return

    for stale_path in autosaves[:excess_count]:
        try:
            stale_path.unlink()
        except OSError as exc:
            logger.warning("Failed to prune old autosave %s: %s", stale_path, exc)
        else:
            logger.info("Pruned old autosave: %s", stale_path)

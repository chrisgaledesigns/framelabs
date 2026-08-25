"""Asset service for Audio/References/Overlays.

Audio, References, and Overlays are structurally identical on Project --
one list attribute, one matching subfolder -- so this module holds one
shared add_asset()/remove_asset() implementation rather than three
near-copies of the same logic.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from framelabs.core.event_bus import EventBus
from framelabs.project.project import Project
from framelabs.project.serializer import ProjectSerializer

logger = logging.getLogger(__name__)

# Maps each supported asset kind to its subfolder name and past-tense
# EventBus event names.
_ASSET_KINDS = {
    "audio": {
        "subfolder": "audio",
        "added_event": "AUDIO_ADDED",
        "removed_event": "AUDIO_REMOVED",
    },
    "references": {
        "subfolder": "references",
        "added_event": "REFERENCE_ADDED",
        "removed_event": "REFERENCE_REMOVED",
    },
    "overlays": {
        "subfolder": "overlays",
        "added_event": "OVERLAY_ADDED",
        "removed_event": "OVERLAY_REMOVED",
    },
}


class AssetServiceError(Exception):
    """Raised for an invalid asset kind, missing source file, or a
    relative_path that isn't currently tracked on the project."""


def _get_kind_info(kind: str) -> dict:
    try:
        return _ASSET_KINDS[kind]
    except KeyError as exc:
        raise AssetServiceError(
            f"Unknown asset kind {kind!r}; expected one of {sorted(_ASSET_KINDS)}"
        ) from exc


def _get_asset_list(project: Project, kind: str) -> list[str]:
    return getattr(project, kind)


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    """Return a collision-free path inside dest_dir, Explorer/Finder-style:
    "name.ext" -> "name (2).ext" -> "name (3).ext" ... if "name.ext"
    already exists in dest_dir.
    """
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def add_asset(
    project: Project, event_bus: EventBus, kind: str, source_path: Path
) -> str:
    """Copy a real file from anywhere on disk into the project's own
    subfolder for `kind`, track it on the Project, save, and publish
    the kind's ADDED event.

    The source file is always copied in, never referenced in place --
    keeps the project self-contained and portable. Filename collisions
    are handled Explorer/Finder-style (see _unique_destination).

    Args:
        project: The active project. Must have a non-None project_path.
        event_bus: The event bus the kind's ADDED event is published on.
        kind: One of "audio", "references", "overlays".
        source_path: Path to the real file to copy in, anywhere on disk.

    Returns:
        The new project-relative path (e.g. "audio/scratch_track.wav")
        that was added to the project.

    Raises:
        AssetServiceError: If kind is invalid, source_path doesn't exist,
            or the copy fails.
    """
    info = _get_kind_info(kind)

    if not source_path.exists() or not source_path.is_file():
        raise AssetServiceError(f"Source file does not exist: {source_path}")

    dest_dir = project.project_path / info["subfolder"]
    dest_path = _unique_destination(dest_dir, source_path.name)

    try:
        shutil.copy2(source_path, dest_path)
    except OSError as exc:
        raise AssetServiceError(
            f"Failed to copy {source_path} into project: {exc}"
        ) from exc

    relative_path = f"{info['subfolder']}/{dest_path.name}"
    _get_asset_list(project, kind).append(relative_path)

    ProjectSerializer.save(project)
    event_bus.publish(info["added_event"], {"path": relative_path})
    logger.info("Added %s asset: %s", kind, relative_path)

    return relative_path


def remove_asset(
    project: Project, event_bus: EventBus, kind: str, relative_path: str
) -> None:
    """Untrack a previously-added asset and delete its real file.

    Args:
        project: The active project. Must have a non-None project_path.
        event_bus: The event bus the kind's REMOVED event is published on.
        kind: One of "audio", "references", "overlays".
        relative_path: The project-relative path previously returned by
            add_asset(), e.g. "audio/scratch_track.wav".

    Raises:
        AssetServiceError: If kind is invalid, or relative_path is not
            currently tracked on the project.
    """
    info = _get_kind_info(kind)
    asset_list = _get_asset_list(project, kind)

    if relative_path not in asset_list:
        raise AssetServiceError(
            f"{relative_path!r} is not currently tracked as a {kind} asset."
        )

    asset_list.remove(relative_path)

    real_path = project.project_path / relative_path
    try:
        real_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to delete %s file %s: %s", kind, real_path, exc)

    ProjectSerializer.save(project)
    event_bus.publish(info["removed_event"], {"path": relative_path})
    logger.info("Removed %s asset: %s", kind, relative_path)

"""Create new FrameLabs project folders and initial project files."""

from __future__ import annotations

import shutil
from pathlib import Path

from framelabs.project.project import Project
from framelabs.project.serializer import CURRENT_VERSION, ProjectSerializer

# Characters invalid in filenames on Windows. Disallowed on every platform
# so a project created on one OS is always safe to move to another.
_INVALID_NAME_CHARS = '<>:"/\\|?*'

# Reserved device names on Windows. Reserved everywhere for the same
# cross-platform-safety reason as _INVALID_NAME_CHARS.
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}

SUBFOLDERS = ("images", "thumbnails", "cache", "exports", "metadata")


class ProjectCreationError(Exception):
    """Raised when a new project folder or project file cannot be created."""


def _validate_name(name: str) -> None:
    """Raise ProjectCreationError if name is not a safe project folder name."""
    if not name or not name.strip():
        raise ProjectCreationError("Project name cannot be empty.")

    if any(char in _INVALID_NAME_CHARS for char in name):
        raise ProjectCreationError(
            f"Project name cannot contain any of: {_INVALID_NAME_CHARS}"
        )

    if name.strip(" .") != name:
        raise ProjectCreationError(
            "Project name cannot start or end with a space or period."
        )

    if name.upper() in _RESERVED_NAMES:
        raise ProjectCreationError(f'"{name}" is a reserved name and cannot be used.')


def create_new_project(
    name: str,
    parent_dir: Path,
    fps: int,
    resolution: tuple[int, int],
    camera_model: str | None = None,
    camera_lens: str | None = None,
) -> Project:
    """Create a new project folder, its subfolders, and initial project.ffproj.

    Args:
        name: Project name. Used as the folder name and stored in the
            project file.
        parent_dir: Existing folder the new project folder will be created
            inside.
        fps: Frames per second for the new project.
        resolution: (width, height) in pixels.
        camera_model: Optional camera model to record, if known at creation
            time.
        camera_lens: Optional camera lens to record, if known at creation
            time.

    Returns:
        The newly created Project, already saved to disk.

    Raises:
        ProjectCreationError: If the name is invalid, a folder with that
            name already exists, the parent folder isn't writable, or
            folder/file creation fails for any other reason (e.g. disk
            full). On any failure after folder creation has begun, the
            partially created project folder is removed so a failed
            "New Project" never leaves broken state behind.
    """
    _validate_name(name)

    project_dir = parent_dir / name

    if project_dir.exists():
        raise ProjectCreationError(
            f'A folder named "{name}" already exists in {parent_dir}.'
        )

    try:
        project_dir.mkdir(parents=True)
        for subfolder in SUBFOLDERS:
            (project_dir / subfolder).mkdir()

        project = Project(
            version=CURRENT_VERSION,
            name=name,
            fps=fps,
            resolution=resolution,
            camera_model=camera_model,
            camera_lens=camera_lens,
            frames=[],
            project_path=project_dir,
        )
        ProjectSerializer.save(project)

    except PermissionError as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise ProjectCreationError(
            f"No permission to create project in {parent_dir}."
        ) from exc
    except OSError as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise ProjectCreationError(f"Could not create project folder: {exc}") from exc

    return project

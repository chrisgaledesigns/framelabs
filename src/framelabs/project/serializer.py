"""Project serialization for FrameLabs.

Handles reading and writing project.ffproj files as JSON. This module owns
all project file I/O — the Project class itself is a pure data container
with no knowledge of how it gets saved or loaded, per the Developer
Handbook's single-responsibility principle.
"""

from __future__ import annotations

import json
from pathlib import Path

from framelabs.project.project import Frame, Project

CURRENT_VERSION = 3

# Every project.ffproj version this serializer can still read. Per the
# Developer Handbook ("Versioned. Forward-compatible whenever possible."),
# loading an older file must not hard-fail just because CURRENT_VERSION has
# moved on -- v1 files predate Frame.notes/Frame.marker (Feature 5), and
# v1/v2 files predate Project.audio/references/overlays (Project Browser's
# Audio/References/Overlays sections), so those fields are read with
# .get() defaults regardless of which supported version is on disk.
SUPPORTED_VERSIONS = (1, 2, 3)

PROJECT_FILENAME = "project.ffproj"


class ProjectLoadError(Exception):
    """Raised when a project.ffproj file cannot be loaded.

    Covers malformed JSON, missing required fields, and unsupported
    version numbers — anything that prevents reconstructing a valid
    Project from disk.
    """


class ProjectSerializer:
    """Reads and writes project.ffproj files.

    This class owns all project file I/O. Project itself never touches
    the filesystem.
    """

    @staticmethod
    def save(project: Project) -> None:
        """Write a Project to its project.ffproj file.

        Args:
            project: The project to save. Must have project_path set.

        Raises:
            ValueError: If project.project_path is None.
        """
        if project.project_path is None:
            raise ValueError("Cannot save a project with no project_path set.")

        data = {
            "version": project.version,
            "name": project.name,
            "fps": project.fps,
            "resolution": list(project.resolution),
            "camera": {
                "model": project.camera_model,
                "lens": project.camera_lens,
            },
            "frames": [
                {
                    "number": frame.number,
                    "file": frame.file,
                    "notes": frame.notes,
                    "marker": frame.marker,
                }
                for frame in project.frames
            ],
            "audio": list(project.audio),
            "references": list(project.references),
            "overlays": list(project.overlays),
        }

        file_path = project.project_path / PROJECT_FILENAME
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def load(project_path: Path) -> Project:
        """Load a Project from a project.ffproj file.

        Args:
            project_path: The project's folder (containing project.ffproj).

        Returns:
            The reconstructed Project, with project_path set. Files at any
            version in SUPPORTED_VERSIONS load successfully; the returned
            Project is always upgraded to CURRENT_VERSION in memory, so the
            next save() call persists it at the current schema (a v1 file
            with no notes/marker fields transparently becomes v2 on disk
            the next time it's saved, not before).

        Raises:
            ProjectLoadError: If the file is missing, malformed, missing
                required fields, or has an unsupported version.
        """
        file_path = project_path / PROJECT_FILENAME

        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectLoadError(f"Could not read project file: {file_path}") from exc

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProjectLoadError(
                f"Project file is not valid JSON: {file_path}"
            ) from exc

        try:
            version = data["version"]
        except KeyError as exc:
            raise ProjectLoadError(
                f"Project file is missing 'version': {file_path}"
            ) from exc

        if version not in SUPPORTED_VERSIONS:
            raise ProjectLoadError(
                f"Unsupported project version {version!r} "
                f"(supported: {SUPPORTED_VERSIONS}): {file_path}"
            )

        try:
            camera = data.get("camera") or {}
            frames = [
                Frame(
                    number=f["number"],
                    file=f["file"],
                    notes=f.get("notes", ""),
                    marker=f.get("marker", False),
                )
                for f in data["frames"]
            ]
            project = Project(
                version=CURRENT_VERSION,
                name=data["name"],
                fps=data["fps"],
                resolution=tuple(data["resolution"]),
                camera_model=camera.get("model"),
                camera_lens=camera.get("lens"),
                frames=frames,
                audio=list(data.get("audio", [])),
                references=list(data.get("references", [])),
                overlays=list(data.get("overlays", [])),
                project_path=project_path,
            )
        except KeyError as exc:
            raise ProjectLoadError(
                f"Project file is missing required field {exc}: {file_path}"
            ) from exc

        # Projects created before Project.audio/references/overlays existed
        # (schema v1/v2) won't have these subfolders on disk yet. Per the
        # Developer Handbook's "forward-compatible whenever possible" rule,
        # opening an old project transparently upgrades it -- create the
        # missing folders now rather than erroring the first time a user
        # tries to add an audio/reference/overlay file.
        for subfolder in ("audio", "references", "overlays"):
            (project_path / subfolder).mkdir(exist_ok=True)

        return project

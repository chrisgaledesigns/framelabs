"""Project data model for FrameLabs.

Defines the in-memory representation of a stop-motion project. This module
contains only data — no file I/O. Reading and writing `project.ffproj` files
is handled by `project/serializer.py`, per the single-responsibility
principle in the Developer Handbook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Frame:
    """A single captured frame in a project's timeline.

    Attributes:
        number: The frame's position/number in the sequence.
        file: Path to the frame's image file, relative to the project
            root (e.g. "images/000001.png").
    """

    number: int
    file: str


@dataclass
class Project:
    """In-memory representation of a FrameLabs stop-motion project.

    This class holds project state only. It does not read or write files —
    see `project/serializer.py` for loading/saving `project.ffproj`.

    Attributes:
        version: Schema version of the project file format.
        name: Human-readable project name.
        fps: Playback frames per second.
        resolution: Capture resolution as (width, height).
        camera_model: Name of the camera used, if known.
        camera_lens: Lens description, if known.
        frames: Ordered list of captured frames.
        project_path: Filesystem folder this project lives in. Not part of
            the serialized project.ffproj file — set in memory after a
            project is created or loaded, since a project shouldn't
            reference its own containing folder from inside the file
            (that would break if the folder is renamed or moved).
    """

    version: int
    name: str
    fps: int
    resolution: tuple[int, int]
    camera_model: str | None
    camera_lens: str | None
    frames: list[Frame] = field(default_factory=list)
    project_path: Path | None = None

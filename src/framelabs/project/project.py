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
        notes: Free-text note attached to this frame. Defaults to empty
            string, matching Feature 5's spec (notes are optional).
        marker: Whether this frame is flagged with a marker, per Feature 5.
            Defaults to False.
    """

    number: int
    file: str
    notes: str = ""
    marker: bool = False


@dataclass
class CompositeLayer:
    """One layer in the Composite workspace's effects stack.

    Layers composite over every frame in the timeline (a project-wide
    stack, not a per-frame one) -- the Composite workspace is meant as a
    lightweight "look" pass over the whole shot (a vignette, a color
    wash, a rough matte painting behind the puppet), not a per-frame
    rotoscoping tool. `source` always points at an existing Project.overlays
    entry rather than owning its own file, so adding a layer never copies
    anything new onto disk -- see composite_commands.py.

    Attributes:
        source: Relative path (from the project root) of the overlay image
            this layer draws from, e.g. "overlays/vignette.png". Must
            already appear in Project.overlays.
        opacity: 0.0-1.0 strength this layer is blended in at.
        blend_mode: One of image_processing.compositor.BLEND_MODES
            ("normal", "multiply", "screen", "overlay", "add").
        visible: Whether this layer is currently included in the
            composite. Kept separate from deleting the layer so a look
            can be toggled off/on while iterating, per the same
            show/hide-without-losing-settings pattern as Frame.marker.
    """

    source: str
    opacity: float = 1.0
    blend_mode: str = "normal"
    visible: bool = True


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
        audio: Relative paths (from the project root) of audio files added
            to the project, e.g. "audio/scratch_track.wav". Files
            themselves live under the project's `audio/` folder.
        references: Relative paths of reference files added to the
            project, e.g. "references/pose_sketch.png". References are
            always added from outside the app (dragged in from the OS
            file browser) — never copied from a captured Frame. Files
            live under the project's `references/` folder.
        overlays: Relative paths of overlay image files added to the
            project, e.g. "overlays/rough_layout.png". Files live under
            the project's `overlays/` folder.
        composite_layers: Ordered effects stack for the Composite
            workspace, bottom-to-top (index 0 composites first, last
            entry is drawn on top). Each entry draws from an existing
            `overlays` file -- see CompositeLayer's own docstring.
        working_range: Optional (start_frame, end_frame) inclusive range,
            by Frame.number, marking which part of the sequence is
            currently "in" for the Composite workspace's NLA-style strip
            editor. None means the whole sequence is in range (the
            default for every existing and newly-created project).
            Non-destructive: frames outside this range are never removed
            or altered, only flagged out-of-range by whichever UI is
            displaying the sequence (both the Composite workspace's strip
            editor and the Capture tab's TimelineWidget read the same
            field, since they share one Project -- see
            composite_commands.py's SetWorkingRangeCommand).
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
    audio: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    overlays: list[str] = field(default_factory=list)
    composite_layers: list[CompositeLayer] = field(default_factory=list)
    working_range: tuple[int, int] | None = None
    project_path: Path | None = None

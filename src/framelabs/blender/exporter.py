"""Blender export-data generation for FrameLabs.

Feature 10's "Generate Export Data" step. Pure business logic -- no Qt, no
bpy. Writes a JSON manifest describing the project (frames in Timeline
order, fps, resolution, camera info) that a Blender-side script (run
inside Blender's own Python by launcher.py) reads to build the scene.

Per the Developer Handbook, Blender integration is isolated to this
package -- the core app never imports bpy, and nothing here imports Qt.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from framelabs.project.project import Project

MANIFEST_FILENAME = "blender_manifest.json"

# Fallback used whenever camera_lens is missing or has no parseable
# number in it -- 50mm is the standard "normal" lens focal length, close
# to human eye perspective, and a reasonable default for a stop-motion
# reference camera with no real lens data to go on.
DEFAULT_FOCAL_LENGTH_MM = 50.0

_LEADING_NUMBER = re.compile(r"(\d+(?:\.\d+)?)")


class BlenderExportError(Exception):
    """Raised when export-data generation fails."""


@dataclass
class BlenderManifest:
    """Everything the Blender-side script needs to build the scene.

    Attributes:
        project_name: Human-readable project name, used for the .blend
            filename.
        fps: Playback frames per second.
        resolution: (width, height) in pixels.
        focal_length_mm: Parsed or defaulted camera focal length -- see
            parse_focal_length_mm().
        frame_paths: Absolute paths to each frame image, in Timeline
            order. Absolute because the Blender-side script runs as its
            own process with no guaranteed cwd relationship to the
            project folder.
        blend_output_path: Absolute path the .blend should be saved to.
    """

    project_name: str
    fps: int
    resolution: tuple[int, int]
    focal_length_mm: float
    frame_paths: list[str]
    blend_output_path: str


def parse_focal_length_mm(
    camera_lens: str | None, default: float = DEFAULT_FOCAL_LENGTH_MM
) -> float:
    """Pull a focal length in mm out of a free-text lens description.

    camera_lens is user-entered free text (e.g. "50mm", "24-70mm f/2.8",
    "Canon 50mm STM") -- there is no structured numeric focal-length field
    in the data model. This takes the first number found and returns it;
    if camera_lens is None, empty, or has no number in it at all, returns
    `default` instead of raising, since a missing/malformed lens string
    must never block a Blender export.

    For a range like "24-70mm", this returns the first number (24.0) --
    a reasonable single value is required for a static camera, and the
    wide end is the more common default framing.

    Args:
        camera_lens: Project.camera_lens, or None.
        default: Value to return when nothing parseable is found.

    Returns:
        A focal length in mm.
    """
    if not camera_lens:
        return default
    match = _LEADING_NUMBER.search(camera_lens)
    if match is None:
        return default
    return float(match.group(1))


def _ordered_frame_paths(project: Project) -> list[str]:
    """Absolute frame image paths, in Timeline order.

    Mirrors export_service.py's _ordered_frames() -- exports must follow
    the same ordering Timeline/Playback/Onion Skin already use, not raw
    on-disk filename order.
    """
    frames = sorted(project.frames, key=lambda f: f.number)
    return [str(project.project_path / f.file) for f in frames]


def build_manifest(project: Project) -> BlenderManifest:
    """Build the manifest describing `project` for the Blender-side script.

    Args:
        project: The active project. Must have a non-None project_path
            and at least one frame.

    Returns:
        A BlenderManifest ready to be written to disk.

    Raises:
        BlenderExportError: If the project has no project_path or no
            frames -- there is nothing to send to Blender either way.
    """
    if project.project_path is None:
        raise BlenderExportError("Project has no project_path set.")
    frame_paths = _ordered_frame_paths(project)
    if not frame_paths:
        raise BlenderExportError("Project has no frames to export.")

    blend_output_path = project.project_path / "exports" / f"{project.name}.blend"

    return BlenderManifest(
        project_name=project.name,
        fps=project.fps,
        resolution=tuple(project.resolution),
        focal_length_mm=parse_focal_length_mm(project.camera_lens),
        frame_paths=frame_paths,
        blend_output_path=str(blend_output_path),
    )


def write_manifest(project: Project) -> Path:
    """Build and write the manifest to project_path/cache/blender/.

    Lives under cache/, same as undo backups -- transient, regenerated
    data, not something the user needs to see or that belongs in
    version-controllable project state.

    Args:
        project: The active project.

    Returns:
        Path to the written manifest JSON file.

    Raises:
        BlenderExportError: See build_manifest(). Also raised if the
            file write itself fails.
    """
    manifest = build_manifest(project)
    manifest_dir = project.project_path / "cache" / "blender"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / MANIFEST_FILENAME

    try:
        manifest_path.write_text(json.dumps(asdict(manifest), indent=2))
    except OSError as exc:
        raise BlenderExportError(f"Failed to write Blender manifest: {exc}") from exc

    return manifest_path

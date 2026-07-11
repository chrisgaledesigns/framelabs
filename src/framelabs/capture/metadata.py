"""Per-frame capture metadata I/O.

Writes a small JSON file for each captured frame containing the capture
timestamp and camera identity. Deliberately does NOT record exposure
settings (ISO/shutter/aperture) — CameraInterface only exposes setters
for those, not getters, so we cannot honestly report the values actually
used for a given shot.

This module has no knowledge of CameraManager or any camera backend —
it receives a CameraMetadata object from the caller (capture_service.py)
and writes it out. This keeps camera-layer logic from leaking into the
capture I/O layer, per the handbook's "no backend-specific logic should
leak into other modules" rule.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from framelabs.camera.camera_interface import CameraMetadata
from framelabs.project.project import Project


class MetadataWriteError(Exception):
    """Raised when per-frame metadata fails to write to disk."""


def write_metadata(
    project: Project, frame_number: int, camera_metadata: CameraMetadata
) -> Path:
    """Write per-frame capture metadata as JSON to the project's metadata folder.

    Args:
        project: The active project. Must have a non-None project_path.
        frame_number: The frame number this metadata belongs to.
        camera_metadata: Camera identity info for the camera that captured
            this frame.

    Returns:
        The path to the written metadata JSON file.

    Raises:
        ValueError: If project.project_path is None.
        MetadataWriteError: If the JSON file fails to write to disk.
    """
    if project.project_path is None:
        raise ValueError("project.project_path is None; cannot write metadata")

    metadata_dir = project.project_path / "metadata"
    metadata_path = metadata_dir / f"{frame_number:06d}.json"

    payload = {
        "frame_number": frame_number,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "camera": {
            "camera_id": camera_metadata.camera_id,
            "display_name": camera_metadata.display_name,
            "backend_type": camera_metadata.backend_type,
        },
    }

    try:
        metadata_path.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        raise MetadataWriteError(
            f"Failed to write metadata for frame {frame_number}: {exc}"
        ) from exc

    return metadata_path

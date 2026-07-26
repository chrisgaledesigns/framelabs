"""Video / image-sequence / GIF export service for FrameLabs.

This is the real implementation behind the "Export Video, Sequence & GIF"
menu action (ui/main_window.py). It is a SEPARATE thing from the existing
`export_action`/`export_service` stub reserved for Feature 10's future
Blender-export pipeline ("Generate Export Data" in the spec) -- that stub
is untouched by this module. Every export lands in the project's own
`exports/` folder, which is already created up front by
`project/creator.py` and already scanned/listed by
`ProjectBrowserWidget`'s Exports section.

Per the Developer Handbook, this module is pure business logic -- no Qt,
no UI, no threading. See `ui/export_controller.py` for the worker-thread
wrapper that keeps a long export from blocking the UI.
"""

from __future__ import annotations

import datetime
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import cv2
from PIL import Image

from framelabs.core.event_bus import EventBus
from framelabs.project.project import Frame, Project

logger = logging.getLogger(__name__)

# FourCC codes to try, in order, when opening the video writer. Not every
# OpenCV build ships a real H.264 encoder ("avc1"), so this falls back to
# "mp4v" (MPEG-4 in an .mp4 container), which is present in every build
# shipped as the opencv-python wheel -- see export_video()'s docstring.
_VIDEO_FOURCCS = ("avc1", "mp4v")

# Characters that are unsafe in a filename on at least one of
# Windows/macOS/Linux.
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


class ExportServiceError(Exception):
    """Raised when a project has nothing to export, or a real export
    (video/image-sequence/GIF write) fails."""


@dataclass
class ExportResult:
    """Outcome of an export_all() call.

    Attributes:
        succeeded: Maps each format key ("video", "image_sequence", "gif")
            that completed successfully to the real Path it wrote.
        failed: Maps each format key that raised ExportServiceError to its
            error message. A format failing doesn't stop the others from
            running -- see export_all()'s docstring.
    """

    succeeded: dict[str, Path] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)


def _ordered_frames(project: Project) -> list[Frame]:
    """Frames in sequence order, sorted by frame number.

    Mirrors timeline/timeline.py's Timeline.frames property -- exports
    must follow the same ordering Timeline/Playback/Onion Skin already
    use, not raw on-disk filename order.
    """
    return sorted(project.frames, key=lambda f: f.number)


def _sanitized_name(name: str) -> str:
    """Strip characters unsafe in a filename on any platform, collapsing
    each to an underscore. Falls back to "export" if nothing is left."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip()
    return cleaned or "export"


def _export_basename(project: Project) -> str:
    """A collision-resistant base filename shared by one export_all()
    call's video/sequence/GIF outputs, e.g.
    "Robot_Walk_Cycle_20260726_143512" -- so the three results are
    recognizable in the Exports list as having come from the same click.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{_sanitized_name(project.name)}_{timestamp}"


def _require_frames(project: Project) -> list[Frame]:
    """Frames in order, or raise ExportServiceError if there is nothing
    to export. Checked up front, before any output is created, so a
    project with no frames yet never leaves a half-written file behind.
    """
    if project.project_path is None:
        raise ExportServiceError("Project has no project_path set.")
    frames = _ordered_frames(project)
    if not frames:
        raise ExportServiceError("Project has no frames to export.")
    return frames


def _exports_dir(project: Project) -> Path:
    """The project's exports/ folder, creating it if the project predates
    it or it was somehow removed -- mirrors create_new_project()'s own
    layout rather than assuming it's always already there.
    """
    exports_dir = project.project_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    return exports_dir


def export_video(project: Project, event_bus: EventBus, basename: str) -> Path:
    """Render every frame, in Timeline order, to an MP4 at project.fps.

    Tries "avc1" (H.264) first, falling back to the always-available
    "mp4v" (MPEG-4) FourCC. cv2.VideoWriter.isOpened() is checked
    explicitly after each attempt rather than assumed -- OpenCV silently
    hands back an unusable writer instead of raising when a FourCC isn't
    supported by the local build/system codecs.

    Args:
        project: The active project. Must have a non-None project_path
            and at least one frame.
        event_bus: The event bus VIDEO_EXPORTED is published on.
        basename: Shared base filename, no extension (see
            _export_basename()).

    Returns:
        The real path of the written .mp4 file.

    Raises:
        ExportServiceError: If the project has no frames, no FourCC this
            OpenCV build supports could open a writer, or a frame image
            can't be read.
    """
    frames = _require_frames(project)
    width, height = project.resolution
    output_path = _exports_dir(project) / f"{basename}.mp4"

    writer = None
    for fourcc_code in _VIDEO_FOURCCS:
        fourcc = cv2.VideoWriter.fourcc(*fourcc_code)
        candidate = cv2.VideoWriter(
            str(output_path), fourcc, float(project.fps), (width, height)
        )
        if candidate.isOpened():
            writer = candidate
            break
        candidate.release()

    if writer is None:
        raise ExportServiceError(
            "No available video codec could open a writer for this export."
        )

    try:
        for frame in frames:
            image = cv2.imread(str(project.project_path / frame.file))
            if image is None:
                raise ExportServiceError(f"Could not read frame image: {frame.file}")
            if (image.shape[1], image.shape[0]) != (width, height):
                image = cv2.resize(image, (width, height))
            writer.write(image)
    finally:
        writer.release()

    event_bus.publish("VIDEO_EXPORTED", {"path": str(output_path)})
    logger.info("Video exported: %s", output_path)
    return output_path


def export_image_sequence(project: Project, event_bus: EventBus, basename: str) -> Path:
    """Copy every frame, in Timeline order, into a fresh
    exports/<basename>_sequence/ folder, renumbered sequentially from 1
    with no gaps -- regardless of the original (possibly non-contiguous,
    e.g. after a Delete Frame) frame numbers.

    Copies the original files directly (shutil.copy2) rather than
    round-tripping through cv2.imread/imwrite, so the exported sequence
    is bit-for-bit identical to the captured images, not a re-encode.

    Args:
        project: The active project. Must have a non-None project_path
            and at least one frame.
        event_bus: The event bus IMAGE_SEQUENCE_EXPORTED is published on.
        basename: Shared base filename, no extension (see
            _export_basename()).

    Returns:
        The real path of the written sequence folder.

    Raises:
        ExportServiceError: If the project has no frames, or a copy
            fails.
    """
    frames = _require_frames(project)
    sequence_dir = _exports_dir(project) / f"{basename}_sequence"
    sequence_dir.mkdir(parents=True, exist_ok=True)

    for index, frame in enumerate(frames, start=1):
        source_path = project.project_path / frame.file
        suffix = Path(frame.file).suffix or ".png"
        dest_path = sequence_dir / f"{index:06d}{suffix}"
        try:
            shutil.copy2(source_path, dest_path)
        except OSError as exc:
            raise ExportServiceError(
                f"Failed to copy frame {frame.file} into image sequence: {exc}"
            ) from exc

    event_bus.publish("IMAGE_SEQUENCE_EXPORTED", {"path": str(sequence_dir)})
    logger.info("Image sequence exported: %s", sequence_dir)
    return sequence_dir


def export_gif(project: Project, event_bus: EventBus, basename: str) -> Path:
    """Render every frame, in Timeline order, to a looping animated GIF
    at project.fps.

    Uses Pillow rather than OpenCV -- OpenCV has no animated GIF encoder,
    and Pillow's is small, well-established, and MIT-licensed like the
    rest of FrameLabs' dependencies.

    Args:
        project: The active project. Must have a non-None project_path
            and at least one frame.
        event_bus: The event bus GIF_EXPORTED is published on.
        basename: Shared base filename, no extension (see
            _export_basename()).

    Returns:
        The real path of the written .gif file.

    Raises:
        ExportServiceError: If the project has no frames, a frame image
            can't be read, or the write fails.
    """
    frames = _require_frames(project)
    output_path = _exports_dir(project) / f"{basename}.gif"
    duration_ms = round(1000 / project.fps)

    images = []
    for frame in frames:
        source_path = project.project_path / frame.file
        try:
            images.append(Image.open(source_path).convert("RGB"))
        except OSError as exc:
            raise ExportServiceError(
                f"Could not read frame image for GIF: {frame.file}: {exc}"
            ) from exc

    try:
        images[0].save(
            output_path,
            save_all=True,
            append_images=images[1:],
            duration=duration_ms,
            loop=0,
        )
    except OSError as exc:
        raise ExportServiceError(f"Failed to write GIF: {exc}") from exc

    event_bus.publish("GIF_EXPORTED", {"path": str(output_path)})
    logger.info("GIF exported: %s", output_path)
    return output_path


def export_all(project: Project, event_bus: EventBus) -> ExportResult:
    """Export video, image sequence, and GIF in one call, sharing one
    timestamped basename so the three outputs are recognizable in the
    Exports list as belonging together.

    Runs all three independently -- one format failing (e.g. no usable
    video codec on this machine) doesn't stop the other two from being
    written, per the Handbook's "never lose user data" spirit: partial
    output beats none. Only raises if the project has no frames at all,
    since in that case none of the three could ever succeed anyway.

    Args:
        project: The active project.
        event_bus: The event bus each successful format's *_EXPORTED
            event is published on.

    Returns:
        An ExportResult listing which formats succeeded (with their real
        paths) and which failed (with an error message each).

    Raises:
        ExportServiceError: If the project has no project_path or no
            frames.
    """
    _require_frames(project)
    basename = _export_basename(project)

    result = ExportResult()
    for key, export_func in (
        ("video", export_video),
        ("image_sequence", export_image_sequence),
        ("gif", export_gif),
    ):
        try:
            result.succeeded[key] = export_func(project, event_bus, basename)
        except ExportServiceError as exc:
            logger.error("%s export failed: %s", key, exc)
            result.failed[key] = str(exc)

    return result

"""Orchestrates the full frame capture sequence.

Per the Developer Handbook, capture must follow this exact sequence:
Trigger camera -> Receive image -> Verify image -> Write image ->
Write metadata -> Generate thumbnail -> Update timeline -> Autosave ->
Emit FRAME_CAPTURED.

This is Feature 4 in the Feature Specification -- "the most important
feature" -- so failure handling here matters more than almost anywhere
else in the codebase. See module-level docstrings in frame_writer.py and
metadata.py for the guarantees each of those modules makes; this module
ties them together with CameraManager and ProjectSerializer.
"""

import logging

from framelabs.camera.camera_interface import CameraError
from framelabs.camera.camera_manager import CameraManager
from framelabs.capture.frame_writer import (
    CaptureWriteError,
    DiskFullError,
    generate_thumbnail,
    write_frame,
)
from framelabs.capture.metadata import MetadataWriteError, write_metadata
from framelabs.core.event_bus import EventBus
from framelabs.project.project import Frame, Project
from framelabs.project.serializer import ProjectSerializer

logger = logging.getLogger(__name__)


class CaptureServiceError(Exception):
    """Raised when no valid frame could be captured.

    This is only raised for failures before a valid image exists on disk
    (camera trigger failure, or frame_writer exhausting its own internal
    retry). A metadata-write failure after the image is already good does
    NOT raise this -- see _write_metadata_with_one_retry's docstring below.
    """


class DiskFullServiceError(CaptureServiceError):
    """Raised when the frame image write failed specifically because the
    disk is full.

    A subclass of CaptureServiceError, not a sibling -- any existing
    caller that catches CaptureServiceError still catches this too. Wraps
    frame_writer.DiskFullError, which is itself only raised after a real
    OSError with errno.ENOSPC. Lets the UI layer show Feature 4's
    distinct "Disk Full" / "Capture Aborted" dialog instead of the
    generic capture-failed one.
    """


def capture_frame(
    project: Project, camera_manager: CameraManager, event_bus: EventBus
) -> Frame:
    """Capture a new frame: trigger the camera, write it to disk, update the project.

    Runs the handbook's full capture sequence: triggers the active camera,
    verifies and writes the image, generates a thumbnail, writes per-frame
    metadata, appends the new Frame to the project's timeline, autosaves
    the project, and publishes FRAME_CAPTURED.

    Args:
        project: The active project. Must have a non-None project_path.
        camera_manager: The CameraManager whose active camera will be
            triggered.
        event_bus: The event bus FRAME_CAPTURED will be published on.

    Returns:
        The newly captured Frame, already appended to project.frames.

    Raises:
        ValueError: If project.project_path is None.
        CaptureServiceError: If the camera trigger fails, or if
            frame_writer cannot produce a valid written image after its
            own internal retry. No frame is added to the timeline and
            nothing is left on disk in either case.
        DiskFullServiceError: If the frame image write failed after
            retry specifically because the disk is full. A subclass of
            CaptureServiceError.
    """
    if project.project_path is None:
        raise ValueError("project.project_path is None; cannot capture frame")

    frame_number = _next_frame_number(project)

    # Trigger + Receive
    try:
        image_bytes = camera_manager.capture()
    except CameraError as exc:
        logger.error("Capture failed for frame %d: %s", frame_number, exc)
        raise CaptureServiceError(f"Camera capture failed: {exc}") from exc

    # Verify + Write image
    try:
        write_frame(image_bytes, project, frame_number)
    except DiskFullError as exc:
        logger.error("Disk full writing frame %d: %s", frame_number, exc)
        raise DiskFullServiceError(f"Disk full while writing frame: {exc}") from exc
    except CaptureWriteError as exc:
        logger.error("Failed to write frame %d: %s", frame_number, exc)
        raise CaptureServiceError(f"Failed to write frame: {exc}") from exc

    # Generate thumbnail
    try:
        generate_thumbnail(image_bytes, project, frame_number)
    except CaptureWriteError as exc:
        # The real frame image already exists and is valid at this point.
        # A thumbnail is a disposable derived preview (see frame_writer.py),
        # so losing it is not worth discarding an already-good captured
        # frame over. Log clearly and continue. This is deliberately still
        # a bare CaptureWriteError catch (covers DiskFullError too, since
        # it's a subclass) -- a disk-full thumbnail failure is exactly as
        # non-fatal as any other thumbnail failure.
        logger.error(
            "Thumbnail generation failed for frame %d (frame image is still "
            "valid and kept): %s",
            frame_number,
            exc,
        )

    # Write metadata, with one retry at this orchestration level (separate
    # from metadata.py's own no-retry-internally rule).
    _write_metadata_with_one_retry(project, frame_number, camera_manager)

    # Update timeline
    frame = Frame(number=frame_number, file=f"images/{frame_number:06d}.png")
    project.frames.append(frame)

    # Autosave
    ProjectSerializer.save(project)

    # Emit FRAME_CAPTURED
    event_bus.publish("FRAME_CAPTURED", {"frame_number": frame_number})
    logger.info("Captured frame %d", frame_number)

    return frame


def _next_frame_number(project: Project) -> int:
    """Compute the next frame number as max(existing, default=0) + 1.

    Deliberately not len(frames) + 1, so numbering stays correct once
    delete/replace exist (Feature 4's "no duplicate frame numbers"
    acceptance criterion).
    """
    if not project.frames:
        return 1
    return max(f.number for f in project.frames) + 1


def _write_metadata_with_one_retry(
    project: Project, frame_number: int, camera_manager: CameraManager
) -> None:
    """Write per-frame metadata, retrying once at this orchestration level.

    If both attempts fail, the failure is logged and swallowed -- the
    already-written image and thumbnail are kept regardless (never deleted
    for a metadata problem), and the frame still gets added to the
    timeline by the caller. This bounded, single retry cannot cascade: a
    string of failing frames each get exactly one extra attempt, never
    more.
    """
    camera_metadata = camera_manager.get_active_camera_metadata()

    for attempt in (1, 2):
        try:
            write_metadata(project, frame_number, camera_metadata)
            return
        except MetadataWriteError as exc:
            if attempt == 1:
                logger.warning(
                    "Metadata write failed for frame %d, retrying once: %s",
                    frame_number,
                    exc,
                )
            else:
                logger.error(
                    "Metadata write failed for frame %d after retry; frame "
                    "image and thumbnail are kept, metadata is missing: %s",
                    frame_number,
                    exc,
                )

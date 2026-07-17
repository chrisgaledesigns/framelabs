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

Also implements Feature 5's delete/replace/duplicate frame actions
(delete_frame, replace_frame, duplicate_frame), since they share the same
capture/write pipeline and file-layout knowledge as capture_frame itself.
"""

import logging
import shutil

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


class FrameNotFoundError(CaptureServiceError):
    """Raised when delete/replace/duplicate is given a frame_number that
    doesn't exist in the project.

    A subclass of CaptureServiceError, not a sibling -- any existing
    caller that catches CaptureServiceError still catches this too.
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

    _write_captured_image(project, camera_manager, frame_number)

    # Update timeline
    frame = Frame(number=frame_number, file=f"images/{frame_number:06d}.png")
    project.frames.append(frame)

    # Autosave
    ProjectSerializer.save(project)

    # Emit FRAME_CAPTURED
    event_bus.publish("FRAME_CAPTURED", {"frame_number": frame_number})
    logger.info("Captured frame %d", frame_number)

    return frame


def replace_frame(
    project: Project,
    camera_manager: CameraManager,
    event_bus: EventBus,
    frame_number: int,
) -> Frame:
    """Replace an existing frame's image with a freshly captured one.

    Per Feature 5's spec, the frame number stays the same -- only the
    image, thumbnail, and metadata files are overwritten. The existing
    Frame's notes and marker are left untouched, since replacing the
    photo isn't the same operation as editing those fields.

    Args:
        project: The active project. Must have a non-None project_path.
        camera_manager: The CameraManager whose active camera will be
            triggered.
        event_bus: The event bus FRAME_REPLACED will be published on.
        frame_number: The existing frame to replace.

    Returns:
        The same Frame instance that was already in project.frames,
        unchanged except for the files on disk now being newer.

    Raises:
        ValueError: If project.project_path is None.
        FrameNotFoundError: If no frame with frame_number exists.
        CaptureServiceError: If the camera trigger fails, or if
            frame_writer cannot produce a valid written image after its
            own internal retry. The original frame's files are left
            exactly as they were if the new capture never got as far as
            overwriting them.
        DiskFullServiceError: If the frame image write failed after
            retry specifically because the disk is full. A subclass of
            CaptureServiceError.
    """
    if project.project_path is None:
        raise ValueError("project.project_path is None; cannot replace frame")

    frame = _find_frame(project, frame_number)

    _write_captured_image(project, camera_manager, frame_number)

    ProjectSerializer.save(project)

    event_bus.publish("FRAME_REPLACED", {"frame_number": frame_number})
    logger.info("Replaced frame %d", frame_number)

    return frame


def duplicate_frame(project: Project, event_bus: EventBus, frame_number: int) -> Frame:
    """Duplicate an existing frame's image/thumbnail/metadata as a new frame.

    The duplicate is appended to the end of the sequence under the next
    available frame number, matching how capture_frame already numbers
    new frames -- inserting a duplicate adjacent to its source would
    require reordering, which the Feature Specification explicitly marks
    "(future)". The duplicate's notes are copied from the source (useful
    context to keep), but its marker is reset to False, since a marker
    flags a specific, deliberately-chosen frame rather than a property
    that should propagate to copies.

    Args:
        project: The active project. Must have a non-None project_path.
        event_bus: The event bus FRAME_DUPLICATED will be published on.
        frame_number: The existing frame to duplicate.

    Returns:
        The newly created Frame, already appended to project.frames.

    Raises:
        ValueError: If project.project_path is None.
        FrameNotFoundError: If no frame with frame_number exists.
        CaptureServiceError: If the source frame's image file can't be
            copied. Thumbnail/metadata copy failures are logged and
            skipped instead, matching capture_frame's own treatment of
            thumbnails/metadata as non-fatal derived data.
    """
    if project.project_path is None:
        raise ValueError("project.project_path is None; cannot duplicate frame")

    source = _find_frame(project, frame_number)
    new_number = _next_frame_number(project)

    _copy_frame_files(project, frame_number, new_number)

    new_frame = Frame(
        number=new_number,
        file=f"images/{new_number:06d}.png",
        notes=source.notes,
        marker=False,
    )
    project.frames.append(new_frame)

    ProjectSerializer.save(project)

    event_bus.publish(
        "FRAME_DUPLICATED",
        {"source_frame_number": frame_number, "new_frame_number": new_number},
    )
    logger.info("Duplicated frame %d as frame %d", frame_number, new_number)

    return new_frame


def delete_frame(project: Project, event_bus: EventBus, frame_number: int) -> None:
    """Delete a frame's files and remove it from the project's timeline.

    Args:
        project: The active project. Must have a non-None project_path.
        event_bus: The event bus FRAME_DELETED will be published on.
        frame_number: The frame to delete.

    Raises:
        ValueError: If project.project_path is None.
        FrameNotFoundError: If no frame with frame_number exists.
    """
    if project.project_path is None:
        raise ValueError("project.project_path is None; cannot delete frame")

    frame = _find_frame(project, frame_number)

    _delete_frame_files(project, frame_number)
    project.frames.remove(frame)

    ProjectSerializer.save(project)

    event_bus.publish("FRAME_DELETED", {"frame_number": frame_number})
    logger.info("Deleted frame %d", frame_number)


def _write_captured_image(
    project: Project, camera_manager: CameraManager, frame_number: int
) -> None:
    """Run the shared trigger/verify/write/thumbnail/metadata pipeline.

    Shared by capture_frame (new frame) and replace_frame (existing frame
    number, overwritten files), so the two can never silently drift apart
    in how a captured image actually gets to disk.

    Raises:
        CaptureServiceError: If the camera trigger fails, or if
            frame_writer cannot produce a valid written image after its
            own internal retry.
        DiskFullServiceError: If the frame image write failed after
            retry specifically because the disk is full.
    """
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


def _find_frame(project: Project, frame_number: int) -> Frame:
    """Return the Frame with the given number, or raise FrameNotFoundError."""
    for frame in project.frames:
        if frame.number == frame_number:
            return frame
    raise FrameNotFoundError(f"No frame numbered {frame_number} in project.")


def _copy_frame_files(project: Project, source_number: int, dest_number: int) -> None:
    """Copy a frame's image, thumbnail, and metadata files to a new frame number.

    The image copy is treated as mandatory -- a duplicate with no image
    isn't a real frame, so a failure here raises. Thumbnail and metadata
    are treated the same as capture_frame treats them: missing or
    uncopyable is logged and skipped, never fatal.
    """
    src_image = project.project_path / "images" / f"{source_number:06d}.png"
    dst_image = project.project_path / "images" / f"{dest_number:06d}.png"
    try:
        shutil.copy2(src_image, dst_image)
    except OSError as exc:
        raise CaptureServiceError(
            f"Failed to duplicate frame {source_number}'s image: {exc}"
        ) from exc

    src_thumb = project.project_path / "thumbnails" / f"{source_number:06d}.jpg"
    dst_thumb = project.project_path / "thumbnails" / f"{dest_number:06d}.jpg"
    if src_thumb.exists():
        try:
            shutil.copy2(src_thumb, dst_thumb)
        except OSError as exc:
            logger.warning(
                "Failed to duplicate thumbnail for frame %d: %s", source_number, exc
            )

    src_meta = project.project_path / "metadata" / f"{source_number:06d}.json"
    dst_meta = project.project_path / "metadata" / f"{dest_number:06d}.json"
    if src_meta.exists():
        try:
            shutil.copy2(src_meta, dst_meta)
        except OSError as exc:
            logger.warning(
                "Failed to duplicate metadata for frame %d: %s", source_number, exc
            )


def _delete_frame_files(project: Project, frame_number: int) -> None:
    """Delete a frame's image, thumbnail, and metadata files, if present.

    Missing files are not errors -- e.g. a frame whose thumbnail
    generation previously failed (see _write_captured_image's
    thumbnail-failure handling) legitimately has no thumbnail to delete.
    """
    targets = (
        project.project_path / "images" / f"{frame_number:06d}.png",
        project.project_path / "thumbnails" / f"{frame_number:06d}.jpg",
        project.project_path / "metadata" / f"{frame_number:06d}.json",
    )
    for path in targets:
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Failed to delete %s: %s", path, exc)


def _next_frame_number(project: Project) -> int:
    """Compute the next frame number as max(existing, default=0) + 1.

    Deliberately not len(frames) + 1, so numbering stays correct with
    delete/duplicate now in play (Feature 4's "no duplicate frame
    numbers" acceptance criterion) -- e.g. deleting the last frame and
    capturing again must not reissue a number still referenced by a
    duplicate made earlier.
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

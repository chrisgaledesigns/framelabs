"""Verify, write, and thumbnail captured frame images.

Implements the "Write image" / "Generate thumbnail" steps of the capture
sequence defined in the Developer Handbook:

    Trigger camera -> Receive image -> Verify image -> Write image ->
    Write metadata -> Generate thumbnail -> Update timeline -> Autosave ->
    Emit FRAME_CAPTURED

This module only knows about raw image bytes and a Project's folder layout.
It has no knowledge of cameras, the event bus, or the timeline -- that
orchestration lives in capture_service.py.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from framelabs.project.project import Project

# Thumbnails are generated at this width, preserving aspect ratio. Chosen
# for sharpness on high-DPI displays while staying light to generate/store.
THUMBNAIL_WIDTH = 400

# JPEG quality for thumbnails (0-100). Thumbnails are disposable derived
# previews, not archival, so lossy compression is appropriate here even
# though the actual frame is always written as lossless PNG.
THUMBNAIL_JPEG_QUALITY = 85

# How many total attempts to make writing to disk before giving up, per
# Feature 4's "Write failure: Retry once" requirement (1 initial attempt +
# 1 retry).
WRITE_ATTEMPTS = 2


class CaptureWriteError(Exception):
    """Raised when a captured frame cannot be verified, written, or thumbnailed."""


class DiskFullError(CaptureWriteError):
    """Raised specifically when a write failed because the disk is full.

    A subclass of CaptureWriteError, not a sibling -- any existing caller
    that catches CaptureWriteError still catches this too. Only raised when
    the underlying OSError's errno is ENOSPC ("No space left on device"),
    so this is never a guess based on a message string. Lets the UI layer
    show Feature 4's distinct "Disk Full" / "Capture Aborted" dialog
    instead of the generic capture-failed one.
    """


def _decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode raw image bytes into a real image, or raise CaptureWriteError.

    This is the actual verification step -- a corrupt or truncated capture
    will fail to decode here, before anything is ever written to disk.
    """
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise CaptureWriteError("Captured image data could not be decoded.")
    return image


def _write_with_retry(path: Path, write_fn: Callable[[Path], bool]) -> None:
    """Call write_fn(path), retrying once on failure.

    write_fn must return a truthy value on success, matching cv2.imwrite's
    own return convention (True on success, False on failure -- it does not
    raise for most failure modes, so the return value has to be checked).

    Raises DiskFullError instead of the generic CaptureWriteError if the
    final failed attempt's OSError.errno is ENOSPC -- this is checked only
    after retries are exhausted, so a transient disk-full condition that
    clears up by the second attempt never surfaces as an error at all.
    """
    last_error: OSError | None = None
    for _ in range(WRITE_ATTEMPTS):
        try:
            if write_fn(path):
                return
        except OSError as exc:
            last_error = exc

    if last_error is not None and last_error.errno == errno.ENOSPC:
        raise DiskFullError(f"Disk full while writing {path}: {last_error}")

    detail = f": {last_error}" if last_error else ""
    raise CaptureWriteError(f"Failed to write {path} after retry{detail}.")


def write_frame(image_bytes: bytes, project: Project, frame_number: int) -> Path:
    """Verify and write a captured frame as a PNG into the project's images folder.

    Args:
        image_bytes: Raw encoded image data as returned by
            CameraInterface.capture().
        project: The active Project. Must have project_path set.
        frame_number: The frame number to write this image as.

    Returns:
        The path the PNG was written to.

    Raises:
        CaptureWriteError: If project.project_path is None, the image data
            cannot be decoded, or writing to disk fails even after one
            retry.
        DiskFullError: If writing to disk fails after one retry
            specifically because the disk is full. A subclass of
            CaptureWriteError.
    """
    if project.project_path is None:
        raise CaptureWriteError("Project has no project_path; cannot write frame.")

    image = _decode_image(image_bytes)

    output_path = project.project_path / "images" / f"{frame_number:06d}.png"
    _write_with_retry(output_path, lambda path: cv2.imwrite(str(path), image))

    return output_path


def generate_thumbnail(image_bytes: bytes, project: Project, frame_number: int) -> Path:
    """Generate and write a JPEG thumbnail for a captured frame.

    Args:
        image_bytes: Raw encoded image data as returned by
            CameraInterface.capture().
        project: The active Project. Must have project_path set.
        frame_number: The frame number this thumbnail belongs to.

    Returns:
        The path the thumbnail JPEG was written to.

    Raises:
        CaptureWriteError: If project.project_path is None, the image data
            cannot be decoded, or writing to disk fails even after one
            retry.
        DiskFullError: If writing to disk fails after one retry
            specifically because the disk is full. A subclass of
            CaptureWriteError. Note that capture_service.py currently
            treats ANY thumbnail failure as non-fatal (the real frame
            image is already written and kept), so this being a disk-full
            case specifically does not change that -- it's still just
            logged and continued past, same as before.
    """
    if project.project_path is None:
        raise CaptureWriteError("Project has no project_path; cannot write thumbnail.")

    image = _decode_image(image_bytes)

    height, width = image.shape[:2]
    scale = THUMBNAIL_WIDTH / width
    thumbnail = cv2.resize(
        image,
        (THUMBNAIL_WIDTH, round(height * scale)),
        interpolation=cv2.INTER_AREA,
    )

    output_path = project.project_path / "thumbnails" / f"{frame_number:06d}.jpg"
    _write_with_retry(
        output_path,
        lambda path: cv2.imwrite(
            str(path), thumbnail, [cv2.IMWRITE_JPEG_QUALITY, THUMBNAIL_JPEG_QUALITY]
        ),
    )

    return output_path

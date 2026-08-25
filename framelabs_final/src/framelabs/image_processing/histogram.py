"""Luminance histogram computation for Live View's Inspector panel.

Pure image-processing logic: converts an RGB frame into a normalized
luminance histogram. No Qt, camera, or threading dependencies -- safe to
unit test directly, and safe to call from any thread (used from the Live
View worker thread, per session 9's histogram overlay work).
"""

from __future__ import annotations

import numpy as np

HISTOGRAM_BINS = 256
DOWNSAMPLE_MAX_DIMENSION = 256

# Rec. 601 luma weights -- standard perceptual RGB-to-luminance conversion.
_LUMA_WEIGHTS = (0.299, 0.587, 0.114)


def compute_luminance_histogram(frame: np.ndarray) -> np.ndarray:
    """Compute a normalized luminance histogram from an RGB frame.

    The frame is downsampled before analysis so this stays cheap enough
    to run on every Live View frame (target: 30+ FPS) without becoming
    the bottleneck. Downsampling affects the histogram's smoothness
    only, not its overall shape -- we're aggregating pixel counts into
    a fixed 256 bins regardless of input resolution.

    Args:
        frame: RGB image array, shape (H, W, 3) or (H, W, 4), dtype uint8.

    Returns:
        A length-256 float64 array of normalized bin counts (0.0-1.0),
        where each value is that bin's share of total pixels.

    Raises:
        ValueError: if frame is not a 3-dimensional RGB(A) array.
    """
    if frame.ndim != 3 or frame.shape[2] < 3:
        raise ValueError("Expected an RGB frame with shape (H, W, 3) or (H, W, 4)")

    downsampled = _downsample(frame)

    weighted = (
        _LUMA_WEIGHTS[0] * downsampled[..., 0].astype(np.float64)
        + _LUMA_WEIGHTS[1] * downsampled[..., 1].astype(np.float64)
        + _LUMA_WEIGHTS[2] * downsampled[..., 2].astype(np.float64)
    )
    # Round rather than truncate: floating-point summation of the luma
    # weights doesn't always land on an exact integer (e.g. 0.299 + 0.587
    # + 0.114 can be a hair under 1.0), so plain truncation via astype()
    # would silently shift values down a bin near round numbers like 128.
    luminance = np.clip(np.round(weighted), 0, 255).astype(np.uint8)

    total_pixels = luminance.size
    if total_pixels == 0:
        return np.zeros(HISTOGRAM_BINS, dtype=np.float64)

    histogram, _ = np.histogram(luminance, bins=HISTOGRAM_BINS, range=(0, 255))

    return histogram.astype(np.float64) / total_pixels


def _downsample(frame: np.ndarray) -> np.ndarray:
    """Downsample a frame so its largest dimension is at most
    DOWNSAMPLE_MAX_DIMENSION, using simple strided sampling.

    Strided sampling (rather than interpolation) is intentional: for a
    histogram, only the distribution of pixel values matters, not a
    smooth resample, so nearest-neighbor-via-stride is both correct and
    fast.
    """
    height, width = frame.shape[:2]
    largest_dimension = max(height, width)

    if largest_dimension <= DOWNSAMPLE_MAX_DIMENSION:
        return frame

    stride = largest_dimension // DOWNSAMPLE_MAX_DIMENSION
    return frame[::stride, ::stride]

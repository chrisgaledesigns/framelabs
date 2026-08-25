"""Tests for compute_luminance_histogram -- pure image logic, no mocking needed."""

import numpy as np
import pytest

from framelabs.image_processing.histogram import (
    HISTOGRAM_BINS,
    compute_luminance_histogram,
)


def _solid_frame(height: int, width: int, rgb: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[..., 0] = rgb[0]
    frame[..., 1] = rgb[1]
    frame[..., 2] = rgb[2]
    return frame


def test_all_black_frame_spikes_at_bin_zero():
    frame = _solid_frame(10, 10, (0, 0, 0))
    histogram = compute_luminance_histogram(frame)
    assert histogram[0] == pytest.approx(1.0)
    assert histogram.sum() == pytest.approx(1.0)


def test_all_white_frame_spikes_at_top_bin():
    frame = _solid_frame(10, 10, (255, 255, 255))
    histogram = compute_luminance_histogram(frame)
    assert histogram[-1] == pytest.approx(1.0)


def test_uniform_gray_frame_spikes_at_expected_bin():
    frame = _solid_frame(10, 10, (128, 128, 128))
    histogram = compute_luminance_histogram(frame)
    assert histogram[128] == pytest.approx(1.0)


def test_histogram_has_256_bins():
    frame = _solid_frame(10, 10, (50, 50, 50))
    histogram = compute_luminance_histogram(frame)
    assert len(histogram) == HISTOGRAM_BINS


def test_histogram_is_normalized():
    frame = np.random.default_rng(seed=0).integers(
        0, 256, size=(20, 30, 3), dtype=np.uint8
    )
    histogram = compute_luminance_histogram(frame)
    assert histogram.sum() == pytest.approx(1.0)


def test_non_rgb_frame_raises():
    frame = np.zeros((10, 10), dtype=np.uint8)
    with pytest.raises(ValueError):
        compute_luminance_histogram(frame)


def test_large_frame_is_downsampled_but_still_returns_256_bins():
    frame = _solid_frame(4000, 6000, (200, 200, 200))
    histogram = compute_luminance_histogram(frame)
    assert len(histogram) == HISTOGRAM_BINS
    assert histogram.argmax() == 200


def test_rgba_frame_ignores_alpha_channel():
    frame = np.zeros((10, 10, 4), dtype=np.uint8)
    frame[..., 0] = 100
    frame[..., 1] = 100
    frame[..., 2] = 100
    frame[..., 3] = 0
    histogram = compute_luminance_histogram(frame)
    assert histogram[100] == pytest.approx(1.0)

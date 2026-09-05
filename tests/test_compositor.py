"""Tests for compositor.py -- pure layer-blending logic, no mocking needed."""

import numpy as np
import pytest

from framelabs.image_processing.compositor import (
    BLEND_MODES,
    CompositorError,
    composite_frame,
)


def _solid_frame(height: int, width: int, rgb: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[..., 0] = rgb[0]
    frame[..., 1] = rgb[1]
    frame[..., 2] = rgb[2]
    return frame


# ---------------------------------------------------------------------------
# No layers / pass-through
# ---------------------------------------------------------------------------


def test_no_layers_returns_base_frame_unchanged():
    base = _solid_frame(10, 10, (100, 150, 200))
    result = composite_frame(base, [])
    assert np.array_equal(result, base)


# ---------------------------------------------------------------------------
# Normal mode
# ---------------------------------------------------------------------------


def test_normal_mode_full_opacity_replaces_base_entirely():
    base = _solid_frame(10, 10, (0, 0, 0))
    top = _solid_frame(10, 10, (200, 100, 50))
    result = composite_frame(base, [(top, 1.0, "normal")])
    assert np.array_equal(result, top)


def test_normal_mode_zero_opacity_leaves_base_unchanged():
    base = _solid_frame(10, 10, (10, 20, 30))
    top = _solid_frame(10, 10, (255, 255, 255))
    result = composite_frame(base, [(top, 0.0, "normal")])
    assert np.array_equal(result, base)


def test_normal_mode_half_opacity_is_midpoint():
    base = _solid_frame(10, 10, (0, 0, 0))
    top = _solid_frame(10, 10, (200, 200, 200))
    result = composite_frame(base, [(top, 0.5, "normal")])
    assert result[0, 0, 0] == pytest.approx(100, abs=1)


# ---------------------------------------------------------------------------
# Multiply / screen / overlay / add formulas
# ---------------------------------------------------------------------------


def test_multiply_with_white_top_leaves_base_unchanged():
    base = _solid_frame(10, 10, (80, 120, 40))
    top = _solid_frame(10, 10, (255, 255, 255))
    result = composite_frame(base, [(top, 1.0, "multiply")])
    assert np.array_equal(result, base)


def test_multiply_with_black_top_produces_black():
    base = _solid_frame(10, 10, (200, 200, 200))
    top = _solid_frame(10, 10, (0, 0, 0))
    result = composite_frame(base, [(top, 1.0, "multiply")])
    assert np.array_equal(result, _solid_frame(10, 10, (0, 0, 0)))


def test_screen_with_black_top_leaves_base_unchanged():
    base = _solid_frame(10, 10, (80, 120, 40))
    top = _solid_frame(10, 10, (0, 0, 0))
    result = composite_frame(base, [(top, 1.0, "screen")])
    assert np.array_equal(result, base)


def test_screen_with_white_top_produces_white():
    base = _solid_frame(10, 10, (50, 60, 70))
    top = _solid_frame(10, 10, (255, 255, 255))
    result = composite_frame(base, [(top, 1.0, "screen")])
    assert np.array_equal(result, _solid_frame(10, 10, (255, 255, 255)))


def test_overlay_with_mid_gray_base_leaves_top_unchanged():
    # At base == 0.5 exactly, overlay's multiply branch (base <= 0.5)
    # reduces to top: 2 * 0.5 * top == top.
    base = _solid_frame(10, 10, (128, 128, 128))
    top = _solid_frame(10, 10, (90, 180, 30))
    result = composite_frame(base, [(top, 1.0, "overlay")])
    assert np.allclose(result.astype(int), top.astype(int), atol=1)


def test_add_mode_sums_and_clips_at_255():
    base = _solid_frame(10, 10, (200, 10, 0))
    top = _solid_frame(10, 10, (100, 10, 0))
    result = composite_frame(base, [(top, 1.0, "add")])
    assert result[0, 0, 0] == 255  # 200 + 100 clipped
    assert result[0, 0, 1] == 20  # 10 + 10, no clip needed


# ---------------------------------------------------------------------------
# Layer stacking order
# ---------------------------------------------------------------------------


def test_layers_apply_bottom_to_top_in_list_order():
    base = _solid_frame(10, 10, (0, 0, 0))
    red = _solid_frame(10, 10, (255, 0, 0))
    blue = _solid_frame(10, 10, (0, 0, 255))
    # Blue applied last (normal, full opacity) should win.
    result = composite_frame(base, [(red, 1.0, "normal"), (blue, 1.0, "normal")])
    assert np.array_equal(result, blue)


def test_multiple_layers_each_contribute():
    base = _solid_frame(10, 10, (0, 0, 0))
    half_white = _solid_frame(10, 10, (255, 255, 255))
    result = composite_frame(
        base,
        [
            (half_white, 0.5, "normal"),
            (half_white, 0.5, "normal"),
        ],
    )
    # First layer: 0 -> 127.5. Second layer (0.5 lerp of 127.5 and 255): ~191
    assert result[0, 0, 0] == pytest.approx(191, abs=2)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_unknown_blend_mode_raises_compositor_error():
    base = _solid_frame(10, 10, (0, 0, 0))
    top = _solid_frame(10, 10, (255, 255, 255))
    with pytest.raises(CompositorError):
        composite_frame(base, [(top, 1.0, "not-a-real-mode")])


def test_mismatched_layer_shape_raises_compositor_error():
    base = _solid_frame(10, 10, (0, 0, 0))
    wrong_shape_top = _solid_frame(5, 5, (255, 255, 255))
    with pytest.raises(CompositorError):
        composite_frame(base, [(wrong_shape_top, 1.0, "normal")])


def test_all_declared_blend_modes_are_accepted_without_error():
    base = _solid_frame(4, 4, (100, 100, 100))
    top = _solid_frame(4, 4, (50, 50, 50))
    for mode in BLEND_MODES:
        # Should not raise for any mode BLEND_MODES actually declares.
        composite_frame(base, [(top, 1.0, mode)])


# ---------------------------------------------------------------------------
# Return shape/dtype contract
# ---------------------------------------------------------------------------


def test_result_has_same_shape_and_dtype_as_base():
    base = _solid_frame(12, 8, (10, 20, 30))
    top = _solid_frame(12, 8, (200, 150, 100))
    result = composite_frame(base, [(top, 0.7, "screen")])
    assert result.shape == base.shape
    assert result.dtype == np.uint8


def test_result_values_never_exceed_uint8_range():
    base = _solid_frame(10, 10, (255, 255, 255))
    top = _solid_frame(10, 10, (255, 255, 255))
    result = composite_frame(base, [(top, 1.0, "add")])
    assert result.max() <= 255
    assert result.min() >= 0

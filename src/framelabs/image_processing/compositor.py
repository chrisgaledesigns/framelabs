"""Layer compositing for the Composite workspace.

Pure image-processing logic: takes a base frame and an ordered stack of
CompositeLayer entries and returns the blended result. No Qt, Project, or
filesystem-path-resolution dependencies here -- same "safe to unit test
directly, safe to call from any thread" split as histogram.py. MainWindow
resolves each layer's relative `source` path against project_path and
loads the pixels before calling in here; this module only ever sees
already-loaded arrays.
"""

from __future__ import annotations

import numpy as np

# Every blend mode the Composite workspace's mode dropdown offers, in the
# order they're listed there. Kept as a tuple (not a set) so composite_
# workspace.py can build its QComboBox straight from this instead of the
# two lists risking drifting apart.
BLEND_MODES = ("normal", "multiply", "screen", "overlay", "add")


class CompositorError(Exception):
    """Raised for an unknown blend mode or a shape mismatch between a
    layer and the base frame."""


def _to_float(image: np.ndarray) -> np.ndarray:
    """Normalize a uint8 RGB(A) array to float64 in [0, 1] for blending
    math. Blend formulas below (screen, overlay in particular) are
    defined in normalized terms; doing the arithmetic in uint8 would
    silently overflow/truncate instead of clipping correctly.
    """
    return image.astype(np.float64) / 255.0


def _blend(base: np.ndarray, top: np.ndarray, mode: str) -> np.ndarray:
    """Apply one blend mode's formula. Both arrays are float64 RGB in
    [0, 1], already the same shape. Returns the blended RGB, unclamped --
    clamping happens once at the end of composite_frame() rather than
    after every layer, so a later layer can still pull an over-bright
    intermediate value back down.
    """
    if mode == "normal":
        return top
    if mode == "multiply":
        return base * top
    if mode == "screen":
        return 1.0 - (1.0 - base) * (1.0 - top)
    if mode == "overlay":
        # Standard overlay: multiply where base is dark, screen where
        # base is light -- the 0.5 split point is what makes it read as
        # "punchier contrast" rather than a flat multiply or screen.
        return np.where(
            base <= 0.5,
            2.0 * base * top,
            1.0 - 2.0 * (1.0 - base) * (1.0 - top),
        )
    if mode == "add":
        return base + top
    raise CompositorError(f"Unknown blend mode {mode!r}; expected one of {BLEND_MODES}")


def composite_frame(
    base_frame: np.ndarray,
    layers: list[tuple[np.ndarray, float, str]],
) -> np.ndarray:
    """Composite `layers` over `base_frame`, bottom-to-top.

    Args:
        base_frame: RGB image array, shape (H, W, 3), dtype uint8. The
            captured frame the Composite workspace is previewing.
        layers: Ordered (image, opacity, blend_mode) tuples -- already
            filtered down to only the layers that are visible, in the
            same bottom-to-top order as Project.composite_layers. Each
            layer image must already be the same (H, W, 3) shape as
            base_frame; resizing/cropping to fit is the caller's job
            (main_window.py), since this module has no opinion on
            resampling quality.

        opacity is 0.0-1.0. blend_mode is one of BLEND_MODES.

    Returns:
        The composited RGB frame, shape (H, W, 3), dtype uint8.

    Raises:
        CompositorError: If a layer's shape doesn't match base_frame, or
            an unknown blend_mode is given.
    """
    result = _to_float(base_frame)

    for layer_image, opacity, blend_mode in layers:
        if layer_image.shape != base_frame.shape:
            raise CompositorError(
                f"Layer shape {layer_image.shape} does not match "
                f"base frame shape {base_frame.shape}"
            )
        top = _to_float(layer_image)
        blended = _blend(result, top, blend_mode)
        # Opacity is a straight lerp between the pre-blend and post-blend
        # result, applied after the mode's own formula -- this is what
        # lets "50% Multiply" mean "half as much darkening", matching
        # every NLE/compositor's convention, rather than 50% of the
        # layer's own alpha.
        result = result * (1.0 - opacity) + blended * opacity

    return np.clip(result * 255.0, 0, 255).astype(np.uint8)

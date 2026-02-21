"""MA-XRF map correction pipeline and processing logic."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import tifffile as tiff
from scipy.ndimage import gaussian_filter, shift as nd_shift

from sciim_toolkit.features.maxrf_corrections.image_io import (
    make_mask,
    normalize_feature,
    read_image,
    resize_to,
    robust_minmax,
    to_float,
)


@dataclass
class CorrectionParams:
    """Parameters for a single correction layer."""

    enabled: bool = True
    strength: float = 0.0
    threshold: float = 0.0
    softness: float = 0.0
    blur_sigma: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    invert: bool = False


def apply_one_correction(
    base: np.ndarray,
    corr: np.ndarray | None,
    params: CorrectionParams,
    base_range: float,
) -> np.ndarray:
    """
    Apply a single correction layer to the base map.

    Algorithm:
      1. Normalize correction image to [0, 1] (feature)
      2. Optionally invert feature
      3. Apply Gaussian blur
      4. Create mask from threshold (optionally soft-ramped)
      5. Apply subpixel shift
      6. Compute delta = strength * base_range * feature * mask
      7. Return base + delta

    Args:
        base: Base (elemental) map
        corr: Correction/feature image (or None if disabled)
        params: Correction parameters
        base_range: Range of the base map for strength scaling

    Returns:
        Base + correction delta
    """
    if corr is None or (not params.enabled) or abs(params.strength) < 1e-8:
        return base

    # Normalize correction to [0, 1]
    feat = normalize_feature(corr, 1.0, 99.0)
    if params.invert:
        feat = 1.0 - feat

    # Optional Gaussian blur
    if params.blur_sigma > 0:
        feat = gaussian_filter(feat, sigma=params.blur_sigma)

    # Create mask: either all-ones or threshold-based with optional softness
    if params.threshold > 0:
        mask = make_mask(feat, thresh=params.threshold, softness=params.softness)
    else:
        mask = np.ones_like(feat, dtype=np.float32)

    # Optional subpixel shift (note: scipy uses (dy, dx) order)
    if params.dx != 0 or params.dy != 0:
        feat = nd_shift(feat, shift=(params.dy, params.dx), order=1, mode="nearest")
        mask = nd_shift(mask, shift=(params.dy, params.dx), order=1, mode="nearest")

    # Compute delta and add to base
    delta = (params.strength * base_range) * feat * mask
    out = base + delta

    return out


def compute_corrected(
    base: np.ndarray,
    corr_a: np.ndarray | None,
    params_a: CorrectionParams,
    corr_b: np.ndarray | None,
    params_b: CorrectionParams,
    corr_c: np.ndarray | None = None,
    params_c: CorrectionParams | None = None,
) -> np.ndarray:
    """
    Compute the fully corrected map by applying all correction layers sequentially.

    Args:
        base: Base elemental map
        corr_a: First correction image
        params_a: Parameters for correction A
        corr_b: Second correction image
        params_b: Parameters for correction B
        corr_c: Optional third correction image
        params_c: Optional parameters for correction C

    Returns:
        Fully corrected map
    """
    lo, hi = robust_minmax(base, 1.0, 99.0)
    base_range = max(1e-6, hi - lo)

    out = base.copy()
    out = apply_one_correction(out, corr_a, params_a, base_range)
    out = apply_one_correction(out, corr_b, params_b, base_range)

    if corr_c is not None and params_c is not None:
        out = apply_one_correction(out, corr_c, params_c, base_range)

    return out

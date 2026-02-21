"""Image I/O utilities for MA-XRF map processing."""
from __future__ import annotations

from pathlib import Path

import imageio.v3 as iio
import numpy as np
import tifffile as tiff


def robust_minmax(
    x: np.ndarray, p_lo: float = 1.0, p_hi: float = 99.0
) -> tuple[float, float]:
    """Compute robust min/max using percentiles (robust to outliers)."""
    x = x[np.isfinite(x)]
    if x.size == 0:
        return 0.0, 1.0
    lo = np.percentile(x, p_lo)
    hi = np.percentile(x, p_hi)
    if hi <= lo:
        hi = lo + 1e-6
    return float(lo), float(hi)


def to_float(img: np.ndarray) -> np.ndarray:
    """Convert image to float32, preserving NaNs if already floating-point."""
    if np.issubdtype(img.dtype, np.floating):
        return img.astype(np.float32, copy=False)
    return img.astype(np.float32)


def read_image(path: str) -> tuple[np.ndarray, dict]:
    """
    Read TIFF, PNG, JPG, or other formats.
    
    Returns image array as [height, width] (row-major, standard NumPy format).
    """
    p = Path(path)
    meta = {"path": str(p), "name": p.name}

    if p.suffix.lower() in {".tif", ".tiff"}:
        with tiff.TiffFile(p) as tf:
            arr = tf.asarray()
            # Squeeze extra dimensions if present
            if arr.ndim > 2:
                arr = np.squeeze(arr)
            meta["dtype"] = str(arr.dtype)
            meta["format"] = "tiff"
            return arr, meta
    
    elif p.suffix.lower() in {".png"}:
        arr = iio.imread(p)
        # Convert RGB/RGBA to grayscale
        if arr.ndim > 2:
            arr = np.mean(arr[..., :3], axis=-1) if arr.shape[2] >= 3 else arr[..., 0]
        meta["dtype"] = str(arr.dtype)
        meta["format"] = "png"
        return arr, meta
    
    elif p.suffix.lower() in {".jpg", ".jpeg"}:
        arr = iio.imread(p)
        # Convert RGB to grayscale
        if arr.ndim > 2:
            arr = np.mean(arr, axis=-1)
        meta["dtype"] = str(arr.dtype)
        meta["format"] = "jpeg"
        return arr, meta
    
    else:
        # Generic fallback for other formats
        arr = iio.imread(p)
        if arr.ndim > 2:
            arr = np.mean(arr[..., :3], axis=-1) if arr.shape[2] >= 3 else arr[..., 0]
        meta["dtype"] = str(arr.dtype)
        meta["format"] = "other"
        return arr, meta


def resize_to(img: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Resize image to target shape using bilinear interpolation."""
    from skimage.transform import resize
    
    if img.shape == shape:
        return img
    return resize(
        img, shape, order=1, preserve_range=True, anti_aliasing=True
    ).astype(np.float32)


def normalize_feature(
    img: np.ndarray, p_lo: float = 1.0, p_hi: float = 99.0
) -> np.ndarray:
    """Normalize image to [0, 1] using robust percentile-based scaling."""
    img_f = to_float(img)
    lo, hi = robust_minmax(img_f, p_lo, p_hi)
    feat = (img_f - lo) / (hi - lo)
    return np.clip(feat, 0.0, 1.0)


def make_mask(
    feature01: np.ndarray, thresh: float, softness: float = 0.0
) -> np.ndarray:
    """Create a binary or soft mask from a normalized feature [0..1]."""
    if softness <= 0:
        return (feature01 >= thresh).astype(np.float32)
    
    lo = max(0.0, thresh - softness)
    hi = min(1.0, thresh)
    m = (feature01 - lo) / max(1e-6, (hi - lo))
    return np.clip(m, 0.0, 1.0).astype(np.float32)

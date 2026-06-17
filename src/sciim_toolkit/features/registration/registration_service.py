from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class SolveResult:
    model: str
    matrix: np.ndarray
    rms_error: float


def solve_transform(
    source_points: list[tuple[float, float]],
    target_points: list[tuple[float, float]],
    model: str,
) -> SolveResult:
    if len(source_points) != len(target_points):
        raise ValueError("Source and target point counts must match")

    src = np.array(source_points, dtype=np.float32)
    dst = np.array(target_points, dtype=np.float32)

    if model == "affine":
        if len(src) < 3:
            raise ValueError("Affine transform needs at least 3 point pairs")
        matrix = cv2.getAffineTransform(src[:3], dst[:3]) if len(src) == 3 else cv2.estimateAffine2D(src, dst)[0]
        if matrix is None:
            raise ValueError("Could not solve affine transform")
        projected = cv2.transform(src.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    elif model == "homography":
        if len(src) < 4:
            raise ValueError("Homography needs at least 4 point pairs")
        matrix, _mask = cv2.findHomography(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
        if matrix is None:
            raise ValueError("Could not solve homography")
        projected = cv2.perspectiveTransform(src.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    else:
        raise ValueError(f"Unsupported model: {model}")

    residuals = np.linalg.norm(projected - dst, axis=1)
    rms_error = float(np.sqrt(np.mean(np.square(residuals)))) if len(residuals) else 0.0

    return SolveResult(model=model, matrix=matrix, rms_error=rms_error)


def warp_to_target(
    source_image: np.ndarray,
    matrix: np.ndarray,
    target_shape: tuple[int, int],
    model: str,
) -> np.ndarray:
    height, width = target_shape
    if model == "affine":
        return cv2.warpAffine(source_image, matrix, (width, height), flags=cv2.INTER_LINEAR)
    if model == "homography":
        return cv2.warpPerspective(source_image, matrix, (width, height), flags=cv2.INTER_LINEAR)
    raise ValueError(f"Unsupported model: {model}")


def make_overlay(
    target_rgb: np.ndarray,
    warped_source_gray: np.ndarray,
    alpha: float,
) -> np.ndarray:
    clamped_alpha = max(0.0, min(float(alpha), 1.0))
    if warped_source_gray.ndim == 2:
        source_rgb = np.stack([warped_source_gray] * 3, axis=-1)
    else:
        source_rgb = warped_source_gray

    target_float = target_rgb.astype(np.float32)
    source_float = source_rgb.astype(np.float32)
    out = (1.0 - clamped_alpha) * target_float + clamped_alpha * source_float
    return np.clip(out, 0, 255).astype(np.uint8)

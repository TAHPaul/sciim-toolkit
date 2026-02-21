from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass
class TilePlan:
    modality: str
    columns: int
    rows: int
    tile_count: int
    tile_width_cm: float
    tile_height_cm: float
    overlap_value: float
    overlap_unit: str


@dataclass
class TilePlacement:
    index: int
    row: int
    col: int
    x_cm: float
    y_cm: float
    width_cm: float
    height_cm: float


def compute_axis_tile_count(total_cm: float, tile_cm: float, overlap_percent: float) -> int:
    return compute_axis_tile_count_with_unit(total_cm, tile_cm, overlap_percent, "percent")


def compute_axis_tile_count_with_unit(
    total_cm: float,
    tile_cm: float,
    overlap_value: float,
    overlap_unit: str,
) -> int:
    if total_cm <= 0 or tile_cm <= 0:
        return 0

    step = compute_step(tile_cm, overlap_value, overlap_unit)
    if step <= 1e-9:
        return 1

    if total_cm <= tile_cm:
        return 1

    return int(ceil((total_cm - tile_cm) / step) + 1)


def compute_step(tile_cm: float, overlap_value: float, overlap_unit: str) -> float:
    if overlap_unit == "cm":
        return max(1e-6, tile_cm - max(0.0, overlap_value))
    overlap = max(0.0, min(overlap_value, 95.0)) / 100.0
    return max(1e-6, tile_cm * (1.0 - overlap))


def compute_axis_positions(
    total_cm: float,
    tile_cm: float,
    overlap_value: float,
    overlap_unit: str,
) -> list[float]:
    if total_cm <= 0 or tile_cm <= 0:
        return []
    if total_cm <= tile_cm:
        return [0.0]

    step = compute_step(tile_cm, overlap_value, overlap_unit)
    if step <= 1e-9:
        return [0.0]

    positions = [0.0]
    while True:
        nxt = positions[-1] + step
        if nxt + tile_cm >= total_cm:
            if nxt - positions[-1] > 1e-6:
                positions.append(nxt)
            break
        positions.append(nxt)
        if len(positions) > 100000:
            break

    return positions


def generate_tile_placements(
    width_cm: float,
    height_cm: float,
    tile_width_cm: float,
    tile_height_cm: float,
    overlap_value: float,
    overlap_unit: str,
) -> list[TilePlacement]:
    if width_cm <= 0 or height_cm <= 0:
        return []

    xs = compute_axis_positions(width_cm, tile_width_cm, overlap_value, overlap_unit)
    ys = compute_axis_positions(height_cm, tile_height_cm, overlap_value, overlap_unit)
    if not xs or not ys:
        return []

    placements: list[TilePlacement] = []
    tile_index = 1
    for row_idx, y_cm in enumerate(ys, start=1):
        for col_idx, x_cm in enumerate(xs, start=1):
            w_cm = min(tile_width_cm, max(0.0, width_cm - x_cm))
            h_cm = min(tile_height_cm, max(0.0, height_cm - y_cm))
            placements.append(
                TilePlacement(
                    index=tile_index,
                    row=row_idx,
                    col=col_idx,
                    x_cm=x_cm,
                    y_cm=y_cm,
                    width_cm=w_cm,
                    height_cm=h_cm,
                )
            )
            tile_index += 1

    return placements


def compute_tile_plan(
    modality: str,
    width_cm: float,
    height_cm: float,
    tile_width_cm: float,
    tile_height_cm: float,
    overlap_value: float,
    overlap_unit: str,
) -> TilePlan:
    cols = compute_axis_tile_count_with_unit(width_cm, tile_width_cm, overlap_value, overlap_unit)
    rows = compute_axis_tile_count_with_unit(height_cm, tile_height_cm, overlap_value, overlap_unit)
    return TilePlan(
        modality=modality,
        columns=cols,
        rows=rows,
        tile_count=cols * rows,
        tile_width_cm=tile_width_cm,
        tile_height_cm=tile_height_cm,
        overlap_value=overlap_value,
        overlap_unit=overlap_unit,
    )


SCANNER_CONFIGS = [84.0, 120.0, 150.0]
EASEL_MIN = 5.0
EASEL_MAX = 150.0


def propose_maxrf_plan(painting_h: float, tile_h: float) -> dict[str, str]:
    configs = {
        "84": (84.0, 84.0 + tile_h),
        "120": (120.0, 120.0 + tile_h),
        "150": (150.0, 150.0 + tile_h),
    }

    def full_reach(c_bottom: float, c_top: float) -> tuple[float, float]:
        lowest_paint_bottom = EASEL_MAX
        highest_paint_top = EASEL_MIN + painting_h
        return lowest_paint_bottom, highest_paint_top

    def can_cover_without_flip(c_bottom: float, c_top: float) -> bool:
        low, high = full_reach(c_bottom, c_top)
        return (low >= c_bottom) and (high <= c_top)

    def can_cover_with_flip(c_bottom: float, c_top: float) -> bool:
        window_reach = c_top - c_bottom + (EASEL_MAX - EASEL_MIN)
        return painting_h <= 2 * window_reach

    def uncovered_in_upright(c_top: float) -> float:
        top_lowest = EASEL_MIN + painting_h
        diff = top_lowest - c_top
        return diff if diff > 0 else 0.0

    cb, ct = configs["120"]
    if can_cover_without_flip(cb, ct):
        return {
            "summary": "Use standard 120 cm configuration; adjust easel only.",
            "details": "Full painting fits within 120–176.5 cm scan window via easel travel.",
        }
    if can_cover_with_flip(cb, ct):
        missing = uncovered_in_upright(ct)
        return {
            "summary": "Use standard 120 cm configuration; flip painting once to reach upper section.",
            "details": f"Top {missing:.1f} cm exceed 176.5 cm upright range but are reachable when flipped.",
        }

    for key in ("84", "150"):
        cb, ct = configs[key]
        if can_cover_without_flip(cb, ct):
            return {
                "summary": f"Use single {key} cm configuration; adjust easel only.",
                "details": f"Painting fits within {cb:.1f}–{ct:.1f} cm scan window.",
            }
        if can_cover_with_flip(cb, ct):
            missing = uncovered_in_upright(ct)
            return {
                "summary": f"Use {key} cm configuration; flip painting once to reach upper section.",
                "details": f"Top {missing:.1f} cm exceed {ct:.1f} cm upright range but reachable when flipped.",
            }

    cb1, ct1 = configs["120"]
    cb2, ct2 = configs["150"]
    if can_cover_with_flip(cb1, ct2):
        return {
            "summary": "Use 120 cm and 150 cm configurations; adjust easel between scans.",
            "details": "Standard covers most; 150 cm config reaches remaining top region.",
        }

    return {
        "summary": "Painting exceeds combined scanner range (84–206.5 cm).",
        "details": "Even with flipping and all configs, some areas remain unreachable; consider sectional mounting.",
    }

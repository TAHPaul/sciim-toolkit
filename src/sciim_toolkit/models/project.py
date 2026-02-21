from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ArtworkMetadata:
    title: str = ""
    artist: str = ""
    hki: str = ""
    inventory_id: str = ""
    width_cm: float = 0.0
    height_cm: float = 0.0
    notes: str = ""


@dataclass
class ModalityConfig:
    enabled: bool = False
    tile_width_cm: float = 20.0
    tile_height_cm: float = 20.0
    overlap_value: float = 10.0
    overlap_unit: str = "percent"


@dataclass
class ImagingPlannerState:
    painting_image_path: str = ""
    modalities: dict[str, ModalityConfig] = field(
        default_factory=lambda: {
            "IRR": ModalityConfig(
                enabled=False,
                tile_width_cm=50.0,
                tile_height_cm=50.0,
                overlap_value=25.0,
                overlap_unit="percent",
            ),
            "X-radiography": ModalityConfig(
                enabled=False,
                tile_width_cm=34.4,
                tile_height_cm=43.0,
                overlap_value=40.0,
                overlap_unit="percent",
            ),
            "MA-XRF": ModalityConfig(
                enabled=False,
                tile_width_cm=76.0,
                tile_height_cm=57.5,
                overlap_value=8.0,
                overlap_unit="cm",
            ),
        }
    )


@dataclass
class MaxrfMapRecord:
    """Track per-map state in MA-XRF pipeline"""

    map_id: str = ""  # filename stem (unique identifier)
    filename: str = ""  # original filename
    element: str = ""
    line_family: str = ""  # K, L, M
    original_path: str = ""  # path in user's folder before copy
    copied_to_raw: bool = False
    corrections_applied: bool = False
    false_colour_variants: list[str] = field(default_factory=list)  # profile names applied
    overlay_variants: list[str] = field(default_factory=list)  # overlay names created


@dataclass
class MaxrfPipelineState:
    """Track MA-XRF project pipeline state"""

    project_root: str = ""  # path to maxrf workspace folder
    map_registry: dict[str, MaxrfMapRecord] = field(default_factory=dict)
    last_selected_folder: str = ""  # folder last selected in Map Setup tab


@dataclass
class ProjectSession:
    project_name: str = "Untitled SciIm Project"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    project_file: str = ""
    artwork: ArtworkMetadata = field(default_factory=ArtworkMetadata)
    imaging_planner: ImagingPlannerState = field(default_factory=ImagingPlannerState)
    maxrf_pipeline: MaxrfPipelineState = field(default_factory=MaxrfPipelineState)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectSession":
        artwork_data = data.get("artwork", {})
        planner_data = data.get("imaging_planner", {})
        maxrf_data = data.get("maxrf_pipeline", {})

        modalities_data = planner_data.get("modalities", {})
        modalities: dict[str, ModalityConfig] = {}
        for key in ("IRR", "X-radiography", "MA-XRF"):
            raw = modalities_data.get(key, {})
            overlap_value = raw.get("overlap_value")
            overlap_unit = raw.get("overlap_unit")
            if overlap_value is None:
                overlap_value = float(raw.get("overlap_percent", 10.0))
                overlap_unit = "percent"
            modalities[key] = ModalityConfig(
                enabled=bool(raw.get("enabled", False)),
                tile_width_cm=float(raw.get("tile_width_cm", 20.0)),
                tile_height_cm=float(raw.get("tile_height_cm", 20.0)),
                overlap_value=float(overlap_value),
                overlap_unit=str(overlap_unit or "percent"),
            )

        # Reconstruct map_registry from maxrf_data
        map_registry: dict[str, MaxrfMapRecord] = {}
        for map_id, record_data in maxrf_data.get("map_registry", {}).items():
            map_registry[map_id] = MaxrfMapRecord(
                map_id=str(map_id),
                filename=str(record_data.get("filename", "")),
                element=str(record_data.get("element", "")),
                line_family=str(record_data.get("line_family", "")),
                original_path=str(record_data.get("original_path", "")),
                copied_to_raw=bool(record_data.get("copied_to_raw", False)),
                corrections_applied=bool(record_data.get("corrections_applied", False)),
                false_colour_variants=list(record_data.get("false_colour_variants", [])),
                overlay_variants=list(record_data.get("overlay_variants", [])),
            )

        return cls(
            project_name=str(data.get("project_name", "Untitled SciIm Project")),
            created_at=str(data.get("created_at", datetime.now().isoformat(timespec="seconds"))),
            updated_at=str(data.get("updated_at", datetime.now().isoformat(timespec="seconds"))),
            project_file=str(data.get("project_file", "")),
            artwork=ArtworkMetadata(
                title=str(artwork_data.get("title", "")),
                artist=str(artwork_data.get("artist", "")),
                hki=str(artwork_data.get("hki", artwork_data.get("inventory_id", ""))),
                inventory_id=str(artwork_data.get("inventory_id", "")),
                width_cm=float(artwork_data.get("width_cm", 0.0)),
                height_cm=float(artwork_data.get("height_cm", 0.0)),
                notes=str(artwork_data.get("notes", "")),
            ),
            imaging_planner=ImagingPlannerState(
                painting_image_path=str(planner_data.get("painting_image_path", "")),
                modalities=modalities,
            ),
            maxrf_pipeline=MaxrfPipelineState(
                project_root=str(maxrf_data.get("project_root", "")),
                map_registry=map_registry,
                last_selected_folder=str(maxrf_data.get("last_selected_folder", "")),
            ),
        )

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def resolve_relative_path(self, path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute() or not self.project_file:
            return path
        return (Path(self.project_file).parent / path).resolve()

    def relativize_for_project(self, path: Path) -> str:
        if not self.project_file:
            return str(path)
        try:
            return str(path.resolve().relative_to(Path(self.project_file).parent.resolve()))
        except ValueError:
            return str(path)

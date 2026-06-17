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
    collection: str = ""
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
    overlay_stack_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class RegistrationPointPair:
    source_x: float = 0.0
    source_y: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0


@dataclass
class RegistrationTransform:
    model: str = ""
    matrix: list[list[float]] = field(default_factory=list)
    rms_error: float = 0.0
    solved_at: str = ""


@dataclass
class RegistrationMapState:
    map_id: str = ""
    source_map_path: str = ""
    point_pairs: list[RegistrationPointPair] = field(default_factory=list)
    transform: RegistrationTransform = field(default_factory=RegistrationTransform)


@dataclass
class RegistrationState:
    reference_photo_path: str = ""
    active_map_id: str = ""
    shared_point_pairs: list[RegistrationPointPair] = field(default_factory=list)
    shared_transform: RegistrationTransform = field(default_factory=RegistrationTransform)
    map_states: dict[str, RegistrationMapState] = field(default_factory=dict)


@dataclass
class ProjectSession:
    project_name: str = "Untitled SciIm Project"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    project_file: str = ""
    artwork: ArtworkMetadata = field(default_factory=ArtworkMetadata)
    imaging_planner: ImagingPlannerState = field(default_factory=ImagingPlannerState)
    maxrf_pipeline: MaxrfPipelineState = field(default_factory=MaxrfPipelineState)
    registration: RegistrationState = field(default_factory=RegistrationState)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectSession":
        artwork_data = data.get("artwork", {})
        planner_data = data.get("imaging_planner", {})
        maxrf_data = data.get("maxrf_pipeline", {})
        registration_data = data.get("registration", {})

        def _parse_point_pairs(raw_pairs: Any) -> list[RegistrationPointPair]:
            point_pairs: list[RegistrationPointPair] = []
            if not isinstance(raw_pairs, list):
                return point_pairs
            for pair_data in raw_pairs:
                if not isinstance(pair_data, dict):
                    continue
                point_pairs.append(
                    RegistrationPointPair(
                        source_x=float(pair_data.get("source_x", 0.0)),
                        source_y=float(pair_data.get("source_y", 0.0)),
                        target_x=float(pair_data.get("target_x", 0.0)),
                        target_y=float(pair_data.get("target_y", 0.0)),
                    )
                )
            return point_pairs

        def _parse_transform(raw_transform: Any) -> RegistrationTransform:
            transform_data = raw_transform if isinstance(raw_transform, dict) else {}
            raw_matrix = transform_data.get("matrix", [])
            matrix: list[list[float]] = []
            if isinstance(raw_matrix, list):
                for row in raw_matrix:
                    if not isinstance(row, list):
                        continue
                    matrix.append([float(value) for value in row])

            return RegistrationTransform(
                model=str(transform_data.get("model", "")),
                matrix=matrix,
                rms_error=float(transform_data.get("rms_error", 0.0)),
                solved_at=str(transform_data.get("solved_at", "")),
            )

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

        registration_map_states: dict[str, RegistrationMapState] = {}
        for map_id, map_data in registration_data.get("map_states", {}).items():
            point_pairs = _parse_point_pairs(map_data.get("point_pairs", []))
            parsed_transform = _parse_transform(map_data.get("transform", {}))

            registration_map_states[str(map_id)] = RegistrationMapState(
                map_id=str(map_data.get("map_id", map_id)),
                source_map_path=str(map_data.get("source_map_path", "")),
                point_pairs=point_pairs,
                transform=parsed_transform,
            )

        active_map_id = str(registration_data.get("active_map_id", ""))
        shared_point_pairs = _parse_point_pairs(registration_data.get("shared_point_pairs", []))
        shared_transform = _parse_transform(registration_data.get("shared_transform", {}))

        if not shared_point_pairs and active_map_id in registration_map_states:
            shared_point_pairs = [
                RegistrationPointPair(
                    source_x=pair.source_x,
                    source_y=pair.source_y,
                    target_x=pair.target_x,
                    target_y=pair.target_y,
                )
                for pair in registration_map_states[active_map_id].point_pairs
            ]

        if not shared_transform.matrix and active_map_id in registration_map_states:
            legacy_transform = registration_map_states[active_map_id].transform
            shared_transform = RegistrationTransform(
                model=legacy_transform.model,
                matrix=[list(row) for row in legacy_transform.matrix],
                rms_error=legacy_transform.rms_error,
                solved_at=legacy_transform.solved_at,
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
                collection=str(artwork_data.get("collection", "")),
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
                overlay_stack_state=maxrf_data.get("overlay_stack_state", {}) if isinstance(maxrf_data.get("overlay_stack_state", {}), dict) else {},
            ),
            registration=RegistrationState(
                reference_photo_path=str(registration_data.get("reference_photo_path", "")),
                active_map_id=active_map_id,
                shared_point_pairs=shared_point_pairs,
                shared_transform=shared_transform,
                map_states=registration_map_states,
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

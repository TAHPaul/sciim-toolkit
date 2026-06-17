from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

import cv2
import imageio.v3 as iio
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.registration.registration_service import (
    make_overlay,
    solve_transform,
    warp_to_target,
)
from sciim_toolkit.models.project import (
    ProjectSession,
    RegistrationMapState,
    RegistrationPointPair,
    RegistrationTransform,
)


class RegistrationImageView(QtWidgets.QGraphicsView):
    point_clicked = QtCore.Signal(float, float)
    view_changed = QtCore.Signal(object, float, float, float)

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)

        self._title_item = self._scene.addText(title)
        self._title_item.setDefaultTextColor(QtGui.QColor("#ddd"))
        self._pixmap_item: QtWidgets.QGraphicsPixmapItem | None = None

        self._zoom_factor = 1.0
        self._suppress_sync_emit = False

        self.setMinimumSize(300, 220)
        self.setStyleSheet("border: 1px solid #888; background: #111;")
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.NoAnchor)

        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    def scene_bounds(self) -> QtCore.QRectF:
        if self._pixmap_item is None:
            return QtCore.QRectF()
        return self._pixmap_item.sceneBoundingRect()

    def normalized_center(self) -> tuple[float, float]:
        bounds = self.scene_bounds()
        if bounds.isEmpty():
            return 0.5, 0.5

        center_scene = self.mapToScene(self.viewport().rect().center())
        cx = (center_scene.x() - bounds.left()) / max(bounds.width(), 1e-6)
        cy = (center_scene.y() - bounds.top()) / max(bounds.height(), 1e-6)
        return max(0.0, min(cx, 1.0)), max(0.0, min(cy, 1.0))

    def set_zoom_and_center(self, zoom_factor: float, center_norm: tuple[float, float] | None, emit: bool = True) -> None:
        bounds = self.scene_bounds()
        if bounds.isEmpty():
            return

        clamped = max(0.05, min(float(zoom_factor), 20.0))
        self._suppress_sync_emit = True
        try:
            self._zoom_factor = clamped
            self.resetTransform()
            self.scale(self._zoom_factor, self._zoom_factor)

            if center_norm is None:
                self.centerOn(bounds.center())
            else:
                cx = bounds.left() + center_norm[0] * bounds.width()
                cy = bounds.top() + center_norm[1] * bounds.height()
                self.centerOn(QtCore.QPointF(cx, cy))
        finally:
            self._suppress_sync_emit = False

        if emit:
            self._emit_view_changed()

    def set_image(self, image_rgb: np.ndarray) -> None:
        h, w = image_rgb.shape[:2]
        q_image = QtGui.QImage(
            image_rgb.data,
            w,
            h,
            image_rgb.strides[0],
            QtGui.QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QtGui.QPixmap.fromImage(q_image)

        old_zoom = self._zoom_factor
        old_center = self.normalized_center() if self.has_image() else None

        if self._pixmap_item is None:
            self._pixmap_item = self._scene.addPixmap(pixmap)
        else:
            self._pixmap_item.setPixmap(pixmap)

        self._title_item.setVisible(False)
        self._scene.setSceneRect(QtCore.QRectF(0, 0, float(w), float(h)))

        if old_center is None:
            self._fit_initial_view()
        else:
            self.set_zoom_and_center(old_zoom, old_center, emit=False)

    def clear_placeholder(self, title: str) -> None:
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
            self._pixmap_item = None

        self._title_item.setPlainText(title)
        self._title_item.setPos(10, 10)
        self._title_item.setVisible(True)
        self._scene.setSceneRect(QtCore.QRectF(0, 0, max(self.width(), 10), max(self.height(), 10)))
        self.resetTransform()
        self._zoom_factor = 1.0

    def _fit_initial_view(self) -> None:
        self.fit_to_view(emit=False)

    def fit_to_view(self, emit: bool = True) -> None:
        """Fit the full image in view and optionally emit sync update."""
        bounds = self.scene_bounds()
        if bounds.isEmpty():
            return

        view_w = max(self.viewport().width(), 1)
        view_h = max(self.viewport().height(), 1)
        factor_x = view_w / bounds.width()
        factor_y = view_h / bounds.height()
        fit_factor = max(0.05, min(factor_x, factor_y))
        self.set_zoom_and_center(fit_factor, (0.5, 0.5), emit=False)
        if emit:
            self._emit_view_changed()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if not self.has_image():
            super().wheelEvent(event)
            return

        cursor_scene = self.mapToScene(event.position().toPoint())
        step = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        new_zoom = self._zoom_factor * step
        self.set_zoom_and_center(new_zoom, self.normalized_center(), emit=False)
        self.centerOn(cursor_scene)
        self._emit_view_changed()
        event.accept()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if (
            event.key() == QtCore.Qt.Key.Key_F
            and event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier
            and self.has_image()
        ):
            self.fit_to_view(emit=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.has_image():
            scene_pos = self.mapToScene(event.position().toPoint())
            bounds = self.scene_bounds()
            if bounds.contains(scene_pos):
                self.point_clicked.emit(float(scene_pos.x()), float(scene_pos.y()))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self._emit_view_changed()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.has_image() and self._zoom_factor <= 0.1:
            self._fit_initial_view()

    def _on_scroll_changed(self) -> None:
        self._emit_view_changed()

    def _emit_view_changed(self) -> None:
        if self._suppress_sync_emit or not self.has_image():
            return
        cx, cy = self.normalized_center()
        self.view_changed.emit(self, float(self._zoom_factor), float(cx), float(cy))


class RegistrationTab(QtWidgets.QWidget):
    session_changed = QtCore.Signal()
    SUPPORTED_IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._photo_path: Path | None = None
        self._source_path: Path | None = None

        self._photo_rgb: np.ndarray | None = None
        self._source_gray: np.ndarray | None = None
        self._preview_rgb: np.ndarray | None = None
        self._standalone_maps_folder: Path | None = None

        self._current_map_id = ""
        self._current_pairs: list[RegistrationPointPair] = []
        self._pending_source_point: tuple[float, float] | None = None
        self._is_loading_session = False
        self._syncing_views = False
        self._is_updating_pairs_table = False

        self._build_ui()
        self._bind_signals()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        controls = QtWidgets.QGridLayout()

        self.ed_photo_path = QtWidgets.QLineEdit()
        self.ed_photo_path.setReadOnly(True)
        self.btn_load_photo = QtWidgets.QPushButton("Select Photograph…")

        self.combo_source_mode = QtWidgets.QComboBox()
        self.btn_select_maps_folder = QtWidgets.QPushButton("Select Maps Folder…")
        self.ed_maps_folder = QtWidgets.QLineEdit()
        self.ed_maps_folder.setReadOnly(True)

        self.combo_map = QtWidgets.QComboBox()
        self.btn_refresh_maps = QtWidgets.QPushButton("Refresh maps")

        self.slider_alpha = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_alpha.setRange(0, 100)
        self.slider_alpha.setValue(50)
        self.lbl_alpha = QtWidgets.QLabel("Overlay alpha: 0.50")

        controls.addWidget(QtWidgets.QLabel("Ground-truth photograph"), 0, 0)
        controls.addWidget(self.ed_photo_path, 0, 1)
        controls.addWidget(self.btn_load_photo, 0, 2)
        controls.addWidget(QtWidgets.QLabel("Map source"), 1, 0)
        controls.addWidget(self.combo_source_mode, 1, 1)
        controls.addWidget(self.btn_select_maps_folder, 1, 2)
        controls.addWidget(QtWidgets.QLabel("Maps folder"), 2, 0)
        controls.addWidget(self.ed_maps_folder, 2, 1, 1, 2)
        controls.addWidget(QtWidgets.QLabel("MA-XRF map"), 3, 0)
        controls.addWidget(self.combo_map, 3, 1)
        controls.addWidget(self.btn_refresh_maps, 3, 2)
        controls.addWidget(self.lbl_alpha, 4, 0)
        controls.addWidget(self.slider_alpha, 4, 1, 1, 2)

        root.addLayout(controls)

        image_split = QtWidgets.QHBoxLayout()
        self.view_source = RegistrationImageView("Source map (click to add source points)")
        self.view_photo = RegistrationImageView("Photograph (click to pair target point)")
        image_split.addWidget(self.view_source, 1)
        image_split.addWidget(self.view_photo, 1)
        root.addLayout(image_split)

        self.shortcut_fit_source = QtGui.QShortcut(QtGui.QKeySequence("F"), self.view_source)
        self.shortcut_fit_source.setContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.shortcut_fit_source.activated.connect(
            lambda: self.view_source.fit_to_view(emit=True)
        )

        self.shortcut_fit_photo = QtGui.QShortcut(QtGui.QKeySequence("F"), self.view_photo)
        self.shortcut_fit_photo.setContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.shortcut_fit_photo.activated.connect(
            lambda: self.view_photo.fit_to_view(emit=True)
        )

        self.view_overlay = QtWidgets.QLabel("Overlay preview")
        self.view_overlay.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.view_overlay.setMinimumHeight(260)
        self.view_overlay.setStyleSheet("border: 1px solid #888; background: #111; color: #ddd;")
        root.addWidget(self.view_overlay)

        action_row = QtWidgets.QHBoxLayout()
        self.btn_remove_last = QtWidgets.QPushButton("Remove last pair")
        self.btn_delete_selected = QtWidgets.QPushButton("Delete selected pair(s)")
        self.btn_clear = QtWidgets.QPushButton("Clear all pairs")
        self.btn_solve_affine = QtWidgets.QPushButton("Solve Affine")
        self.btn_solve_homography = QtWidgets.QPushButton("Solve Homography")
        self.btn_export_matrix = QtWidgets.QPushButton("Export Matrix…")
        self.btn_export_all = QtWidgets.QPushButton("Export All Registered Maps…")
        action_row.addWidget(self.btn_remove_last)
        action_row.addWidget(self.btn_delete_selected)
        action_row.addWidget(self.btn_clear)
        action_row.addStretch(1)
        action_row.addWidget(self.btn_solve_affine)
        action_row.addWidget(self.btn_solve_homography)
        action_row.addWidget(self.btn_export_matrix)
        action_row.addWidget(self.btn_export_all)
        root.addLayout(action_row)

        self.table_pairs = QtWidgets.QTableWidget(0, 7)
        self.table_pairs.setHorizontalHeaderLabels(["#", "Source X", "Source Y", "Target X", "Target Y", "dx", "dy"])
        self.table_pairs.horizontalHeader().setStretchLastSection(True)
        self.table_pairs.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_pairs.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.table_pairs)

        self.lbl_status = QtWidgets.QLabel("Select a map and photograph, then click source → photo to create control-point pairs.")
        root.addWidget(self.lbl_status)

    def _bind_signals(self) -> None:
        self.btn_load_photo.clicked.connect(self._on_load_photo)
        self.combo_source_mode.currentIndexChanged.connect(self._on_source_mode_changed)
        self.btn_select_maps_folder.clicked.connect(self._on_select_maps_folder)
        self.btn_refresh_maps.clicked.connect(self._refresh_map_combo)
        self.combo_map.currentIndexChanged.connect(self._on_map_changed)
        self.view_source.point_clicked.connect(self._on_source_clicked)
        self.view_photo.point_clicked.connect(self._on_target_clicked)
        self.view_source.view_changed.connect(self._on_view_changed)
        self.view_photo.view_changed.connect(self._on_view_changed)
        self.btn_remove_last.clicked.connect(self._remove_last_pair)
        self.btn_delete_selected.clicked.connect(self._delete_selected_pairs)
        self.btn_clear.clicked.connect(self._clear_pairs)
        self.table_pairs.cellChanged.connect(self._on_pair_cell_changed)
        self.btn_solve_affine.clicked.connect(lambda: self._solve("affine"))
        self.btn_solve_homography.clicked.connect(lambda: self._solve("homography"))
        self.btn_export_matrix.clicked.connect(self._export_matrix)
        self.btn_export_all.clicked.connect(self._export_all_registered_maps)
        self.slider_alpha.valueChanged.connect(self._on_alpha_changed)

    def _active_transform(self) -> RegistrationTransform | None:
        if self._session is None:
            return None

        shared = self._session.registration.shared_transform
        if shared.matrix and shared.model:
            return shared

        if self._current_map_id:
            state = self._session.registration.map_states.get(self._current_map_id)
            if state is not None and state.transform.matrix and state.transform.model:
                return state.transform

        return None

    def _is_project_mode(self) -> bool:
        return self._session is not None and bool(self._session.maxrf_pipeline.project_root)

    def _configure_source_mode_ui(self) -> None:
        self.combo_source_mode.blockSignals(True)
        self.combo_source_mode.clear()

        if self._is_project_mode():
            self.combo_source_mode.addItem("Raw scans", "raw")
            self.combo_source_mode.addItem("Final scans", "final")
            self.btn_select_maps_folder.setEnabled(False)
            self.ed_maps_folder.setText("Project-managed map sources")
        else:
            self.combo_source_mode.addItem("Standalone folder", "standalone")
            self.btn_select_maps_folder.setEnabled(True)
            if self._standalone_maps_folder is not None:
                self.ed_maps_folder.setText(str(self._standalone_maps_folder))
            else:
                self.ed_maps_folder.setText("No folder selected")

        self.combo_source_mode.blockSignals(False)

    def _current_source_mode(self) -> str:
        mode = self.combo_source_mode.currentData()
        return str(mode) if mode else "raw"

    def _on_source_mode_changed(self, _index: int) -> None:
        self._refresh_map_combo()

    def _on_select_maps_folder(self) -> None:
        if self._is_project_mode():
            return

        start_dir = str(self._standalone_maps_folder) if self._standalone_maps_folder else str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select elemental maps folder", start_dir)
        if not folder:
            return

        self._standalone_maps_folder = Path(folder)
        self.ed_maps_folder.setText(str(self._standalone_maps_folder))
        self._refresh_map_combo()

    def _project_raw_maps(self, root: Path) -> list[tuple[str, Path, str]]:
        entries: list[tuple[str, Path, str]] = []
        for map_id, record in sorted(self._session.maxrf_pipeline.map_registry.items()):
            filename = (record.filename or "").strip()
            if not filename:
                continue
            raw_path = root / "raw_data" / filename
            if not raw_path.exists():
                continue
            label = f"{record.element or 'Unknown'} {record.line_family or ''} — {raw_path.name}".strip()
            entries.append((str(map_id), raw_path, label))
        return entries

    def _project_final_maps(self, root: Path) -> list[tuple[str, Path, str]]:
        final_dir = root / "final_maps"
        if not final_dir.exists():
            return []

        entries: list[tuple[str, Path, str]] = []
        for path in sorted(final_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in self.SUPPORTED_IMAGE_EXTS:
                continue
            entries.append((path.stem, path, path.name))
        return entries

    def _standalone_maps(self) -> list[tuple[str, Path, str]]:
        if self._standalone_maps_folder is None or not self._standalone_maps_folder.exists():
            return []

        entries: list[tuple[str, Path, str]] = []
        for path in sorted(self._standalone_maps_folder.iterdir()):
            if not path.is_file() or path.suffix.lower() not in self.SUPPORTED_IMAGE_EXTS:
                continue
            entries.append((path.stem, path, path.name))
        return entries

    def _export_matrix(self) -> None:
        if self._session is None:
            return

        transform = self._active_transform()
        if transform is None:
            QtWidgets.QMessageBox.warning(self, "Export matrix", "No solved transform available yet.")
            return

        default_name = "registration_transform.json"
        if self._current_map_id:
            default_name = f"registration_transform_{self._current_map_id}.json"

        project_root = (
            Path(self._session.maxrf_pipeline.project_root)
            if self._session.maxrf_pipeline.project_root
            else None
        )

        if project_root is not None:
            out_root = project_root / "registered_maps"
            out_root.mkdir(parents=True, exist_ok=True)
            path = out_root / default_name
        else:
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export transformation matrix",
                str(Path.home() / default_name),
                "JSON (*.json)",
            )
            if not chosen:
                return

            path = Path(chosen)
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")

        payload = {
            "model": transform.model,
            "matrix": transform.matrix,
            "rms_error": transform.rms_error,
            "solved_at": transform.solved_at,
            "active_map_id": self._session.registration.active_map_id,
            "reference_photo_path": self._session.registration.reference_photo_path,
            "shared_point_pair_count": len(self._session.registration.shared_point_pairs),
        }

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export matrix", f"Failed to export matrix:\n{exc}")
            return

        self.lbl_status.setText(f"Exported transform matrix to {path}")

    def _export_all_registered_maps(self) -> None:
        if self._session is None:
            return

        transform = self._active_transform()
        if transform is None:
            QtWidgets.QMessageBox.warning(self, "Export maps", "No solved transform available yet.")
            return

        if self._photo_rgb is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Export maps",
                "Load/select the ground-truth photograph first so export target dimensions are known.",
            )
            return

        if self._is_project_mode():
            self._export_project_registered_maps(transform)
        else:
            self._export_standalone_registered_maps(transform)

    def _export_paths(self, transform: RegistrationTransform, source_paths: list[Path], out_root: Path) -> tuple[int, list[str]]:
        out_root.mkdir(parents=True, exist_ok=True)

        matrix = np.array(transform.matrix, dtype=np.float32)
        target_shape = (self._photo_rgb.shape[0], self._photo_rgb.shape[1])

        exported_count = 0
        failures: list[str] = []

        for source_path in source_paths:
            if not source_path.exists():
                failures.append(f"{source_path.name}: source file not found")
                continue
            try:
                src = iio.imread(source_path)
                warped = warp_to_target(src, matrix, target_shape=target_shape, model=transform.model)

                ext = source_path.suffix or ".tif"
                out_name = f"{source_path.stem}_registered{ext}"
                out_path = out_root / out_name
                iio.imwrite(out_path, warped)
                exported_count += 1
            except Exception as exc:
                failures.append(f"{source_path.name}: {exc}")

        return exported_count, failures

    def _export_standalone_registered_maps(self, transform: RegistrationTransform) -> None:
        if self._standalone_maps_folder is None or not self._standalone_maps_folder.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Export maps",
                "Select a standalone maps folder first.",
            )
            return

        source_paths = [
            p for p in sorted(self._standalone_maps_folder.iterdir())
            if p.is_file() and p.suffix.lower() in self.SUPPORTED_IMAGE_EXTS
        ]
        if not source_paths:
            QtWidgets.QMessageBox.warning(self, "Export maps", "Selected folder has no supported image files.")
            return

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select output folder for registered MA-XRF maps",
            str(self._standalone_maps_folder),
        )
        if not output_dir:
            return

        out_root = Path(output_dir)
        exported_count, failures = self._export_paths(transform, source_paths, out_root)
        self._report_export_results("Export maps", exported_count, failures, out_root)

    def _prompt_project_export_targets(self) -> list[str]:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Export Registration Targets")
        layout = QtWidgets.QVBoxLayout(dialog)

        layout.addWidget(QtWidgets.QLabel("Apply transform to:"))

        chk_raw = QtWidgets.QCheckBox("Raw maps")
        chk_corrected = QtWidgets.QCheckBox("Corrected maps")
        chk_false_colour = QtWidgets.QCheckBox("False colour maps")
        chk_overlays = QtWidgets.QCheckBox("Overlays")
        chk_raw.setChecked(True)

        layout.addWidget(chk_raw)
        layout.addWidget(chk_corrected)
        layout.addWidget(chk_false_colour)
        layout.addWidget(chk_overlays)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            return []

        selected: list[str] = []
        if chk_raw.isChecked():
            selected.append("raw")
        if chk_corrected.isChecked():
            selected.append("corrected")
        if chk_false_colour.isChecked():
            selected.append("false_colour")
        if chk_overlays.isChecked():
            selected.append("overlays")
        return selected

    def _project_raw_paths(self, project_root: Path) -> list[Path]:
        paths: list[Path] = []
        for _map_id, record in sorted(self._session.maxrf_pipeline.map_registry.items()):
            filename = (record.filename or "").strip()
            if not filename:
                continue
            raw_path = project_root / "raw_data" / filename
            if raw_path.exists():
                paths.append(raw_path)
        return paths

    def _project_corrected_paths(self, project_root: Path) -> list[Path]:
        paths: list[Path] = []
        corrected_dir = project_root / "corrected_maps"
        for _map_id, record in sorted(self._session.maxrf_pipeline.map_registry.items()):
            if not bool(record.corrections_applied):
                continue
            filename = (record.filename or "").strip()
            if not filename:
                continue
            stem = Path(filename).stem
            ext = Path(filename).suffix
            corrected_path = corrected_dir / f"{stem}_corrected{ext}"
            if corrected_path.exists():
                paths.append(corrected_path)
        return paths

    def _all_files_in_dir(self, folder: Path) -> list[Path]:
        if not folder.exists():
            return []
        return [
            p for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in self.SUPPORTED_IMAGE_EXTS
        ]

    def _export_project_registered_maps(self, transform: RegistrationTransform) -> None:
        project_root = Path(self._session.maxrf_pipeline.project_root)

        selected_targets = self._prompt_project_export_targets()
        if not selected_targets:
            return

        tasks: list[tuple[str, list[Path], Path]] = []

        registered_root = project_root / "registered_maps"

        if "raw" in selected_targets:
            tasks.append((
                "raw",
                self._project_raw_paths(project_root),
                registered_root / "registered_raw_maps",
            ))

        if "corrected" in selected_targets:
            tasks.append((
                "corrected",
                self._project_corrected_paths(project_root),
                registered_root / "registered_corrected_maps",
            ))

        if "false_colour" in selected_targets:
            tasks.append((
                "false_colour",
                self._all_files_in_dir(project_root / "false_coloured_maps"),
                registered_root / "registered_false_colour_maps",
            ))

        if "overlays" in selected_targets:
            tasks.append((
                "overlays",
                self._all_files_in_dir(project_root / "overlays"),
                registered_root / "registered_overlays",
            ))

        total_exported = 0
        all_failures: list[str] = []
        out_dirs: list[Path] = []

        for label, source_paths, out_root in tasks:
            if not source_paths:
                all_failures.append(f"{label}: no source maps found")
                continue
            exported_count, failures = self._export_paths(transform, source_paths, out_root)
            total_exported += exported_count
            all_failures.extend([f"{label} - {msg}" for msg in failures])
            out_dirs.append(out_root)

        if out_dirs:
            summary_root = registered_root
        else:
            summary_root = registered_root
        self._report_export_results("Export maps", total_exported, all_failures, summary_root)

    def _report_export_results(self, title: str, exported_count: int, failures: list[str], out_root: Path) -> None:
        if failures:
            QtWidgets.QMessageBox.warning(
                self,
                f"{title} completed with warnings",
                f"Exported {exported_count} map(s). Failed {len(failures)} map(s).\n\n"
                + "\n".join(failures[:8]),
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                f"{title} complete",
                f"Exported {exported_count} registered map(s) to:\n{out_root}",
            )

        self.lbl_status.setText(f"Exported {exported_count} registered map(s) to {out_root}")

    def _on_view_changed(self, source_view: object, zoom: float, center_x: float, center_y: float) -> None:
        if self._syncing_views:
            return

        target_view = self.view_photo if source_view is self.view_source else self.view_source
        if not isinstance(target_view, RegistrationImageView) or not target_view.has_image():
            return

        self._syncing_views = True
        try:
            target_view.set_zoom_and_center(zoom, (center_x, center_y), emit=False)
        finally:
            self._syncing_views = False

    def set_session(self, session: ProjectSession) -> None:
        self._session = session
        self._is_loading_session = True

        try:
            self._configure_source_mode_ui()
            self._current_pairs = [replace(pair) for pair in session.registration.shared_point_pairs]
            self._pending_source_point = None

            registration_photo = session.registration.reference_photo_path
            fallback_photo = session.imaging_planner.painting_image_path
            photo_path = registration_photo or fallback_photo
            if photo_path:
                self._load_photo(Path(photo_path), emit_change=False)

            self._refresh_map_combo()
        finally:
            self._is_loading_session = False

    def _refresh_map_combo(self) -> None:
        self.combo_map.blockSignals(True)
        self.combo_map.clear()
        self.combo_map.addItem("Select map…", ("", ""))

        if self._session is None:
            self.combo_map.blockSignals(False)
            return

        mode = self._current_source_mode()
        entries: list[tuple[str, Path, str]] = []
        if self._is_project_mode():
            root = Path(self._session.maxrf_pipeline.project_root)
            if mode == "final":
                entries = self._project_final_maps(root)
            else:
                entries = self._project_raw_maps(root)
        else:
            entries = self._standalone_maps()

        for map_id, map_path, label in entries:
            self.combo_map.addItem(label, (map_id, str(map_path)))

        active_map_id = self._session.registration.active_map_id
        if active_map_id:
            for index in range(self.combo_map.count()):
                map_id, _path = self.combo_map.itemData(index)
                if map_id == active_map_id:
                    self.combo_map.setCurrentIndex(index)
                    break

        self.combo_map.blockSignals(False)
        if self.combo_map.currentIndex() <= 0 and self.combo_map.count() > 1:
            self.combo_map.setCurrentIndex(1)

    def _on_map_changed(self) -> None:
        if self._session is None:
            return

        map_id, path_value = self.combo_map.currentData() or ("", "")
        self._current_map_id = str(map_id)
        self._source_path = Path(path_value) if path_value else None

        self._pending_source_point = None
        self._load_source_image(self._source_path)
        self._populate_pairs_table()
        self._redraw_views()

        self._session.registration.active_map_id = self._current_map_id
        if not self._is_loading_session:
            self.session_changed.emit()

    def _on_load_photo(self) -> None:
        chosen, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select ground-truth photograph",
            str(Path.home()),
            "Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp)",
        )
        if not chosen:
            return
        self._load_photo(Path(chosen), emit_change=True)

    def _load_photo(self, path: Path, emit_change: bool) -> None:
        image = self._read_image(path)
        if image is None:
            return

        if image.ndim == 2:
            photo_rgb = np.stack([image] * 3, axis=-1)
        else:
            photo_rgb = image

        self._photo_rgb = photo_rgb
        self._photo_path = path
        self.ed_photo_path.setText(str(path))
        self.lbl_status.setText("Photo loaded. Click map first, then photo to define point pairs.")

        if self._session is not None:
            self._session.registration.reference_photo_path = str(path)
            if emit_change:
                self.session_changed.emit()

        self._redraw_views()

    def _load_source_image(self, path: Path | None) -> None:
        self._source_gray = None
        if path is None:
            self.view_source.clear_placeholder("Source map (click to add source points)")
            return

        image = self._read_image(path)
        if image is None:
            self.view_source.clear_placeholder("Source map (click to add source points)")
            return

        if image.ndim == 3:
            if image.shape[2] >= 3:
                self._source_gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2GRAY)
            else:
                self._source_gray = image[:, :, 0]
        else:
            self._source_gray = image

    def _read_image(self, path: Path) -> np.ndarray | None:
        if not path.exists():
            self.lbl_status.setText(f"Missing file: {path}")
            return None

        try:
            data = iio.imread(path)
        except Exception as exc:
            self.lbl_status.setText(f"Failed reading {path.name}: {exc}")
            return None

        if data.ndim == 3 and data.shape[2] == 4:
            data = data[:, :, :3]

        if data.dtype != np.uint8:
            data = self._normalize_uint8(data)

        return data

    def _normalize_uint8(self, data: np.ndarray) -> np.ndarray:
        finite = np.isfinite(data)
        if not np.any(finite):
            return np.zeros_like(data, dtype=np.uint8)

        min_v = float(np.min(data[finite]))
        max_v = float(np.max(data[finite]))
        if max_v <= min_v:
            return np.zeros_like(data, dtype=np.uint8)

        scaled = (data.astype(np.float32) - min_v) / (max_v - min_v)
        return np.clip(scaled * 255.0, 0, 255).astype(np.uint8)

    def _on_source_clicked(self, x: float, y: float) -> None:
        self._pending_source_point = (x, y)
        self.lbl_status.setText(f"Source point set at ({x:.1f}, {y:.1f}). Now click matching point on photograph.")

    def _on_target_clicked(self, x: float, y: float) -> None:
        if self._pending_source_point is None:
            self.lbl_status.setText("Click source map first, then photograph.")
            return

        source_x, source_y = self._pending_source_point
        self._current_pairs.append(
            RegistrationPointPair(
                source_x=float(source_x),
                source_y=float(source_y),
                target_x=float(x),
                target_y=float(y),
            )
        )
        self._pending_source_point = None

        self._populate_pairs_table()
        self._persist_pairs_only()
        self._redraw_views()

    def _remove_last_pair(self) -> None:
        if not self._current_pairs:
            return
        self._current_pairs.pop()
        self._populate_pairs_table()
        self._persist_pairs_only()
        self._redraw_views()

    def _clear_pairs(self) -> None:
        self._current_pairs = []
        self._pending_source_point = None
        self._populate_pairs_table()
        self._persist_pairs_only()
        self._redraw_views()

    def _delete_selected_pairs(self) -> None:
        selected_rows = sorted({idx.row() for idx in self.table_pairs.selectionModel().selectedRows()}, reverse=True)
        if not selected_rows:
            return

        for row in selected_rows:
            if 0 <= row < len(self._current_pairs):
                self._current_pairs.pop(row)

        self._populate_pairs_table()
        self._persist_pairs_only()
        self._redraw_views()

    def _on_pair_cell_changed(self, row: int, col: int) -> None:
        if self._is_updating_pairs_table:
            return
        if col not in {1, 2, 3, 4}:
            return
        if row < 0 or row >= len(self._current_pairs):
            return

        item = self.table_pairs.item(row, col)
        if item is None:
            return

        try:
            value = float(item.text())
        except ValueError:
            self.lbl_status.setText("Invalid coordinate value. Please enter a numeric value.")
            self._populate_pairs_table()
            return

        pair = self._current_pairs[row]
        if col == 1:
            pair.source_x = value
        elif col == 2:
            pair.source_y = value
        elif col == 3:
            pair.target_x = value
        elif col == 4:
            pair.target_y = value

        self._populate_pairs_table()
        self._persist_pairs_only()
        self._redraw_views()

    def _make_readonly_item(self, value: str) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(value)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        return item

    def _populate_pairs_table(self) -> None:
        self._is_updating_pairs_table = True
        try:
            self.table_pairs.setRowCount(len(self._current_pairs))
            for idx, pair in enumerate(self._current_pairs):
                dx = pair.target_x - pair.source_x
                dy = pair.target_y - pair.source_y

                self.table_pairs.setItem(idx, 0, self._make_readonly_item(str(idx + 1)))
                self.table_pairs.setItem(idx, 1, QtWidgets.QTableWidgetItem(f"{pair.source_x:.3f}"))
                self.table_pairs.setItem(idx, 2, QtWidgets.QTableWidgetItem(f"{pair.source_y:.3f}"))
                self.table_pairs.setItem(idx, 3, QtWidgets.QTableWidgetItem(f"{pair.target_x:.3f}"))
                self.table_pairs.setItem(idx, 4, QtWidgets.QTableWidgetItem(f"{pair.target_y:.3f}"))
                self.table_pairs.setItem(idx, 5, self._make_readonly_item(f"{dx:+.3f}"))
                self.table_pairs.setItem(idx, 6, self._make_readonly_item(f"{dy:+.3f}"))
        finally:
            self._is_updating_pairs_table = False

    def _persist_pairs_only(self) -> None:
        if self._session is None:
            return

        self._session.registration.shared_point_pairs = [replace(pair) for pair in self._current_pairs]

        if self._current_map_id:
            current = self._session.registration.map_states.get(self._current_map_id)
            if current is None:
                current = RegistrationMapState(map_id=self._current_map_id)
            if self._source_path is not None:
                current.source_map_path = str(self._source_path)
            current.point_pairs = [replace(pair) for pair in self._current_pairs]
            self._session.registration.active_map_id = self._current_map_id
            self._session.registration.map_states[self._current_map_id] = current

        self._sync_registration_to_manifest()

        if not self._is_loading_session:
            self.session_changed.emit()

    def _solve(self, model: str) -> None:
        if self._photo_rgb is None or self._source_gray is None:
            self.lbl_status.setText("Load photograph and source map first.")
            return

        src_points = [(pair.source_x, pair.source_y) for pair in self._current_pairs]
        dst_points = [(pair.target_x, pair.target_y) for pair in self._current_pairs]

        try:
            result = solve_transform(src_points, dst_points, model=model)
        except ValueError as exc:
            self.lbl_status.setText(str(exc))
            return

        warped = warp_to_target(
            self._source_gray,
            result.matrix,
            target_shape=(self._photo_rgb.shape[0], self._photo_rgb.shape[1]),
            model=model,
        )
        alpha = self.slider_alpha.value() / 100.0
        self._preview_rgb = make_overlay(self._photo_rgb, warped, alpha=alpha)
        self._render_overlay_image(self._preview_rgb)

        solved_at = datetime.now().isoformat(timespec="seconds")
        self.lbl_status.setText(
            f"Solved {model} transform with RMS error {result.rms_error:.2f} px at {solved_at}."
        )

        if self._session is None:
            return

        shared_transform = RegistrationTransform(
            model=model,
            matrix=result.matrix.tolist(),
            rms_error=result.rms_error,
            solved_at=solved_at,
        )
        self._session.registration.shared_point_pairs = [replace(pair) for pair in self._current_pairs]
        self._session.registration.shared_transform = shared_transform

        self._session.registration.reference_photo_path = str(self._photo_path) if self._photo_path else ""

        if self._current_map_id:
            state = self._session.registration.map_states.get(self._current_map_id)
            if state is None:
                state = RegistrationMapState(map_id=self._current_map_id)
            if self._source_path is not None:
                state.source_map_path = str(self._source_path)
            state.point_pairs = [replace(pair) for pair in self._current_pairs]
            state.transform = shared_transform
            self._session.registration.active_map_id = self._current_map_id
            self._session.registration.map_states[self._current_map_id] = state

        self._sync_registration_to_manifest()

        self.session_changed.emit()

    def _sync_registration_to_manifest(self) -> None:
        if self._session is None or not self._session.maxrf_pipeline.project_root:
            return

        project_root = Path(self._session.maxrf_pipeline.project_root)
        manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
        if not manifest_path.exists():
            return

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            registration_payload = {
                "reference_photo_path": self._session.registration.reference_photo_path,
                "active_map_id": self._session.registration.active_map_id,
                "shared_point_pair_count": len(self._session.registration.shared_point_pairs),
                "shared_point_pairs": [
                    {
                        "source_x": pair.source_x,
                        "source_y": pair.source_y,
                        "target_x": pair.target_x,
                        "target_y": pair.target_y,
                    }
                    for pair in self._session.registration.shared_point_pairs
                ],
                "shared_transform": {
                    "model": self._session.registration.shared_transform.model,
                    "matrix": self._session.registration.shared_transform.matrix,
                    "rms_error": self._session.registration.shared_transform.rms_error,
                    "solved_at": self._session.registration.shared_transform.solved_at,
                },
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            manifest_data["registration"] = registration_payload
            manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        except Exception:
            return

    def _on_alpha_changed(self, value: int) -> None:
        self.lbl_alpha.setText(f"Overlay alpha: {value / 100.0:.2f}")
        if self._preview_rgb is not None and self._photo_rgb is not None and self._source_gray is not None:
            self._solve_preview_only()

    def _solve_preview_only(self) -> None:
        if self._session is None:
            return

        if self._photo_rgb is None or self._source_gray is None:
            return

        transform = self._session.registration.shared_transform
        if not transform.matrix and self._current_map_id:
            state = self._session.registration.map_states.get(self._current_map_id)
            if state is not None:
                transform = state.transform
        if not transform.matrix:
            return

        matrix = np.array(transform.matrix, dtype=np.float32)
        warped = warp_to_target(
            self._source_gray,
            matrix,
            target_shape=(self._photo_rgb.shape[0], self._photo_rgb.shape[1]),
            model=transform.model,
        )
        alpha = self.slider_alpha.value() / 100.0
        self._preview_rgb = make_overlay(self._photo_rgb, warped, alpha=alpha)
        self._render_overlay_image(self._preview_rgb)

    def _redraw_views(self) -> None:
        if self._source_gray is not None:
            source_rgb = np.stack([self._source_gray] * 3, axis=-1)
            source_marked = self._draw_points(
                source_rgb,
                [(p.source_x, p.source_y) for p in self._current_pairs],
                color=(0, 255, 255),
            )
            self._render_image(self.view_source, source_marked)
        else:
            self.view_source.clear_placeholder("Source map (click to add source points)")

        if self._photo_rgb is not None:
            photo_marked = self._draw_points(
                self._photo_rgb,
                [(p.target_x, p.target_y) for p in self._current_pairs],
                color=(255, 64, 64),
            )
            self._render_image(self.view_photo, photo_marked)
        else:
            self.view_photo.clear_placeholder("Photograph (click to pair target point)")

        self._solve_preview_only()

    def _draw_points(
        self,
        image_rgb: np.ndarray,
        points: list[tuple[float, float]],
        color: tuple[int, int, int],
    ) -> np.ndarray:
        out = image_rgb.copy()
        for idx, (x, y) in enumerate(points, start=1):
            cx = int(round(x))
            cy = int(round(y))
            cv2.circle(out, (cx, cy), 7, color, 2)
            cv2.putText(
                out,
                str(idx),
                (cx + 9, cy - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                1,
                cv2.LINE_AA,
            )
        return out

    def _render_image(self, view: RegistrationImageView, image_rgb: np.ndarray) -> None:
        view.set_image(image_rgb)

    def _render_overlay_image(self, image_rgb: np.ndarray) -> None:
        h, w = image_rgb.shape[:2]
        q_image = QtGui.QImage(
            image_rgb.data,
            w,
            h,
            image_rgb.strides[0],
            QtGui.QImage.Format.Format_RGB888,
        ).copy()

        pixmap = QtGui.QPixmap.fromImage(q_image)
        target_size = self.view_overlay.size()
        if target_size.width() <= 1 or target_size.height() <= 1:
            return

        scaled = pixmap.scaled(
            target_size,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.view_overlay.setPixmap(scaled)

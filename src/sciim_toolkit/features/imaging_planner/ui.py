from __future__ import annotations

import csv
import json
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.imaging_planner.planner_service import (
    compute_tile_plan,
    generate_tile_placements,
    propose_maxrf_plan,
)
from sciim_toolkit.models.project import ModalityConfig, ProjectSession


class ImagingPlannerTab(QtWidgets.QWidget):
    session_changed = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._base_pixmap: QtGui.QPixmap | None = None
        self._last_plan_rows: list[dict[str, object]] = []
        self._last_maxrf_notes: dict[str, str] | None = None
        self._preview_notes_text = ""
        self._is_loading_ui = False
        self._is_applying_irr_mode = False

        self._build_ui()
        self._bind_signals()

    def _build_ui(self) -> None:
        root = QtWidgets.QHBoxLayout(self)

        controls_scroll = QtWidgets.QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setMinimumWidth(380)
        controls_scroll.setMaximumWidth(520)
        controls_container = QtWidgets.QWidget()
        controls_container.setMinimumWidth(360)
        self.controls_layout = QtWidgets.QVBoxLayout(controls_container)
        controls_layout = self.controls_layout
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(10)

        controls_scroll.setWidget(controls_container)

        preview_container = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_container)

        split = QtWidgets.QHBoxLayout()
        self.preview_normal = QtWidgets.QLabel("Normal orientation")
        self.preview_normal.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_normal.setMinimumSize(220, 220)
        self.preview_normal.setStyleSheet("border: 1px solid #aaa; background: #111; color: #ddd;")

        self.preview_sideways = QtWidgets.QLabel("Sideways orientation")
        self.preview_sideways.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_sideways.setMinimumSize(220, 220)
        self.preview_sideways.setStyleSheet("border: 1px solid #aaa; background: #111; color: #ddd;")

        split.addWidget(self.preview_normal, 1)
        split.addWidget(self.preview_sideways, 1)
        preview_layout.addLayout(split, 1)

        self.preview_notes = QtWidgets.QLabel("")
        self.preview_notes.setWordWrap(True)
        self.preview_notes.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignHCenter)
        self.preview_notes.setStyleSheet(
            "color: #333; background: #f8f8f8; border: 1px solid #ddd; padding: 10px; font-size: 14px;"
        )
        preview_layout.addWidget(self.preview_notes)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(preview_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 900])
        root.addWidget(splitter, 1)
        self.main_splitter = splitter

        self._build_modality_group()
        self._build_summary_group()
        self.controls_layout.addStretch(1)

    def _modality_row(self, name: str) -> tuple[QtWidgets.QWidget, dict[str, QtWidgets.QWidget]]:
        row = QtWidgets.QGridLayout()
        row.setContentsMargins(2, 2, 2, 2)
        row.setHorizontalSpacing(6)
        row.setVerticalSpacing(6)
        chk = QtWidgets.QCheckBox(name)
        tile_w = QtWidgets.QDoubleSpinBox()
        tile_h = QtWidgets.QDoubleSpinBox()
        overlap = QtWidgets.QDoubleSpinBox()
        unit_combo = QtWidgets.QComboBox()

        tile_w.setRange(1.0, 500.0)
        tile_h.setRange(1.0, 500.0)
        overlap.setRange(0.0, 95.0)

        tile_w.setSuffix(" cm")
        tile_h.setSuffix(" cm")
        overlap.setSuffix(" %")
        tile_w.setMaximumWidth(95)
        tile_h.setMaximumWidth(95)
        overlap.setMaximumWidth(95)
        unit_combo.addItems(["%", "cm"])
        unit_combo.setMaximumWidth(70)

        row.addWidget(chk, 0, 0, 1, 2)
        if name == "IRR":
            mode_combo = QtWidgets.QComboBox()
            mode_combo.addItems(["High-res 50×50", "Low-res 100×100"])
            mode_combo.setMaximumWidth(180)
            row.addWidget(mode_combo, 0, 2, 1, 4)
        else:
            mode_combo = None
        row.addWidget(QtWidgets.QLabel("Tile W"), 1, 0)
        row.addWidget(tile_w, 1, 1)
        row.addWidget(QtWidgets.QLabel("Tile H"), 1, 2)
        row.addWidget(tile_h, 1, 3)
        row.addWidget(QtWidgets.QLabel("Overlap"), 1, 4)
        row.addWidget(overlap, 1, 5)
        row.addWidget(unit_combo, 1, 6)
        row.setColumnStretch(7, 1)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(row)

        return wrapper, {
            "check": chk,
            "tile_w": tile_w,
            "tile_h": tile_h,
            "overlap": overlap,
            "unit_combo": unit_combo,
            "mode_combo": mode_combo,
        }

    def _build_modality_group(self) -> None:
        group = QtWidgets.QGroupBox("Imaging Modalities")
        outer = QtWidgets.QVBoxLayout(group)

        self.modality_widgets: dict[str, dict[str, QtWidgets.QWidget]] = {}
        for key in ("IRR", "X-radiography", "MA-XRF"):
            row_container, row_widget = self._modality_row(key)
            outer.addWidget(row_container)
            self.modality_widgets[key] = row_widget
            unit_combo: QtWidgets.QComboBox = row_widget["unit_combo"]
            overlap_spin: QtWidgets.QDoubleSpinBox = row_widget["overlap"]
            unit_combo.currentIndexChanged.connect(
                lambda _idx, spin=overlap_spin, combo=unit_combo: self._on_unit_changed(spin, combo)
            )
            if row_widget.get("mode_combo") is not None:
                row_widget["mode_combo"].currentIndexChanged.connect(
                    lambda _idx, row=row_widget: self._apply_irr_mode(row)
                )
                row_widget["tile_w"].valueChanged.connect(self.recompute)
                row_widget["tile_h"].valueChanged.connect(self.recompute)
                row_widget["overlap"].valueChanged.connect(self.recompute)
                row_widget["unit_combo"].currentIndexChanged.connect(self.recompute)

        controls = QtWidgets.QHBoxLayout()
        self.combo_preview_modality = QtWidgets.QComboBox()
        self.combo_preview_modality.addItems(["IRR", "X-radiography", "MA-XRF"])
        self.btn_recompute = QtWidgets.QPushButton("Recompute tile plans")
        controls.addWidget(QtWidgets.QLabel("Preview modality"))
        controls.addWidget(self.combo_preview_modality)
        controls.addStretch(1)
        controls.addWidget(self.btn_recompute)

        outer.addLayout(controls)
        self.controls_layout.addWidget(group)

    def _build_summary_group(self) -> None:
        group = QtWidgets.QGroupBox("Plan Summary")
        layout = QtWidgets.QVBoxLayout(group)
        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(220)
        export_row = QtWidgets.QHBoxLayout()
        self.btn_export_summary = QtWidgets.QPushButton("Export TXT…")
        self.btn_export_csv = QtWidgets.QPushButton("Export CSV…")
        self.btn_export_json = QtWidgets.QPushButton("Export JSON…")
        self.btn_export_visual = QtWidgets.QPushButton("Export visual (PNG/PDF)…")

        export_row.addWidget(self.btn_export_summary)
        export_row.addWidget(self.btn_export_csv)
        export_row.addWidget(self.btn_export_json)

        layout.addWidget(self.summary)
        layout.addLayout(export_row)
        layout.addWidget(self.btn_export_visual)
        self.controls_layout.addWidget(group)

    def _bind_signals(self) -> None:
        self.btn_recompute.clicked.connect(self.recompute)
        self.combo_preview_modality.currentIndexChanged.connect(self.recompute)
        self.btn_export_summary.clicked.connect(self._export_summary)
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_export_visual.clicked.connect(self._export_visual)

        for row in self.modality_widgets.values():
            row["check"].stateChanged.connect(self._pull_ui_into_session)
            row["tile_w"].valueChanged.connect(self._pull_ui_into_session)
            row["tile_h"].valueChanged.connect(self._pull_ui_into_session)
            row["overlap"].valueChanged.connect(self._pull_ui_into_session)
            row["unit_combo"].currentIndexChanged.connect(self._pull_ui_into_session)

    def set_session(self, session: ProjectSession) -> None:
        self._session = session
        self._push_session_to_ui()
        self.recompute()

    def _push_session_to_ui(self) -> None:
        if self._session is None:
            return

        self._is_loading_ui = True
        try:
            image_path = self._session.imaging_planner.painting_image_path

            for name, cfg in self._session.imaging_planner.modalities.items():
                row = self.modality_widgets[name]
                row["check"].setChecked(cfg.enabled)
                row["tile_w"].setValue(cfg.tile_width_cm)
                row["tile_h"].setValue(cfg.tile_height_cm)
                row["overlap"].setValue(cfg.overlap_value)
                unit_combo: QtWidgets.QComboBox = row["unit_combo"]
                unit_combo.setCurrentText("cm" if cfg.overlap_unit == "cm" else "%")
                self._on_unit_changed(row["overlap"], unit_combo)
                if name == "IRR" and row.get("mode_combo") is not None:
                    self._sync_irr_mode(row)

            self._load_preview_pixmap(Path(image_path))
        finally:
            self._is_loading_ui = False

    def _pull_ui_into_session(self) -> None:
        if self._session is None or self._is_loading_ui:
            return

        for name, row in self.modality_widgets.items():
            cfg: ModalityConfig = self._session.imaging_planner.modalities[name]
            cfg.enabled = bool(row["check"].isChecked())
            cfg.tile_width_cm = float(row["tile_w"].value())
            cfg.tile_height_cm = float(row["tile_h"].value())
            cfg.overlap_value = float(row["overlap"].value())
            unit_combo: QtWidgets.QComboBox = row["unit_combo"]
            cfg.overlap_unit = "cm" if unit_combo.currentText() == "cm" else "percent"

        self.session_changed.emit()

    def _load_preview_pixmap(self, path: Path) -> None:
        if not path or not path.exists():
            self._base_pixmap = None
            self.preview_normal.setText("Load a painting image to preview tile layout")
            self.preview_sideways.setText("Load a painting image to preview tile layout")
            self.preview_normal.setPixmap(QtGui.QPixmap())
            self.preview_sideways.setPixmap(QtGui.QPixmap())
            return

        pm = QtGui.QPixmap(str(path))
        if pm.isNull():
            self._base_pixmap = None
            self.preview_normal.setText("Failed to load image")
            self.preview_sideways.setText("Failed to load image")
            self.preview_normal.setPixmap(QtGui.QPixmap())
            self.preview_sideways.setPixmap(QtGui.QPixmap())
            return

        self._base_pixmap = pm

    def recompute(self) -> None:
        if self._session is None:
            return

        self._pull_ui_into_session()
        width_cm = self._session.artwork.width_cm
        height_cm = self._session.artwork.height_cm

        lines: list[str] = []
        self._last_plan_rows = []
        self._last_maxrf_notes = None
        any_enabled = False

        for name, cfg in self._session.imaging_planner.modalities.items():
            if not cfg.enabled:
                continue
            any_enabled = True
            plan = compute_tile_plan(
                modality=name,
                width_cm=width_cm,
                height_cm=height_cm,
                tile_width_cm=cfg.tile_width_cm,
                tile_height_cm=cfg.tile_height_cm,
                overlap_value=cfg.overlap_value,
                overlap_unit=cfg.overlap_unit,
            )
            plan_side = compute_tile_plan(
                modality=name,
                width_cm=height_cm,
                height_cm=width_cm,
                tile_width_cm=cfg.tile_width_cm,
                tile_height_cm=cfg.tile_height_cm,
                overlap_value=cfg.overlap_value,
                overlap_unit=cfg.overlap_unit,
            )
            overlap_label = f"{cfg.overlap_value:.1f}%" if cfg.overlap_unit == "percent" else f"{cfg.overlap_value:.1f} cm"
            lines.append(
                f"{name}: {plan.columns} cols × {plan.rows} rows = {plan.tile_count} tiles "
                f"(tile {cfg.tile_width_cm:.1f}×{cfg.tile_height_cm:.1f} cm, overlap {overlap_label})"
            )
            lines.append(
                f"  Sideways: {plan_side.columns} cols × {plan_side.rows} rows = {plan_side.tile_count} tiles"
            )
            self._last_plan_rows.append(
                {
                    "modality": name,
                    "columns": plan.columns,
                    "rows": plan.rows,
                    "tile_count": plan.tile_count,
                    "sideways_columns": plan_side.columns,
                    "sideways_rows": plan_side.rows,
                    "sideways_tile_count": plan_side.tile_count,
                    "tile_width_cm": cfg.tile_width_cm,
                    "tile_height_cm": cfg.tile_height_cm,
                    "overlap_value": cfg.overlap_value,
                    "overlap_unit": cfg.overlap_unit,
                }
            )
            if name == "MA-XRF":
                normal_note = propose_maxrf_plan(painting_h=height_cm, tile_h=cfg.tile_height_cm)
                sideways_note = propose_maxrf_plan(painting_h=width_cm, tile_h=cfg.tile_height_cm)
                self._last_maxrf_notes = {
                    "normal": normal_note["summary"],
                    "normal_details": normal_note["details"],
                    "sideways": sideways_note["summary"],
                    "sideways_details": sideways_note["details"],
                }
                lines.append("  MA-XRF easel plan (normal): " + normal_note["summary"])
                if normal_note["details"]:
                    lines.append("    " + normal_note["details"])
                lines.append("  MA-XRF easel plan (sideways): " + sideways_note["summary"])
                if sideways_note["details"]:
                    lines.append("    " + sideways_note["details"])

        if not any_enabled:
            lines.append("No modality enabled.")

        self.summary.setPlainText("\n".join(lines))
        self._draw_grid_preview()

    def _draw_grid_preview(self) -> None:
        normal = self._render_preview_pixmap(orientation="Normal")
        sideways = self._render_preview_pixmap(orientation="Sideways")
        if normal is None or sideways is None:
            return

        self.preview_normal.setPixmap(
            normal.scaled(
                self.preview_normal.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_sideways.setPixmap(
            sideways.scaled(
                self.preview_sideways.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_notes.setText(self._preview_notes_text)

    def _col_letter(self, n: int) -> str:
        result = ""
        idx = n
        while idx >= 0:
            idx, rem = divmod(idx, 26)
            result = chr(65 + rem) + result
            idx -= 1
        return result

    def _style_for_modality(self, modality: str) -> str:
        if modality == "MA-XRF":
            return "xrf"
        if modality == "IRR":
            return "irr"
        return "xray"

    def _format_overlap_label(self, cfg: ModalityConfig) -> str:
        if cfg.overlap_unit == "cm":
            return f"{cfg.overlap_value:.1f} cm"
        return f"{cfg.overlap_value:.1f}%"

    def _last_tile_label_for_plan(self, plan) -> str:
        if plan.columns <= 0 or plan.rows <= 0:
            return "XX"
        return f"{self._col_letter(plan.columns - 1)}{plan.rows}"

    def _build_modality_footer(self, modality: str, cfg: ModalityConfig) -> str:
        if self._session is None:
            return ""

        width_cm = self._session.artwork.width_cm
        height_cm = self._session.artwork.height_cm
        if width_cm <= 0 or height_cm <= 0:
            return ""

        if modality == "IRR":
            if self._is_irr_custom_config(cfg):
                plan_n = compute_tile_plan(
                    modality=modality,
                    width_cm=width_cm,
                    height_cm=height_cm,
                    tile_width_cm=cfg.tile_width_cm,
                    tile_height_cm=cfg.tile_height_cm,
                    overlap_value=cfg.overlap_value,
                    overlap_unit=cfg.overlap_unit,
                )
                plan_s = compute_tile_plan(
                    modality=modality,
                    width_cm=height_cm,
                    height_cm=width_cm,
                    tile_width_cm=cfg.tile_width_cm,
                    tile_height_cm=cfg.tile_height_cm,
                    overlap_value=cfg.overlap_value,
                    overlap_unit=cfg.overlap_unit,
                )
                return (
                    "Green rectangles = IRR image tiles with semi-transparent neutral fill. "
                    f"Custom settings: {cfg.tile_width_cm:.1f}×{cfg.tile_height_cm:.1f} cm, "
                    f"overlap {self._format_overlap_label(cfg)}. "
                    "Labels mark first (A1) and last tile. "
                    f"Normal: {plan_n.columns}×{plan_n.rows} = {plan_n.tile_count} scans. "
                    f"Sideways: {plan_s.columns}×{plan_s.rows} = {plan_s.tile_count} scans."
                )

            plan_hr_n = compute_tile_plan(
                modality=modality,
                width_cm=width_cm,
                height_cm=height_cm,
                tile_width_cm=50.0,
                tile_height_cm=50.0,
                overlap_value=25.0,
                overlap_unit="percent",
            )
            plan_hr_s = compute_tile_plan(
                modality=modality,
                width_cm=height_cm,
                height_cm=width_cm,
                tile_width_cm=50.0,
                tile_height_cm=50.0,
                overlap_value=25.0,
                overlap_unit="percent",
            )
            plan_lr_n = compute_tile_plan(
                modality=modality,
                width_cm=width_cm,
                height_cm=height_cm,
                tile_width_cm=100.0,
                tile_height_cm=100.0,
                overlap_value=25.0,
                overlap_unit="percent",
            )
            plan_lr_s = compute_tile_plan(
                modality=modality,
                width_cm=height_cm,
                height_cm=width_cm,
                tile_width_cm=100.0,
                tile_height_cm=100.0,
                overlap_value=25.0,
                overlap_unit="percent",
            )
            return (
                "Green rectangles = IRR image tiles with semi-transparent neutral fill. "
                "Labels mark first (A1) and last tile. "
                "High-res: 50×50 cm, Low-res: 100×100 cm (both 25% overlap). "
                f"High-res normal: {plan_hr_n.tile_count} scans, sideways: {plan_hr_s.tile_count} scans. "
                f"Low-res normal: {plan_lr_n.tile_count} scans, sideways: {plan_lr_s.tile_count} scans."
            )

        plan_n = compute_tile_plan(
            modality=modality,
            width_cm=width_cm,
            height_cm=height_cm,
            tile_width_cm=cfg.tile_width_cm,
            tile_height_cm=cfg.tile_height_cm,
            overlap_value=cfg.overlap_value,
            overlap_unit=cfg.overlap_unit,
        )
        plan_s = compute_tile_plan(
            modality=modality,
            width_cm=height_cm,
            height_cm=width_cm,
            tile_width_cm=cfg.tile_width_cm,
            tile_height_cm=cfg.tile_height_cm,
            overlap_value=cfg.overlap_value,
            overlap_unit=cfg.overlap_unit,
        )
        if modality == "MA-XRF":
            normal_note = propose_maxrf_plan(painting_h=height_cm, tile_h=cfg.tile_height_cm)
            sideways_note = propose_maxrf_plan(painting_h=width_cm, tile_h=cfg.tile_height_cm)
            return (
                "Red rectangles = µ-XRF scan tiles with semi-transparent neutral fill "
                f"({cfg.tile_width_cm:.1f}×{cfg.tile_height_cm:.1f} cm, {self._format_overlap_label(cfg)} overlap). "
                "Labels mark first (A1) and last tile. "
                f"Normal orientation: {plan_n.columns}×{plan_n.rows} = {plan_n.tile_count} scans. "
                f"Sideways: {plan_s.columns}×{plan_s.rows} = {plan_s.tile_count} scans. "
                f"Normal → {normal_note['summary']} Sideways → {sideways_note['summary']}"
            )

        return (
            "Blue rectangles = X-radiography film positions with semi-transparent neutral fill "
            f"({cfg.tile_width_cm:.1f}×{cfg.tile_height_cm:.1f} cm, {self._format_overlap_label(cfg)} overlap). "
            "Labels mark first (A1) and last tile. "
            f"Normal: {plan_n.columns}×{plan_n.rows} = {plan_n.tile_count} scans. "
            f"Sideways: {plan_s.columns}×{plan_s.rows} = {plan_s.tile_count} scans."
        )

    def _metadata_line(self) -> str:
        if self._session is None:
            return ""
        art = self._session.artwork
        artist = art.artist.strip() or "Unknown artist"
        title = art.title.strip() or "Untitled"
        hki = art.hki.strip() or "-"
        inv = art.inventory_id.strip() or "-"
        collection = art.collection.strip() or "-"
        return f"{artist} - \"{title}\" (HKI{hki}; INV {inv}; Collection {collection})"

    def _build_export_composite(self, modality: str, cfg: ModalityConfig) -> QtGui.QPixmap:
        if self._session is None:
            return QtGui.QPixmap()

        width_cm = self._session.artwork.width_cm
        height_cm = self._session.artwork.height_cm
        style = self._style_for_modality(modality)
        panels: list[QtGui.QPixmap] = []
        labels: list[str] = []

        if modality == "IRR":
            if self._is_irr_custom_config(cfg):
                panels.append(
                    self._render_static_plan_pixmap(
                        width_cm,
                        height_cm,
                        cfg.tile_width_cm,
                        cfg.tile_height_cm,
                        cfg.overlap_value,
                        cfg.overlap_unit,
                        "Normal",
                        style,
                    )
                )
                labels.append("Custom - Normal orientation")
                panels.append(
                    self._render_static_plan_pixmap(
                        height_cm,
                        width_cm,
                        cfg.tile_width_cm,
                        cfg.tile_height_cm,
                        cfg.overlap_value,
                        cfg.overlap_unit,
                        "Sideways",
                        style,
                    )
                )
                labels.append("Custom - Flipped orientation")
            else:
                presets = [
                    ("High-res", 50.0, 50.0),
                    ("Low-res", 100.0, 100.0),
                ]
                for name, tw, th in presets:
                    panels.append(
                        self._render_static_plan_pixmap(
                            width_cm,
                            height_cm,
                            tw,
                            th,
                            25.0,
                            "percent",
                            "Normal",
                            style,
                        )
                    )
                    labels.append(f"{name} - Normal orientation")
                    panels.append(
                        self._render_static_plan_pixmap(
                            height_cm,
                            width_cm,
                            tw,
                            th,
                            25.0,
                            "percent",
                            "Sideways",
                            style,
                        )
                    )
                    labels.append(f"{name} - Flipped orientation")
        else:
            panels.append(
                self._render_static_plan_pixmap(
                    width_cm,
                    height_cm,
                    cfg.tile_width_cm,
                    cfg.tile_height_cm,
                    cfg.overlap_value,
                    cfg.overlap_unit,
                    "Normal",
                    style,
                )
            )
            labels.append("Normal orientation")
            panels.append(
                self._render_static_plan_pixmap(
                    height_cm,
                    width_cm,
                    cfg.tile_width_cm,
                    cfg.tile_height_cm,
                    cfg.overlap_value,
                    cfg.overlap_unit,
                    "Sideways",
                    style,
                )
            )
            labels.append("Flipped orientation")

        gap = 20
        panel_w = max(p.width() for p in panels)
        panel_h = max(p.height() for p in panels)
        cols = 2
        rows = 2 if (modality == "IRR" and len(panels) == 4) else 1
        title_h = 46
        subtitle_h = 32
        top_pad = 14
        panel_caption_h = 30
        footer_h = 142

        out_w = cols * panel_w + (cols + 1) * gap
        out_h = (
            top_pad
            + title_h
            + subtitle_h
            + rows * (panel_h + panel_caption_h)
            + (rows + 1) * gap
            + footer_h
        )

        composite = QtGui.QPixmap(out_w, out_h)
        composite.fill(QtGui.QColor("white"))
        painter = QtGui.QPainter(composite)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)

        title_rect = QtCore.QRect(0, top_pad, out_w, title_h)
        painter.setFont(QtGui.QFont("Helvetica", 20, QtGui.QFont.Weight.Bold))
        painter.setPen(QtGui.QColor("black"))
        painter.drawText(title_rect, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter, f"{modality} plan")

        subtitle_rect = QtCore.QRect(0, top_pad + title_h, out_w, subtitle_h)
        subtitle_font = QtGui.QFont("Helvetica", 13)
        subtitle_font.setItalic(True)
        painter.setFont(subtitle_font)
        painter.drawText(
            subtitle_rect,
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter,
            self._metadata_line(),
        )

        base_y = top_pad + title_h + subtitle_h + gap
        painter.setFont(QtGui.QFont("Helvetica", 13, QtGui.QFont.Weight.Bold))
        for idx, panel in enumerate(panels):
            row = idx // cols
            col = idx % cols
            x = gap + col * (panel_w + gap)
            y = base_y + row * (panel_h + panel_caption_h + gap)
            painter.drawText(QtCore.QRect(x, y, panel_w, panel_caption_h), QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter, labels[idx])
            panel_y = y + panel_caption_h
            painter.drawPixmap(x, panel_y, panel.scaled(panel_w, panel_h, QtCore.Qt.AspectRatioMode.KeepAspectRatio))

        footer_text = self._build_modality_footer(modality, cfg)
        footer_y = out_h - footer_h + 8
        footer_rect = QtCore.QRect(gap, footer_y, out_w - 2 * gap, footer_h - 16)
        painter.setFont(QtGui.QFont("Helvetica", 12))
        painter.setPen(QtGui.QColor(40, 40, 40))
        painter.drawText(
            footer_rect,
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.TextFlag.TextWordWrap,
            footer_text,
        )

        painter.end()
        return composite

    def _draw_tiles_on_pixmap(
        self,
        pixmap: QtGui.QPixmap,
        placements,
        width_cm: float,
        height_cm: float,
        *,
        style: str,
        plot_rect: QtCore.QRect | None = None,
    ) -> None:
        if not placements:
            return

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        edge_color = QtGui.QColor(255, 0, 0, 210)
        fill_color = QtGui.QColor(140, 140, 140, 55)
        label_color = QtGui.QColor(255, 0, 0, 230)
        if style == "xrf":
            edge_color = QtGui.QColor(255, 0, 0, 230)
            fill_color = QtGui.QColor(140, 140, 140, 55)
            label_color = QtGui.QColor(255, 0, 0, 240)
        elif style == "irr":
            edge_color = QtGui.QColor(0, 170, 0, 210)
            fill_color = QtGui.QColor(140, 140, 140, 55)
            label_color = QtGui.QColor(0, 135, 0, 240)
        elif style == "xray":
            edge_color = QtGui.QColor(0, 90, 230, 210)
            fill_color = QtGui.QColor(140, 140, 140, 55)
            label_color = QtGui.QColor(0, 75, 200, 240)

        base_pen = QtGui.QPen(edge_color)
        base_pen.setWidth(2)
        highlight_pen = QtGui.QPen(edge_color)
        highlight_pen.setWidth(4)

        painter.setFont(QtGui.QFont("Helvetica", 10, QtGui.QFont.Weight.Bold))

        if plot_rect is None:
            px_w = float(pixmap.width())
            px_h = float(pixmap.height())
            x0 = 0.0
            y0 = 0.0
        else:
            px_w = float(plot_rect.width())
            px_h = float(plot_rect.height())
            x0 = float(plot_rect.x())
            y0 = float(plot_rect.y())

        last_tile = placements[-1]
        first_tile_rect: QtCore.QRect | None = None
        last_tile_rect: QtCore.QRect | None = None
        for placement in placements:
            rx = int(x0 + (placement.x_cm / width_cm) * px_w)
            ry = int(y0 + (placement.y_cm / height_cm) * px_h)
            rw = max(1, int((placement.width_cm / width_cm) * px_w))
            rh = max(1, int((placement.height_cm / height_cm) * px_h))
            tile_rect = QtCore.QRect(rx, ry, rw, rh)

            pen = highlight_pen if placement.index in (1, last_tile.index) else base_pen
            painter.setPen(pen)
            if fill_color.alpha() > 0:
                painter.fillRect(tile_rect, fill_color)
            painter.drawRect(tile_rect)

            if placement.index == 1:
                first_tile_rect = tile_rect
            if placement.index == last_tile.index:
                last_tile_rect = tile_rect

        painter.setPen(label_color)
        label_font = QtGui.QFont("Helvetica", 26, QtGui.QFont.Weight.Bold)
        painter.setFont(label_font)

        if first_tile_rect is None:
            first_tile_rect = QtCore.QRect(
                int(x0 + (placements[0].x_cm / width_cm) * px_w),
                int(y0 + (placements[0].y_cm / height_cm) * px_h),
                max(1, int((placements[0].width_cm / width_cm) * px_w)),
                max(1, int((placements[0].height_cm / height_cm) * px_h)),
            )
        painter.drawText(first_tile_rect, QtCore.Qt.AlignmentFlag.AlignCenter, "A1")

        last_label = f"{self._col_letter(last_tile.col - 1)}{last_tile.row}"
        if last_tile_rect is None:
            last_tile_rect = QtCore.QRect(
                int(x0 + (last_tile.x_cm / width_cm) * px_w),
                int(y0 + (last_tile.y_cm / height_cm) * px_h),
                max(1, int((last_tile.width_cm / width_cm) * px_w)),
                max(1, int((last_tile.height_cm / height_cm) * px_h)),
            )
        painter.drawText(last_tile_rect, QtCore.Qt.AlignmentFlag.AlignCenter, last_label)

        painter.end()

    def _draw_fitted_image(
        self,
        painter: QtGui.QPainter,
        src: QtGui.QPixmap,
        dest_rect: QtCore.QRect,
    ) -> None:
        fitted = src.scaled(
            dest_rect.size(),
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(dest_rect, fitted)

    def _render_oriented_chart(
        self,
        *,
        width_cm: float,
        height_cm: float,
        tile_w: float,
        tile_h: float,
        overlap_value: float,
        overlap_unit: str,
        orientation: str,
        style: str,
    ) -> QtGui.QPixmap:
        px_per_cm = 5.0
        plot_w = max(200, int(round(width_cm * px_per_cm)))
        plot_h = max(200, int(round(height_cm * px_per_cm)))

        margin_left = 52
        margin_right = 20
        margin_top = 20
        margin_bottom = 46
        canvas = QtGui.QPixmap(
            margin_left + plot_w + margin_right,
            margin_top + plot_h + margin_bottom,
        )
        canvas.fill(QtGui.QColor("white"))

        plot_rect = QtCore.QRect(margin_left, margin_top, plot_w, plot_h)
        painter = QtGui.QPainter(canvas)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        if self._base_pixmap is not None:
            src = self._base_pixmap
            if orientation.startswith("Sideways"):
                src = src.transformed(QtGui.QTransform().rotate(90))
            self._draw_fitted_image(painter, src, plot_rect)
        else:
            painter.fillRect(plot_rect, QtGui.QColor("white"))

        tick_step = 10.0
        grid_pen = QtGui.QPen(QtGui.QColor(180, 180, 180, 170))
        grid_pen.setStyle(QtCore.Qt.PenStyle.DotLine)
        grid_pen.setWidth(1)
        axis_pen = QtGui.QPen(QtGui.QColor("black"))
        axis_pen.setWidth(1)
        text_pen = QtGui.QPen(QtGui.QColor("black"))
        painter.setFont(QtGui.QFont("Helvetica", 11))

        x = 0.0
        while x <= width_cm + 1e-9:
            px = int(plot_rect.x() + (x / width_cm) * plot_rect.width())
            painter.setPen(grid_pen)
            painter.drawLine(px, plot_rect.y(), px, plot_rect.y() + plot_rect.height())
            painter.setPen(axis_pen)
            painter.drawLine(px, plot_rect.y() + plot_rect.height(), px, plot_rect.y() + plot_rect.height() + 5)
            painter.setPen(text_pen)
            painter.drawText(px - 14, plot_rect.y() + plot_rect.height() + 24, f"{int(round(x))}")
            x += tick_step

        y = 0.0
        while y <= height_cm + 1e-9:
            py = int(plot_rect.y() + (y / height_cm) * plot_rect.height())
            painter.setPen(grid_pen)
            painter.drawLine(plot_rect.x(), py, plot_rect.x() + plot_rect.width(), py)
            painter.setPen(axis_pen)
            painter.drawLine(plot_rect.x() - 5, py, plot_rect.x(), py)
            painter.setPen(text_pen)
            painter.drawText(5, py + 6, f"{int(round(y))}")
            y += tick_step

        painter.setPen(axis_pen)
        painter.drawRect(plot_rect)
        painter.setFont(QtGui.QFont("Helvetica", 12, QtGui.QFont.Weight.Bold))
        painter.drawText(plot_rect.x() + plot_rect.width() + 8, plot_rect.y() + plot_rect.height() + 24, "cm")
        painter.drawText(8, plot_rect.y() - 2, "cm")
        painter.end()

        placements = generate_tile_placements(
            width_cm=width_cm,
            height_cm=height_cm,
            tile_width_cm=tile_w,
            tile_height_cm=tile_h,
            overlap_value=overlap_value,
            overlap_unit=overlap_unit,
        )
        self._draw_tiles_on_pixmap(
            canvas,
            placements,
            width_cm,
            height_cm,
            style=style,
            plot_rect=plot_rect,
        )
        return canvas

    def _render_preview_pixmap(self, orientation: str) -> QtGui.QPixmap | None:
        if self._session is None:
            return None

        modality = self.combo_preview_modality.currentText()
        cfg = self._session.imaging_planner.modalities[modality]
        width_cm = self._session.artwork.width_cm
        height_cm = self._session.artwork.height_cm
        if width_cm <= 0 or height_cm <= 0:
            return None

        if orientation.startswith("Sideways"):
            width_cm, height_cm = height_cm, width_cm

        if not cfg.enabled:
            self._preview_notes_text = f"{modality} is currently disabled. Enable it to see scan count details."
            return self._render_oriented_chart(
                width_cm=width_cm,
                height_cm=height_cm,
                tile_w=cfg.tile_width_cm,
                tile_h=cfg.tile_height_cm,
                overlap_value=cfg.overlap_value,
                overlap_unit=cfg.overlap_unit,
                orientation=orientation,
                style="xrf" if modality == "MA-XRF" else ("irr" if modality == "IRR" else "xray"),
            )

        if width_cm <= 0 or height_cm <= 0:
            return None

        style = self._style_for_modality(modality)
        pixmap = self._render_oriented_chart(
            width_cm=width_cm,
            height_cm=height_cm,
            tile_w=cfg.tile_width_cm,
            tile_h=cfg.tile_height_cm,
            overlap_value=cfg.overlap_value,
            overlap_unit=cfg.overlap_unit,
            orientation=orientation,
            style=style,
        )

        if orientation.startswith("Normal"):
            self._preview_notes_text = self._build_modality_footer(modality, cfg)
        return pixmap

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._draw_grid_preview()

    def _export_summary(self) -> None:
        text = self.summary.toPlainText().strip()
        if not text:
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export planner summary",
            str(Path.home() / self._default_export_name("planner_summary", "txt")),
            "Text (*.txt)",
        )
        if not path:
            return

        Path(path).write_text(text + "\n", encoding="utf-8")

    def _default_export_name(self, stem: str, ext: str) -> str:
        hki = ""
        if self._session is not None:
            hki = self._session.artwork.hki.strip()
        if hki:
            return f"HKI{hki}_{stem}.{ext}"
        stamp = QtCore.QDateTime.currentDateTime().toString("yyyyMMdd_HHmm")
        return f"{stamp}_{stem}.{ext}"

    def _on_unit_changed(self, spin: QtWidgets.QDoubleSpinBox, combo: QtWidgets.QComboBox) -> None:
        unit = combo.currentText()
        spin.setSuffix(" cm" if unit == "cm" else " %")

    def _apply_irr_mode(self, row: dict[str, QtWidgets.QWidget]) -> None:
        mode_combo: QtWidgets.QComboBox = row["mode_combo"]
        if mode_combo is None:
            return
        self._is_applying_irr_mode = True
        if mode_combo.currentIndex() == 0:
            row["tile_w"].setValue(50.0)
            row["tile_h"].setValue(50.0)
        else:
            row["tile_w"].setValue(100.0)
            row["tile_h"].setValue(100.0)
        # Preset mode implies standard overlap in percent.
        row["unit_combo"].setCurrentText("%")
        row["overlap"].setValue(25.0)
        self._is_applying_irr_mode = False
        self.recompute()

    def _sync_irr_mode(self, row: dict[str, QtWidgets.QWidget]) -> None:
        mode_combo: QtWidgets.QComboBox = row["mode_combo"]
        if mode_combo is None:
            return
        tile_w = row["tile_w"].value()
        tile_h = row["tile_h"].value()
        if abs(tile_w - 100.0) < 1e-3 and abs(tile_h - 100.0) < 1e-3:
            mode_combo.setCurrentIndex(1)
        else:
            mode_combo.setCurrentIndex(0)

    def _is_irr_custom_config(self, cfg: ModalityConfig) -> bool:
        """Return True when IRR settings differ from untouched preset configs."""
        is_percent = cfg.overlap_unit == "percent"
        matches_high = (
            abs(cfg.tile_width_cm - 50.0) < 1e-6
            and abs(cfg.tile_height_cm - 50.0) < 1e-6
            and is_percent
            and abs(cfg.overlap_value - 25.0) < 1e-6
        )
        matches_low = (
            abs(cfg.tile_width_cm - 100.0) < 1e-6
            and abs(cfg.tile_height_cm - 100.0) < 1e-6
            and is_percent
            and abs(cfg.overlap_value - 25.0) < 1e-6
        )
        return not (matches_high or matches_low)

    def _render_static_plan_pixmap(
        self,
        width_cm: float,
        height_cm: float,
        tile_w: float,
        tile_h: float,
        overlap_value: float,
        overlap_unit: str,
        orientation: str,
        style: str,
    ) -> QtGui.QPixmap:
        return self._render_oriented_chart(
            width_cm=width_cm,
            height_cm=height_cm,
            tile_w=tile_w,
            tile_h=tile_h,
            overlap_value=overlap_value,
            overlap_unit=overlap_unit,
            orientation=orientation,
            style=style,
        )

    def _export_csv(self) -> None:
        if not self._last_plan_rows:
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export planner CSV",
            str(Path.home() / self._default_export_name("planner_summary", "csv")),
            "CSV (*.csv)",
        )
        if not path:
            return

        out_path = Path(path)
        if out_path.suffix.lower() != ".csv":
            out_path = out_path.with_suffix(".csv")

        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "modality",
                    "columns",
                    "rows",
                    "tile_count",
                    "sideways_columns",
                    "sideways_rows",
                    "sideways_tile_count",
                    "tile_width_cm",
                    "tile_height_cm",
                    "overlap_value",
                    "overlap_unit",
                ],
            )
            writer.writeheader()
            writer.writerows(self._last_plan_rows)

    def _export_json(self) -> None:
        if self._session is None:
            return

        payload = {
            "artwork": {
                "title": self._session.artwork.title,
                "artist": self._session.artwork.artist,
                "hki": self._session.artwork.hki,
                "collection": self._session.artwork.collection,
                "inventory_id": self._session.artwork.inventory_id,
                "width_cm": self._session.artwork.width_cm,
                "height_cm": self._session.artwork.height_cm,
                "painting_image_path": self._session.imaging_planner.painting_image_path,
            },
            "plans": self._last_plan_rows,
            "maxrf_notes": self._last_maxrf_notes or {},
        }

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export planner JSON",
            str(Path.home() / self._default_export_name("planner_summary", "json")),
            "JSON (*.json)",
        )
        if not path:
            return

        out_path = Path(path)
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _export_visual(self) -> None:
        if self._session is None:
            return

        width_cm = self._session.artwork.width_cm
        height_cm = self._session.artwork.height_cm
        if width_cm <= 0 or height_cm <= 0:
            return

        enabled_modalities = [
            (name, cfg)
            for name, cfg in self._session.imaging_planner.modalities.items()
            if cfg.enabled
        ]
        if not enabled_modalities:
            return

        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose folder for planner visualisations",
            str(Path.home()),
        )
        if not out_dir:
            return

        fmt, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Export format",
            "Export all enabled modalities as:",
            ["PNG", "PDF"],
            0,
            False,
        )
        if not ok:
            return

        use_pdf = fmt == "PDF"
        output_paths: list[str] = []
        output_dir = Path(out_dir)

        for modality, cfg in enabled_modalities:
            rendered = self._build_export_composite(modality, cfg)
            safe_modality = modality.lower().replace(" ", "_").replace("-", "_")
            ext = "pdf" if use_pdf else "png"
            out_path = output_dir / self._default_export_name(f"{safe_modality}_plan", ext)

            if use_pdf:
                writer = QtGui.QPdfWriter(str(out_path))
                writer.setResolution(300)
                painter = QtGui.QPainter(writer)
                page_rect = writer.pageLayout().paintRectPixels(writer.resolution())
                scaled = rendered.scaled(
                    page_rect.size(),
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                x = page_rect.x() + (page_rect.width() - scaled.width()) // 2
                y = page_rect.y() + (page_rect.height() - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
                painter.end()
            else:
                rendered.save(str(out_path), "PNG")

            output_paths.append(str(out_path.name))

        QtWidgets.QMessageBox.information(
            self,
            "Planner export complete",
            "Exported files:\n" + "\n".join(output_paths),
        )

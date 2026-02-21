from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.maxrf_corrections.image_io import (
    normalize_feature,
    read_image,
    resize_to,
)


class ColorMap:
    """Colormap for intensity-to-colour mapping using linear interpolation between control points."""
    
    def __init__(self, stops: dict[float, str]):
        """
        Initialize colormap with control points.
        
        Args:
            stops: dict of position (0.0-1.0) -> hex colour string
                   Positions should span 0.0 to 1.0
        """
        self.stops = {}
        for pos, colour in stops.items():
            c = QtGui.QColor(colour)
            self.stops[pos] = np.array([c.redF(), c.greenF(), c.blueF()], dtype=np.float32)
    
    def apply(self, intensity: np.ndarray) -> np.ndarray:
        """
        Apply colormap to intensity array.
        
        Args:
            intensity: (H, W) array with values in [0, 1]
        
        Returns:
            (H, W, 3) RGB array with values in [0, 1]
        """
        h, w = intensity.shape
        result = np.zeros((h, w, 3), dtype=np.float32)
        
        # Get sorted positions
        sorted_positions = sorted(self.stops.keys())
        
        # Handle each range between control points
        for i in range(len(sorted_positions) - 1):
            pos1 = sorted_positions[i]
            pos2 = sorted_positions[i + 1]
            colour1 = self.stops[pos1]
            colour2 = self.stops[pos2]
            
            # Find pixels in this range
            mask = (intensity >= pos1) & (intensity < pos2)
            if not np.any(mask):
                continue
            
            # Linear interpolation between colours
            range_width = pos2 - pos1
            t = (intensity[mask] - pos1) / range_width if range_width > 0 else 0.0
            
            # Interpolate each channel
            for c_idx in range(3):
                result[mask, c_idx] = colour1[c_idx] * (1 - t) + colour2[c_idx] * t
        
        # Handle max value
        max_pos = sorted_positions[-1]
        mask = intensity >= max_pos
        result[mask] = self.stops[max_pos]
        
        return result


@dataclass
class OverlayMapEntry:
    """Entry for an element map in the Overlay tab."""
    element: str
    line_family: str
    path: Path  # Current path (raw or corrected based on using_raw)
    color: str  # User-selected colour (white or FC colour)
    raw_path: Path | None = None  # Raw version if exists
    corrected_path: Path | None = None  # Corrected version if exists
    using_corrected: bool = False  # Which source is selected
    fc_path: Path | None = None  # False-colour version if exists
    fc_profile: str = ""  # FC profile name


@dataclass
class EditLayer:
    name: str
    path: Path  # The white/uncoloured map (working map)
    color: str = "#ffffff"  # Default to white
    opacity: float = 1.0
    blend_mode: str = "Normal"
    visible: bool = True
    fc_path: Path | None = None  # False-colour version if it exists
    fc_colour: str | None = None  # Colour used in the FC for display preview
    fc_profile: str = ""  # Profile name used for the FC (e.g., "Default", "HKI/Fitz")
    raw_path: Path | None = None  # Raw data version if it exists
    using_raw: bool = False  # Whether to use raw or corrected version


class MaxrfEditTab(QtWidgets.QWidget):
    """MA-XRF editing tab with n-layer false-colour compositing."""

    BLEND_MODES = ["Normal", "Add", "Multiply", "Screen", "Subtract", "Difference"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        
        # Project session (set via set_session if working from project)
        self.session = None
        
        self.work_folder: Path | None = None
        self.map_entries: list[OverlayMapEntry] = []  # Element maps from manifest
        self.layers: list[EditLayer] = []  # Layers added to the stack
        self._norm_cache: dict[Path, np.ndarray] = {}
        self._is_syncing_layer_ui = False
        self._last_composite: np.ndarray | None = None
        self._project_root: Path | None = None  # Track project root for refreshing manifest
        self._preview_mode = "composite"  # "composite" or "single" (single element)
        self._preview_single_index = -1  # Which layer to show in single mode
        
        # Heatmap settings
        self._heatmap_enabled = False
        self._heatmap_auto_range = True
        self._heatmap_min = 0.0
        self._heatmap_max = 1.0
        
        # Default colormap: jet-like (black → blue → cyan → yellow → orange → red)
        self._colormap = ColorMap({
            0.00: "#000000",  # black
            0.10: "#00002a",  # very dark blue
            0.30: "#0033ff",  # blue
            0.45: "#00ffff",  # cyan
            0.65: "#ffff00",  # yellow
            0.82: "#ff7a00",  # orange
            1.00: "#d40000",  # red
        })

        self.presets_path = Path.home() / ".sciim_false_colour_presets.json"

        self._build_ui()
        self._refresh_presets()

    def _build_ui(self) -> None:
        root = QtWidgets.QHBoxLayout(self)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # Left: controls
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        folder_group = QtWidgets.QGroupBox("Element Maps")
        folder_layout = QtWidgets.QVBoxLayout(folder_group)
        row = QtWidgets.QHBoxLayout()
        self.btn_browse = QtWidgets.QPushButton("Select folder…")
        self.lbl_folder = QtWidgets.QLabel("No folder selected")
        self.lbl_folder.setWordWrap(True)
        row.addWidget(self.btn_browse)
        row.addWidget(self.lbl_folder, 1)
        folder_layout.addLayout(row)

        # Table for element maps
        self.table_maps = QtWidgets.QTableWidget()
        self.table_maps.setColumnCount(4)
        self.table_maps.setHorizontalHeaderLabels(["Element", "Line", "Source", "Colour"])
        self.table_maps.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table_maps.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table_maps.setMinimumHeight(150)
        self.table_maps.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table_maps.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table_maps.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_maps.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        folder_layout.addWidget(self.table_maps)

        maps_buttons = QtWidgets.QHBoxLayout()
        self.btn_add_layers = QtWidgets.QPushButton("Add selected as layers")
        maps_buttons.addWidget(self.btn_add_layers)
        folder_layout.addLayout(maps_buttons)

        left_layout.addWidget(folder_group)

        layer_group = QtWidgets.QGroupBox("Layer Stack")
        layer_layout = QtWidgets.QVBoxLayout(layer_group)
        self.list_layers = QtWidgets.QListWidget()
        self.list_layers.setMinimumHeight(220)
        layer_layout.addWidget(self.list_layers)

        layer_buttons = QtWidgets.QHBoxLayout()
        self.btn_move_up = QtWidgets.QPushButton("Move up")
        self.btn_move_down = QtWidgets.QPushButton("Move down")
        self.btn_remove_layer = QtWidgets.QPushButton("Remove")
        layer_buttons.addWidget(self.btn_move_up)
        layer_buttons.addWidget(self.btn_move_down)
        layer_buttons.addWidget(self.btn_remove_layer)
        layer_layout.addLayout(layer_buttons)

        left_layout.addWidget(layer_group)

        edit_group = QtWidgets.QGroupBox("Selected Layer")
        form = QtWidgets.QFormLayout(edit_group)
        self.chk_visible = QtWidgets.QCheckBox("Visible")

        color_row = QtWidgets.QHBoxLayout()
        self.btn_color = QtWidgets.QPushButton("Choose color…")
        self.lbl_color = QtWidgets.QLabel("#ffffff")
        self.lbl_color.setMinimumWidth(80)
        color_row.addWidget(self.btn_color)
        color_row.addWidget(self.lbl_color)
        color_row.addStretch(1)

        self.sl_opacity = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.sl_opacity.setRange(0, 100)
        self.sp_opacity = QtWidgets.QSpinBox()
        self.sp_opacity.setRange(0, 100)

        op_row = QtWidgets.QHBoxLayout()
        op_row.addWidget(self.sl_opacity, 1)
        op_row.addWidget(self.sp_opacity)

        self.combo_blend = QtWidgets.QComboBox()
        self.combo_blend.addItems(self.BLEND_MODES)

        form.addRow(self.chk_visible)
        form.addRow("Color", color_row)
        form.addRow("Opacity (%)", op_row)
        form.addRow("Blend mode", self.combo_blend)

        left_layout.addWidget(edit_group)

        presets_group = QtWidgets.QGroupBox("False-colour Presets")
        presets_layout = QtWidgets.QVBoxLayout(presets_group)

        preset_row = QtWidgets.QHBoxLayout()
        self.combo_presets = QtWidgets.QComboBox()
        self.btn_apply_preset = QtWidgets.QPushButton("Apply")
        preset_row.addWidget(self.combo_presets, 1)
        preset_row.addWidget(self.btn_apply_preset)
        presets_layout.addLayout(preset_row)

        preset_buttons = QtWidgets.QHBoxLayout()
        self.btn_save_preset = QtWidgets.QPushButton("Save current as preset…")
        self.btn_delete_preset = QtWidgets.QPushButton("Delete preset")
        preset_buttons.addWidget(self.btn_save_preset)
        preset_buttons.addWidget(self.btn_delete_preset)
        presets_layout.addLayout(preset_buttons)

        left_layout.addWidget(presets_group)

        export_row = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Export composite…")
        export_row.addWidget(self.btn_export)
        left_layout.addLayout(export_row)

        left_layout.addStretch(1)

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left)

        splitter.addWidget(left_scroll)

        # Right: preview
        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        
        # Preview mode toggle
        mode_row = QtWidgets.QHBoxLayout()
        self.btn_preview_composite = QtWidgets.QPushButton("Composite")
        self.btn_preview_composite.setCheckable(True)
        self.btn_preview_composite.setChecked(True)
        self.btn_preview_single = QtWidgets.QPushButton("Single Element")
        self.btn_preview_single.setCheckable(True)
        mode_row.addWidget(QtWidgets.QLabel("Preview:"))
        mode_row.addWidget(self.btn_preview_composite)
        mode_row.addWidget(self.btn_preview_single)
        mode_row.addStretch(1)
        right_layout.addLayout(mode_row)
        
        # Heatmap controls
        heatmap_row = QtWidgets.QHBoxLayout()
        self.btn_heatmap = QtWidgets.QPushButton("Heatmap")
        self.btn_heatmap.setCheckable(True)
        self.btn_heatmap.setChecked(False)
        heatmap_row.addWidget(QtWidgets.QLabel("Render:"))
        heatmap_row.addWidget(self.btn_heatmap)
        heatmap_row.addStretch(1)
        right_layout.addLayout(heatmap_row)
        
        # Heatmap range controls
        heatmap_range_group = QtWidgets.QGroupBox("Heatmap Range")
        heatmap_range_layout = QtWidgets.QFormLayout(heatmap_range_group)
        
        auto_range_row = QtWidgets.QHBoxLayout()
        self.chk_heatmap_auto = QtWidgets.QCheckBox("Auto-range (1-99 percentile)")
        self.chk_heatmap_auto.setChecked(True)
        auto_range_row.addWidget(self.chk_heatmap_auto)
        auto_range_row.addStretch(1)
        heatmap_range_layout.addRow(auto_range_row)
        
        min_max_row = QtWidgets.QHBoxLayout()
        self.sp_heatmap_min = QtWidgets.QDoubleSpinBox()
        self.sp_heatmap_min.setRange(0.0, 1.0)
        self.sp_heatmap_min.setSingleStep(0.01)
        self.sp_heatmap_min.setValue(0.0)
        self.sp_heatmap_min.setEnabled(False)
        
        self.sp_heatmap_max = QtWidgets.QDoubleSpinBox()
        self.sp_heatmap_max.setRange(0.0, 1.0)
        self.sp_heatmap_max.setSingleStep(0.01)
        self.sp_heatmap_max.setValue(1.0)
        self.sp_heatmap_max.setEnabled(False)
        
        min_max_row.addWidget(QtWidgets.QLabel("Min:"))
        min_max_row.addWidget(self.sp_heatmap_min, 1)
        min_max_row.addWidget(QtWidgets.QLabel("Max:"))
        min_max_row.addWidget(self.sp_heatmap_max, 1)
        heatmap_range_layout.addRow(min_max_row)
        
        right_layout.addWidget(heatmap_range_group)
        
        self.lbl_preview = QtWidgets.QLabel("Load element maps and add layers to preview")
        self.lbl_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setMinimumSize(320, 240)
        self.lbl_preview.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.lbl_preview.setStyleSheet("border:1px solid #999; background:#111; color:#ddd;")
        right_layout.addWidget(self.lbl_preview, 1)
        splitter.addWidget(right)

        splitter.setHandleWidth(8)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 980])

        self._bind_signals()

    def _bind_signals(self) -> None:
        self.btn_browse.clicked.connect(self.browse_folder)
        self.btn_add_layers.clicked.connect(self.add_selected_layers)

        # Element Maps table selection
        self.table_maps.itemSelectionChanged.connect(self._on_element_map_selected)
        
        self.list_layers.currentRowChanged.connect(self._sync_selected_layer_to_ui)
        self.btn_move_up.clicked.connect(self.move_layer_up)
        self.btn_move_down.clicked.connect(self.move_layer_down)
        self.btn_remove_layer.clicked.connect(self.remove_selected_layer)

        self.chk_visible.stateChanged.connect(self._apply_selected_layer_ui)
        self.btn_color.clicked.connect(self.pick_layer_color)
        self.sl_opacity.valueChanged.connect(self._sync_opacity_slider)
        self.sp_opacity.valueChanged.connect(self._sync_opacity_spin)
        self.combo_blend.currentIndexChanged.connect(self._apply_selected_layer_ui)

        self.btn_save_preset.clicked.connect(self.save_preset)
        self.btn_apply_preset.clicked.connect(self.apply_preset)
        self.btn_delete_preset.clicked.connect(self.delete_preset)

        self.btn_preview_composite.clicked.connect(self._set_preview_composite)
        self.btn_preview_single.clicked.connect(self._set_preview_single)

        # Heatmap controls
        self.btn_heatmap.clicked.connect(self._toggle_heatmap)
        self.chk_heatmap_auto.stateChanged.connect(self._on_heatmap_auto_changed)
        self.sp_heatmap_min.valueChanged.connect(self._on_heatmap_range_changed)
        self.sp_heatmap_max.valueChanged.connect(self._on_heatmap_range_changed)

        self.btn_export.clicked.connect(self.export_composite)

    def browse_folder(self) -> None:
        start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select element map folder", start_dir)
        if not folder:
            return

        selected = Path(folder)
        exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
        files = sorted([p for p in selected.iterdir() if p.is_file() and p.suffix.lower() in exts])

        if not files:
            QtWidgets.QMessageBox.warning(
                self,
                "No images found",
                f"The selected folder '{selected.name}' contains no supported image files."
            )
            self.work_folder = selected
            self.lbl_folder.setText(selected.name)
            self.map_files = []
            self.list_maps.clear()
            return

        self.work_folder = selected
        self.map_files = files
        self.lbl_folder.setText(selected.name)

        self.list_maps.clear()
        for p in files:
            self.list_maps.addItem(p.name)

    def add_selected_layers(self) -> None:
        """Add selected element maps from the table to the layer stack."""
        selected_rows = self.table_maps.selectionModel().selectedRows()
        if not selected_rows:
            return

        existing = {layer.path for layer in self.layers}

        for row in sorted([r.row() for r in selected_rows]):
            if 0 <= row < len(self.map_entries):
                entry = self.map_entries[row]
                
                # Skip if already in layers
                if entry.path in existing:
                    continue
                
                # Create a layer from this entry
                layer = EditLayer(
                    name=f"{entry.element} {entry.line_family}",
                    path=entry.path,
                    color=entry.color,
                    opacity=1.0,
                    blend_mode="Normal",
                    visible=True,
                    fc_path=entry.fc_path,
                    fc_colour=entry.color,  # Use the entry's colour
                    fc_profile=entry.fc_profile,
                    raw_path=entry.raw_path,
                    using_raw=not entry.using_corrected,  # True if using raw
                )
                self.layers.append(layer)
                existing.add(entry.path)

        self._refresh_layer_list()
        if self.layers:
            self.list_layers.setCurrentRow(len(self.layers) - 1)
        self._recompute_preview()

    def _refresh_layer_list(self) -> None:
        self.list_layers.clear()
        for layer in self.layers:
            fc_indicator = " [FC]" if layer.fc_path else ""
            self.list_layers.addItem(
                f"{'✓' if layer.visible else '✗'} {layer.name} | {layer.blend_mode} | {int(layer.opacity * 100)}%{fc_indicator}"
            )

    def _current_layer_index(self) -> int:
        idx = self.list_layers.currentRow()
        if idx < 0 or idx >= len(self.layers):
            return -1
        return idx

    def _sync_selected_layer_to_ui(self) -> None:
        idx = self._current_layer_index()
        self._is_syncing_layer_ui = True
        try:
            enabled = idx >= 0
            for widget in [self.chk_visible, self.btn_color, self.sl_opacity, self.sp_opacity, self.combo_blend]:
                widget.setEnabled(enabled)
            if idx < 0:
                self.lbl_color.setText("-")
                # No layer selected, check if Element Maps has selection
                selected_rows = self.table_maps.selectionModel().selectedRows()
                if not selected_rows:
                    # Nothing selected anywhere
                    self._last_composite = None
                    self.lbl_preview.setText("Select an element map or add layers to preview")
                    self.lbl_preview.setPixmap(QtGui.QPixmap())
                return

            # A layer was selected - clear Element Maps selection to show Layer Stack preview
            self.table_maps.selectionModel().blockSignals(True)
            self.table_maps.clearSelection()
            self.table_maps.selectionModel().blockSignals(False)

            layer = self.layers[idx]
            self.chk_visible.setChecked(layer.visible)
            self.sl_opacity.setValue(int(round(layer.opacity * 100)))
            self.sp_opacity.setValue(int(round(layer.opacity * 100)))
            self.combo_blend.setCurrentText(layer.blend_mode)
            self.lbl_color.setText(layer.color)
            self.lbl_color.setStyleSheet(f"color:{layer.color}; font-weight:600;")
            
            # Show Layer Stack preview based on mode
            self._preview_single_index = idx  # Track selected layer for single element mode
            self._recompute_preview()
        finally:
            self._is_syncing_layer_ui = False

    def _on_element_map_selected(self) -> None:
        """Handle Element Maps table selection - show selected element in preview."""
        selected_rows = self.table_maps.selectionModel().selectedRows()
        
        # If a row in Element Maps is selected, show that element
        if selected_rows:
            row = selected_rows[0].row()  # Get the first selected row
            if 0 <= row < len(self.map_entries):
                entry = self.map_entries[row]
                # Show this element's map with its colour
                self._preview_element_map(entry)
                return
        
        # If no Element Maps selection, show layer stack preview instead
        # Fallback to the layer preview
        idx = self._current_layer_index()
        if idx < 0:
            # Nothing selected anywhere
            self._last_composite = None
            self.lbl_preview.setText("Select an element map or add layers to preview")
            self.lbl_preview.setPixmap(QtGui.QPixmap())
        else:
            # Layer is selected, show based on preview mode
            self._recompute_preview()

    def _preview_element_map(self, entry: OverlayMapEntry) -> None:
        """Preview a single element map from the Element Maps table."""
        try:
            # Load the map image
            img = self._load_norm_image(entry.path)
            h, w = img.shape[:2]
            
            # Apply the element's colour
            color = self._hex_to_rgb(entry.color)
            coloured = img[..., None] * color[None, None, :]
            
            # Store for rendering
            self._last_composite = np.clip(coloured, 0.0, 1.0)
            self._render_preview()
        except Exception as e:
            self.lbl_preview.setText(f"Error loading map: {str(e)}")
            self.lbl_preview.setPixmap(QtGui.QPixmap())

    def _sync_opacity_slider(self, val: int) -> None:
        if self._is_syncing_layer_ui:
            return
        self.sp_opacity.blockSignals(True)
        self.sp_opacity.setValue(val)
        self.sp_opacity.blockSignals(False)
        self._apply_selected_layer_ui()

    def _sync_opacity_spin(self, val: int) -> None:
        if self._is_syncing_layer_ui:
            return
        self.sl_opacity.blockSignals(True)
        self.sl_opacity.setValue(val)
        self.sl_opacity.blockSignals(False)
        self._apply_selected_layer_ui()

    def _apply_selected_layer_ui(self) -> None:
        if self._is_syncing_layer_ui:
            return
        idx = self._current_layer_index()
        if idx < 0:
            return

        layer = self.layers[idx]
        layer.visible = self.chk_visible.isChecked()
        layer.opacity = self.sp_opacity.value() / 100.0
        layer.blend_mode = self.combo_blend.currentText()

        self._refresh_layer_list()
        self.list_layers.setCurrentRow(idx)
        self._recompute_preview()

    def _set_preview_composite(self) -> None:
        """Switch to composite preview mode showing all visible layers blended."""
        self._preview_mode = "composite"
        self.btn_preview_composite.setChecked(True)
        self.btn_preview_single.setChecked(False)
        self._recompute_preview()

    def _set_preview_single(self) -> None:
        """Switch to single element preview mode showing only selected layer."""
        self._preview_mode = "single"
        self.btn_preview_composite.setChecked(False)
        self.btn_preview_single.setChecked(True)
        idx = self._current_layer_index()
        self._preview_single_index = idx
        self._recompute_preview()

    def _toggle_heatmap(self) -> None:
        """Toggle heatmap rendering on/off."""
        self._heatmap_enabled = self.btn_heatmap.isChecked()
        self._recompute_preview()

    def _on_heatmap_auto_changed(self) -> None:
        """Handle auto-range checkbox change."""
        self._heatmap_auto_range = self.chk_heatmap_auto.isChecked()
        self.sp_heatmap_min.setEnabled(not self._heatmap_auto_range)
        self.sp_heatmap_max.setEnabled(not self._heatmap_auto_range)
        
        # If enabling auto-range, immediately compute percentiles
        if self._heatmap_auto_range and self._last_composite is not None:
            self._compute_heatmap_range()
        
        self._recompute_preview()

    def _on_heatmap_range_changed(self) -> None:
        """Handle manual min/max changes."""
        if not self._heatmap_auto_range:
            self._heatmap_min = self.sp_heatmap_min.value()
            self._heatmap_max = self.sp_heatmap_max.value()
            self._recompute_preview()

    def _compute_heatmap_range(self) -> None:
        """Compute heatmap range using percentile clipping (1-99)."""
        if self._last_composite is None:
            return
        
        # Get intensity values (assuming composite is RGB, use luminance or first channel)
        if len(self._last_composite.shape) == 3:
            intensity = np.mean(self._last_composite, axis=2)
        else:
            intensity = self._last_composite
        
        # Remove NaN values
        valid = intensity[~np.isnan(intensity)]
        if len(valid) == 0:
            self._heatmap_min = 0.0
            self._heatmap_max = 1.0
            return
        
        # Use 1st and 99th percentiles
        p1 = np.percentile(valid, 1)
        p99 = np.percentile(valid, 99)
        
        self._heatmap_min = float(p1)
        self._heatmap_max = float(p99) if p99 > p1 else p1 + 0.1
        
        # Update spinboxes without triggering changes
        self.sp_heatmap_min.blockSignals(True)
        self.sp_heatmap_max.blockSignals(True)
        self.sp_heatmap_min.setValue(self._heatmap_min)
        self.sp_heatmap_max.setValue(self._heatmap_max)
        self.sp_heatmap_min.blockSignals(False)
        self.sp_heatmap_max.blockSignals(False)

    def pick_layer_color(self) -> None:
        idx = self._current_layer_index()
        if idx < 0:
            return
        current = QtGui.QColor(self.layers[idx].color)
        chosen = QtWidgets.QColorDialog.getColor(current, self, "Select false colour")
        if not chosen.isValid():
            return

        self.layers[idx].color = chosen.name()
        self._sync_selected_layer_to_ui()
        self._refresh_layer_list()
        self.list_layers.setCurrentRow(idx)
        self._recompute_preview()

    def move_layer_up(self) -> None:
        idx = self._current_layer_index()
        if idx <= 0:
            return
        self.layers[idx - 1], self.layers[idx] = self.layers[idx], self.layers[idx - 1]
        self._refresh_layer_list()
        self.list_layers.setCurrentRow(idx - 1)
        self._recompute_preview()

    def move_layer_down(self) -> None:
        idx = self._current_layer_index()
        if idx < 0 or idx >= len(self.layers) - 1:
            return
        self.layers[idx + 1], self.layers[idx] = self.layers[idx], self.layers[idx + 1]
        self._refresh_layer_list()
        self.list_layers.setCurrentRow(idx + 1)
        self._recompute_preview()

    def remove_selected_layer(self) -> None:
        idx = self._current_layer_index()
        if idx < 0:
            return
        del self.layers[idx]
        self._refresh_layer_list()
        if self.layers:
            self.list_layers.setCurrentRow(min(idx, len(self.layers) - 1))
        self._recompute_preview()

    def _load_norm_image(self, path: Path) -> np.ndarray:
        cached = self._norm_cache.get(path)
        if cached is not None:
            return cached
        arr, _ = read_image(str(path))
        norm = normalize_feature(arr)
        self._norm_cache[path] = norm
        return norm

    def _hex_to_rgb(self, color_hex: str) -> np.ndarray:
        c = QtGui.QColor(color_hex)
        return np.array([c.redF(), c.greenF(), c.blueF()], dtype=np.float32)

    def _blend(self, dst: np.ndarray, src: np.ndarray, alpha: float, mode: str) -> np.ndarray:
        if mode == "Normal":
            return (1.0 - alpha) * dst + alpha * src
        if mode == "Add":
            return np.clip(dst + alpha * src, 0.0, 1.0)
        if mode == "Multiply":
            blended = dst * src
            return (1.0 - alpha) * dst + alpha * blended
        if mode == "Screen":
            blended = 1.0 - (1.0 - dst) * (1.0 - src)
            return (1.0 - alpha) * dst + alpha * blended
        if mode == "Subtract":
            return np.clip(dst - alpha * src, 0.0, 1.0)
        if mode == "Difference":
            blended = np.abs(dst - src)
            return (1.0 - alpha) * dst + alpha * blended
        return (1.0 - alpha) * dst + alpha * src

    def _recompute_preview(self) -> None:
        # Handle single element preview mode
        if self._preview_mode == "single":
            if 0 <= self._preview_single_index < len(self.layers):
                layer = self.layers[self._preview_single_index]
                if not layer.visible:
                    self._last_composite = None
                    self.lbl_preview.setText("Selected layer is hidden")
                    self.lbl_preview.setPixmap(QtGui.QPixmap())
                    return
                
                # Always use neutral (raw/corrected) image, even if FC exists
                # This allows colour editing and supports corrected+FC combinations
                working_path = layer.raw_path if (layer.using_raw and layer.raw_path) else layer.path
                layer_img = self._load_norm_image(working_path)
                h, w = layer_img.shape[:2]
                
                # Always colorize using the layer's colour (from manifest or user-selected)
                color = self._hex_to_rgb(layer.color)
                src_rgb = layer_img[..., None] * color[None, None, :]
                
                # Apply opacity
                canvas = src_rgb * layer.opacity
                self._last_composite = np.clip(canvas, 0.0, 1.0)
                
                # Compute auto-range for heatmap if needed
                if self._heatmap_enabled and self._heatmap_auto_range:
                    self._compute_heatmap_range()
                
                self._render_preview()
                return
            else:
                self._last_composite = None
                self.lbl_preview.setText("No layer selected")
                self.lbl_preview.setPixmap(QtGui.QPixmap())
                return
        
        # Composite preview mode (default)
        visible_layers = [layer for layer in self.layers if layer.visible]
        if not visible_layers:
            self._last_composite = None
            self.lbl_preview.setText("Add visible layers to preview")
            self.lbl_preview.setPixmap(QtGui.QPixmap())
            return

        # Determine the path to use for the first layer based on using_raw flag
        first_layer = visible_layers[0]
        first_path = first_layer.raw_path if (first_layer.using_raw and first_layer.raw_path) else first_layer.path
        
        # Always use neutral (raw/corrected) image for consistent handling
        base = self._load_norm_image(first_path)
        h, w = base.shape[:2]
        canvas = np.zeros((h, w, 3), dtype=np.float32)

        # Render layers in reverse order so top layer (visually) renders on top (compositionally)
        for layer in reversed(visible_layers):
            # Always use neutral (raw/corrected) path, ignoring FC file
            # This allows colour editing even when false-colouring exists
            working_path = layer.raw_path if (layer.using_raw and layer.raw_path) else layer.path
            layer_img = self._load_norm_image(working_path)
            if layer_img.shape != (h, w):
                layer_img = resize_to(layer_img, (h, w))
            
            # Always colorize using the layer's colour (from manifest or user-selected)
            # This works for both FC and non-FC elements
            color = self._hex_to_rgb(layer.color)
            src_rgb = layer_img[..., None] * color[None, None, :]
            
            canvas = self._blend(canvas, src_rgb, layer.opacity, layer.blend_mode)

        self._last_composite = np.clip(canvas, 0.0, 1.0)
        
        # Compute auto-range for heatmap if needed
        if self._heatmap_enabled and self._heatmap_auto_range:
            self._compute_heatmap_range()
        
        self._render_preview()

    def _render_preview(self) -> None:
        if self._last_composite is None:
            return
        
        # Apply heatmap if enabled
        if self._heatmap_enabled:
            # Convert composite to intensity
            if len(self._last_composite.shape) == 3 and self._last_composite.shape[2] == 3:
                intensity = np.mean(self._last_composite, axis=2)
            else:
                intensity = self._last_composite if len(self._last_composite.shape) == 2 else self._last_composite[:, :, 0]
            
            # Normalize to [0, 1] range based on heatmap_min/max
            range_val = self._heatmap_max - self._heatmap_min
            if range_val > 0:
                normalized = np.clip((intensity - self._heatmap_min) / range_val, 0.0, 1.0)
            else:
                normalized = np.ones_like(intensity) * 0.5  # Default to mid-range if min == max
            
            # Apply colormap
            composite = self._colormap.apply(normalized)
        else:
            composite = self._last_composite
        
        img = (composite * 255).astype(np.uint8)
        h, w, _ = img.shape
        qimg = QtGui.QImage(img.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
        pixmap = QtGui.QPixmap.fromImage(qimg)
        self.lbl_preview.setPixmap(
            pixmap.scaled(
                self.lbl_preview.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Refresh from manifest when tab becomes visible (to pick up new corrections/FC)."""
        super().showEvent(event)
        if self._project_root:
            self._load_from_manifest(self._project_root)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._last_composite is not None:
            self._render_preview()

    def _read_presets(self) -> dict[str, list[dict[str, object]]]:
        if not self.presets_path.exists():
            return {}
        try:
            data = json.loads(self.presets_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _write_presets(self, presets: dict[str, list[dict[str, object]]]) -> None:
        self.presets_path.write_text(json.dumps(presets, indent=2), encoding="utf-8")

    def _refresh_presets(self) -> None:
        current = self.combo_presets.currentText()
        presets = self._read_presets()
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        self.combo_presets.addItems(sorted(presets.keys()))
        if current and current in presets:
            self.combo_presets.setCurrentText(current)
        self.combo_presets.blockSignals(False)

    def save_preset(self) -> None:
        if not self.layers:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        preset_name = name.strip()

        payload = []
        for layer in self.layers:
            payload.append(
                {
                    "name": layer.name,
                    "color": layer.color,
                    "opacity": layer.opacity,
                    "blend_mode": layer.blend_mode,
                    "visible": layer.visible,
                }
            )

        presets = self._read_presets()
        presets[preset_name] = payload
        self._write_presets(presets)
        self._refresh_presets()
        self.combo_presets.setCurrentText(preset_name)

    def apply_preset(self) -> None:
        preset_name = self.combo_presets.currentText()
        if not preset_name or not self.layers:
            return

        presets = self._read_presets()
        config = presets.get(preset_name)
        if not isinstance(config, list):
            return

        by_name = {entry.get("name"): entry for entry in config if isinstance(entry, dict)}
        for layer in self.layers:
            entry = by_name.get(layer.name)
            if not entry:
                continue
            layer.color = str(entry.get("color", layer.color))
            layer.opacity = float(entry.get("opacity", layer.opacity))
            layer.blend_mode = str(entry.get("blend_mode", layer.blend_mode))
            layer.visible = bool(entry.get("visible", layer.visible))

        self._refresh_layer_list()
        self._sync_selected_layer_to_ui()
        self._recompute_preview()

    def delete_preset(self) -> None:
        preset_name = self.combo_presets.currentText()
        if not preset_name:
            return
        presets = self._read_presets()
        if preset_name not in presets:
            return
        del presets[preset_name]
        self._write_presets(presets)
        self._refresh_presets()

    def set_session(self, session) -> None:
        """Set the project session and auto-load maps from manifest if available."""
        self.session = session
        
        # If project has MA-XRF workspace, load from manifest
        if session and session.maxrf_pipeline.project_root:
            project_root = Path(session.maxrf_pipeline.project_root)
            self._project_root = project_root  # Store for refresh on tab show
            self.lbl_folder.setText(f"Project: {project_root.name}")
            self.btn_browse.setEnabled(False)
            self.btn_browse.setToolTip("(Folder locked: using project workspace)")
            
            # Load from manifest to auto-populate with all elements
            self._load_from_manifest(project_root)
            return
        
        # No project: enable browse button
        self.btn_browse.setEnabled(True)
        self.btn_browse.setToolTip("")
        self.work_folder = None
        self.lbl_folder.setText("No folder selected")
        self._project_root = None
        self.map_entries.clear()
        self.layers.clear()
        self.table_maps.setRowCount(0)
        self.list_layers.clear()

    def _load_from_manifest(self, project_root: Path) -> None:
        """Load element maps from manifest into the Element Maps table.
        
        Populates table with:
        - Element and Line family
        - Source selector (raw/corrected toggle when both available)
        - Colour (white if no FC, or palette colour if FC exists)
        """
        manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
        if not manifest_path.exists():
            self.map_entries = []
            self.table_maps.setRowCount(0)
            return

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            map_registry = manifest_data.get("map_registry", {})
        except Exception:
            self.map_entries = []
            self.table_maps.setRowCount(0)
            return

        # Build a map of element+line_family -> available file paths
        raw_data = project_root / "raw_data"
        corrected_maps = project_root / "corrected_maps"
        
        element_entries: dict[tuple[str, str], dict] = {}
        
        for map_id, record_dict in map_registry.items():
            element = record_dict.get("element", "")
            line_family = record_dict.get("line_family", "")
            filename = record_dict.get("filename", "")
            
            # Skip if element is "None" or empty (non-elemental maps)
            if not element or element == "None":
                continue
            
            key = (element, line_family)
            
            if key not in element_entries:
                element_entries[key] = {
                    "element": element,
                    "line_family": line_family,
                    "raw": None,
                    "corrected": None,
                    "map_id": map_id,
                }
            
            # Check for raw version
            if raw_data.exists():
                raw_path = raw_data / filename
                if raw_path.exists():
                    element_entries[key]["raw"] = raw_path
            
            # Check for corrected version
            if corrected_maps.exists():
                stem = Path(filename).stem
                ext = Path(filename).suffix
                corrected_filename = f"{stem}_corrected{ext}"
                corrected_path = corrected_maps / corrected_filename
                if corrected_path.exists():
                    element_entries[key]["corrected"] = corrected_path

        # Build entries: prefer corrected as default, but track both versions
        self.map_entries = []
        palette = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff"]
        
        for idx, ((element, line_family), info) in enumerate(sorted(element_entries.items())):
            corrected_path = info["corrected"]
            raw_path = info["raw"]
            
            # Determine default path and source
            if corrected_path:
                default_path = corrected_path
                using_corrected = True
            elif raw_path:
                default_path = raw_path
                using_corrected = False
            else:
                continue  # Skip if neither exists
            
            # Get FC variant info to determine colour
            fc_path, fc_colour = self._get_fc_variant_info(default_path)
            
            # Determine colour: use FC colour if available (even if FC file doesn't exist)
            # The colour code in the manifest is what matters - it indicates false-colouring was applied
            if fc_colour:
                # Use the colour code from the false-colouring
                colour = fc_colour
            else:
                colour = "#ffffff"  # White if no false-colouring applied
            
            entry = OverlayMapEntry(
                element=element,
                line_family=line_family,
                path=default_path,
                color=colour,
                raw_path=raw_path,
                corrected_path=corrected_path,
                using_corrected=using_corrected,
                fc_path=fc_path,
                fc_profile="",  # No longer storing profile name
            )
            self.map_entries.append(entry)

        # Refresh the table display
        self._refresh_map_table()

    def _refresh_map_table(self) -> None:
        """Refresh the Element Maps table display."""
        self.table_maps.setRowCount(len(self.map_entries))
        
        for row, entry in enumerate(self.map_entries):
            # Column 0: Element
            element_item = QtWidgets.QTableWidgetItem(entry.element)
            element_item.setFlags(element_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.table_maps.setItem(row, 0, element_item)
            
            # Column 1: Line Family
            line_item = QtWidgets.QTableWidgetItem(entry.line_family)
            line_item.setFlags(line_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.table_maps.setItem(row, 1, line_item)
            
            # Column 2: Source selector (Raw/Corrected toggle)
            source_widget = QtWidgets.QWidget()
            source_layout = QtWidgets.QHBoxLayout(source_widget)
            source_layout.setContentsMargins(0, 0, 0, 0)
            
            if entry.raw_path and entry.corrected_path:
                # Both versions available - show toggle button
                source_btn = QtWidgets.QPushButton("Corrected" if entry.using_corrected else "Raw")
                source_btn.setMaximumWidth(90)
                source_btn.clicked.connect(lambda _checked=False, r=row: self._toggle_map_source(r))
                source_layout.addWidget(source_btn)
            else:
                # Only one version available - show label
                source_label = QtWidgets.QLabel("Corrected" if entry.using_corrected else "Raw")
                source_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                source_layout.addWidget(source_label)
            
            self.table_maps.setCellWidget(row, 2, source_widget)
            
            # Column 3: Colour button
            colour_btn = QtWidgets.QPushButton()
            colour_btn.setStyleSheet(f"background-color: {entry.color}; color: #111; font-weight: 600;")
            colour_btn.setText(entry.color)
            colour_btn.setMaximumWidth(90)
            colour_btn.clicked.connect(lambda _checked=False, r=row: self._choose_map_colour(r))
            self.table_maps.setCellWidget(row, 3, colour_btn)

    def _toggle_map_source(self, row: int) -> None:
        """Toggle the source (raw/corrected) for a map entry and update preview."""
        if 0 <= row < len(self.map_entries):
            entry = self.map_entries[row]
            if entry.raw_path and entry.corrected_path:
                entry.using_corrected = not entry.using_corrected
                entry.path = entry.corrected_path if entry.using_corrected else entry.raw_path
                self._refresh_map_table()
                
                # Update preview if this entry is currently selected
                selected_rows = self.table_maps.selectionModel().selectedRows()
                if selected_rows and selected_rows[0].row() == row:
                    self._preview_element_map(entry)

    def _choose_map_colour(self, row: int) -> None:
        """Choose colour for a map entry."""
        if 0 <= row < len(self.map_entries):
            entry = self.map_entries[row]
            current = QtGui.QColor(entry.color)
            chosen = QtWidgets.QColorDialog.getColor(current, self, "Select colour")
            if chosen.isValid():
                entry.color = chosen.name()
                self._refresh_map_table()

    def _get_fc_variant_info(self, map_path: Path) -> tuple[Path | None, str]:
        """Get FC variant colour code from manifest if false-colouring was applied.
        
        Returns (fc_path, colour_code) where:
        - fc_path is the path to FC file if it exists, else None
        - colour_code is the hex colour from the manifest (returned even if file doesn't exist yet)
        
        The colour code is what matters - it tells us this element was false-coloured,
        regardless of whether the FC file has been generated or is available.
        """
        if not self.session or not self.session.maxrf_pipeline.project_root:
            return None, ""
        
        try:
            project_root = Path(self.session.maxrf_pipeline.project_root)
            manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
            
            if not manifest_path.exists():
                return None, ""
            
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            map_registry = manifest_data.get("map_registry", {})
            
            # Extract base map name: remove "_corrected" suffix if present
            map_stem = map_path.stem
            if map_stem.endswith("_corrected"):
                map_stem = map_stem.replace("_corrected", "")
            
            map_id = map_stem
            if map_id not in map_registry:
                return None, ""
            
            record = map_registry[map_id]
            variants = record.get("false_colour_variants", [])
            
            if not variants:
                return None, ""
            
            # Get the colour code from manifest (first variant is now a colour code like "#ff4ba8")
            colour_code = variants[0] if variants else ""
            
            # Try to find the actual FC file, but don't require it to exist
            # The colour code is what matters - it proves false-colouring was applied
            fc_filename = f"{map_id}_fc{map_path.suffix}"
            fc_path = project_root / "false_coloured_maps" / fc_filename
            
            return (fc_path if fc_path.exists() else None), colour_code
        except Exception:
            return None, ""

    def _get_raw_and_corrected_paths(self, map_name: str) -> tuple[Path | None, Path | None]:
        """Get both raw and corrected versions of a map if they exist.
        
        Returns (raw_path, corrected_path) or (None, None).
        """
        if not self.session or not self.session.maxrf_pipeline.project_root:
            return None, None
        
        try:
            project_root = Path(self.session.maxrf_pipeline.project_root)
            raw_data_path = project_root / "raw_data"
            corrected_path = project_root / "corrected_maps"
            
            exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
            raw_file = None
            corrected_file = None
            
            # Look for raw version
            for ext in exts:
                candidate = raw_data_path / f"{map_name}{ext}"
                if candidate.exists():
                    raw_file = candidate
                    break
            
            # Look for corrected version
            for ext in exts:
                candidate = corrected_path / f"{map_name}_corrected{ext}"
                if candidate.exists():
                    corrected_file = candidate
                    break
            
            return raw_file, corrected_file
        except Exception:
            return None, None
    
    def _get_fc_colour_from_manifest(self, map_name: str) -> str | None:
        """Get the colour used for FC from the false colour profile.
        
        Returns hex color string or None if not found.
        """
        if not self.session or not self.session.maxrf_pipeline.project_root:
            return None
        
        try:
            # This would require reading the false colour profile - for now, return None
            # In a full implementation, we'd read from the colour profiles
            return None
        except Exception:
            return None

    def _compute_export_composite(self) -> np.ndarray | None:
        """Compute composite using white (uncoloured) maps for export.
        
        Uses actual layer colors set by user, not FC colours.
        Respects the using_raw flag for each layer.
        """
        visible_layers = [layer for layer in self.layers if layer.visible]
        if not visible_layers:
            return None

        # Determine which path to use for the first layer
        first_layer = visible_layers[0]
        first_path = first_layer.raw_path if (first_layer.using_raw and first_layer.raw_path) else first_layer.path
        
        # Always use white map (layer.path or layer.raw_path) for export, never FC
        base = self._load_norm_image(first_path)
        h, w = base.shape[:2]
        canvas = np.zeros((h, w, 3), dtype=np.float32)

        # Render layers in reverse order so top layer (visually) renders on top (compositionally)
        for layer in reversed(visible_layers):
            # Determine which source to export (raw or corrected)
            export_path = layer.raw_path if (layer.using_raw and layer.raw_path) else layer.path
            layer_img = self._load_norm_image(export_path)  # Use selected source
            if layer_img.shape != (h, w):
                layer_img = resize_to(layer_img, (h, w))
            color = self._hex_to_rgb(layer.color)
            src_rgb = layer_img[..., None] * color[None, None, :]
            canvas = self._blend(canvas, src_rgb, layer.opacity, layer.blend_mode)

        return np.clip(canvas, 0.0, 1.0)

    def export_composite(self) -> None:
        # Compute export composite using white maps
        export_composite = self._compute_export_composite()
        if export_composite is None:
            return
        
        # Apply heatmap if enabled
        if self._heatmap_enabled:
            intensity = np.mean(export_composite, axis=2)
            range_val = self._heatmap_max - self._heatmap_min
            if range_val > 0:
                normalized = np.clip(
                    (intensity - self._heatmap_min) / range_val,
                    0.0,
                    1.0,
                )
            else:
                normalized = np.ones_like(intensity) * 0.5  # Default to mid-range if min == max
            export_composite = self._colormap.apply(normalized)
            heatmap_suffix = "_heatmap"
        else:
            heatmap_suffix = ""
        
        # Auto-export to project folder if in project mode
        if self.session and self.session.maxrf_pipeline.project_root:
            overlays_folder = Path(self.session.maxrf_pipeline.project_root) / "overlays"
            overlays_folder.mkdir(parents=True, exist_ok=True)
            
            # Ask for custom name in project mode
            name, ok = QtWidgets.QInputDialog.getText(
                self,
                "Save Overlay Composite",
                "Composite name:",
                QtWidgets.QLineEdit.EchoMode.Normal,
                "overlay_composite"
            )
            if not ok or not name:
                return
            
            # Use PNG by default in project mode, add heatmap suffix if enabled
            out_path = overlays_folder / f"{name}{heatmap_suffix}.png"
        else:
            # Normal file dialog for standalone mode
            start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
            default_name = f"maxrf_composite{heatmap_suffix}.png"
            path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export composite",
                str(Path(start_dir) / default_name),
                "PNG (*.png);;TIFF (*.tif *.tiff)",
            )
            if not path:
                return

            out_path = Path(path)
            # Insert heatmap suffix before extension if not already present
            if heatmap_suffix and heatmap_suffix not in out_path.stem:
                out_path = out_path.with_stem(f"{out_path.stem}{heatmap_suffix}")
            
            if "TIFF" in selected_filter and out_path.suffix.lower() not in {".tif", ".tiff"}:
                out_path = out_path.with_suffix(".tif")
            if "PNG" in selected_filter and out_path.suffix.lower() != ".png":
                out_path = out_path.with_suffix(".png")

        rgb_u8 = (np.clip(export_composite, 0.0, 1.0) * 255).astype(np.uint8)
        try:
            if out_path.suffix.lower() in {".tif", ".tiff"}:
                import tifffile as tiff

                tiff.imwrite(str(out_path), rgb_u8)
            else:
                import imageio.v3 as iio

                iio.imwrite(out_path, rgb_u8)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(e))

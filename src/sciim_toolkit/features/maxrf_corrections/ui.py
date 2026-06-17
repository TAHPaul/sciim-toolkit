"""MA-XRF Map Correction UI: Interactive folder browser with multi-layer corrections."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
import tifffile as tiff

from sciim_toolkit.features.maxrf_corrections.drawing_widget import PolygonDrawingWidget
from sciim_toolkit.features.maxrf_corrections.image_io import (
    read_image,
    resize_to,
    robust_minmax,
    normalize_feature,
)
from sciim_toolkit.features.maxrf_corrections.pipeline import (
    CorrectionParams,
    compute_corrected,
)


class ClickableLabel(QtWidgets.QLabel):
    """Label that emits signals on click and double-click."""
    clicked = QtCore.Signal()
    double_clicked = QtCore.Signal()
    
    def mousePressEvent(self, event):
        self.clicked.emit()
    
    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()


class ResetableSlider(QtWidgets.QSlider):
    """Slider that resets to default value on double-click."""
    def __init__(self, orientation, reset_value=0, parent=None):
        super().__init__(orientation, parent)
        self.reset_value = reset_value
    
    def mouseDoubleClickEvent(self, event):
        self.setValue(self.reset_value)


class EditableValueWidget(QtWidgets.QWidget):
    """Widget with a label and inline editable numeric value."""

    value_changed = QtCore.Signal(float)
    reset_requested = QtCore.Signal()

    def __init__(self, field_name: str, initial_value: str = "0.00", parent=None) -> None:
        super().__init__(parent)
        self.field_name = field_name  # Just the name, e.g., "Strength"
        self.value_text = initial_value
        self.is_editing = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Normal text label with field name only
        self.label = QtWidgets.QLabel(self.field_name + ":")
        self.label.setStyleSheet("color: black;")
        layout.addWidget(self.label)
        
        # Editable value display using custom ClickableLabel
        self.value_label = ClickableLabel(self.value_text)
        self.value_label.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.value_label.setStyleSheet("color: #0066cc; text-decoration: underline;")
        self.value_label.clicked.connect(self._start_edit)
        self.value_label.double_clicked.connect(self._on_reset)
        layout.addWidget(self.value_label)
        
        # Inline input field (hidden by default)
        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setMaximumWidth(80)
        self.input_field.setVisible(False)
        self.input_field.returnPressed.connect(self._finish_edit)
        self.input_field.editingFinished.connect(self._finish_edit)
        layout.addWidget(self.input_field)
        
        layout.addStretch(1)

    def _on_reset(self):
        """Handle double-click reset request."""
        self.reset_requested.emit()

    def _start_edit(self):
        """Start inline editing by showing the input field."""
        if self.is_editing:
            return  # Already editing
        
        self.is_editing = True
        numeric_str = self.value_text.strip().split()[0]
        self.input_field.setText(numeric_str)
        self.value_label.setVisible(False)
        self.input_field.setVisible(True)
        self.input_field.setFocus()
        self.input_field.selectAll()

    def _finish_edit(self):
        """Finish inline editing and commit the value."""
        if not self.is_editing:
            return
        
        self.is_editing = False
        value_str = self.input_field.text().strip()
        
        try:
            value = float(value_str)
            self.value_changed.emit(value)
        except ValueError:
            # Invalid input, just revert to old value
            pass
        
        # Hide input field, show label
        self.input_field.setVisible(False)
        self.value_label.setVisible(True)

    def set_text(self, text: str) -> None:
        """Update the display text (extract value part)."""
        # text is like "Strength: 50%" or "Brightness: 0.50"
        # we only want to update the value part
        parts = text.split(":")
        if len(parts) >= 2:
            self.value_text = parts[-1].strip()
        else:
            self.value_text = text.strip()
        self.value_label.setText(self.value_text)


class CollapsibleGroupBox(QtWidgets.QWidget):
    """Collapsible group box with expand/collapse arrow and content area."""

    def __init__(self, title: str, parent=None, initial_checked: bool = True) -> None:
        super().__init__(parent)
        self.is_expanded = initial_checked
        
        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header with expand/collapse arrow
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.arrow_label = QtWidgets.QLabel("▼" if self.is_expanded else "▶")
        self.arrow_label.setMaximumWidth(20)
        
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        header_layout.addWidget(self.arrow_label)
        header_layout.addWidget(self.title_label, 1)
        
        header_widget = QtWidgets.QWidget()
        header_widget.setLayout(header_layout)
        header_widget.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        header_widget.mousePressEvent = self._toggle_expanded
        
        main_layout.addWidget(header_widget)
        
        # Content area
        self.content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(15, 5, 10, 10)
        
        main_layout.addWidget(self.content_widget)
        
        # Set initial visibility
        self.content_widget.setVisible(self.is_expanded)
    
    def _toggle_expanded(self, event) -> None:
        """Toggle expanded state."""
        self.is_expanded = not self.is_expanded
        self.content_widget.setVisible(self.is_expanded)
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
    
    def layout(self) -> QtWidgets.QVBoxLayout:
        """Return the content layout for adding widgets."""
        return self.content_layout


class PolygonDrawerDialog(QtWidgets.QDialog):
    """Modal dialog for interactive mask drawing with multiple tools."""

    mask_created = QtCore.Signal(np.ndarray)

    def __init__(
        self,
        image: np.ndarray,
        parent=None,
        source_path: Path | None = None,
        source_dtype: np.dtype | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Draw Correction Mask")
        self.setMinimumSize(1400, 800)

        self.image = image
        self.source_path = source_path
        self.source_dtype = source_dtype
        self.mask: np.ndarray | None = None
        self.selected_corr: str | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        # Drawing widget (canvas)
        self.drawer = PolygonDrawingWidget(self.image)
        root.addWidget(self.drawer, 1)

        self.shortcut_fit_drawer = QtGui.QShortcut(QtGui.QKeySequence("F"), self.drawer)
        self.shortcut_fit_drawer.setContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.shortcut_fit_drawer.activated.connect(self.drawer.reset_zoom)

        # Tools and controls row
        tools_row = QtWidgets.QHBoxLayout()

        # Drawing tools (mutually exclusive radio buttons)
        tool_group = QtWidgets.QGroupBox("Drawing Tools")
        tool_layout = QtWidgets.QHBoxLayout(tool_group)

        self.tool_button_group = QtWidgets.QButtonGroup()

        self.btn_polygon = QtWidgets.QRadioButton("Polygon")
        self.btn_polygon.setChecked(True)
        self.tool_button_group.addButton(self.btn_polygon)
        self.btn_polygon.toggled.connect(
            lambda checked: checked and self.drawer.set_tool("polygon")
        )

        self.btn_rect = QtWidgets.QRadioButton("Rectangle")
        self.tool_button_group.addButton(self.btn_rect)
        self.btn_rect.toggled.connect(
            lambda checked: checked and self.drawer.set_tool("rectangle")
        )

        self.btn_brush = QtWidgets.QRadioButton("Brush")
        self.tool_button_group.addButton(self.btn_brush)
        self.btn_brush.toggled.connect(
            lambda checked: checked and self.drawer.set_tool("brush")
        )

        self.btn_eraser = QtWidgets.QRadioButton("Eraser")
        self.tool_button_group.addButton(self.btn_eraser)
        self.btn_eraser.toggled.connect(
            lambda checked: checked and self.drawer.set_tool("eraser")
        )

        tool_layout.addWidget(self.btn_polygon)
        tool_layout.addWidget(self.btn_rect)
        tool_layout.addWidget(self.btn_brush)
        tool_layout.addWidget(self.btn_eraser)
        tool_layout.addSpacing(20)

        # Brush size
        tool_layout.addWidget(QtWidgets.QLabel("Brush size:"))
        self.slider_brush_size = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_brush_size.setMinimum(1)
        self.slider_brush_size.setMaximum(50)
        self.slider_brush_size.setValue(15)
        self.slider_brush_size.setMaximumWidth(100)
        self.slider_brush_size.valueChanged.connect(
            lambda val: setattr(self.drawer, "brush_size", val)
        )
        tool_layout.addWidget(self.slider_brush_size)

        tool_layout.addSpacing(20)

        # Eraser size
        tool_layout.addWidget(QtWidgets.QLabel("Eraser size:"))
        self.slider_eraser_size = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_eraser_size.setMinimum(1)
        self.slider_eraser_size.setMaximum(50)
        self.slider_eraser_size.setValue(15)
        self.slider_eraser_size.setMaximumWidth(100)
        self.slider_eraser_size.valueChanged.connect(
            lambda val: setattr(self.drawer, "eraser_size", val)
        )
        tool_layout.addWidget(self.slider_eraser_size)

        tool_layout.addStretch(1)
        tools_row.addWidget(tool_group)

        # Combine mode
        combine_group = QtWidgets.QGroupBox("Combine Mode")
        combine_layout = QtWidgets.QHBoxLayout(combine_group)

        self.combine_button_group = QtWidgets.QButtonGroup()
        self.combine_button_group.setExclusive(True)

        self.btn_add = QtWidgets.QPushButton("Add ∪")
        self.btn_add.setCheckable(True)
        self.btn_add.setChecked(True)
        self.combine_button_group.addButton(self.btn_add, 0)
        self.btn_add.clicked.connect(lambda: self._set_combine_mode("add"))

        self.btn_subtract = QtWidgets.QPushButton("Subtract −")
        self.btn_subtract.setCheckable(True)
        self.combine_button_group.addButton(self.btn_subtract, 1)
        self.btn_subtract.clicked.connect(lambda: self._set_combine_mode("subtract"))

        self.btn_intersect = QtWidgets.QPushButton("Intersect ∩")
        self.btn_intersect.setCheckable(True)
        self.combine_button_group.addButton(self.btn_intersect, 2)
        self.btn_intersect.clicked.connect(lambda: self._set_combine_mode("intersect"))

        combine_layout.addWidget(self.btn_add)
        combine_layout.addWidget(self.btn_subtract)
        combine_layout.addWidget(self.btn_intersect)
        combine_layout.addStretch(1)
        tools_row.addWidget(combine_group)

        # Edit controls
        edit_group = QtWidgets.QGroupBox("Edit")
        edit_layout = QtWidgets.QHBoxLayout(edit_group)

        self.btn_finalize = QtWidgets.QPushButton("Finalize Polygon")
        self.btn_finalize.clicked.connect(self.drawer.finalize_polygon)

        self.btn_undo = QtWidgets.QPushButton("Undo")
        self.btn_undo.clicked.connect(self.drawer.undo)

        self.btn_clear = QtWidgets.QPushButton("Clear All")
        self.btn_clear.clicked.connect(self.drawer.clear_all)

        self.btn_fit = QtWidgets.QPushButton("Fit / Reset Zoom")
        self.btn_fit.clicked.connect(self.drawer.reset_zoom)

        edit_layout.addWidget(self.btn_finalize)
        edit_layout.addWidget(self.btn_undo)
        edit_layout.addWidget(self.btn_clear)
        edit_layout.addWidget(self.btn_fit)
        edit_layout.addStretch(1)
        tools_row.addWidget(edit_group)

        root.addLayout(tools_row)

        # Bottom buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_load_a = QtWidgets.QPushButton("Load as Correction A")
        btn_load_b = QtWidgets.QPushButton("Load as Correction B")
        btn_load_c = QtWidgets.QPushButton("Load as Correction C")
        btn_save = QtWidgets.QPushButton("Save mask…")
        btn_cancel = QtWidgets.QPushButton("Cancel")

        btn_layout.addWidget(btn_load_a)
        btn_layout.addWidget(btn_load_b)
        btn_layout.addWidget(btn_load_c)
        btn_layout.addWidget(btn_save)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_cancel)

        root.addLayout(btn_layout)

        btn_load_a.clicked.connect(lambda: self._finalize("A"))
        btn_load_b.clicked.connect(lambda: self._finalize("B"))
        btn_load_c.clicked.connect(lambda: self._finalize("C"))
        btn_save.clicked.connect(self.save_mask)
        btn_cancel.clicked.connect(self.reject)

    def _set_combine_mode(self, mode: str) -> None:
        """Set combine mode and update drawer."""
        self.drawer.set_combine_mode(mode)

        if mode == "add":
            self.btn_add.setChecked(True)
        elif mode == "subtract":
            self.btn_subtract.setChecked(True)
        elif mode == "intersect":
            self.btn_intersect.setChecked(True)

    def _get_mask_export_dtype(self) -> np.dtype:
        """Return export dtype matching the loaded base map where possible."""
        if self.source_dtype is not None:
            return np.dtype(self.source_dtype)
        return np.dtype(np.uint16)

    def save_mask(self) -> None:
        """Save current mask to disk using source map format and bit depth."""
        mask = self.drawer.get_mask().astype(np.float32)
        export_dtype = self._get_mask_export_dtype()

        if np.issubdtype(export_dtype, np.integer):
            max_val = np.iinfo(export_dtype).max
            out = (mask * max_val).astype(export_dtype)
        else:
            out = mask.astype(export_dtype)

        if self.source_path is not None:
            default_ext = self.source_path.suffix if self.source_path.suffix else ".tif"
            default_name = self.source_path.with_name(
                self.source_path.stem + "_mask" + default_ext
            ).name
            start_dir = str(self.source_path.parent)
        else:
            default_ext = ".tif"
            default_name = "mask.tif"
            start_dir = str(Path.home())

        filter_str = "TIFF (*.tif *.tiff);;PNG (*.png);;JPEG (*.jpg *.jpeg)"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save mask",
            str(Path(start_dir) / default_name),
            filter_str,
        )
        if not path:
            return

        out_path = Path(path)
        out_path = out_path.with_suffix(default_ext)

        try:
            if out_path.suffix.lower() in {".tif", ".tiff"}:
                tiff.imwrite(str(out_path), out)
            else:
                import imageio.v3 as iio

                iio.imwrite(out_path, out)
            QtWidgets.QMessageBox.information(
                self,
                "Mask saved",
                f"Saved {out_path.name} ({out.dtype})",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(e))

    def _finalize(self, which: str) -> None:
        """Finalize mask and close dialog."""
        self.mask = self.drawer.get_mask()
        self.selected_corr = which
        self.mask_created.emit(self.mask)
        self.accept()


class MaxrfCorrectionsTab(QtWidgets.QWidget):
    """MA-XRF map correction UI with folder browser, element selector, and multi-layer corrections."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Project session (set via set_session if working from project)
        self.session = None

        # Folder and element browsing
        self.work_folder: Path | None = None
        self.element_maps: list[Path] = []
        self.current_index = 0

        # Base and correction maps
        self.base: np.ndarray | None = None
        self.base_path: Path | None = None
        self.base_lo = 0.0
        self.base_hi = 1.0

        self.corr_a: np.ndarray | None = None
        self.corr_b: np.ndarray | None = None
        self.corr_c: np.ndarray | None = None
        self.params_a = CorrectionParams(enabled=False)
        self.params_b = CorrectionParams(enabled=False)
        self.params_c = CorrectionParams(enabled=False)

        self.display_brightness = 0.0
        self.display_contrast = 1.0
        self.display_gamma = 1.0

        # Image transform state (rotation and mirroring)
        self.rotation_angle = 0  # 0, 90, 180, 270 degrees
        self.mirror_h = False  # Horizontal mirror
        self.mirror_v = False  # Vertical mirror

        self._build_ui()
        self._set_workflow_enabled(False)
        self._load_session()

    def _build_ui(self) -> None:
        """Build the entire UI layout."""
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        
        root = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(500)  # Ensure buttons don't overflow
        left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(10, 10, 10, 10)
        self.left_layout.setSpacing(10)
        left_scroll.setWidget(left_panel)
        root.addWidget(left_scroll)

        self._build_folder_controls()
        self.display_group = self._build_display_controls()
        self.corr_group_a = self._make_corr_group("A", "Stitching overlap", self.params_a)
        self.corr_group_b = self._make_corr_group("B", "Support features", self.params_b)
        self.corr_group_c = self._make_corr_group("C", "Additional correction", self.params_c)
        self.left_layout.addWidget(self.corr_group_a)
        self.left_layout.addWidget(self.corr_group_b)
        self.left_layout.addWidget(self.corr_group_c)

        self.info = QtWidgets.QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(140)
        self.left_layout.addWidget(self.info)
        self.left_layout.addStretch(1)
        
        self.right_container = QtWidgets.QWidget()
        self.right_stack = QtWidgets.QStackedLayout(self.right_container)

        placeholder_page = QtWidgets.QWidget()
        placeholder_layout = QtWidgets.QVBoxLayout(placeholder_page)
        placeholder_layout.addStretch(1)
        self.lbl_placeholder = QtWidgets.QLabel(
            "Select your folder with elemental distribution maps to begin"
        )
        self.lbl_placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_placeholder.setWordWrap(True)
        self.lbl_placeholder.setStyleSheet("color: #666; font-size: 15px; padding: 24px;")
        placeholder_layout.addWidget(self.lbl_placeholder)
        placeholder_layout.addStretch(1)

        self.graphics = pg.GraphicsLayoutWidget()
        self.right_stack.addWidget(placeholder_page)
        self.right_stack.addWidget(self.graphics)
        self.right_stack.setCurrentIndex(0)
        root.addWidget(self.right_container)
        root.setSizes([500, 400])  # Initial split: left=500, right=400
        root.setCollapsible(0, False)  # Don't allow left panel to collapse completely
        root_layout.addWidget(root)
        
        self.view = self.graphics.addViewBox(lockAspect=True)
        self.img_item = pg.ImageItem()
        self.view.addItem(self.img_item)
        self.view.invertY(False)  # PyQtGraph uses bottom-left origin

        self.shortcut_fit_preview = QtGui.QShortcut(QtGui.QKeySequence("F"), self.graphics)
        self.shortcut_fit_preview.setContext(
            QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.shortcut_fit_preview.activated.connect(self._fit_preview_view)

    def _fit_preview_view(self) -> None:
        """Fit correction preview image in the pyqtgraph view."""
        if self.base is None:
            return
        self.view.autoRange()

    def _build_folder_controls(self) -> None:
        """Folder browser and element selector controls."""
        folder_group = QtWidgets.QGroupBox("Element Maps Browser")
        v = QtWidgets.QVBoxLayout(folder_group)

        # Folder selection row
        row1 = QtWidgets.QHBoxLayout()
        self.btn_browse = QtWidgets.QPushButton("Browse folder…")
        self.lbl_folder = QtWidgets.QLabel("No folder selected")
        self.lbl_folder.setToolTip("Click Browse folder to select a directory")
        row1.addWidget(self.btn_browse)
        row1.addWidget(self.lbl_folder, 1)
        v.addLayout(row1)

        # Element selector row
        row2 = QtWidgets.QHBoxLayout()
        self.btn_prev = QtWidgets.QPushButton("◀ Prev")
        self.combo_element = QtWidgets.QComboBox()
        self.combo_element.setMinimumWidth(250)
        self.btn_next = QtWidgets.QPushButton("Next ▶")
        self.lbl_counter = QtWidgets.QLabel("0 / 0")
        row2.addWidget(self.btn_prev)
        row2.addWidget(self.combo_element, 1)
        row2.addWidget(self.btn_next)
        row2.addWidget(self.lbl_counter)
        v.addLayout(row2)

        # Viewer controls (rotation and mirroring)
        viewer_controls = QtWidgets.QHBoxLayout()
        self.btn_rot_ccw = QtWidgets.QPushButton("↻ 90°")
        self.btn_rot_cw = QtWidgets.QPushButton("↺ 90°")
        self.btn_mirror_h = QtWidgets.QPushButton("⟷ Flip H")
        self.btn_mirror_v = QtWidgets.QPushButton("⟨⟩ Flip V")
        viewer_controls.addWidget(self.btn_rot_ccw)
        viewer_controls.addWidget(self.btn_rot_cw)
        viewer_controls.addWidget(self.btn_mirror_h)
        viewer_controls.addWidget(self.btn_mirror_v)
        viewer_controls.addStretch(1)
        v.addLayout(viewer_controls)

        # View mode and export row
        row3 = QtWidgets.QHBoxLayout()
        self.view_mode = QtWidgets.QComboBox()
        self.view_mode.addItems(
            ["Corrected", "Base", "Difference (Corrected - Base)"]
        )
        self.chk_lock_levels = QtWidgets.QCheckBox("Lock contrast to base")
        self.chk_lock_levels.setChecked(True)
        self.btn_export = QtWidgets.QPushButton("Export corrected…")
        row3.addWidget(self.view_mode, 1)
        row3.addWidget(self.chk_lock_levels)
        row3.addWidget(self.btn_export)
        v.addLayout(row3)

        # Load correction mask buttons (A, B, C)
        load_mask_layout = QtWidgets.QHBoxLayout()
        self.btn_load_corr_a = QtWidgets.QPushButton("Load correction A…")
        self.btn_load_corr_b = QtWidgets.QPushButton("Load correction B…")
        self.btn_load_corr_c = QtWidgets.QPushButton("Load correction C…")
        load_mask_layout.addWidget(self.btn_load_corr_a)
        load_mask_layout.addWidget(self.btn_load_corr_b)
        load_mask_layout.addWidget(self.btn_load_corr_c)
        v.addLayout(load_mask_layout)

        # Draw mask button
        self.btn_draw_mask = QtWidgets.QPushButton("Draw correction mask…")
        self.btn_draw_mask.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold;"
        )
        v.addWidget(self.btn_draw_mask)

        self.left_layout.addWidget(folder_group)

        # Connect signals
        self.btn_browse.clicked.connect(self.browse_folder)
        self.btn_prev.clicked.connect(self.prev_element)
        self.btn_next.clicked.connect(self.next_element)
        self.combo_element.currentIndexChanged.connect(self.on_element_changed)
        self.view_mode.currentIndexChanged.connect(self.update_preview)
        self.chk_lock_levels.stateChanged.connect(self.update_preview)
        self.btn_export.clicked.connect(self.export_corrected)
        self.btn_load_corr_a.clicked.connect(lambda: self.load_correction("A"))
        self.btn_load_corr_b.clicked.connect(lambda: self.load_correction("B"))
        self.btn_load_corr_c.clicked.connect(lambda: self.load_correction("C"))
        self.btn_draw_mask.clicked.connect(self.open_mask_drawer)
        self.btn_rot_ccw.clicked.connect(self.rotate_ccw)
        self.btn_rot_cw.clicked.connect(self.rotate_cw)
        self.btn_mirror_h.clicked.connect(self.mirror_horizontal)
        self.btn_mirror_v.clicked.connect(self.mirror_vertical)

    def _build_display_controls(self) -> CollapsibleGroupBox:
        """Display adjustment controls (brightness, contrast, gamma) with collapsible group."""
        group = CollapsibleGroupBox("Display adjustments", initial_checked=False)
        v = group.layout()

        self.lbl_brightness = EditableValueWidget("Brightness", "0.00")
        sl_b = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_b.setRange(-100, 100)
        sl_b.setValue(0)

        self.lbl_contrast = EditableValueWidget("Contrast", "1.00")
        sl_c = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=100)
        sl_c.setRange(50, 200)
        sl_c.setValue(100)

        self.lbl_gamma = EditableValueWidget("Gamma", "1.00")
        sl_g = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=100)
        sl_g.setRange(30, 300)
        sl_g.setValue(100)

        v.addWidget(self.lbl_brightness)
        v.addWidget(sl_b)
        v.addWidget(self.lbl_contrast)
        v.addWidget(sl_c)
        v.addWidget(self.lbl_gamma)
        v.addWidget(sl_g)

        self.left_layout.addWidget(group)

        def on_brightness(val: int) -> None:
            self.display_brightness = val / 100.0
            self.lbl_brightness.set_text(f"Brightness: {self.display_brightness:.2f}")
            self.update_preview()

        def on_contrast(val: int) -> None:
            self.display_contrast = val / 100.0
            self.lbl_contrast.set_text(f"Contrast: {self.display_contrast:.2f}")
            self.update_preview()

        def on_gamma(val: int) -> None:
            self.display_gamma = max(0.1, val / 100.0)
            self.lbl_gamma.set_text(f"Gamma: {self.display_gamma:.2f}")
            self.update_preview()

        # Editable value handlers
        def on_brightness_edit(value: float) -> None:
            new_val = max(-100, min(100, int(value * 100)))
            sl_b.blockSignals(True)
            sl_b.setValue(new_val)
            sl_b.blockSignals(False)
            on_brightness(new_val)

        def on_contrast_edit(value: float) -> None:
            new_val = max(50, min(200, int(value * 100)))
            sl_c.blockSignals(True)
            sl_c.setValue(new_val)
            sl_c.blockSignals(False)
            on_contrast(new_val)

        def on_gamma_edit(value: float) -> None:
            new_val = max(30, min(300, int(value * 100)))
            sl_g.blockSignals(True)
            sl_g.setValue(new_val)
            sl_g.blockSignals(False)
            on_gamma(new_val)

        sl_b.valueChanged.connect(on_brightness)
        sl_c.valueChanged.connect(on_contrast)
        sl_g.valueChanged.connect(on_gamma)
        self.lbl_brightness.value_changed.connect(on_brightness_edit)
        self.lbl_contrast.value_changed.connect(on_contrast_edit)
        self.lbl_gamma.value_changed.connect(on_gamma_edit)

        return group

    def _set_workflow_enabled(self, enabled: bool) -> None:
        """Enable/disable all workflow controls except folder browse."""
        for widget_name in [
            "combo_element",
            "btn_prev",
            "btn_next",
            "btn_rot_ccw",
            "btn_rot_cw",
            "btn_mirror_h",
            "btn_mirror_v",
            "view_mode",
            "chk_lock_levels",
            "btn_export",
            "btn_load_corr_a",
            "btn_load_corr_b",
            "btn_load_corr_c",
            "btn_draw_mask",
            "display_group",
            "corr_group_a",
            "corr_group_b",
            "corr_group_c",
            "right_container",
        ]:
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(enabled)

        # Keep the right container visible and switch between placeholder and image
        self.right_container.setEnabled(True)
        if hasattr(self, "right_stack"):
            self.right_stack.setCurrentIndex(1 if enabled else 0)

    def _collect_image_files(self, folder: Path) -> list[Path]:
        """Return supported image files in folder, or empty list if none/error."""
        image_exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
        try:
            return sorted(
                [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in image_exts]
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Folder read error",
                f"Could not read folder '{folder}':\n{e}",
            )
            self._log(f"Folder read error: {e}")
            return []

    def _make_corr_group(
        self, tag: str, label: str, params: CorrectionParams
    ) -> CollapsibleGroupBox:
        """Create a collapsible correction layer panel with editable values."""
        group = CollapsibleGroupBox(f"Correction {tag}: {label}", initial_checked=False)
        v = group.layout()

        chk_enabled = QtWidgets.QCheckBox("Enable")
        chk_enabled.setChecked(False)  # All corrections disabled by default
        chk_invert = QtWidgets.QCheckBox("Invert feature (1 - feature)")

        # Store checkbox reference for auto-enable when loading correction
        if tag == "A":
            self.chk_enabled_a = chk_enabled
        elif tag == "B":
            self.chk_enabled_b = chk_enabled
        elif tag == "C":
            self.chk_enabled_c = chk_enabled

        lbl_strength = EditableValueWidget("Strength", "0%")
        sl_strength = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_strength.setRange(-100, 100)

        lbl_thresh = EditableValueWidget("Threshold", "0.00")
        sl_thresh = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_thresh.setRange(0, 100)

        lbl_soft = EditableValueWidget("Mask softness", "0.00")
        sl_soft = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_soft.setRange(0, 50)

        lbl_blur = EditableValueWidget("Blur sigma", "0.0")
        sl_blur = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_blur.setRange(0, 50)

        lbl_dx = EditableValueWidget("Shift X (px)", "0")
        sl_dx = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_dx.setRange(-200, 200)

        lbl_dy = EditableValueWidget("Shift Y (px)", "0")
        sl_dy = ResetableSlider(QtCore.Qt.Orientation.Horizontal, reset_value=0)
        sl_dy.setRange(-200, 200)

        for w in [
            chk_enabled,
            chk_invert,
            lbl_strength,
            sl_strength,
            lbl_thresh,
            sl_thresh,
            lbl_soft,
            sl_soft,
            lbl_blur,
            sl_blur,
            lbl_dx,
            sl_dx,
            lbl_dy,
            sl_dy,
        ]:
            v.addWidget(w)

        def sync() -> None:
            self.update_preview()

        chk_enabled.stateChanged.connect(
            lambda s: setattr(params, "enabled", bool(s)) or sync()
        )
        chk_invert.stateChanged.connect(
            lambda s: setattr(params, "invert", bool(s)) or sync()
        )

        # Store slider references for resetting
        strength_default = 0
        thresh_default = 0
        soft_default = 0
        blur_default = 0
        dx_default = 0
        dy_default = 0

        def on_strength(vv: int) -> None:
            params.strength = vv / 100.0
            lbl_strength.set_text(f"Strength: {vv:+d}%")
            sync()

        def on_thresh(vv: int) -> None:
            params.threshold = vv / 100.0
            lbl_thresh.set_text(f"Threshold: {params.threshold:.2f}")
            sync()

        def on_soft(vv: int) -> None:
            params.softness = vv / 100.0
            lbl_soft.set_text(f"Mask softness: {params.softness:.2f}")
            sync()

        def on_blur(vv: int) -> None:
            params.blur_sigma = vv / 10.0
            lbl_blur.set_text(f"Blur sigma: {params.blur_sigma:.1f}")
            sync()

        def on_dx(vv: int) -> None:
            params.dx = float(vv)
            lbl_dx.set_text(f"Shift X (px): {vv}")
            sync()

        def on_dy(vv: int) -> None:
            params.dy = float(vv)
            lbl_dy.set_text(f"Shift Y (px): {vv}")
            sync()

        # Editable value handlers
        def on_strength_edit(value: float) -> None:
            new_val = max(-100, min(100, int(value)))
            sl_strength.blockSignals(True)
            sl_strength.setValue(new_val)
            sl_strength.blockSignals(False)
            on_strength(new_val)

        def on_thresh_edit(value: float) -> None:
            new_val = max(0, min(100, int(value * 100)))
            sl_thresh.blockSignals(True)
            sl_thresh.setValue(new_val)
            sl_thresh.blockSignals(False)
            on_thresh(new_val)

        def on_soft_edit(value: float) -> None:
            new_val = max(0, min(50, int(value * 100)))
            sl_soft.blockSignals(True)
            sl_soft.setValue(new_val)
            sl_soft.blockSignals(False)
            on_soft(new_val)

        def on_blur_edit(value: float) -> None:
            new_val = max(0, min(50, int(value * 10)))
            sl_blur.blockSignals(True)
            sl_blur.setValue(new_val)
            sl_blur.blockSignals(False)
            on_blur(new_val)

        def on_dx_edit(value: float) -> None:
            new_val = max(-200, min(200, int(value)))
            sl_dx.blockSignals(True)
            sl_dx.setValue(new_val)
            sl_dx.blockSignals(False)
            on_dx(new_val)

        def on_dy_edit(value: float) -> None:
            new_val = max(-200, min(200, int(value)))
            sl_dy.blockSignals(True)
            sl_dy.setValue(new_val)
            sl_dy.blockSignals(False)
            on_dy(new_val)

        sl_strength.valueChanged.connect(on_strength)
        sl_thresh.valueChanged.connect(on_thresh)
        sl_soft.valueChanged.connect(on_soft)
        sl_blur.valueChanged.connect(on_blur)
        sl_dx.valueChanged.connect(on_dx)
        sl_dy.valueChanged.connect(on_dy)
        
        lbl_strength.value_changed.connect(on_strength_edit)
        lbl_thresh.value_changed.connect(on_thresh_edit)
        lbl_soft.value_changed.connect(on_soft_edit)
        lbl_blur.value_changed.connect(on_blur_edit)
        lbl_dx.value_changed.connect(on_dx_edit)
        lbl_dy.value_changed.connect(on_dy_edit)

        return group

    def rotate_ccw(self) -> None:
        """Rotate image counter-clockwise by 90 degrees."""
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self.update_preview()

    def rotate_cw(self) -> None:
        """Rotate image clockwise by 90 degrees."""
        self.rotation_angle = (self.rotation_angle - 90) % 360
        self.update_preview()

    def mirror_horizontal(self) -> None:
        """Mirror image horizontally."""
        self.mirror_h = not self.mirror_h
        self.update_preview()

    def mirror_vertical(self) -> None:
        """Mirror image vertically."""
        self.mirror_v = not self.mirror_v
        self.update_preview()

    def _apply_image_transforms(self, img: np.ndarray) -> np.ndarray:
        """Apply rotation and mirroring transforms to image in numpy space.
        
        For image arrays in [height, width] = [rows, cols] format:
        - np.fliplr: flip left-right (along columns, affects x/width)
        - np.flipud: flip up-down (along rows, affects y/height)  
        - np.rot90: rotates counter-clockwise by k*90 degrees
        
        Note: rotation_angle is in clockwise degrees, so we negate for rot90.
        """
        result = img.copy()
        
        # Apply mirroring first (operates in image space)
        if self.mirror_h:
            result = np.fliplr(result)
        if self.mirror_v:
            result = np.flipud(result)
        
        # Apply rotation: rotation_angle is CW, np.rot90 is CCW
        # So we negate: positive rotation_angle means negative k for rot90
        k = (self.rotation_angle // 90) % 4
        if k != 0:
            result = np.rot90(result, k=-k)
        
        return result

    def _log(self, msg: str) -> None:
        """Append message to info panel."""
        self.info.appendPlainText(msg)

    def _reset_correction_params(self) -> None:
        """Reset correction parameters while preserving UI signal bindings."""
        for params in (self.params_a, self.params_b, self.params_c):
            params.enabled = False
            params.strength = 0.0
            params.threshold = 0.0
            params.softness = 0.0
            params.blur_sigma = 0.0
            params.dx = 0.0
            params.dy = 0.0
            params.invert = False

    def browse_folder(self) -> None:
        """Open folder dialog to select element maps directory."""
        start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Element Maps Folder", start_dir
        )
        if not folder:
            return

        self.work_folder = Path(folder)
        self._refresh_element_list()
        self._log(f"Folder: {self.work_folder.name}")

    def _refresh_element_list(self) -> None:
        """Crawl folder for image files and populate element selector."""
        if not self.work_folder:
            return

        self.element_maps = self._collect_image_files(self.work_folder)

        self.combo_element.blockSignals(True)
        self.combo_element.clear()
        for p in self.element_maps:
            self.combo_element.addItem(p.stem, userData=p)
        self.combo_element.blockSignals(False)

        self.current_index = 0
        self._update_counter()

        if self.element_maps:
            self._set_workflow_enabled(True)
            self.combo_element.setCurrentIndex(0)
            self.on_element_changed(0)
        else:
            self._set_workflow_enabled(False)
            self.base = None
            self.base_path = None
            self.corr_a = None
            self.corr_b = None
            self.corr_c = None
            self.img_item.setImage(np.zeros((1, 1), dtype=np.float32), autoLevels=False)
            self._log(f"No image files found in {self.work_folder.name}")
            QtWidgets.QMessageBox.warning(
                self,
                "No images found",
                f"The selected folder '{self.work_folder.name}' contains no supported image files\n"
                "(.tif, .tiff, .png, .jpg, .jpeg).",
            )

    def on_element_changed(self, index: int) -> None:
        """Load selected element map as base."""
        if not self.element_maps or index < 0 or index >= len(self.element_maps):
            return

        self.current_index = index
        self._update_counter()

        path = self.element_maps[index]
        try:
            image_array, meta = read_image(str(path))
            self.base = image_array
            self.base_path = path
            self.base_lo, self.base_hi = robust_minmax(self.base, 1.0, 99.0)
            
            # Reset rotation and mirroring to identity when loading new image
            self.rotation_angle = 0
            self.mirror_h = False
            self.mirror_v = False

            # Resize corrections if necessary
            if self.corr_a is not None and self.corr_a.shape != self.base.shape:
                self.corr_a = resize_to(self.corr_a, self.base.shape)
            if self.corr_b is not None and self.corr_b.shape != self.base.shape:
                self.corr_b = resize_to(self.corr_b, self.base.shape)
            if self.corr_c is not None and self.corr_c.shape != self.base.shape:
                self.corr_c = resize_to(self.corr_c, self.base.shape)

            self._log(f"[Base] {path.name} shape={self.base.shape} dtype={meta['dtype']}")
            self.update_preview()
        except Exception as e:
            self._log(f"Error loading {path.name}: {e}")

    def _update_counter(self) -> None:
        """Update element counter label."""
        total = len(self.element_maps)
        current = self.current_index + 1 if self.element_maps else 0
        self.lbl_counter.setText(f"{current} / {total}")
        self.lbl_folder.setText(
            self.work_folder.name if self.work_folder else "No folder selected"
        )

    def prev_element(self) -> None:
        """Navigate to previous element."""
        if self.element_maps and self.current_index > 0:
            self.combo_element.setCurrentIndex(self.current_index - 1)

    def next_element(self) -> None:
        """Navigate to next element."""
        if self.element_maps and self.current_index < len(self.element_maps) - 1:
            self.combo_element.setCurrentIndex(self.current_index + 1)

    def load_correction(self, which: str) -> None:
        """Load a correction mask from file (A, B, or C)."""
        if self.base is None:
            self._log("Load a base map first.")
            return

        # Open file dialog
        filter_str = "Image files (*.tif *.tiff *.png *.jpg *.jpeg);;All files (*)"
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Load Correction {which}", "", filter_str
        )
        if not path:
            return

        try:
            arr, meta = read_image(path)
            # Resize to match base if needed
            if arr.shape != self.base.shape:
                arr = resize_to(arr, self.base.shape)

            # Normalize to [0, 1]
            arr = normalize_feature(arr)

            # Store in appropriate variable and auto-enable
            if which == "A":
                self.corr_a = arr
                self.params_a.enabled = True
                self.chk_enabled_a.setChecked(True)
            elif which == "B":
                self.corr_b = arr
                self.params_b.enabled = True
                self.chk_enabled_b.setChecked(True)
            elif which == "C":
                self.corr_c = arr
                self.params_c.enabled = True
                self.chk_enabled_c.setChecked(True)

            self._log(f"[Corr {which}] Loaded from {Path(path).name}, shape={arr.shape}")
            self.update_preview()
        except Exception as e:
            self._log(f"✗ Failed to load correction {which}: {e}")

    def open_mask_drawer(self) -> None:
        """Open interactive mask drawing dialog."""
        if self.base is None:
            self._log("Load a base map first.")
            return

        dlg = PolygonDrawerDialog(
            self.base,
            self,
            source_path=self.base_path,
            source_dtype=self.base.dtype,
        )
        result = dlg.exec()
        if result == QtWidgets.QDialog.Accepted and dlg.mask is not None:
            # Use the correction selected in the dialog
            which = dlg.selected_corr
            
            if which == "A":
                self.corr_a = dlg.mask
                self.params_a.enabled = True
                self.chk_enabled_a.setChecked(True)
                self._log(f"[Corr A] Loaded drawn mask shape={dlg.mask.shape}")
            elif which == "B":
                self.corr_b = dlg.mask
                self.params_b.enabled = True
                self.chk_enabled_b.setChecked(True)
                self._log(f"[Corr B] Loaded drawn mask shape={dlg.mask.shape}")
            elif which == "C":
                self.corr_c = dlg.mask
                self.params_c.enabled = True
                self.chk_enabled_c.setChecked(True)
                self._log(f"[Corr C] Loaded drawn mask shape={dlg.mask.shape}")

            self.update_preview()

    def _compute_corrected(self) -> np.ndarray | None:
        """Compute fully corrected map using all three layers."""
        if self.base is None:
            return None
        return compute_corrected(
            base=self.base,
            corr_a=self.corr_a,
            params_a=self.params_a,
            corr_b=self.corr_b,
            params_b=self.params_b,
            corr_c=self.corr_c,
            params_c=self.params_c,
        )

    def _apply_display_adjustments(self, img01: np.ndarray) -> np.ndarray:
        """Apply brightness, contrast, and gamma adjustments."""
        out = img01 + self.display_brightness
        out = 0.5 + self.display_contrast * (out - 0.5)
        out = np.clip(out, 0.0, 1.0)
        out = np.power(out, 1.0 / max(0.1, self.display_gamma))
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    def update_preview(self) -> None:
        """Update the visualization based on current corrections and display settings."""
        if self.base is None:
            return

        corrected = self._compute_corrected()
        if corrected is None:
            return

        mode = self.view_mode.currentText()
        if mode == "Base":
            source = self.base
        elif mode.startswith("Difference"):
            source = corrected - self.base
        else:
            source = corrected

        lock_levels = self.chk_lock_levels.isChecked()
        if mode in ("Base", "Corrected") and lock_levels:
            lo, hi = self.base_lo, self.base_hi
        elif mode.startswith("Difference"):
            lo_d, hi_d = robust_minmax(source, 1.0, 99.0)
            m = max(abs(lo_d), abs(hi_d), 1e-6)
            lo, hi = -m, m
        else:
            lo, hi = robust_minmax(source, 1.0, 99.0)

        norm = (source - lo) / max(1e-6, hi - lo)
        norm = np.clip(norm, 0.0, 1.0)
        disp = self._apply_display_adjustments(norm)
        
        # Apply user-requested transforms (rotation, mirroring)
        disp = self._apply_image_transforms(disp)
        
        # WORKAROUND: Apply 180° rotation + horizontal flip to fix coordinate system issue
        disp = np.fliplr(np.rot90(disp, k=2))

        self.img_item.setImage(disp, levels=(0.0, 1.0), autoLevels=False)
        self.view.autoRange()
        self.view.autoRange()

    def export_corrected(self) -> None:
        """Export the fully corrected map, matching the viewer display and original format."""
        if self.base is None:
            self._log("No base image loaded.")
            return

        corrected = self._compute_corrected()
        if corrected is None:
            self._log("Nothing to export.")
            return

        # Determine export filename and directory
        default_name = "corrected.tif"
        start_dir = str(Path.home())
        original_dtype = self.base.dtype
        original_path = self.base_path
        
        if self.base_path is not None:
            default_name = self.base_path.with_name(
                self.base_path.stem + "_corrected" + self.base_path.suffix
            ).name
            start_dir = str(self.base_path.parent)

        # Auto-export to project folder if in project mode
        if self.session and self.session.maxrf_pipeline.project_root:
            corrected_maps_folder = Path(self.session.maxrf_pipeline.project_root) / "corrected_maps"
            corrected_maps_folder.mkdir(parents=True, exist_ok=True)
            out_path = corrected_maps_folder / default_name
            skip_dialog = True
        else:
            # Dialog for file format selection
            filter_str = "TIFF (*.tif *.tiff);;PNG (*.png);;JPEG (*.jpg *.jpeg)"
            path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Export corrected map",
                str(Path(start_dir) / default_name),
                filter_str,
            )
            if not path:
                return
            out_path = Path(path)
            skip_dialog = False

        if not skip_dialog:
            # Ensure correct extension based on selection
            if "TIFF" in selected_filter:
                if out_path.suffix.lower() not in {".tif", ".tiff"}:
                    out_path = out_path.with_suffix(".tif")
            elif "PNG" in selected_filter:
                if out_path.suffix.lower() != ".png":
                    out_path = out_path.with_suffix(".png")
            elif "JPEG" in selected_filter:
                if out_path.suffix.lower() not in {".jpg", ".jpeg"}:
                    out_path = out_path.with_suffix(".jpg")

        # Get normalization parameters matching the viewer
        mode = self.view_mode.currentText()
        if mode == "Base":
            source = self.base
        elif mode.startswith("Difference"):
            source = corrected - self.base
        else:
            source = corrected

        lock_levels = self.chk_lock_levels.isChecked()
        if mode in ("Base", "Corrected") and lock_levels:
            lo, hi = self.base_lo, self.base_hi
        elif mode.startswith("Difference"):
            lo_d, hi_d = robust_minmax(source, 1.0, 99.0)
            m = max(abs(lo_d), abs(hi_d), 1e-6)
            lo, hi = -m, m
        else:
            lo, hi = robust_minmax(source, 1.0, 99.0)

        # Normalize to 0-1 range using same scaling as viewer
        norm = (source - lo) / max(1e-6, hi - lo)
        norm = np.clip(norm, 0.0, 1.0)
        
        # Apply display adjustments (brightness, contrast, gamma) to match viewer
        disp = self._apply_display_adjustments(norm)
        
        # Apply image transforms (rotation and mirroring) to match viewer
        disp = self._apply_image_transforms(disp)
        
        # Log transforms being applied for debugging
        if self.rotation_angle != 0 or self.mirror_h or self.mirror_v:
            transforms_applied = []
            if self.rotation_angle != 0:
                transforms_applied.append(f"rotate {self.rotation_angle}° CW")
            if self.mirror_h:
                transforms_applied.append("flip H")
            if self.mirror_v:
                transforms_applied.append("flip V")
            self._log(f"[Export] Applying transforms: {', '.join(transforms_applied)}")
        
        # Convert to output format matching original bit depth
        if original_dtype == np.uint8:
            out = (disp * 255).astype(np.uint8)
        elif original_dtype == np.uint16:
            out = (disp * 65535).astype(np.uint16)
        elif original_dtype == np.uint32:
            out = (disp * 4294967295).astype(np.uint32)
        elif original_dtype == np.float64 or original_dtype == np.float32:
            out = disp.astype(original_dtype)
        else:
            # Default: try to scale to original dtype range
            info = np.iinfo(original_dtype) if np.issubdtype(original_dtype, np.integer) else None
            if info is not None:
                out = (disp * (info.max - info.min) + info.min).astype(original_dtype)
            else:
                out = disp.astype(np.float32)
        
        # Write file with metadata preservation
        try:
            if out_path.suffix.lower() in {".tif", ".tiff"}:
                # For TIFF, preserve original metadata if available
                import tifffile as tiff_lib
                metadata = None
                if original_path and original_path.exists():
                    try:
                        with tiff_lib.TiffFile(original_path) as tf:
                            if tf.pages and hasattr(tf.pages[0], 'tags'):
                                # Extract common TIFF tags for preservation
                                tags_dict = {}
                                for tag_name in ['XResolution', 'YResolution', 'ResolutionUnit']:
                                    if tag_name in tf.pages[0].tags:
                                        tags_dict[tag_name] = tf.pages[0].tags[tag_name].value
                                metadata = tags_dict if tags_dict else None
                    except Exception:
                        pass
                
                tiff_lib.imwrite(str(out_path), out)
            else:
                # For PNG/JPEG, use imageio
                import imageio.v3 as iio
                iio.imwrite(out_path, out)
            
            self._log(f"Exported: {out_path.name} dtype={out.dtype} shape={out.shape}")
            
            # Update manifest if in project mode
            if self.session and self.session.maxrf_pipeline.project_root:
                self._update_manifest_for_export(original_path)
        except Exception as e:
            self._log(f"Export failed: {e}")

    def _update_manifest_for_export(self, original_path: Path | None) -> None:
        """Update manifest to mark corrections_applied=true for the exported map."""
        if not original_path:
            self._log("Manifest: No path to update")
            return
        
        if not self.session:
            self._log("Manifest: No session set")
            return
        
        if not self.session.maxrf_pipeline.project_root:
            self._log("Manifest: No project root in session")
            return
        
        try:
            project_root = Path(self.session.maxrf_pipeline.project_root)
            manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
            
            if not manifest_path.exists():
                self._log(f"Manifest: File not found at {manifest_path}")
                return
            
            # Read manifest
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            map_registry = manifest_data.get("map_registry", {})
            
            # Find the map_id corresponding to this file
            self._log(f"Manifest: Looking for file: {original_path.name}")
            map_id_found = None
            for map_id, record in map_registry.items():
                record_filename = record.get("filename", "")
                if record_filename == original_path.name:
                    map_id_found = map_id
                    self._log(f"Manifest: Found match - map_id={map_id}, filename={record_filename}")
                    break
            
            if not map_id_found:
                self._log(f"Manifest: No matching map found for {original_path.name}")
                return
            
            # Update corrections_applied flag
            map_registry[map_id_found]["corrections_applied"] = True
            
            # Write manifest back
            manifest_data["map_registry"] = map_registry
            manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
            self._log(f"Manifest: Updated {map_id_found} -> corrections_applied=true")
            
            # Also update session if map is in registry
            if map_id_found in self.session.maxrf_pipeline.map_registry:
                self.session.maxrf_pipeline.map_registry[map_id_found].corrections_applied = True
                
        except Exception as e:
            self._log(f"Manifest: Error updating - {type(e).__name__}: {e}")

    def set_session(self, session) -> None:
        """Set the project session and auto-load project workspace if available."""
        self.session = session
        
        # Reset correction parameters when switching projects
        self._reset_correction_params()
        self.rotation_angle = 0
        self.mirror_h = False
        self.mirror_v = False
        
        # Clear visualization and UI
        self.base = None
        self.base_path = None
        self.corr_a = None
        self.corr_b = None
        self.corr_c = None
        self.element_maps = []
        self.combo_element.blockSignals(True)
        self.combo_element.clear()
        self.combo_element.blockSignals(False)
        self._set_workflow_enabled(False)
        self.right_stack.setCurrentIndex(0)  # Show placeholder page
        
        # If project has MA-XRF workspace, auto-load from raw_data
        if session and session.maxrf_pipeline.project_root:
            raw_data_path = Path(session.maxrf_pipeline.project_root) / "raw_data"
            if raw_data_path.exists():
                self.work_folder = raw_data_path
                self.lbl_folder.setText(str(raw_data_path))
                self.btn_browse.setEnabled(False)
                self.btn_browse.setToolTip("(Folder locked: using project workspace)")
                self._refresh_element_list()
                return

        if session and session.maxrf_pipeline.last_selected_folder:
            last_folder = Path(session.maxrf_pipeline.last_selected_folder)
            if last_folder.exists() and last_folder.is_dir():
                self.work_folder = last_folder
                self.lbl_folder.setText(str(last_folder))
                self.btn_browse.setEnabled(True)
                self.btn_browse.setToolTip("")
                self._refresh_element_list()
                return
        
        # No project or no workspace: allow browsing
        self.btn_browse.setEnabled(True)
        self.btn_browse.setToolTip("")
        self.work_folder = None
        self.lbl_folder.setText("No folder selected")
        self._update_counter()

    def _load_session(self) -> None:
        """Load session state from QSettings."""
        from PySide6.QtCore import QSettings

        settings = QSettings("SCIIM", "MaxrfCorrections")
        folder = settings.value("lastFolder")
        if folder and Path(folder).exists():
            self.work_folder = Path(folder)
            self._refresh_element_list()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Refresh preview when tab becomes visible."""
        super().showEvent(event)
        self.update_preview()

    def _refresh_correction_ui(self) -> None:
        """Refresh correction group UI to show current parameter state."""
        if hasattr(self, 'corr_group_a'):
            # The groups would need to update their UI to reflect reset params
            # For now, the next update_preview will handle visual refresh
            pass

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Save session state before closing."""
        from PySide6.QtCore import QSettings

        if self.work_folder:
            settings = QSettings("SCIIM", "MaxrfCorrections")
            settings.setValue("lastFolder", str(self.work_folder))

        super().closeEvent(event)

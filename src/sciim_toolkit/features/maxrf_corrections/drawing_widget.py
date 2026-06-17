"""Drawing widget for interactive polygon mask creation in corrections module."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.maxrf_corrections.image_io import robust_minmax, to_float


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


class CanvasView(QtWidgets.QGraphicsView):
    """Custom graphics view for polygon drawing with mouse event handling."""

    mouse_pressed = QtCore.Signal(int, int)  # x, y
    mouse_moved = QtCore.Signal(int, int)  # x, y
    mouse_released = QtCore.Signal(int, int)  # x, y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QtWidgets.QGraphicsScene()
        self.setScene(self.scene_obj)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.setMinimumSize(400, 400)

        self.img_item = QtWidgets.QGraphicsPixmapItem()
        self.scene_obj.addItem(self.img_item)

        self.image_width = 1
        self.image_height = 1
        self._fitted_once = False
        self._has_user_zoom = False
        self._zoom_level = 1.0
        self._zoom_step = 1.15
        self._min_zoom_level = 0.2
        self._max_zoom_level = 20.0

    def _fit_image_in_view(self):
        """Fit full image in view and reset zoom state."""
        self.resetTransform()
        self._zoom_level = 1.0
        self._has_user_zoom = False
        self.fitInView(
            self.scene_obj.itemsBoundingRect(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._fitted_once = True

    def reset_zoom(self):
        """Reset zoom and fit the full image in view."""
        if self.image_width > 1 and self.image_height > 1:
            self._fit_image_in_view()

    def resizeEvent(self, event):
        """Refill the view when resized."""
        super().resizeEvent(event)
        if self.image_width > 1 and self.image_height > 1 and not self._has_user_zoom:
            self._fit_image_in_view()

    def set_image(self, img_array: np.ndarray):
        """Set the image to display (should be RGB or RGBA, 0-1 float)."""
        prev_width = self.image_width
        prev_height = self.image_height
        self.image_height, self.image_width = img_array.shape[:2]
        image_size_changed = (
            self.image_width != prev_width or self.image_height != prev_height
        )

        # Convert to uint8
        if img_array.dtype == np.float32 or img_array.dtype == np.float64:
            img_uint8 = (np.clip(img_array, 0, 1) * 255).astype(np.uint8)
        else:
            img_uint8 = img_array.astype(np.uint8)

        # Handle 2D and 3D arrays
        if img_uint8.ndim == 2:
            h, w = img_uint8.shape
            rgb_array = np.stack([img_uint8, img_uint8, img_uint8], axis=-1)
            img_uint8 = rgb_array

        # Convert numpy to QImage
        if img_uint8.shape[2] == 3:
            h, w = img_uint8.shape[:2]
            bytes_per_line = 3 * w
            q_img = QtGui.QImage(
                img_uint8.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGB888
            ).copy()
        else:
            h, w = img_uint8.shape[:2]
            bytes_per_line = 4 * w
            q_img = QtGui.QImage(
                img_uint8.data, w, h, bytes_per_line, QtGui.QImage.Format.Format_RGBA8888
            ).copy()

        # Display
        pixmap = QtGui.QPixmap.fromImage(q_img)
        self.img_item.setPixmap(pixmap)

        if image_size_changed or not self._fitted_once:
            self._fit_image_in_view()

    def wheelEvent(self, event: QtGui.QWheelEvent):
        """Zoom in/out with mouse wheel while keeping cursor as zoom anchor."""
        if self.img_item.pixmap().isNull():
            event.ignore()
            return

        delta_y = event.angleDelta().y()
        if delta_y == 0:
            event.ignore()
            return

        step_count = delta_y / 120.0
        zoom_multiplier = self._zoom_step**step_count
        target_zoom = self._zoom_level * zoom_multiplier
        target_zoom = min(max(target_zoom, self._min_zoom_level), self._max_zoom_level)

        applied_multiplier = target_zoom / self._zoom_level
        if applied_multiplier != 1.0:
            self.scale(applied_multiplier, applied_multiplier)
            self._zoom_level = target_zoom
            self._has_user_zoom = abs(self._zoom_level - 1.0) > 1e-6

        event.accept()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        """Reset to fit view with the F key."""
        if (
            event.key() == QtCore.Qt.Key.Key_F
            and event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier
        ):
            self.reset_zoom()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        """Handle mouse press."""
        pos = self.mapToScene(
            event.globalPos() - self.mapToGlobal(self.rect().topLeft())
        )
        x, y = int(pos.x()), int(pos.y())
        self.mouse_pressed.emit(x, y)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        """Handle mouse move."""
        pos = self.mapToScene(
            event.globalPos() - self.mapToGlobal(self.rect().topLeft())
        )
        x, y = int(pos.x()), int(pos.y())
        self.mouse_moved.emit(x, y)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        """Handle mouse release."""
        pos = self.mapToScene(
            event.globalPos() - self.mapToGlobal(self.rect().topLeft())
        )
        x, y = int(pos.x()), int(pos.y())
        self.mouse_released.emit(x, y)


class PolygonDrawingWidget(QtWidgets.QWidget):
    """Interactive canvas for drawing polygons, rectangles, and circles to create masks."""

    def __init__(self, image: np.ndarray, parent=None):
        super().__init__(parent)
        self.original_image = to_float(image)
        self.height, self.width = self.original_image.shape[:2]

        # Initialize mask and drawing state
        self.mask = np.zeros((self.height, self.width), dtype=np.float32)
        self.undo_stack = []

        # Drawing state
        self.current_tool = "polygon"  # polygon, rectangle, brush, eraser
        self.drawing = False
        self.polygon_points = []
        self.combine_mode = "add"  # add, subtract, intersect
        self.rect_start = None
        self.current_mouse_pos = None

        # Brush and eraser sizes
        self.brush_size = 15
        self.eraser_size = 15

        # Display adjustments
        self.display_contrast = 1.0
        self.display_brightness = 0.0
        self.display_gamma = 1.0

        # Mask overlay color (RGB, 0-1 range)
        self.mask_color = (1.0, 0.0, 0.0)  # Red by default

        # Cache for display base image
        self.cached_base_image = None
        self.base_cache_valid = False

        # Layout with canvas
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas_view = CanvasView(self)
        self.canvas_view.mouse_pressed.connect(self._on_mouse_pressed)
        self.canvas_view.mouse_moved.connect(self._on_mouse_moved)
        self.canvas_view.mouse_released.connect(self._on_mouse_released)

        layout.addWidget(self.canvas_view)

        self._update_display()

    def set_tool(self, tool: str):
        """Set the active drawing tool."""
        self.current_tool = tool
        self.polygon_points = []
        self.rect_start = None
        self.current_mouse_pos = None
        self.drawing = False
        self._update_display()

    def set_combine_mode(self, mode: str):
        """Set the combine mode: 'add', 'subtract', or 'intersect'."""
        self.combine_mode = mode

    def reset_zoom(self):
        """Reset canvas zoom to fit image."""
        self.canvas_view.reset_zoom()

    def _on_mouse_pressed(self, x: int, y: int):
        """Handle mouse press event."""
        x = max(0, min(x, self.width - 1))
        y = max(0, min(y, self.height - 1))

        if self.current_tool == "polygon":
            if len(self.polygon_points) >= 3:
                first_pt = self.polygon_points[0]
                distance = ((x - first_pt[0]) ** 2 + (y - first_pt[1]) ** 2) ** 0.5
                if distance < 50:  # Close polygon
                    self.finalize_polygon()
                    return

            self.polygon_points.append((x, y))
            self._update_display()
        elif self.current_tool == "rectangle":
            self.drawing = True
            self.rect_start = (x, y)
            self.current_mouse_pos = (x, y)
        elif self.current_tool == "brush":
            self._save_undo()
            self.drawing = True
            self._paint_brush(x, y)
            self._update_display()
        elif self.current_tool == "eraser":
            self._save_undo()
            self.drawing = True
            self._erase_at(x, y, radius=self.eraser_size)
            self._update_display()

    def _on_mouse_moved(self, x: int, y: int):
        """Handle mouse move event (for preview)."""
        x = max(0, min(x, self.width - 1))
        y = max(0, min(y, self.height - 1))
        self.current_mouse_pos = (x, y)

        if self.current_tool == "rectangle" and self.drawing:
            self._update_display()
        elif self.current_tool == "brush" and self.drawing:
            self._paint_brush(x, y)
            self._update_display()
        elif self.current_tool == "eraser" and self.drawing:
            self._erase_at(x, y, radius=self.eraser_size)
            self._update_display()
        elif self.current_tool == "polygon" and len(self.polygon_points) > 0:
            self._update_display()

    def _on_mouse_released(self, x: int, y: int):
        """Handle mouse release event."""
        if not self.drawing:
            return

        x = max(0, min(x, self.width - 1))
        y = max(0, min(y, self.height - 1))

        self._save_undo()

        if self.current_tool == "rectangle":
            self._draw_rectangle(self.rect_start, (x, y))

        self.polygon_points = []
        self.drawing = False
        self._update_display()

    def finalize_polygon(self):
        """Finish current polygon and apply to mask."""
        if len(self.polygon_points) < 3:
            self.polygon_points = []
            self._update_display()
            return

        self._save_undo()
        self._draw_polygon(self.polygon_points)
        self.polygon_points = []
        self._update_display()

    def _draw_polygon(self, points: list[tuple[int, int]]):
        """Draw a filled polygon on the mask."""
        if len(points) < 3:
            return

        pts = np.array(points, dtype=np.int32)
        temp = np.zeros_like(self.mask)
        cv2.fillPoly(temp, [pts], 1.0)

        self._apply_combine(temp)

    def _draw_rectangle(self, pt1: tuple[int, int], pt2: tuple[int, int]):
        """Draw a filled rectangle on the mask."""
        x1, y1 = pt1
        x2, y2 = pt2
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)

        temp = np.zeros_like(self.mask)
        temp[y_min : y_max + 1, x_min : x_max + 1] = 1.0

        self._apply_combine(temp)

    def _erase_at(self, x: int, y: int, radius: int = 15):
        """Erase a circular area from the mask."""
        cv2.circle(self.mask, (x, y), max(1, radius), 0.0, -1)

    def _paint_brush(self, x: int, y: int):
        """Paint a circular area to the mask (brush tool)."""
        temp = np.zeros_like(self.mask)
        cv2.circle(temp, (x, y), max(1, self.brush_size), 1.0, -1)
        self._apply_combine(temp)

    def _apply_combine(self, shape: np.ndarray):
        """Apply the combine mode to add a shape to the mask."""
        if self.combine_mode == "add":
            self.mask = np.maximum(self.mask, shape)
        elif self.combine_mode == "subtract":
            self.mask = np.maximum(self.mask - shape, 0.0)
        elif self.combine_mode == "intersect":
            self.mask = np.minimum(self.mask, shape)

    def undo(self):
        """Undo the last drawing action."""
        if self.undo_stack:
            self.mask = self.undo_stack.pop()
            self._update_display()

    def clear_all(self):
        """Clear all drawings."""
        self._save_undo()
        self.mask = np.zeros_like(self.mask)
        self.polygon_points = []
        self.rect_start = None
        self.drawing = False
        self._update_display()

    def _save_undo(self):
        """Save current mask to undo stack."""
        self.undo_stack.append(self.mask.copy())

    def _update_display(self):
        """Redraw the canvas with the current mask overlay."""
        if not self.base_cache_valid:
            self._rebuild_display_cache()

        overlay = self.cached_base_image.copy()
        mask_indices = self.mask > 0.5
        if mask_indices.any():
            overlay[mask_indices] = (
                np.array(self.mask_color, dtype=np.float32) * overlay[mask_indices]
            )

        # Draw preview shapes
        if (
            self.drawing
            and self.current_tool == "rectangle"
            and self.rect_start is not None
            and self.current_mouse_pos is not None
        ):
            x1, y1 = self.rect_start
            x2, y2 = self.current_mouse_pos
            x_min, x_max = min(x1, x2), max(x1, x2)
            y_min, y_max = min(y1, y2), max(y1, y2)
            line_thickness = 6
            offset = line_thickness // 2
            cv2.rectangle(
                overlay,
                (x_min + offset, y_min + offset),
                (x_max - offset, y_max - offset),
                (0.0, 1.0, 0.0),
                line_thickness,
            )

        if self.current_tool == "brush" and self.current_mouse_pos is not None:
            cv2.circle(overlay, self.current_mouse_pos, self.brush_size, (1.0, 1.0, 0.0), 2)
        elif self.current_tool == "eraser" and self.current_mouse_pos is not None:
            cv2.circle(overlay, self.current_mouse_pos, self.eraser_size, (1.0, 0.0, 1.0), 2)

        if self.current_tool == "polygon" and len(self.polygon_points) > 0:
            if len(self.polygon_points) > 1:
                pts = np.array(self.polygon_points, dtype=np.int32)
                cv2.polylines(overlay, [pts], False, (0.0, 1.0, 0.0), 6)

            for pt in self.polygon_points:
                cv2.circle(overlay, pt, 4, (0.0, 1.0, 0.0), -1)

            if self.current_mouse_pos is not None and len(self.polygon_points) > 1:
                last_pt = self.polygon_points[-1]
                cv2.line(overlay, last_pt, self.current_mouse_pos, (0.0, 1.0, 0.0), 6)

        self.canvas_view.set_image(overlay)

    def _rebuild_display_cache(self):
        """Rebuild the cached base display (expensive operations)."""
        img_norm = to_float(self.original_image)
        lo, hi = robust_minmax(img_norm, 1.0, 99.0)
        if hi <= lo:
            hi = lo + 1e-6
        img_disp = (img_norm - lo) / (hi - lo)
        img_disp = np.clip(img_disp, 0.0, 1.0)

        img_disp = self._apply_display_adjustments(img_disp)

        self.cached_base_image = np.stack([img_disp, img_disp, img_disp], axis=-1)
        self.base_cache_valid = True

    def _apply_display_adjustments(self, img: np.ndarray) -> np.ndarray:
        """Apply contrast, brightness, and gamma adjustments."""
        result = img + self.display_brightness
        result = 0.5 + self.display_contrast * (result - 0.5)

        if self.display_gamma != 1.0:
            result = np.clip(result, 0.0, 1.0)
            result = np.power(result, 1.0 / self.display_gamma)

        return np.clip(result, 0.0, 1.0).astype(np.float32)

    def get_mask(self) -> np.ndarray:
        """Return the current binary mask."""
        return (self.mask > 0.5).astype(np.float32)

    def set_display_contrast(self, value: float):
        """Set contrast adjustment (1.0 = no change, >1 = increase, <1 = decrease)."""
        self.display_contrast = value
        self.base_cache_valid = False
        self._update_display()

    def set_display_brightness(self, value: float):
        """Set brightness adjustment (-1.0 to +1.0)."""
        self.display_brightness = value
        self.base_cache_valid = False
        self._update_display()

    def set_display_gamma(self, value: float):
        """Set gamma correction (1.0 = no change, <1 = brighten, >1 = darken)."""
        self.display_gamma = max(0.1, value)
        self.base_cache_valid = False
        self._update_display()

    def set_mask_color(self, r: float, g: float, b: float):
        """Set the mask overlay color (0-1 range)."""
        self.mask_color = (r, g, b)
        self._update_display()

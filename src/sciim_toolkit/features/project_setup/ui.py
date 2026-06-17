from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.models.project import ProjectSession


class ProjectSetupTab(QtWidgets.QWidget):
    session_changed = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: ProjectSession | None = None
        self._is_loading_ui = False
        self._build_ui()
        self._bind_signals()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)

        form_group = QtWidgets.QGroupBox("Project Setup")
        form = QtWidgets.QFormLayout(form_group)

        self.ed_title = QtWidgets.QLineEdit()
        self.ed_artist = QtWidgets.QLineEdit()
        self.sp_width = QtWidgets.QDoubleSpinBox()
        self.sp_width.setRange(0.0, 10000.0)
        self.sp_width.setDecimals(1)
        self.sp_width.setSuffix(" cm")
        self.sp_height = QtWidgets.QDoubleSpinBox()
        self.sp_height.setRange(0.0, 10000.0)
        self.sp_height.setDecimals(1)
        self.sp_height.setSuffix(" cm")
        self.ed_hki = QtWidgets.QLineEdit()
        self.ed_collection = QtWidgets.QLineEdit()
        self.ed_inventory = QtWidgets.QLineEdit()
        self.ed_image_path = QtWidgets.QLineEdit()
        self.ed_image_path.setReadOnly(True)
        self.ed_image_path.setPlaceholderText("No painting image selected")
        self.btn_load_image = QtWidgets.QPushButton("Load painting image…")

        dimensions = QtWidgets.QHBoxLayout()
        dimensions.addWidget(self.sp_height)
        dimensions.addWidget(QtWidgets.QLabel("×"))
        dimensions.addWidget(self.sp_width)
        dimensions_wrap = QtWidgets.QWidget()
        dimensions_wrap.setLayout(dimensions)

        form.addRow("Title", self.ed_title)
        form.addRow("Artist", self.ed_artist)
        form.addRow("Dimensions (HxW)", dimensions_wrap)
        form.addRow("HKI number", self.ed_hki)
        form.addRow("Collection", self.ed_collection)
        form.addRow("Inv. #", self.ed_inventory)
        form.addRow(self.btn_load_image)
        form.addRow("Painting image", self.ed_image_path)

        self.preview = QtWidgets.QLabel("No painting image loaded")
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setStyleSheet("border: 1px solid #aaa; background: #111; color: #ddd;")

        content_layout.addWidget(form_group)
        content_layout.addWidget(self.preview, 1)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _bind_signals(self) -> None:
        self.ed_title.textChanged.connect(self._pull_ui_into_session)
        self.ed_artist.textChanged.connect(self._pull_ui_into_session)
        self.sp_width.valueChanged.connect(self._pull_ui_into_session)
        self.sp_height.valueChanged.connect(self._pull_ui_into_session)
        self.ed_hki.textChanged.connect(self._pull_ui_into_session)
        self.ed_collection.textChanged.connect(self._pull_ui_into_session)
        self.ed_inventory.textChanged.connect(self._pull_ui_into_session)
        self.btn_load_image.clicked.connect(self._on_load_image)

    def set_session(self, session: ProjectSession) -> None:
        self._session = session
        self._push_session_to_ui()

    def _push_session_to_ui(self) -> None:
        if self._session is None:
            return

        self._is_loading_ui = True
        try:
            art = self._session.artwork
            self.ed_title.setText(art.title)
            self.ed_artist.setText(art.artist)
            self.sp_width.setValue(art.width_cm)
            self.sp_height.setValue(art.height_cm)
            self.ed_hki.setText(art.hki)
            self.ed_collection.setText(art.collection)
            self.ed_inventory.setText(art.inventory_id)

            path = self._session.imaging_planner.painting_image_path
            self.ed_image_path.setText(path)
            self.ed_image_path.setToolTip(path or "No image selected")
            self._load_preview_pixmap(Path(path) if path else None)
        finally:
            self._is_loading_ui = False

    def _pull_ui_into_session(self) -> None:
        if self._session is None or self._is_loading_ui:
            return

        art = self._session.artwork
        art.title = self.ed_title.text().strip()
        art.artist = self.ed_artist.text().strip()
        art.width_cm = float(self.sp_width.value())
        art.height_cm = float(self.sp_height.value())
        art.hki = self.ed_hki.text().strip()
        art.collection = self.ed_collection.text().strip()
        art.inventory_id = self.ed_inventory.text().strip()
        self.session_changed.emit()

    def _on_load_image(self) -> None:
        if self._session is None:
            return

        start_dir = str(Path.home())
        if self._session.imaging_planner.painting_image_path:
            start_dir = str(Path(self._session.imaging_planner.painting_image_path).parent)

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load painting image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not path:
            return

        self._session.imaging_planner.painting_image_path = path
        self.ed_image_path.setText(path)
        self.ed_image_path.setToolTip(path)
        self._load_preview_pixmap(Path(path))
        self.session_changed.emit()

    def _load_preview_pixmap(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.preview.setPixmap(QtGui.QPixmap())
            self.preview.setText("No painting image loaded")
            return

        pixmap = QtGui.QPixmap(str(path))
        if pixmap.isNull():
            self.preview.setPixmap(QtGui.QPixmap())
            self.preview.setText("Failed to load image")
            return

        self.preview.setText("")
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        path = self.ed_image_path.text().strip()
        self._load_preview_pixmap(Path(path) if path else None)

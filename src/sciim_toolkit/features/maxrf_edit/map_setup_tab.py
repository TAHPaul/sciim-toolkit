"""
Map Setup tab for MA-XRF pipeline: folder selection, element/line detection, and raw data ingest.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from sciim_toolkit.models.project import ProjectSession

logger = logging.getLogger(__name__)


class MapSetupTab(QWidget):
    """Tab for ingesting MA-XRF elemental maps into project workspace."""

    session_changed = Signal(object)  # emits updated ProjectSession
    folder_loaded = Signal()  # emitted when folder is successfully populated

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session: ProjectSession | None = None
        self.current_folder: Path | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()

        # Folder selection button
        self.browse_btn = QPushButton("Select Folder with Maps")
        self.browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self.browse_btn)

        # Table for files
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Filename", "Element", "Line Family", "Copy", "Status"]
        )
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        # Control buttons
        button_layout = QVBoxLayout()
        
        self.check_all_btn = QPushButton("Check All")
        self.check_all_btn.clicked.connect(self._check_all)
        button_layout.addWidget(self.check_all_btn)

        self.uncheck_all_btn = QPushButton("Uncheck All")
        self.uncheck_all_btn.clicked.connect(self._uncheck_all)
        button_layout.addWidget(self.uncheck_all_btn)

        self.ingest_btn = QPushButton("Copy Checked Files to Project")
        self.ingest_btn.clicked.connect(self._on_ingest)
        button_layout.addWidget(self.ingest_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def set_session(self, session: ProjectSession) -> None:
        """Set the current project session and load from existing raw_data if available."""
        self.session = session
        
        # Debug logging
        logger.info(f"MapSetupTab.set_session() called")
        logger.info(f"  project_root: '{session.maxrf_pipeline.project_root}'")
        logger.info(f"  last_selected_folder: '{session.maxrf_pipeline.last_selected_folder}'")
        
        # If loading an existing project with workspace, check for raw_data folder
        if session.maxrf_pipeline.project_root:
            project_root = Path(session.maxrf_pipeline.project_root)
            raw_data_path = project_root / "raw_data"
            logger.info(f"  Checking for raw_data at: {raw_data_path}")
            logger.info(f"  raw_data exists: {raw_data_path.exists()}")
            
            if raw_data_path.exists():
                # Load existing files from raw_data and manifest
                logger.info(f"  Loading from existing raw_data")
                self._load_from_raw_data(raw_data_path, project_root)
                return
            else:
                logger.info(f"  raw_data folder does not exist yet")
                # Project exists but raw_data folder not yet created - show empty
                self.table.setRowCount(0)
                return
        
        logger.info(f"  No project_root, checking last_selected_folder")
        # No project - restore last folder if available for new ingest
        if session.maxrf_pipeline.last_selected_folder:
            self.current_folder = Path(session.maxrf_pipeline.last_selected_folder)
            logger.info(f"  Restoring folder: {self.current_folder}")
            self._populate_table()
            return
        
        logger.info(f"  No folder to load, clearing table")
        self.table.setRowCount(0)
    
    def _load_from_raw_data(self, raw_data_path: Path, project_root: Path) -> None:
        """Load files from existing raw_data folder and manifest."""
        # Read manifest if available
        manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
        manifest_data = {}
        if manifest_path.exists():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        
        map_registry = manifest_data.get("map_registry", {})
        
        # Get all image files from raw_data
        image_extensions = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
        files = sorted(
            f
            for f in raw_data_path.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        )
        
        self.table.setRowCount(len(files))
        
        for idx, fpath in enumerate(files):
            # Filename
            fn_item = QTableWidgetItem(fpath.name)
            fn_item.setFlags(fn_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(idx, 0, fn_item)
            
            # Get element/line from manifest if available
            element = "None"
            line_family = ""
            map_id = fpath.stem
            
            if map_id in map_registry:
                element = map_registry[map_id].get("element", "None")
                line_family = map_registry[map_id].get("line_family", "")
            else:
                # Fallback to detection
                element, line_family = self._detect_element_and_line(fpath.stem)
            
            # Element (editable dropdown)
            elem_combo = QComboBox()
            elem_combo.addItems(self._get_element_list())
            if element:
                idx_elem = elem_combo.findText(element)
                if idx_elem >= 0:
                    elem_combo.setCurrentIndex(idx_elem)
            self.table.setCellWidget(idx, 1, elem_combo)
            
            # Line Family (editable dropdown)
            line_combo = QComboBox()
            line_combo.addItems(["K", "L", "M", ""])
            if line_family:
                idx_line = line_combo.findText(line_family)
                if idx_line >= 0:
                    line_combo.setCurrentIndex(idx_line)
            self.table.setCellWidget(idx, 2, line_combo)
            
            # Copy checkbox - already copied, so uncheck and disable
            copy_item = QTableWidgetItem()
            copy_item.setCheckState(Qt.CheckState.Unchecked)
            copy_item.setFlags(copy_item.flags() & ~Qt.ItemIsUserCheckable)  # Disabled
            self.table.setItem(idx, 3, copy_item)
            
            # Status - mark as already copied
            status_item = QTableWidgetItem("Already in raw_data")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(idx, 4, status_item)

    def _on_browse(self) -> None:
        """Browse for folder containing elemental maps."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with Maps")
        if folder:
            self.current_folder = Path(folder)
            if self.session:
                self.session.maxrf_pipeline.last_selected_folder = str(self.current_folder)
                self.session.touch()
                self.session_changed.emit(self.session)
            self._populate_table()

    def _populate_table(self) -> None:
        """Scan folder and populate table with detected maps."""
        if not self.current_folder or not self.current_folder.is_dir():
            QMessageBox.warning(self, "Invalid Folder", "Please select a valid folder.")
            return

        # Get all image files
        image_extensions = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
        files = sorted(
            f
            for f in self.current_folder.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        )

        self.table.setRowCount(len(files))

        for idx, fpath in enumerate(files):
            # Filename
            fn_item = QTableWidgetItem(fpath.name)
            fn_item.setFlags(fn_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(idx, 0, fn_item)

            # Element (editable dropdown)
            element, line_family = self._detect_element_and_line(fpath.stem)
            elem_combo = QComboBox()
            elem_combo.addItems(self._get_element_list())
            if element:
                idx_elem = elem_combo.findText(element)
                if idx_elem >= 0:
                    elem_combo.setCurrentIndex(idx_elem)
            self.table.setCellWidget(idx, 1, elem_combo)

            # Line Family (editable dropdown)
            line_combo = QComboBox()
            line_combo.addItems(["K", "L", "M", ""])  # Include empty option for non-elemental
            if line_family:
                idx_line = line_combo.findText(line_family)
                if idx_line >= 0:
                    line_combo.setCurrentIndex(idx_line)
            self.table.setCellWidget(idx, 2, line_combo)

            # Copy checkbox
            copy_item = QTableWidgetItem()
            copy_item.setCheckState(Qt.CheckState.Checked)
            copy_item.setFlags(copy_item.flags() | Qt.ItemIsUserCheckable)
            self.table.setItem(idx, 3, copy_item)

            # Status
            status_item = QTableWidgetItem("Ready")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(idx, 4, status_item)

        # Emit signal to trigger tab switch in main window
        self.folder_loaded.emit()

    def _detect_element_and_line(self, filename_stem: str) -> tuple[str, str]:
        """Detect element and line family from filename using XRF naming conventions.
        
        Returns ("None", "") if no element is detected (e.g., Continuum, chisq).
        """
        upper_stem = filename_stem.upper()

        # Special cases: non-elemental maps
        if upper_stem in ("CONTINUUM", "CHISQ", "CHI2", "CHI_SQ", "BACKGROUND"):
            return "None", ""

        # Find line family (K, L, M) in stem
        line_families_order = ["M", "L", "K"]

        for line in line_families_order:
            if line not in upper_stem:
                continue

            # Find the position of the line family
            line_pos = upper_stem.rfind(line)
            before_line = upper_stem[:line_pos]

            if not before_line:
                continue

            # Try 2-letter element symbols first (more specific: Cl, Fe, Cu, etc.)
            for length in [2, 1]:
                candidate = before_line[-length:].strip()
                if self._is_valid_element_symbol(candidate):
                    return candidate.title(), line

        # No line family found, but check if there's a standalone element symbol
        for elem in self._get_element_list():
            if elem.upper() in upper_stem:
                return elem, ""

        # No element detected
        return "None", ""

    def _is_valid_element_symbol(self, symbol: str) -> bool:
        """Check if symbol is a valid element."""
        valid = {
            "H",
            "He",
            "Li",
            "Be",
            "B",
            "C",
            "N",
            "O",
            "F",
            "Ne",
            "Na",
            "Mg",
            "Al",
            "Si",
            "P",
            "S",
            "Cl",
            "Ar",
            "K",
            "Ca",
            "Sc",
            "Ti",
            "V",
            "Cr",
            "Mn",
            "Fe",
            "Co",
            "Ni",
            "Cu",
            "Zn",
            "Ga",
            "Ge",
            "As",
            "Se",
            "Br",
            "Kr",
            "Rb",
            "Sr",
            "Y",
            "Zr",
            "Nb",
            "Mo",
            "Tc",
            "Ru",
            "Rh",
            "Pd",
            "Ag",
            "Cd",
            "In",
            "Sn",
            "Sb",
            "Te",
            "I",
            "Xe",
            "Cs",
            "Ba",
            "La",
            "Ce",
            "Pr",
            "Nd",
            "Pm",
            "Sm",
            "Eu",
            "Gd",
            "Tb",
            "Dy",
            "Ho",
            "Er",
            "Tm",
            "Yb",
            "Lu",
            "Hf",
            "Ta",
            "W",
            "Re",
            "Os",
            "Ir",
            "Pt",
            "Au",
            "Hg",
            "Tl",
            "Pb",
            "Bi",
            "Po",
            "At",
            "Rn",
            "Fr",
            "Ra",
            "Ac",
            "Th",
            "Pa",
            "U",
        }
        return symbol.title() in valid

    def _get_element_list(self) -> list[str]:
        """Return list of all element symbols plus None for non-elemental maps."""
        return [
            "None",  # For non-elemental maps like Continuum, chisq
            "H",
            "He",
            "Li",
            "Be",
            "B",
            "C",
            "N",
            "O",
            "F",
            "Ne",
            "Na",
            "Mg",
            "Al",
            "Si",
            "P",
            "S",
            "Cl",
            "Ar",
            "K",
            "Ca",
            "Sc",
            "Ti",
            "V",
            "Cr",
            "Mn",
            "Fe",
            "Co",
            "Ni",
            "Cu",
            "Zn",
            "Ga",
            "Ge",
            "As",
            "Se",
            "Br",
            "Kr",
            "Rb",
            "Sr",
            "Y",
            "Zr",
            "Nb",
            "Mo",
            "Tc",
            "Ru",
            "Rh",
            "Pd",
            "Ag",
            "Cd",
            "In",
            "Sn",
            "Sb",
            "Te",
            "I",
            "Xe",
            "Cs",
            "Ba",
            "La",
            "Ce",
            "Pr",
            "Nd",
            "Pm",
            "Sm",
            "Eu",
            "Gd",
            "Tb",
            "Dy",
            "Ho",
            "Er",
            "Tm",
            "Yb",
            "Lu",
            "Hf",
            "Ta",
            "W",
            "Re",
            "Os",
            "Ir",
            "Pt",
            "Au",
            "Hg",
            "Tl",
            "Pb",
            "Bi",
            "Po",
            "At",
            "Rn",
            "Fr",
            "Ra",
            "Ac",
            "Th",
            "Pa",
            "U",
        ]

    def _check_all(self) -> None:
        """Check all copy checkboxes."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 3)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _uncheck_all(self) -> None:
        """Uncheck all copy checkboxes."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 3)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_ingest(self) -> None:
        """Copy checked files to project's raw_data folder and create manifest."""
        if not self.session or not self.session.project_file:
            QMessageBox.critical(
                self, "No Project", "Please create or open a project first."
            )
            return

        if not self.current_folder:
            QMessageBox.warning(self, "No Folder", "Please select a folder first.")
            return

        # Determine project root folder (same directory as project file)
        project_dir = Path(self.session.project_file).parent
        maxrf_root = project_dir / "MA-XRF_workspace"

        # Create folder structure
        raw_data_folder = maxrf_root / "raw_data"
        corrected_maps_folder = maxrf_root / "corrected_maps"
        false_coloured_folder = maxrf_root / "false_coloured_maps"
        metadata_folder = maxrf_root / "metadata" / "logs"

        try:
            raw_data_folder.mkdir(parents=True, exist_ok=True)
            corrected_maps_folder.mkdir(parents=True, exist_ok=True)
            false_coloured_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Folder Creation Error", f"Failed to create folders: {e}")
            logging.error(f"Failed to create MA-XRF workspace: {e}")
            return

        # Update session
        self.session.maxrf_pipeline.project_root = str(maxrf_root)

        # Copy files and build manifest
        map_registry = {}
        copied_count = 0

        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 3)
            if not check_item or check_item.checkState() != Qt.CheckState.Checked:
                continue

            filename_item = self.table.item(row, 0)
            filename = filename_item.text()
            orig_path = self.current_folder / filename

            # Get element and line from widgets
            elem_combo = self.table.cellWidget(row, 1)
            line_combo = self.table.cellWidget(row, 2)
            element = elem_combo.currentText() if elem_combo else ""
            line_family = line_combo.currentText() if line_combo else ""

            # Copy file
            try:
                dest_path = raw_data_folder / filename
                shutil.copy2(orig_path, dest_path)
                copied_count += 1
            except Exception as e:
                logger.error(f"Failed to copy {filename}: {e}")
                if check_item := self.table.item(row, 4):
                    check_item.setText(f"Error: {e}")
                continue

            # Add to registry
            map_id = orig_path.stem  # filename without extension
            map_registry[map_id] = {
                "map_id": map_id,
                "filename": filename,
                "element": element,
                "line_family": line_family,
                "original_path": str(orig_path),
                "copied_to_raw": True,
                "corrections_applied": False,
                "false_colour_variants": [],
                "overlay_variants": [],
            }

            # Update status
            if status_item := self.table.item(row, 4):
                status_item.setText("Copied")

        # Write manifest
        manifest = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "project_root": str(maxrf_root),
            "map_registry": map_registry,
        }

        manifest_path = metadata_folder / "map_manifest.json"
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            logger.info(f"Manifest written to {manifest_path}")
        except Exception as e:
            logger.error(f"Failed to write manifest: {e}")

        # Update session registry
        for map_id, record_dict in map_registry.items():
            from sciim_toolkit.models.project import MaxrfMapRecord
            self.session.maxrf_pipeline.map_registry[map_id] = MaxrfMapRecord(**record_dict)

        # Emit signal and show success
        self.session.touch()
        self.session_changed.emit(self.session)
        self.folder_loaded.emit()

        QMessageBox.information(
            self, "Success", f"Copied {copied_count} file(s) to project workspace."
        )

        logger.info(f"Ingest complete: {copied_count} files copied to {raw_data_folder}")

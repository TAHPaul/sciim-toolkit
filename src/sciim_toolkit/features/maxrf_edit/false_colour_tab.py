from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.maxrf_corrections.image_io import normalize_feature, read_image


ELEMENT_SYMBOLS = [
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
]

ELEMENT_NAMES = [
    "hydrogen", "helium", "lithium", "beryllium", "boron", "carbon", "nitrogen", "oxygen", "fluorine", "neon",
    "sodium", "magnesium", "aluminium", "silicon", "phosphorus", "sulfur", "chlorine", "argon", "potassium", "calcium",
    "scandium", "titanium", "vanadium", "chromium", "manganese", "iron", "cobalt", "nickel", "copper", "zinc",
    "gallium", "germanium", "arsenic", "selenium", "bromine", "krypton", "rubidium", "strontium", "yttrium", "zirconium",
    "niobium", "molybdenum", "technetium", "ruthenium", "rhodium", "palladium", "silver", "cadmium", "indium", "tin",
    "antimony", "tellurium", "iodine", "xenon", "cesium", "barium", "lanthanum", "cerium", "praseodymium", "neodymium",
    "promethium", "samarium", "europium", "gadolinium", "terbium", "dysprosium", "holmium", "erbium", "thulium", "ytterbium",
    "lutetium", "hafnium", "tantalum", "tungsten", "rhenium", "osmium", "iridium", "platinum", "gold", "mercury",
    "thallium", "lead", "bismuth", "polonium", "astatine", "radon", "francium", "radium", "actinium", "thorium",
    "protactinium", "uranium", "neptunium", "plutonium", "americium", "curium", "berkelium", "californium", "einsteinium", "fermium",
    "mendelevium", "nobelium", "lawrencium", "rutherfordium", "dubnium", "seaborgium", "bohrium", "hassium", "meitnerium", "darmstadtium",
    "roentgenium", "copernicium", "nihonium", "flerovium", "moscovium", "livermorium", "tennessine", "oganesson",
]

NAME_TO_SYMBOL = {name: symbol for name, symbol in zip(ELEMENT_NAMES, ELEMENT_SYMBOLS)}
SYMBOL_SET = set(ELEMENT_SYMBOLS)

DEFAULT_PALETTE = [
    "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff",
    "#ffa500", "#8a2be2", "#1e90ff", "#2e8b57", "#dc143c", "#ffd700",
]

BUILTIN_PROFILES: dict[str, dict[str, str]] = {
    "Default": {},
    "HKI/Fitz": {
        "Fe": "#ff4b4b",
        "Cu": "#4bb2ff",
        "Pb": "#ffd84b",
        "Hg": "#c74bff",
        "Co": "#4bffb2",
        "Mn": "#ff8a4b",
        "Cr": "#7dff4b",
        "Ni": "#4b7dff",
        "Zn": "#ff4ba8",
    },
}


@dataclass
class FalseColourEntry:
    path: Path  # path to the actual file being used (raw or corrected)
    element: str
    line_family: str
    color: str
    export_enabled: bool = True
    raw_path: Path | None = None  # raw data version (if available)
    corrected_path: Path | None = None  # corrected version (if available)
    using_corrected: bool = False  # which source are we using?


class MaxrfFalseColourTab(QtWidgets.QWidget):
    """Folder-wide MA-XRF false-colouring tab."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        
        # Project session (set via set_session if working from project)
        self.session = None
        
        self.work_folder: Path | None = None
        self.entries: list[FalseColourEntry] = []
        self._norm_cache: dict[Path, np.ndarray] = {}
        self.profile_colors: dict[str, str] = {}
        self.active_profile_name = "Default"
        self.user_profiles_path = Path.home() / ".sciim_false_colour_profiles.json"
        self.user_profiles: dict[str, dict[str, str]] = self._read_user_profiles()
        self._project_root: Path | None = None  # Track project root for refreshing

        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QHBoxLayout(self)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        top_row = QtWidgets.QHBoxLayout()
        self.btn_browse = QtWidgets.QPushButton("Select folder…")
        self.lbl_folder = QtWidgets.QLabel("No folder selected")
        self.lbl_folder.setWordWrap(True)
        top_row.addWidget(self.btn_browse)
        top_row.addWidget(self.lbl_folder, 1)
        left_layout.addLayout(top_row)

        self.table_maps = QtWidgets.QTableWidget(0, 6)
        self.table_maps.setHorizontalHeaderLabels(["Filename", "Element", "Line", "Source", "Colour", "Export"])
        self.table_maps.horizontalHeader().setStretchLastSection(False)
        self.table_maps.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table_maps.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_maps.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_maps.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_maps.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_maps.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table_maps.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_maps.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table_maps.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        left_layout.addWidget(self.table_maps, 1)

        export_toggle_row = QtWidgets.QHBoxLayout()
        self.btn_check_all_export = QtWidgets.QPushButton("Check all")
        self.btn_uncheck_all_export = QtWidgets.QPushButton("Uncheck all")
        export_toggle_row.addWidget(self.btn_check_all_export)
        export_toggle_row.addWidget(self.btn_uncheck_all_export)
        export_toggle_row.addStretch(1)
        left_layout.addLayout(export_toggle_row)

        self.lbl_profile = QtWidgets.QLabel("Active colour profile: Default")
        self.lbl_profile.setStyleSheet("color: #444; font-style: italic;")
        left_layout.addWidget(self.lbl_profile)

        profile_row = QtWidgets.QHBoxLayout()
        self.combo_profiles = QtWidgets.QComboBox()
        self.btn_apply_profile = QtWidgets.QPushButton("Apply profile")
        self.btn_set_startup_profile = QtWidgets.QPushButton("Set as startup default")
        profile_row.addWidget(QtWidgets.QLabel("Profile"))
        profile_row.addWidget(self.combo_profiles, 1)
        profile_row.addWidget(self.btn_apply_profile)
        left_layout.addLayout(profile_row)

        profile_io_row = QtWidgets.QHBoxLayout()
        self.btn_import_profile = QtWidgets.QPushButton("Import colour profile…")
        self.btn_export_profile = QtWidgets.QPushButton("Export colour profile…")
        profile_io_row.addWidget(self.btn_import_profile)
        profile_io_row.addWidget(self.btn_export_profile)
        profile_io_row.addStretch(1)
        left_layout.addLayout(profile_io_row)

        left_layout.addWidget(self.btn_set_startup_profile)

        self.btn_export_all = QtWidgets.QPushButton("Export false-coloured set…")
        left_layout.addWidget(self.btn_export_all)

        self.btn_export_selected = QtWidgets.QPushButton("Export selected element…")
        left_layout.addWidget(self.btn_export_selected)

        left_layout.addStretch(1)

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(560)
        left_scroll.setWidget(left)

        splitter.addWidget(left_scroll)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        self.lbl_preview_title = QtWidgets.QLabel("Preview")
        self.lbl_preview_title.setStyleSheet("font-weight: 600;")
        self.lbl_preview = QtWidgets.QLabel("Load a folder and select a map")
        self.lbl_preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setMinimumSize(320, 240)
        self.lbl_preview.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.lbl_preview.setStyleSheet("border: 1px solid #888; background: #111; color: #ddd;")
        right_layout.addWidget(self.lbl_preview_title)
        right_layout.addWidget(self.lbl_preview, 1)
        splitter.addWidget(right)

        splitter.setHandleWidth(8)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([620, 920])

        self.btn_browse.clicked.connect(self.browse_folder)
        self.table_maps.itemSelectionChanged.connect(self._update_preview)
        self.btn_check_all_export.clicked.connect(self.check_all_export)
        self.btn_uncheck_all_export.clicked.connect(self.uncheck_all_export)
        self.btn_import_profile.clicked.connect(self.import_colour_profile)
        self.btn_export_profile.clicked.connect(self.export_colour_profile)
        self.btn_apply_profile.clicked.connect(self.apply_selected_profile)
        self.btn_set_startup_profile.clicked.connect(self.set_startup_default_profile)
        self.btn_export_all.clicked.connect(self.export_false_coloured_set)
        self.btn_export_selected.clicked.connect(self.export_selected_element)

        self._refresh_profile_selector()
        self._load_startup_profile()

    def browse_folder(self) -> None:
        start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select folder with elemental maps",
            start_dir,
        )
        if not folder:
            return

        self._load_from_folder(Path(folder))

    def _load_from_folder(self, selected: Path) -> None:
        """Load elemental maps directly from a selected folder in standalone mode."""
        exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
        files = sorted([p for p in selected.iterdir() if p.is_file() and p.suffix.lower() in exts])

        self.work_folder = selected
        self.lbl_folder.setText(selected.name)

        if not files:
            self.entries = []
            self.table_maps.setRowCount(0)
            self.lbl_preview.setText("No supported image files in selected folder")
            self.lbl_preview.setPixmap(QtGui.QPixmap())
            QtWidgets.QMessageBox.warning(
                self,
                "No images found",
                f"The selected folder '{selected.name}' contains no supported image files.",
            )
            return

        self.entries = []
        for idx, path in enumerate(files):
            element, line_family = self._detect_element_and_line_from_filename(path.stem)
            self.entries.append(
                FalseColourEntry(
                    path=path,
                    element=element,
                    line_family=line_family,
                    color=self._default_colour_for_element(element, idx),
                    export_enabled=True,
                )
            )

        self._refresh_table()
        if self.entries:
            self.table_maps.selectRow(0)
            self._update_preview()

    def _default_colour_for_element(self, element: str, idx: int) -> str:
        prof = self.profile_colors.get(element)
        if prof:
            return prof
        if element in SYMBOL_SET:
            elem_idx = ELEMENT_SYMBOLS.index(element)
            return DEFAULT_PALETTE[elem_idx % len(DEFAULT_PALETTE)]
        return DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)]

    def _read_user_profiles(self) -> dict[str, dict[str, str]]:
        if not self.user_profiles_path.exists():
            return {}
        try:
            raw = json.loads(self.user_profiles_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {}
            cleaned: dict[str, dict[str, str]] = {}
            for name, mapping in raw.items():
                if not isinstance(name, str) or not isinstance(mapping, dict):
                    continue
                colors: dict[str, str] = {}
                for symbol, color in mapping.items():
                    if (
                        isinstance(symbol, str)
                        and isinstance(color, str)
                        and symbol in SYMBOL_SET
                        and re.match(r"^#[0-9a-fA-F]{6}$", color)
                    ):
                        colors[symbol] = color
                cleaned[name] = colors
            return cleaned
        except Exception:
            return {}

    def _write_user_profiles(self) -> None:
        self.user_profiles_path.write_text(json.dumps(self.user_profiles, indent=2), encoding="utf-8")

    def _all_profiles(self) -> dict[str, dict[str, str]]:
        merged: dict[str, dict[str, str]] = {k: dict(v) for k, v in BUILTIN_PROFILES.items()}
        for name, mapping in self.user_profiles.items():
            merged[name] = dict(mapping)
        return merged

    def _refresh_profile_selector(self) -> None:
        current = self.combo_profiles.currentText() if hasattr(self, "combo_profiles") else ""
        names = list(BUILTIN_PROFILES.keys()) + sorted(
            [n for n in self.user_profiles.keys() if n not in BUILTIN_PROFILES]
        )
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        self.combo_profiles.addItems(names)
        if current and current in names:
            self.combo_profiles.setCurrentText(current)
        elif self.active_profile_name in names:
            self.combo_profiles.setCurrentText(self.active_profile_name)
        self.combo_profiles.blockSignals(False)

    def _set_active_profile(self, profile_name: str) -> None:
        profiles = self._all_profiles()
        colors = profiles.get(profile_name)
        if colors is None:
            return
        self.active_profile_name = profile_name
        self.profile_colors = dict(colors)
        self.lbl_profile.setText(f"Active colour profile: {self.active_profile_name}")

    def apply_selected_profile(self) -> None:
        profile_name = self.combo_profiles.currentText()
        if not profile_name:
            return
        self._set_active_profile(profile_name)
        self._auto_assign_colours()

    def _load_startup_profile(self) -> None:
        settings = QtCore.QSettings("SCIIM", "MaxrfFalseColour")
        profile_name = settings.value("defaultColourProfile", "Default")
        if not isinstance(profile_name, str):
            profile_name = "Default"
        self._set_active_profile(profile_name if profile_name in self._all_profiles() else "Default")
        self._refresh_profile_selector()

    def set_startup_default_profile(self) -> None:
        profile_name = self.combo_profiles.currentText()
        if not profile_name:
            return
        self._set_active_profile(profile_name)
        settings = QtCore.QSettings("SCIIM", "MaxrfFalseColour")
        settings.setValue("defaultColourProfile", profile_name)
        QtWidgets.QMessageBox.information(
            self,
            "Startup profile saved",
            f"'{profile_name}' will be used as startup default.",
        )

    def _build_profile_payload(self) -> dict[str, object]:
        colors: dict[str, str] = {}
        for entry in self.entries:
            if entry.element in SYMBOL_SET:
                colors[entry.element] = entry.color

        for symbol, color in self.profile_colors.items():
            if symbol in SYMBOL_SET and re.match(r"^#[0-9a-fA-F]{6}$", color):
                colors[symbol] = color

        return {
            "name": self.active_profile_name,
            "colors": {k: colors[k] for k in sorted(colors.keys())},
        }

    def export_colour_profile(self) -> None:
        payload = self._build_profile_payload()

        start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
        suggested = "false_colour_profile.json"
        if self.active_profile_name and self.active_profile_name != "Default":
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", self.active_profile_name).strip("_")
            if safe_name:
                suggested = f"{safe_name}.json"

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export colour profile",
            str(Path(start_dir) / suggested),
            "JSON (*.json)",
        )
        if not path:
            return

        out_path = Path(path)
        if out_path.suffix.lower() != ".json":
            out_path = out_path.with_suffix(".json")

        try:
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            QtWidgets.QMessageBox.information(
                self,
                "Profile exported",
                f"Saved colour profile to:\n{out_path}",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(e))

    def import_colour_profile(self) -> None:
        start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import colour profile",
            start_dir,
            "JSON (*.json)",
        )
        if not path:
            return

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Import failed", f"Invalid JSON:\n{e}")
            return

        if not isinstance(data, dict) or not isinstance(data.get("colors"), dict):
            QtWidgets.QMessageBox.critical(
                self,
                "Import failed",
                "Profile format invalid. Expected object with 'colors' map.",
            )
            return

        imported_colors: dict[str, str] = {}
        for key, value in data["colors"].items():
            symbol = str(key)
            color = str(value)
            if symbol in SYMBOL_SET and re.match(r"^#[0-9a-fA-F]{6}$", color):
                imported_colors[symbol] = color

        if not imported_colors:
            QtWidgets.QMessageBox.warning(
                self,
                "Import profile",
                "No valid element-colour entries found in the selected profile.",
            )
            return

        self.profile_colors = imported_colors
        self.active_profile_name = str(data.get("name") or Path(path).stem)
        self.lbl_profile.setText(f"Active colour profile: {self.active_profile_name}")

        # Store imported profile so user can re-select it later.
        self.user_profiles[self.active_profile_name] = dict(imported_colors)
        self._write_user_profiles()
        self._refresh_profile_selector()
        self.combo_profiles.setCurrentText(self.active_profile_name)

        # Apply profile immediately to currently loaded entries.
        self._auto_assign_colours()

    def _detect_element_and_line_from_filename(self, stem: str) -> tuple[str, str]:
        lower_name = stem.lower()
        detected_line = "Unknown"

        # Prefer full element names first
        for name, symbol in NAME_TO_SYMBOL.items():
            if re.search(rf"(^|[^a-z]){re.escape(name)}([^a-z]|$)", lower_name):
                # If element full name is present, still try to infer K/L/M family.
                line_match = re.search(r"([KLM])(?:alpha|beta|a|b|1|2)?$", stem)
                if line_match:
                    detected_line = line_match.group(1)
                return symbol, detected_line

        # MA-XRF line notation detection (e.g., ArK, BaL, PbM, yAlK, FeKalpha)
        # We prioritize this to support common elemental-map naming conventions.
        # Split by separators first to avoid matching across unrelated chunks.
        parts = [p for p in re.split(r"[^A-Za-z0-9]+", stem) if p]
        line_pattern = re.compile(
            r"([A-Za-z]{1,2})([KLM])(?:alpha|beta|a|b|1|2)?$"
        )
        for part in parts:
            # Skip plain lowercase words like "continuum"/"chisq" to reduce false positives
            # from incidental trailing 'k'/'l'/'m'.
            if part.islower():
                continue

            # Try direct match first
            match = line_pattern.search(part)
            if match:
                candidate = match.group(1)
                detected_line = match.group(2)
                symbol = candidate[:1].upper() + candidate[1:].lower()
                if symbol in SYMBOL_SET:
                    return symbol, detected_line

            # Try suffix search in longer mixed strings (e.g., yAlK)
            for start in range(max(0, len(part) - 6), len(part)):
                sub = part[start:]
                match = line_pattern.search(sub)
                if not match:
                    continue
                candidate = match.group(1)
                detected_line = match.group(2)
                symbol = candidate[:1].upper() + candidate[1:].lower()
                if symbol in SYMBOL_SET:
                    return symbol, detected_line

        # Fallback: exact symbol token detection
        tokens = re.findall(r"[A-Za-z]{1,3}", stem)
        for token in tokens:
            candidate = token[:1].upper() + token[1:].lower()
            if candidate in SYMBOL_SET:
                return candidate, detected_line

        return "Unknown", detected_line

    def _refresh_table(self) -> None:
        self.table_maps.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            self.table_maps.setItem(row, 0, QtWidgets.QTableWidgetItem(entry.path.name))

            # Editable element selection
            element_combo = QtWidgets.QComboBox()
            element_combo.addItems(["Unknown"] + ELEMENT_SYMBOLS)
            element_combo.setCurrentText(entry.element if entry.element in SYMBOL_SET else "Unknown")
            element_combo.currentTextChanged.connect(
                lambda text, r=row: self._on_element_changed(r, text)
            )
            self.table_maps.setCellWidget(row, 1, element_combo)

            self.table_maps.setItem(row, 2, QtWidgets.QTableWidgetItem(entry.line_family))

            # Source selector (Raw/Corrected toggle)
            source_widget = QtWidgets.QWidget()
            source_layout = QtWidgets.QHBoxLayout(source_widget)
            source_layout.setContentsMargins(0, 0, 0, 0)
            
            # Only show selector if both raw and corrected are available
            if entry.raw_path and entry.corrected_path:
                source_btn = QtWidgets.QPushButton("Corrected" if entry.using_corrected else "Raw")
                source_btn.setMaximumWidth(90)
                source_btn.clicked.connect(lambda _checked=False, r=row: self._toggle_source(r))
                source_layout.addWidget(source_btn)
            else:
                # Show label indicating only one source is available
                source_label = QtWidgets.QLabel("Corrected" if entry.using_corrected else "Raw")
                source_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                source_layout.addWidget(source_label)
            
            self.table_maps.setCellWidget(row, 3, source_widget)

            btn = QtWidgets.QPushButton(entry.color)
            btn.setStyleSheet(f"background-color: {entry.color}; color: #111; font-weight: 600;")
            btn.clicked.connect(lambda _checked=False, r=row: self._choose_row_colour(r))
            self.table_maps.setCellWidget(row, 4, btn)

            chk_export = QtWidgets.QCheckBox()
            chk_export.setChecked(entry.export_enabled)
            chk_export.stateChanged.connect(
                lambda _state, r=row, cb=chk_export: self._on_export_toggled(r, cb.isChecked())
            )
            export_cell = QtWidgets.QWidget()
            export_layout = QtWidgets.QHBoxLayout(export_cell)
            export_layout.setContentsMargins(4, 0, 4, 0)
            export_layout.addWidget(chk_export)
            export_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.table_maps.setCellWidget(row, 5, export_cell)

    def _on_element_changed(self, row: int, element: str) -> None:
        if row < 0 or row >= len(self.entries):
            return
        self.entries[row].element = element
        selected_row = self.table_maps.currentRow()
        self._refresh_table()
        if 0 <= selected_row < len(self.entries):
            self.table_maps.selectRow(selected_row)
        self._update_preview()

    def _on_export_toggled(self, row: int, checked: bool) -> None:
        if row < 0 or row >= len(self.entries):
            return
        self.entries[row].export_enabled = bool(checked)

    def _toggle_source(self, row: int) -> None:
        """Toggle between raw and corrected source for this entry."""
        if row < 0 or row >= len(self.entries):
            return
        entry = self.entries[row]
        
        # Only allow toggling if both sources exist
        if not (entry.raw_path and entry.corrected_path):
            return
        
        # Toggle source
        entry.using_corrected = not entry.using_corrected
        entry.path = entry.corrected_path if entry.using_corrected else entry.raw_path
        
        selected_row = self.table_maps.currentRow()
        self._refresh_table()
        if 0 <= selected_row < len(self.entries):
            self.table_maps.selectRow(selected_row)
        self._update_preview()

    def check_all_export(self) -> None:
        if not self.entries:
            return
        selected_row = self.table_maps.currentRow()
        for entry in self.entries:
            entry.export_enabled = True
        self._refresh_table()
        if 0 <= selected_row < len(self.entries):
            self.table_maps.selectRow(selected_row)
        self._update_preview()

    def uncheck_all_export(self) -> None:
        if not self.entries:
            return
        selected_row = self.table_maps.currentRow()
        for entry in self.entries:
            entry.export_enabled = False
        self._refresh_table()
        if 0 <= selected_row < len(self.entries):
            self.table_maps.selectRow(selected_row)
        self._update_preview()

    def _choose_row_colour(self, row: int) -> None:
        if row < 0 or row >= len(self.entries):
            return
        current = QtGui.QColor(self.entries[row].color)
        chosen = QtWidgets.QColorDialog.getColor(current, self, "Choose false colour")
        if not chosen.isValid():
            return

        self.entries[row].color = chosen.name()
        self._refresh_table()
        self.table_maps.selectRow(row)
        self._update_preview()

    def _auto_assign_colours(self) -> None:
        if not self.entries:
            return
        for idx, entry in enumerate(self.entries):
            entry.color = self._default_colour_for_element(entry.element, idx)
        selected_row = self.table_maps.currentRow()
        self._refresh_table()
        if 0 <= selected_row < len(self.entries):
            self.table_maps.selectRow(selected_row)
        self._update_preview()

    def _load_norm(self, path: Path) -> np.ndarray:
        cached = self._norm_cache.get(path)
        if cached is not None:
            return cached
        arr, _meta = read_image(str(path))
        norm = normalize_feature(arr)
        self._norm_cache[path] = norm
        return norm

    def _update_preview(self) -> None:
        row = self.table_maps.currentRow()
        if row < 0 or row >= len(self.entries):
            return

        entry = self.entries[row]
        try:
            norm = self._load_norm(entry.path)
            color = QtGui.QColor(entry.color)
            rgb = np.array([color.redF(), color.greenF(), color.blueF()], dtype=np.float32)
            out = np.clip(norm[..., None] * rgb[None, None, :], 0.0, 1.0)

            out8 = (out * 255).astype(np.uint8)
            h, w, _ = out8.shape
            qimg = QtGui.QImage(out8.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
            pixmap = QtGui.QPixmap.fromImage(qimg)

            self.lbl_preview_title.setText(
                f"Preview: {entry.path.name} | Element: {entry.element} | Line: {entry.line_family}"
            )
            self.lbl_preview.setPixmap(
                pixmap.scaled(
                    self.lbl_preview.size(),
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
            )
        except Exception as e:
            self.lbl_preview.setText(f"Preview failed: {e}")
            self.lbl_preview.setPixmap(QtGui.QPixmap())

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_preview()

    def _load_from_manifest(self, project_root: Path) -> None:
        """Load entries from manifest, making corrected versions default when available."""
        manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
        if not manifest_path.exists():
            self.entries = []
            self._refresh_table()
            return

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            map_registry = manifest_data.get("map_registry", {})
        except Exception:
            self.entries = []
            self._refresh_table()
            return

        # Build a map of element+line_family -> available file paths
        raw_data = project_root / "raw_data"
        corrected_maps = project_root / "corrected_maps"
        
        element_entries: dict[tuple[str, str], dict] = {}  # (element, line_family) -> {raw, corrected, map_id}
        
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
                # Corrected files should have _corrected suffix before extension
                stem = Path(filename).stem
                ext = Path(filename).suffix
                corrected_filename = f"{stem}_corrected{ext}"
                corrected_path = corrected_maps / corrected_filename
                if corrected_path.exists():
                    element_entries[key]["corrected"] = corrected_path

        # Build entries: prefer corrected, fallback to raw
        self.entries = []
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
            
            entry = FalseColourEntry(
                path=default_path,
                element=element,
                line_family=line_family,
                color=self._default_colour_for_element(element, idx),
                export_enabled=True,
                raw_path=raw_path,
                corrected_path=corrected_path,
                using_corrected=using_corrected,
            )
            self.entries.append(entry)

        self._refresh_table()
        if self.entries:
            self.table_maps.selectRow(0)
            self._update_preview()

    def _update_manifest_for_false_colour(self, exported_entries: list[FalseColourEntry]) -> None:
        """Update manifest to record the colours applied to each element (more robust than profile names)."""
        if not self.session or not self.session.maxrf_pipeline.project_root:
            return
        
        try:
            project_root = Path(self.session.maxrf_pipeline.project_root)
            manifest_path = project_root / "metadata" / "logs" / "map_manifest.json"
            
            if not manifest_path.exists():
                return
            
            # Read manifest
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            map_registry = manifest_data.get("map_registry", {})
            
            # Update each exported entry with its colour code (instead of profile name)
            for entry in exported_entries:
                # Find map_id by element+line_family match
                map_id_found = None
                for map_id, record in map_registry.items():
                    if (record.get("element") == entry.element and 
                        record.get("line_family") == entry.line_family):
                        map_id_found = map_id
                        break
                
                if map_id_found:
                    # Store the colour code instead of profile name (more robust)
                    # Using a format like "Zn:#ff4ba8" to identify which element got which colour
                    colour_code = entry.color  # Hex colour like "#ff4ba8"
                    variants = map_registry[map_id_found].get("false_colour_variants", [])
                    if colour_code not in variants:
                        variants.append(colour_code)
                    map_registry[map_id_found]["false_colour_variants"] = variants
                    
                    # Also update session
                    if map_id_found in self.session.maxrf_pipeline.map_registry:
                        self.session.maxrf_pipeline.map_registry[map_id_found].false_colour_variants = variants
            
            # Write manifest back
            manifest_data["map_registry"] = map_registry
            manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        except Exception as e:
            pass  # Silently fail on manifest update; don't interrupt export

    def set_session(self, session) -> None:
        """Set the project session and auto-load project workspace if available."""
        self.session = session
        
        # Clear visualization from previous project
        self.lbl_preview.setText("")
        self.lbl_preview.setPixmap(QtGui.QPixmap())
        
        # If project has MA-XRF workspace, load from manifest
        if session and session.maxrf_pipeline.project_root:
            project_root = Path(session.maxrf_pipeline.project_root)
            self._project_root = project_root  # Store for refresh on tab show
            self.lbl_folder.setText(f"Project: {project_root.name}")
            self.btn_browse.setEnabled(False)
            self.btn_browse.setToolTip("(Folder locked: using project workspace)")
            
            # Load from manifest to understand element/source structure
            self._load_from_manifest(project_root)
            return
        
        # No project: enable browse button
        self.btn_browse.setEnabled(True)
        self.btn_browse.setToolTip("")
        self._project_root = None

        if session and session.maxrf_pipeline.last_selected_folder:
            last_folder = Path(session.maxrf_pipeline.last_selected_folder)
            if last_folder.exists() and last_folder.is_dir():
                self._load_from_folder(last_folder)
                return

        self.work_folder = None
        self.lbl_folder.setText("No folder selected")
        self.entries.clear()
        self._refresh_table()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Refresh from manifest when tab becomes visible (to pick up new corrections)."""
        super().showEvent(event)
        if self._project_root:
            self._load_from_manifest(self._project_root)

    def export_false_coloured_set(self) -> None:
        if not self.entries:
            return

        to_export = [entry for entry in self.entries if entry.export_enabled]
        if not to_export:
            QtWidgets.QMessageBox.information(
                self,
                "Nothing selected",
                "No maps are checked for export.",
            )
            return

        # Auto-export to project folder if in project mode
        if self.session and self.session.maxrf_pipeline.project_root:
            output = Path(self.session.maxrf_pipeline.project_root) / "false_coloured_maps"
            output.mkdir(parents=True, exist_ok=True)
            suffix_append = "_fc"
        else:
            # Dialog for folder selection
            start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
            out_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Choose output folder for false-coloured maps",
                start_dir,
            )
            if not out_dir:
                return
            output = Path(out_dir)
            suffix_append = "_falsecolour"

        failures: list[str] = []

        success_count = 0
        for entry in to_export:
            try:
                src_arr, _src_meta = read_image(str(entry.path))
                src_dtype = src_arr.dtype
                norm = self._load_norm(entry.path)
                color = QtGui.QColor(entry.color)
                rgb = np.array([color.redF(), color.greenF(), color.blueF()], dtype=np.float32)
                out = np.clip(norm[..., None] * rgb[None, None, :], 0.0, 1.0)

                # Preserve source bit depth where possible
                if np.issubdtype(src_dtype, np.integer):
                    info = np.iinfo(src_dtype)
                    out_data = np.clip(
                        np.round(out * (info.max - info.min) + info.min),
                        info.min,
                        info.max,
                    ).astype(src_dtype)
                elif np.issubdtype(src_dtype, np.floating):
                    out_data = out.astype(src_dtype)
                else:
                    out_data = (out * 255).astype(np.uint8)

                # Preserve source format/extension per map
                target = output / f"{entry.path.stem}{suffix_append}{entry.path.suffix}"
                suffix = entry.path.suffix.lower()

                if suffix in {".tif", ".tiff"}:
                    import tifffile as tiff

                    tiff.imwrite(str(target), out_data)
                else:
                    import imageio.v3 as iio

                    # JPEG commonly only supports 8-bit; cast if needed.
                    if suffix in {".jpg", ".jpeg"} and out_data.dtype != np.uint8:
                        out_data = np.clip(np.round(out * 255), 0, 255).astype(np.uint8)
                    iio.imwrite(target, out_data)
                success_count += 1
            except Exception as exc:
                failures.append(f"{entry.path.name}: {exc}")

        # Update manifest if in project mode
        if self.session and self.session.maxrf_pipeline.project_root and success_count > 0:
            self._update_manifest_for_false_colour(to_export)

        if failures:
            QtWidgets.QMessageBox.warning(
                self,
                "Export completed with errors",
                "Some files could not be exported:\n" + "\n".join(failures[:10]),
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Export complete",
                f"Exported {success_count} false-coloured maps to:\n{output}",
            )

    def export_selected_element(self) -> None:
        """Export only the currently selected element."""
        selected_row = self.table_maps.currentRow()
        if selected_row < 0:
            QtWidgets.QMessageBox.warning(
                self,
                "No selection",
                "Please select an element to export.",
            )
            return

        entry = self.entries[selected_row]

        # Auto-export to project folder if in project mode
        if self.session and self.session.maxrf_pipeline.project_root:
            output = Path(self.session.maxrf_pipeline.project_root) / "false_coloured_maps"
            output.mkdir(parents=True, exist_ok=True)
            suffix_append = "_fc"
        else:
            # Dialog for folder selection
            start_dir = str(self.work_folder) if self.work_folder else str(Path.home())
            out_dir = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Choose output folder for false-coloured map",
                start_dir,
            )
            if not out_dir:
                return
            output = Path(out_dir)
            suffix_append = "_falsecolour"

        try:
            src_arr, _src_meta = read_image(str(entry.path))
            src_dtype = src_arr.dtype
            norm = self._load_norm(entry.path)
            color = QtGui.QColor(entry.color)
            rgb = np.array([color.redF(), color.greenF(), color.blueF()], dtype=np.float32)
            out = np.clip(norm[..., None] * rgb[None, None, :], 0.0, 1.0)

            # Preserve source bit depth where possible
            if np.issubdtype(src_dtype, np.integer):
                info = np.iinfo(src_dtype)
                out_data = np.clip(
                    np.round(out * (info.max - info.min) + info.min),
                    info.min,
                    info.max,
                ).astype(src_dtype)
            elif np.issubdtype(src_dtype, np.floating):
                out_data = out.astype(src_dtype)
            else:
                out_data = (out * 255).astype(np.uint8)

            # Preserve source format/extension
            target = output / f"{entry.path.stem}{suffix_append}{entry.path.suffix}"
            suffix = entry.path.suffix.lower()

            if suffix in {".tif", ".tiff"}:
                import tifffile as tiff
                tiff.imwrite(str(target), out_data)
            else:
                import imageio.v3 as iio
                if suffix in {".jpg", ".jpeg"} and out_data.dtype != np.uint8:
                    out_data = np.clip(np.round(out * 255), 0, 255).astype(np.uint8)
                iio.imwrite(target, out_data)

            # Update manifest if in project mode
            if self.session and self.session.maxrf_pipeline.project_root:
                self._update_manifest_for_false_colour([entry])

            QtWidgets.QMessageBox.information(
                self,
                "Export complete",
                f"Exported {entry.element} to:\n{target.name}",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Export failed",
                f"Failed to export {entry.element}:\n{e}",
            )

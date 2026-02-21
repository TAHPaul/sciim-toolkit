from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.common.placeholder import PlaceholderTab
from sciim_toolkit.features.imaging_planner.ui import ImagingPlannerTab
from sciim_toolkit.features.maxrf_corrections import MaxrfCorrectionsTab
from sciim_toolkit.features.maxrf_edit import MapSetupTab, MaxrfEditTab, MaxrfFalseColourTab
from sciim_toolkit.models.project import ProjectSession
from sciim_toolkit.services.session_io import SessionIOError, load_session, save_session


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SciIm Toolkit")
        self.resize(1400, 900)

        self.session = ProjectSession()
        self._build_ui()
        self._build_menu()
        self._bind_signals()

    def _build_ui(self) -> None:
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab_planner = ImagingPlannerTab(self)
        self.tab_planner.set_session(self.session)

        self.tab_maxrf_tools = QtWidgets.QTabWidget(self)
        self.tab_map_setup = MapSetupTab(self)
        self.tab_map_setup.set_session(self.session)
        self.tab_corrections = MaxrfCorrectionsTab(self)
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour = MaxrfFalseColourTab(self)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays = MaxrfEditTab(self)
        self.tab_overlays.set_session(self.session)

        self.tab_maxrf_tools.addTab(self.tab_map_setup, "Map Setup")
        self.tab_maxrf_tools.addTab(self.tab_corrections, "Corrections")
        self.tab_maxrf_tools.addTab(self.tab_false_colour, "False Colouring")
        self.tab_maxrf_tools.addTab(self.tab_overlays, "Overlay")

        self.tab_registration = PlaceholderTab(
            "Multimodal Registration",
            "Upcoming: manual control-point registration first, then SimpleITK mutual-information auto registration.",
        )

        self.tabs.addTab(self.tab_planner, "Imaging Planner")
        self.tabs.addTab(self.tab_maxrf_tools, "MA-XRF Tools")
        self.tabs.addTab(self.tab_registration, "Multimodal Registration")

        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        menu_file = self.menuBar().addMenu("File")

        self.act_new = QtGui.QAction("New Project", self)
        self.act_open = QtGui.QAction("Open Project…", self)
        self.act_save = QtGui.QAction("Save Project", self)
        self.act_save_as = QtGui.QAction("Save Project As…", self)

        menu_file.addAction(self.act_new)
        menu_file.addAction(self.act_open)
        menu_file.addSeparator()
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_save_as)

    def _bind_signals(self) -> None:
        self.act_new.triggered.connect(self.new_project)
        self.act_open.triggered.connect(self.open_project)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(lambda: self.save_project(force_choose=True))
        
        # Add keyboard shortcuts for save
        save_shortcut = QtGui.QKeySequence.StandardKey.Save
        self.act_save.setShortcut(save_shortcut)

        self.tab_planner.session_changed.connect(self._on_session_changed)
        self.tab_map_setup.session_changed.connect(self._on_session_changed)

    def _on_session_changed(self) -> None:
        self.session.touch()
        self._set_title()
        # Propagate session changes to all tabs
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)

    def _set_title(self) -> None:
        suffix = Path(self.session.project_file).name if self.session.project_file else "Unsaved"
        self.setWindowTitle(f"SciIm Toolkit — {self.session.project_name} ({suffix})")

    def new_project(self) -> None:
        # Ask to save current project if it has been modified
        if self.session.project_file or (self.session.maxrf_pipeline.map_registry):
            reply = QtWidgets.QMessageBox.question(
                self,
                "Save current project?",
                "Do you want to save the current project before creating a new one?",
                QtWidgets.QMessageBox.StandardButton.Save
                | QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Save,
            )
            if reply == QtWidgets.QMessageBox.StandardButton.Save:
                self.save_project()
            elif reply == QtWidgets.QMessageBox.StandardButton.Cancel:
                return
        
        # Create fresh project with cleared state
        self.session = ProjectSession()
        # Ensure last_selected_folder is empty so Map Setup starts fresh
        self.session.maxrf_pipeline.last_selected_folder = ""
        
        self.tab_planner.set_session(self.session)
        self.tab_map_setup.set_session(self.session)
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)
        self._set_title()
        self.statusBar().showMessage("New project")

    def open_project(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open SciIm project",
            str(Path.home()),
            "SciIm Project (*.sciim.json)",
        )
        if not path:
            return

        try:
            self.session = load_session(Path(path))
        except SessionIOError as exc:
            QtWidgets.QMessageBox.critical(self, "Open failed", str(exc))
            return

        self.tab_planner.set_session(self.session)
        self.tab_map_setup.set_session(self.session)
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)
        self._set_title()
        self.statusBar().showMessage(f"Opened {Path(path).name}")

    def save_project(self, force_choose: bool = False) -> None:
        path = Path(self.session.project_file) if self.session.project_file else None

        if force_choose or path is None:
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Save SciIm project",
                str(Path.home() / "new_project"),
                "SciIm Project (*.sciim.json)",
            )
            if not chosen:
                return
            path = Path(chosen)
            # Ensure proper suffix
            if not str(path).endswith(".sciim.json"):
                # Remove any existing suffix and add .sciim.json
                path = path.with_suffix("").with_suffix(".sciim.json")

        try:
            save_session(path, self.session)
        except SessionIOError as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))
            return

        self._set_title()
        self.statusBar().showMessage(f"Saved {path.name}")

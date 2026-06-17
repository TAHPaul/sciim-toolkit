from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from sciim_toolkit.features.imaging_planner.ui import ImagingPlannerTab
from sciim_toolkit.features.maxrf_corrections import MaxrfCorrectionsTab
from sciim_toolkit.features.maxrf_edit import MapSetupTab, MaxrfCompileTab, MaxrfEditTab, MaxrfFalseColourTab
from sciim_toolkit.features.project_setup import ProjectSetupTab
from sciim_toolkit.features.registration import RegistrationTab
from sciim_toolkit.models.project import ProjectSession
from sciim_toolkit.services.session_io import SessionIOError, load_session, save_session
from sciim_toolkit.services.user_settings import (
    UserSettings,
    UserSettingsError,
    autosave_drafts_dir,
    load_user_settings,
    save_user_settings,
)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SciIm Toolkit")
        self.setMinimumSize(720, 500)
        self._apply_initial_window_size()

        self.session = ProjectSession()
        self.user_settings = self._load_user_settings()
        self._autosave_error_reported = False
        self._has_pending_autosave_changes = False
        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(False)
        self._autosave_timer.setInterval(self.user_settings.autosave_interval_ms)
        self._autosave_timer.timeout.connect(self._on_autosave_interval)
        self._build_ui()
        self._build_menu()
        self._bind_signals()
        self._rebuild_recent_projects_menu()
        self._apply_autosave_timer_state()
        self._set_title()

    def _apply_initial_window_size(self) -> None:
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1200, 800)
            return

        available = screen.availableGeometry()
        width = min(1400, max(900, int(available.width() * 0.9)))
        height = min(900, max(650, int(available.height() * 0.9)))
        self.resize(width, height)

    def _load_user_settings(self) -> UserSettings:
        try:
            settings = load_user_settings()
            if settings.autosave_interval_ms == 1200:
                settings.autosave_interval_ms = 60000
                try:
                    save_user_settings(settings)
                except UserSettingsError:
                    pass
            return settings
        except UserSettingsError as exc:
            QtWidgets.QMessageBox.warning(self, "Settings", str(exc))
            return UserSettings()

    def _apply_autosave_timer_state(self) -> None:
        self._autosave_timer.setInterval(int(self.user_settings.autosave_interval_ms))
        if self.user_settings.autosave_enabled:
            if not self._autosave_timer.isActive():
                self._autosave_timer.start()
        else:
            self._autosave_timer.stop()

    def _persist_user_settings(self) -> None:
        try:
            save_user_settings(self.user_settings)
        except UserSettingsError as exc:
            self.statusBar().showMessage(str(exc), 4000)

    def _build_ui(self) -> None:
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab_project_setup = ProjectSetupTab(self)
        self.tab_project_setup.set_session(self.session)

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
        self.tab_compile = MaxrfCompileTab(self)
        self.tab_compile.set_session(self.session)

        self.tab_maxrf_tools.addTab(self.tab_map_setup, "Map Setup")
        self.tab_maxrf_tools.addTab(self.tab_corrections, "Corrections")
        self.tab_maxrf_tools.addTab(self.tab_false_colour, "False Colouring")
        self.tab_maxrf_tools.addTab(self.tab_overlays, "Overlay")
        self.tab_maxrf_tools.addTab(self.tab_compile, "Compile")

        self.tab_registration = RegistrationTab(self)
        self.tab_registration.set_session(self.session)

        self.tabs.addTab(self.tab_project_setup, "Project Setup")
        self.tabs.addTab(self.tab_planner, "Imaging Planner")
        self.tabs.addTab(self.tab_maxrf_tools, "MA-XRF Tools")
        self.tabs.addTab(self.tab_registration, "Multimodal Registration")

        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        menu_file = self.menuBar().addMenu("File")

        self.act_new = QtGui.QAction("New Project", self)
        self.act_open = QtGui.QAction("Open Project…", self)
        self.menu_recent_projects = QtWidgets.QMenu("Open Recent", self)
        self.act_save = QtGui.QAction("Save Project", self)
        self.act_save_as = QtGui.QAction("Save Project As…", self)

        menu_file.addAction(self.act_new)
        menu_file.addAction(self.act_open)
        menu_file.addMenu(self.menu_recent_projects)
        menu_file.addSeparator()
        menu_file.addAction(self.act_save)
        menu_file.addAction(self.act_save_as)

        menu_prefs = self.menuBar().addMenu("Preferences")
        self.act_autosave_enabled = QtGui.QAction("Enable Autosave", self)
        self.act_autosave_enabled.setCheckable(True)
        self.act_autosave_enabled.setChecked(self.user_settings.autosave_enabled)
        self.act_autosave_interval = QtGui.QAction("Set Autosave Interval…", self)

        menu_prefs.addAction(self.act_autosave_enabled)
        menu_prefs.addAction(self.act_autosave_interval)

    def _bind_signals(self) -> None:
        self.act_new.triggered.connect(self.new_project)
        self.act_open.triggered.connect(self.open_project)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as.triggered.connect(lambda: self.save_project(force_choose=True))
        self.act_autosave_enabled.toggled.connect(self._on_autosave_toggled)
        self.act_autosave_interval.triggered.connect(self._on_set_autosave_interval)
        
        # Add keyboard shortcuts for save
        save_shortcut = QtGui.QKeySequence.StandardKey.Save
        self.act_save.setShortcut(save_shortcut)

        self.tab_planner.session_changed.connect(self._on_session_changed)
        self.tab_project_setup.session_changed.connect(self._on_session_changed)
        self.tab_map_setup.session_changed.connect(self._on_session_changed)
        self.tab_map_setup.session_changed.connect(self._on_maxrf_folder_loaded)
        self.tab_map_setup.folder_loaded.connect(self._on_maxrf_folder_loaded)
        self.tab_overlays.session_changed.connect(self._on_session_changed)
        self.tab_registration.session_changed.connect(self._on_session_changed)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tab_maxrf_tools.currentChanged.connect(self._on_tab_changed)

    def _on_maxrf_folder_loaded(self, *_args) -> None:
        """Refresh MA-XRF tabs after Map Setup selects/loads a folder."""
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)
        self.tab_compile.set_session(self.session)

    def _on_session_changed(self, *_args) -> None:
        self.session.touch()
        self._set_title()
        self._mark_autosave_pending()

    def _on_tab_changed(self, _index: int) -> None:
        if self.tabs.currentWidget() is self.tab_planner:
            self.tab_planner.set_session(self.session)

        if self.tabs.currentWidget() is self.tab_registration:
            self.tab_registration.set_session(self.session)

        if self.user_settings.autosave_enabled and self._has_pending_autosave_changes:
            self._autosave_now()

    def _mark_autosave_pending(self) -> None:
        self._has_pending_autosave_changes = True

    def _on_autosave_interval(self) -> None:
        if not self.user_settings.autosave_enabled:
            return
        if not self._has_pending_autosave_changes:
            return
        self._autosave_now()

    def _autosave_path(self) -> Path:
        if self.session.project_file:
            return Path(self.session.project_file)
        return autosave_drafts_dir() / "untitled_autosave.sciim.json"

    def _autosave_now(self) -> None:
        if not self.user_settings.autosave_enabled:
            return
        path = self._autosave_path()
        try:
            save_session(path, self.session, update_project_file=bool(self.session.project_file))
        except SessionIOError:
            if not self._autosave_error_reported:
                self.statusBar().showMessage("Autosave failed")
                self._autosave_error_reported = True
            return

        self._autosave_error_reported = False
        self._has_pending_autosave_changes = False
        if self.session.project_file:
            self.statusBar().showMessage(f"Autosaved {path.name}", 2000)
        else:
            self.statusBar().showMessage(f"Autosaved draft ({path.name})", 2000)

    def _on_autosave_toggled(self, checked: bool) -> None:
        self.user_settings.autosave_enabled = bool(checked)
        self._persist_user_settings()
        self._apply_autosave_timer_state()

    def _on_set_autosave_interval(self) -> None:
        current_ms = int(self.user_settings.autosave_interval_ms)
        value, ok = QtWidgets.QInputDialog.getInt(
            self,
            "Autosave Interval",
            "Autosave interval (milliseconds)",
            current_ms,
            1000,
            600000,
            1000,
        )
        if not ok:
            return

        self.user_settings.autosave_interval_ms = int(value)
        self._apply_autosave_timer_state()
        self._persist_user_settings()
        self.statusBar().showMessage(
            f"Autosave interval set to {self.user_settings.autosave_interval_ms} ms", 2500
        )

    def _add_recent_project(self, project_path: Path) -> None:
        normalized = str(project_path.resolve())
        existing = [p for p in self.user_settings.recent_projects if p != normalized]
        self.user_settings.recent_projects = [normalized, *existing][:10]
        self._persist_user_settings()
        self._rebuild_recent_projects_menu()

    def _clear_recent_projects(self) -> None:
        self.user_settings.recent_projects = []
        self._persist_user_settings()
        self._rebuild_recent_projects_menu()

    def _rebuild_recent_projects_menu(self) -> None:
        self.menu_recent_projects.clear()
        recent_paths = self.user_settings.recent_projects

        if not recent_paths:
            action_empty = QtGui.QAction("No recent projects", self)
            action_empty.setEnabled(False)
            self.menu_recent_projects.addAction(action_empty)
            return

        for raw_path in recent_paths:
            path = Path(raw_path)
            action = QtGui.QAction(path.name, self)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _checked=False, p=path: self._open_recent_project(p))
            self.menu_recent_projects.addAction(action)

        self.menu_recent_projects.addSeparator()
        action_clear = QtGui.QAction("Clear Recent", self)
        action_clear.triggered.connect(self._clear_recent_projects)
        self.menu_recent_projects.addAction(action_clear)

    def _open_recent_project(self, path: Path) -> None:
        normalized = str(path.resolve())
        if not path.exists():
            QtWidgets.QMessageBox.warning(self, "Missing project", f"File not found:\n{path}")
            self.user_settings.recent_projects = [p for p in self.user_settings.recent_projects if p != normalized]
            self._persist_user_settings()
            self._rebuild_recent_projects_menu()
            return

        try:
            self.session = load_session(path)
        except SessionIOError as exc:
            QtWidgets.QMessageBox.critical(self, "Open failed", str(exc))
            return

        self.tab_planner.set_session(self.session)
        self.tab_project_setup.set_session(self.session)
        self.tab_map_setup.set_session(self.session)
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)
        self.tab_compile.set_session(self.session)
        self.tab_registration.set_session(self.session)
        self._set_title()
        self._has_pending_autosave_changes = False
        self._add_recent_project(path)
        self.statusBar().showMessage(f"Opened {path.name}")

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
        self.tab_project_setup.set_session(self.session)
        self.tab_map_setup.set_session(self.session)
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)
        self.tab_compile.set_session(self.session)
        self.tab_registration.set_session(self.session)
        self._set_title()
        self._has_pending_autosave_changes = False
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
        self.tab_project_setup.set_session(self.session)
        self.tab_map_setup.set_session(self.session)
        self.tab_corrections.set_session(self.session)
        self.tab_false_colour.set_session(self.session)
        self.tab_overlays.set_session(self.session)
        self.tab_compile.set_session(self.session)
        self.tab_registration.set_session(self.session)
        self._set_title()
        self._has_pending_autosave_changes = False
        self._add_recent_project(Path(path))
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
        self._has_pending_autosave_changes = False
        self._add_recent_project(path)
        self.statusBar().showMessage(f"Saved {path.name}")

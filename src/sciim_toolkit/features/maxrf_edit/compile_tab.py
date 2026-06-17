from __future__ import annotations

import shutil
from pathlib import Path

from PySide6 import QtWidgets


class MaxrfCompileTab(QtWidgets.QWidget):
    """Compile tab to assemble final MA-XRF dataset from furthest available map versions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.session = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            "Create a compiled final dataset by selecting the furthest available version for each map:\n"
            "corrected+false-coloured → corrected → false-coloured (raw) → raw"
        )
        intro.setWordWrap(True)

        self.btn_compile = QtWidgets.QPushButton("Compile Final Dataset")
        self.btn_compile.clicked.connect(self._compile_final_dataset)

        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("Compilation summary will appear here.")

        root.addWidget(intro)
        root.addWidget(self.btn_compile)
        root.addWidget(self.summary, 1)

    def set_session(self, session) -> None:
        self.session = session

    def _compile_final_dataset(self) -> None:
        if not self.session or not self.session.maxrf_pipeline.project_root:
            QtWidgets.QMessageBox.warning(
                self,
                "Compile Final Dataset",
                "This action requires a project workspace (MA-XRF project root).",
            )
            return

        project_root = Path(self.session.maxrf_pipeline.project_root)
        map_registry = self.session.maxrf_pipeline.map_registry
        if not map_registry:
            QtWidgets.QMessageBox.warning(
                self,
                "Compile Final Dataset",
                "No maps found in project registry. Import maps first in Map Setup.",
            )
            return

        raw_dir = project_root / "raw_data"
        corrected_dir = project_root / "corrected_maps"
        fc_dir = project_root / "false_coloured_maps"
        out_dir = project_root / "final_maps"
        out_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        missing = 0
        by_kind = {
            "corrected_fc": 0,
            "corrected": 0,
            "raw_fc": 0,
            "raw": 0,
        }
        details: list[str] = []

        for map_id, record in sorted(map_registry.items()):
            filename = (record.filename or "").strip()
            if not filename:
                missing += 1
                details.append(f"{map_id}: missing filename in registry")
                continue

            stem = Path(filename).stem
            ext = Path(filename).suffix

            raw_path = raw_dir / filename
            corrected_path = corrected_dir / f"{stem}_corrected{ext}"
            corrected_fc_path = fc_dir / f"{stem}_corrected_fc{ext}"
            raw_fc_path = fc_dir / f"{stem}_fc{ext}"

            selected_path: Path | None = None
            selected_kind = ""

            if corrected_fc_path.exists():
                selected_path = corrected_fc_path
                selected_kind = "corrected_fc"
            elif corrected_path.exists():
                selected_path = corrected_path
                selected_kind = "corrected"
            elif raw_fc_path.exists():
                selected_path = raw_fc_path
                selected_kind = "raw_fc"
            elif raw_path.exists():
                selected_path = raw_path
                selected_kind = "raw"

            if selected_path is None:
                missing += 1
                details.append(f"{map_id}: no source found (raw/corrected/false-colour)")
                continue

            target = out_dir / selected_path.name
            shutil.copy2(selected_path, target)
            copied += 1
            by_kind[selected_kind] += 1
            details.append(f"{map_id}: {selected_kind} -> {target.name}")

        summary_lines = [
            f"Output folder: {out_dir}",
            f"Copied: {copied}",
            f"Missing: {missing}",
            "",
            "Breakdown:",
            f"- corrected + false-coloured: {by_kind['corrected_fc']}",
            f"- corrected only: {by_kind['corrected']}",
            f"- false-coloured (raw) only: {by_kind['raw_fc']}",
            f"- raw only: {by_kind['raw']}",
            "",
            "Details:",
            *details,
        ]
        self.summary.setPlainText("\n".join(summary_lines))

        QtWidgets.QMessageBox.information(
            self,
            "Compile complete",
            f"Compiled {copied} map(s) into:\n{out_dir}",
        )

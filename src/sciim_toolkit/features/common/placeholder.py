from __future__ import annotations

from PySide6 import QtWidgets


class PlaceholderTab(QtWidgets.QWidget):
    def __init__(self, title: str, details: str, parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        description = QtWidgets.QLabel(details)
        description.setWordWrap(True)
        description.setStyleSheet("color: #555;")
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addStretch(1)

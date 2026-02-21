from __future__ import annotations

import sys

from PySide6 import QtWidgets
import pyqtgraph as pg

from sciim_toolkit.app.main_window import MainWindow


def main() -> None:
    # Configure PyQtGraph to use row-major (NumPy standard) image axis order
    pg.setConfigOptions(imageAxisOrder="row-major")
    
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

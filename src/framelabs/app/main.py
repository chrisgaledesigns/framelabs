"""Application entry point for FrameLabs."""

import sys

from PySide6.QtWidgets import QApplication

from framelabs.core.logger import setup_logging
from framelabs.ui.main_window import MainWindow


def main() -> None:
    """Launch the FrameLabs application."""
    setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""Application entry point for FrameLabs."""

import sys

from PySide6.QtWidgets import QApplication

from framelabs.ui.main_window import MainWindow


def main() -> None:
    """Launch the FrameLabs application."""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

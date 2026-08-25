"""Application entry point for FrameLabs."""

import sys

from PySide6.QtWidgets import QApplication, QDialog

from framelabs.core.config import Config
from framelabs.core.logger import setup_logging
from framelabs.plugins.plugin_manager import PluginManager
from framelabs.ui.main_window import MainWindow
from framelabs.ui.splash_screen import FrameLabsSplashScreen
from framelabs.ui.startup_dialog import StartupDialog
from framelabs.ui.theme import STYLESHEET


def main() -> None:
    """Launch the FrameLabs application.

    Startup sequence: splash screen (covers plugin loading) -> startup
    Welcome dialog (New/Open/Recent Project, before MainWindow exists
    at all) -> MainWindow, adopted with whatever project the Welcome
    dialog produced. Quitting from the Welcome dialog exits before
    MainWindow is ever constructed, rather than opening an empty
    window the user already said they didn't want.
    """
    setup_logging()

    # QApplication must exist before any QPixmap/QWidget is built, so
    # it's constructed here rather than left for MainWindow. The
    # stylesheet is applied immediately after, so the splash and the
    # Welcome dialog are already themed, not just MainWindow.
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    splash = FrameLabsSplashScreen()
    splash.show()
    splash.show_random_status()
    app.processEvents()

    plugin_manager = PluginManager()
    plugin_manager.load_plugins()

    splash.show_random_status()
    app.processEvents()

    # Constructed once here and shared with both the Welcome dialog
    # (Recent Projects) and MainWindow (everything else it already
    # used Config for) -- a project opened or created in the Welcome
    # dialog needs to land in the same recent_projects list MainWindow
    # itself reads from and writes back to. See MainWindow.__init__'s
    # docstring.
    config = Config()

    startup_dialog = StartupDialog(config)
    splash.finish(startup_dialog)
    if startup_dialog.exec() != QDialog.DialogCode.Accepted:
        return

    window = MainWindow(config=config)

    if startup_dialog.new_project is not None:
        window.open_created_project(startup_dialog.new_project)
    elif startup_dialog.chosen_path is not None:
        window.open_project_at(startup_dialog.chosen_path)

    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

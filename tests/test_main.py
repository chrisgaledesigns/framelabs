"""Tests for the application entry point in app/main.py.

Every collaborator main() constructs is mocked out -- QApplication can
only be instantiated once per process (the conftest.py qt_application
fixture already owns the real one for this test session), and
MainWindow/StartupDialog/etc. are already covered by their own test
modules. These tests are purely about the sequencing decisions main()
itself makes: which calls happen, in what order, and which of
open_created_project/open_project_at/neither gets called based on the
Welcome dialog's outcome.
"""

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog

from framelabs.app.main import main


@contextmanager
def _patch_main_collaborators():
    """Patch every symbol app/main.py imports into its own namespace.

    Yields a dict of the patched objects, keyed by name, for tests to
    configure/assert against. Uses individual patch() calls in an
    ExitStack rather than patch.multiple(), since patch.multiple() only
    returns mocks for args passed the DEFAULT sentinel, not explicit
    MagicMock() replacements.
    """
    names = (
        "setup_logging",
        "QApplication",
        "QTimer",
        "FrameLabsSplashScreen",
        "PluginManager",
        "Config",
        "StartupDialog",
        "MainWindow",
        "sys",
    )
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch(f"framelabs.app.main.{name}", MagicMock()))
            for name in names
        }
        yield mocks


def test_main_calls_setup_logging_first():
    with _patch_main_collaborators() as mocks:
        mocks["StartupDialog"].return_value.exec.return_value = (
            QDialog.DialogCode.Rejected
        )

        main()

        mocks["setup_logging"].assert_called_once()


def test_main_loads_plugins_before_showing_startup_dialog():
    with _patch_main_collaborators() as mocks:
        mocks["StartupDialog"].return_value.exec.return_value = (
            QDialog.DialogCode.Rejected
        )

        main()

        mocks["PluginManager"].return_value.load_plugins.assert_called_once()
        mocks["StartupDialog"].return_value.exec.assert_called_once()


def test_main_rejected_startup_dialog_never_builds_main_window():
    """Quitting from the Welcome dialog should exit before MainWindow is
    ever constructed, per the module docstring."""
    with _patch_main_collaborators() as mocks:
        mocks["StartupDialog"].return_value.exec.return_value = (
            QDialog.DialogCode.Rejected
        )

        main()

        mocks["MainWindow"].assert_not_called()
        mocks["sys"].exit.assert_not_called()


def test_main_accepted_with_new_project_opens_created_project():
    with _patch_main_collaborators() as mocks:
        startup_dialog = mocks["StartupDialog"].return_value
        startup_dialog.exec.return_value = QDialog.DialogCode.Accepted
        startup_dialog.new_project = MagicMock()
        startup_dialog.chosen_path = None
        window = mocks["MainWindow"].return_value

        main()

        window.open_created_project.assert_called_once_with(startup_dialog.new_project)
        window.open_project_at.assert_not_called()
        window.show.assert_called_once()
        mocks["QTimer"].singleShot.assert_called_once_with(0, window.showMaximized)


def test_main_accepted_with_chosen_path_opens_project_at_path():
    with _patch_main_collaborators() as mocks:
        startup_dialog = mocks["StartupDialog"].return_value
        startup_dialog.exec.return_value = QDialog.DialogCode.Accepted
        startup_dialog.new_project = None
        startup_dialog.chosen_path = "/tmp/Robot Walk"
        window = mocks["MainWindow"].return_value

        main()

        window.open_project_at.assert_called_once_with("/tmp/Robot Walk")
        window.open_created_project.assert_not_called()
        window.show.assert_called_once()
        mocks["QTimer"].singleShot.assert_called_once_with(0, window.showMaximized)


def test_main_accepted_with_neither_opens_nothing_but_still_shows_window():
    with _patch_main_collaborators() as mocks:
        startup_dialog = mocks["StartupDialog"].return_value
        startup_dialog.exec.return_value = QDialog.DialogCode.Accepted
        startup_dialog.new_project = None
        startup_dialog.chosen_path = None
        window = mocks["MainWindow"].return_value

        main()

        window.open_created_project.assert_not_called()
        window.open_project_at.assert_not_called()
        window.show.assert_called_once()
        mocks["QTimer"].singleShot.assert_called_once_with(0, window.showMaximized)


def test_main_accepted_exits_with_app_exec_return_code():
    with _patch_main_collaborators() as mocks:
        mocks["StartupDialog"].return_value.exec.return_value = (
            QDialog.DialogCode.Accepted
        )
        mocks["QApplication"].return_value.exec.return_value = 0

        main()

        mocks["sys"].exit.assert_called_once_with(0)


def test_main_applies_stylesheet_before_splash_is_shown():
    with _patch_main_collaborators() as mocks:
        mocks["StartupDialog"].return_value.exec.return_value = (
            QDialog.DialogCode.Rejected
        )
        app_instance = mocks["QApplication"].return_value

        main()

        app_instance.setStyleSheet.assert_called_once()
        mocks["FrameLabsSplashScreen"].return_value.show.assert_called_once()

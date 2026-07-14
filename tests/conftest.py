"""Shared pytest fixtures for the test suite.

Provides a single QApplication instance for the whole test session, for
tests that instantiate QObject subclasses (e.g. CameraController) and, as
of Feature 5, real QWidget subclasses (e.g. TimelineWidget) -- Qt's
signal/slot machinery, and widget construction itself, both require a
QApplication (not just QCoreApplication) to exist.

QT_QPA_PLATFORM defaults to "offscreen" if not already set, so this still
works with no real display attached (relevant for CI, Phase 9) -- Qt's own
offscreen platform plugin renders widgets into memory instead of a real
window, which is what actually lets a full QApplication (not just
QCoreApplication) exist in a headless environment. Only set as a default,
not forced, so a real display (e.g. Chris's dev machine) is used normally
where one is available.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402 (must follow the env default)


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """Ensure exactly one QApplication exists for the whole session.

    Creating a second QApplication instance in the same process crashes
    Qt, so this reuses an existing instance if one is already running
    (e.g. one pytest-qt itself may construct) rather than always
    constructing a new one.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app

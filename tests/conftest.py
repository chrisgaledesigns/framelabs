"""Shared pytest fixtures for the test suite.

Provides a single QCoreApplication instance for the whole test session, for
tests that instantiate QObject subclasses (e.g. CameraController) --
Qt's signal/slot machinery expects an application instance to exist, even
for tests that never open a window. QCoreApplication (not the full
QApplication) is used deliberately, since no widgets are created in tests
and this avoids requiring a display/GUI environment for a headless
`pytest` run (relevant for CI, Phase 9).
"""

import pytest
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """Ensure exactly one QCoreApplication exists for the whole session.

    Creating a second QApplication/QCoreApplication instance in the same
    process crashes Qt, so this reuses an existing instance if one is
    already running rather than always constructing a new one.
    """
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app

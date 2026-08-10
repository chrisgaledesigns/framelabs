"""Tests for NewProjectDialog in ui/new_project_dialog.py.

Follows this suite's existing widget-test convention (real widgets, real
create_new_project() against tmp_path -- see test_creator.py and
test_startup_dialog.py's docstrings) rather than mocking project
creation, since create_new_project()'s own behavior is already covered
and NewProjectDialog's job is just wiring form values into it correctly.

QFileDialog.getExistingDirectory and QMessageBox are the two things
actually mocked -- both would otherwise block on a real native dialog
during a headless test run.
"""

from unittest.mock import patch

from framelabs.ui.new_project_dialog import NewProjectDialog


def test_defaults_are_1920x1080_12fps(qtbot):
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    assert dialog.fps_spin.value() == 12
    assert dialog.width_spin.value() == 1920
    assert dialog.height_spin.value() == 1080
    assert dialog.folder_edit.text() == ""
    assert dialog.project is None


@patch("framelabs.ui.new_project_dialog.QFileDialog.getExistingDirectory")
def test_browse_sets_folder_text_when_a_folder_is_chosen(mock_get_dir, qtbot, tmp_path):
    mock_get_dir.return_value = str(tmp_path)
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    dialog._on_browse()

    assert dialog.folder_edit.text() == str(tmp_path)


@patch("framelabs.ui.new_project_dialog.QFileDialog.getExistingDirectory")
def test_browse_leaves_folder_text_unchanged_when_cancelled(mock_get_dir, qtbot):
    mock_get_dir.return_value = ""  # Qt's convention for "user cancelled"
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)

    dialog._on_browse()

    assert dialog.folder_edit.text() == ""


@patch("framelabs.ui.new_project_dialog.QMessageBox.warning")
def test_create_with_no_name_warns_and_does_not_close(mock_warning, qtbot, tmp_path):
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    dialog.folder_edit.setText(str(tmp_path))

    dialog._on_create()

    mock_warning.assert_called_once()
    assert dialog.project is None
    assert dialog.result() != dialog.DialogCode.Accepted


@patch("framelabs.ui.new_project_dialog.QMessageBox.warning")
def test_create_with_no_folder_warns_and_does_not_close(mock_warning, qtbot):
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Robot Walk Cycle")

    dialog._on_create()

    mock_warning.assert_called_once()
    assert dialog.project is None
    assert dialog.result() != dialog.DialogCode.Accepted


def test_create_with_valid_inputs_creates_project_and_accepts(qtbot, tmp_path):
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Robot Walk Cycle")
    dialog.folder_edit.setText(str(tmp_path))
    dialog.fps_spin.setValue(24)
    dialog.width_spin.setValue(1280)
    dialog.height_spin.setValue(720)

    dialog._on_create()

    assert dialog.project is not None
    assert dialog.project.name == "Robot Walk Cycle"
    assert dialog.project.fps == 24
    assert dialog.project.resolution == (1280, 720)
    assert (tmp_path / "Robot Walk Cycle" / "project.ffproj").is_file()
    assert dialog.result() == dialog.DialogCode.Accepted


@patch("framelabs.ui.new_project_dialog.QMessageBox.critical")
def test_create_failure_shows_error_and_does_not_close(mock_critical, qtbot, tmp_path):
    """A real ProjectCreationError -- triggered here by a folder that
    already exists -- should show a critical dialog and leave the
    NewProjectDialog open (not accepted), so the user can fix the name
    without re-entering everything."""
    (tmp_path / "Robot Walk Cycle").mkdir()
    dialog = NewProjectDialog()
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Robot Walk Cycle")
    dialog.folder_edit.setText(str(tmp_path))

    dialog._on_create()

    mock_critical.assert_called_once()
    assert dialog.project is None
    assert dialog.result() != dialog.DialogCode.Accepted

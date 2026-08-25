"""Tests for StartupDialog in ui/startup_dialog.py.

Exercises the dialog's own logic (Recent Projects population, which
outcome field gets set) directly against real widget state, following
this suite's existing widget-test convention (see
test_timeline_widget.py's docstring). NewProjectDialog itself is
exercised separately in its own test module, so it isn't re-tested
here -- just that StartupDialog wires its result through correctly.
"""

from framelabs.core.config import Config
from framelabs.ui.startup_dialog import StartupDialog


def _make_config(tmp_path):
    return Config(config_path=tmp_path / "config.json")


def test_no_recent_projects_shows_placeholder(qtbot, tmp_path):
    dialog = StartupDialog(_make_config(tmp_path))
    qtbot.addWidget(dialog)

    assert dialog._recent_list.count() == 1
    assert dialog._recent_list.item(0).text() == "No recent projects yet"
    assert not dialog._open_selected_button.isEnabled()


def test_recent_projects_populate_the_list(qtbot, tmp_path):
    config = _make_config(tmp_path)
    project_dir = tmp_path / "Robot Walk"
    project_dir.mkdir()
    config.add_recent_project(project_dir, "Robot Walk")

    dialog = StartupDialog(config)
    qtbot.addWidget(dialog)

    assert dialog._recent_list.count() == 1
    item = dialog._recent_list.item(0)
    assert "Robot Walk" in item.text()


def test_choosing_a_recent_project_sets_chosen_path_and_accepts(qtbot, tmp_path):
    config = _make_config(tmp_path)
    project_dir = tmp_path / "Robot Walk"
    project_dir.mkdir()
    config.add_recent_project(project_dir, "Robot Walk")

    dialog = StartupDialog(config)
    qtbot.addWidget(dialog)

    item = dialog._recent_list.item(0)
    dialog._on_recent_item_chosen(item)

    assert dialog.chosen_path == project_dir
    assert dialog.new_project is None
    assert dialog.result() == dialog.DialogCode.Accepted


def test_open_selected_button_enables_only_for_a_real_entry(qtbot, tmp_path):
    config = _make_config(tmp_path)
    project_dir = tmp_path / "Robot Walk"
    project_dir.mkdir()
    config.add_recent_project(project_dir, "Robot Walk")

    dialog = StartupDialog(config)
    qtbot.addWidget(dialog)

    dialog._recent_list.setCurrentRow(0)
    assert dialog._open_selected_button.isEnabled()


def test_recent_list_height_hugs_a_couple_of_entries(qtbot, tmp_path):
    """A short recent-projects list shouldn't reserve a big empty
    block below it -- its fixed height should scale with actual row
    count (up to MAX_VISIBLE_RECENT_ROWS), not sit at some unrelated
    minimum regardless of how few entries there are."""
    import framelabs.ui.startup_dialog as startup_dialog_module

    config = _make_config(tmp_path)
    for name in ("fish", "Test Project 8-23-26"):
        project_dir = tmp_path / name
        project_dir.mkdir()
        config.add_recent_project(project_dir, name)

    dialog = StartupDialog(config)
    qtbot.addWidget(dialog)

    row_height = dialog._recent_list.sizeHintForRow(0)
    expected = row_height * 2 + 2 * dialog._recent_list.frameWidth() + 4
    assert dialog._recent_list.height() == expected
    # and it should be comfortably shorter than the old fixed 140px
    # minimum this replaced, for just two entries
    assert dialog._recent_list.height() < 140


def test_recent_list_height_caps_at_max_visible_rows(qtbot, tmp_path):
    """A long recent-projects history should stop growing the list
    (and thus the dialog) past MAX_VISIBLE_RECENT_ROWS, scrolling for
    the rest instead of pushing the buttons off-screen."""
    import framelabs.ui.startup_dialog as startup_dialog_module

    config = _make_config(tmp_path)
    for i in range(startup_dialog_module.MAX_VISIBLE_RECENT_ROWS + 5):
        project_dir = tmp_path / f"Project {i}"
        project_dir.mkdir()
        config.add_recent_project(project_dir, f"Project {i}")

    dialog = StartupDialog(config)
    qtbot.addWidget(dialog)

    row_height = dialog._recent_list.sizeHintForRow(0)
    max_rows = startup_dialog_module.MAX_VISIBLE_RECENT_ROWS
    expected = row_height * max_rows + 2 * dialog._recent_list.frameWidth() + 4
    assert dialog._recent_list.height() == expected


def test_quit_rejects_without_setting_a_result(qtbot, tmp_path):
    dialog = StartupDialog(_make_config(tmp_path))
    qtbot.addWidget(dialog)

    dialog.reject()

    assert dialog.new_project is None
    assert dialog.chosen_path is None
    assert dialog.result() == dialog.DialogCode.Rejected


def test_open_project_sets_chosen_path_and_accepts(qtbot, tmp_path, monkeypatch):
    """_on_open_project() drives a QFileDialog, which can't be clicked in
    a headless test -- so this stubs QFileDialog.getExistingDirectory
    itself, matching how the rest of this suite avoids mocking Qt's own
    widgets by only ever stubbing the one static call that pops a
    native OS dialog (see NewProjectDialog's own Browse button, tested
    the same way elsewhere in this codebase)."""
    project_dir = tmp_path / "Robot Walk"
    project_dir.mkdir()

    import framelabs.ui.startup_dialog as startup_dialog_module

    monkeypatch.setattr(
        startup_dialog_module.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(project_dir)),
    )

    dialog = StartupDialog(_make_config(tmp_path))
    qtbot.addWidget(dialog)

    dialog._on_open_project()

    assert dialog.chosen_path == project_dir
    assert dialog.new_project is None
    assert dialog.result() == dialog.DialogCode.Accepted

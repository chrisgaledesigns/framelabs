"""Tests for framelabs.ui.workspace_tab_bar.WorkspaceTabBar."""

from PySide6.QtCore import Qt

from framelabs.ui.workspace_tab_bar import COMPOSITE, EDIT, EXPORT, WorkspaceTabBar


def test_edit_tab_is_checked_by_default(qtbot):
    bar = WorkspaceTabBar()
    qtbot.addWidget(bar)

    assert bar._buttons[EDIT].isChecked() is True
    assert bar._buttons[COMPOSITE].isChecked() is False
    assert bar._buttons[EXPORT].isChecked() is False


def test_has_a_button_for_each_workspace(qtbot):
    bar = WorkspaceTabBar()
    qtbot.addWidget(bar)

    assert set(bar._buttons.keys()) == {EDIT, COMPOSITE, EXPORT}


def test_clicking_composite_tab_emits_workspace_selected(qtbot):
    bar = WorkspaceTabBar()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.workspace_selected, timeout=1000) as blocker:
        qtbot.mouseClick(bar._buttons[COMPOSITE], Qt.MouseButton.LeftButton)

    assert blocker.args == [COMPOSITE]


def test_clicking_a_tab_highlights_only_that_tab(qtbot):
    bar = WorkspaceTabBar()
    qtbot.addWidget(bar)

    bar._on_clicked(EXPORT)

    assert bar._buttons[EXPORT].isChecked() is True
    assert bar._buttons[EDIT].isChecked() is False
    assert bar._buttons[COMPOSITE].isChecked() is False


def test_set_current_workspace_updates_highlight_without_signal(qtbot):
    bar = WorkspaceTabBar()
    qtbot.addWidget(bar)

    with qtbot.assertNotEmitted(bar.workspace_selected):
        bar.set_current_workspace(COMPOSITE)

    assert bar._buttons[COMPOSITE].isChecked() is True
    assert bar._buttons[EDIT].isChecked() is False


def test_set_current_workspace_can_switch_back_to_edit(qtbot):
    bar = WorkspaceTabBar()
    qtbot.addWidget(bar)

    bar.set_current_workspace(EXPORT)
    bar.set_current_workspace(EDIT)

    assert bar._buttons[EDIT].isChecked() is True
    assert bar._buttons[EXPORT].isChecked() is False

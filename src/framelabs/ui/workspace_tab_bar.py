"""Persistent workspace tab bar for FrameLabs.

Modeled on DaVinci Resolve's Edit/Fusion/Color/Fairlight/Deliver row: a
strip of tabs always visible at the bottom of the window, outside every
page's own content, so switching between Edit/Composite/Export is a
single click from anywhere instead of a menu action or a button buried
in one specific page. This is now the primary way to move between
workspaces -- the Export menu action and Playback Controls' Export button
still exist too, but both just select this bar's Export tab under the
hood (see main_window.py's _on_show_export_page()) rather than being a
second, independent way to switch pages.

A dumb widget, same "UI calls out, MainWindow owns behavior" split as
every other page/control in this app: WorkspaceTabBar only emits which
tab was clicked. It does not know what a "workspace" is, hold a
QStackedWidget reference, or decide what's enabled/disabled -- MainWindow
does the actual page swap and calls set_current_workspace() to keep the
bar's own highlighted tab in sync when a switch happens some other way
(e.g. the Export menu action).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

# Workspace ids, in the order their tabs are shown. Each id is also the
# key main_window.py uses to look up which QStackedWidget page and menu
# action belong to it -- see MainWindow._on_workspace_selected().
EDIT = "edit"
COMPOSITE = "composite"
EXPORT = "export"

_TAB_LABELS = (
    (EDIT, "Edit"),
    (COMPOSITE, "Composite"),
    (EXPORT, "Export"),
)


class WorkspaceTabBar(QWidget):
    """Bottom tab strip for switching between FrameLabs' workspaces."""

    workspace_selected = Signal(str)  # one of EDIT, COMPOSITE, EXPORT

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("workspaceTabBar")
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._buttons: dict[str, QPushButton] = {}
        for workspace_id, label in _TAB_LABELS:
            button = QPushButton(label)
            button.setObjectName("workspaceTab")
            button.setCheckable(True)
            button.setFlat(True)
            # partial-like capture via default arg, not a lambda closing
            # over the loop variable -- otherwise every button would fire
            # with the *last* workspace_id in _TAB_LABELS.
            button.clicked.connect(
                lambda _checked=False, wid=workspace_id: self._on_clicked(wid)
            )
            self._buttons[workspace_id] = button
            layout.addWidget(button)
        layout.addStretch()

        self.set_current_workspace(EDIT)

    def _on_clicked(self, workspace_id: str) -> None:
        self.set_current_workspace(workspace_id)
        self.workspace_selected.emit(workspace_id)

    def set_current_workspace(self, workspace_id: str) -> None:
        """Highlight `workspace_id`'s tab without emitting a signal.

        Called by MainWindow after any page switch that didn't originate
        from this bar (e.g. the Export menu action, or Playback Controls'
        Export button), so the bar's highlighted tab never drifts out of
        sync with the page actually on screen.

        Args:
            workspace_id: One of EDIT, COMPOSITE, EXPORT.
        """
        for wid, button in self._buttons.items():
            button.setChecked(wid == workspace_id)

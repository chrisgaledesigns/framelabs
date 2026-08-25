"""Patches main_window.py to open ExportDialog instead of firing all
three export formats directly. Verifies each old_str is found exactly
once before writing anything; aborts loudly with no changes written
otherwise."""

from pathlib import Path

PATH = Path("src/framelabs/ui/main_window.py")

PATCHES = [
    (
        "from framelabs.ui.export_controller import ExportController\n"
        "from framelabs.ui.inspector_panel import InspectorPanel",
        "from framelabs.ui.export_controller import ExportController\n"
        "from framelabs.ui.export_dialog import ExportDialog\n"
        "from framelabs.ui.inspector_panel import InspectorPanel",
    ),
    (
        '        self.export_render_action = QAction("Export Video, Sequence && GIF...", self)',  # noqa: E501
        '        self.export_render_action = QAction("Export...", self)',
    ),
    (
        '''    def _on_export_render(self) -> None:
        """Trigger the "Export Video, Sequence & GIF" action.

        Fires all three exports in one click, on ExportController's
        worker thread -- see that module's docstring for why. Disables
        the menu action for the duration so a second click can't overlap
        an export already in progress; re-enabled in both
        _on_export_succeeded() and _on_export_failed().
        """
        if self.project is None or self.project.project_path is None:
            return
        self.export_render_action.setEnabled(False)
        self.export_controller.export_requested.emit(self.project)''',
        '''    def _on_export_render(self) -> None:
        """Open the Export dialog, then fire only the formats the user
        checked, on ExportController's worker thread -- see that
        module's docstring for why exports run off the main thread.

        The dialog itself keeps its Export button disabled until at
        least one format is checked, so a Cancel/close is the only way
        to get here with nothing to run. Disables the menu action for
        the export's duration so a second click can't overlap one
        already in progress; re-enabled in both _on_export_succeeded()
        and _on_export_failed().
        """
        if self.project is None or self.project.project_path is None:
            return
        dialog = ExportDialog(self.project, self)
        if not dialog.exec():
            return
        request = dialog.export_request()
        self.export_render_action.setEnabled(False)
        self.export_controller.export_requested.emit(request)''',
    ),
]

text = PATH.read_text()

for old, new in PATCHES:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            "ABORTING, no changes written: expected 1 match, "
            f"found {count} for:\n{old[:80]}..."
        )

for old, new in PATCHES:
    text = text.replace(old, new)

PATH.write_text(text)
print("main_window.py patched successfully.")

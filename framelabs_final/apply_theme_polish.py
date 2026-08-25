#!/usr/bin/env python3
"""Apply the FrameLabs dark theme + polish pass. Idempotent -- safe to re-run.

Run from the repo root:
    python apply_theme_polish.py
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent

THEME_PY = "\"\"\"Dark theme for FrameLabs, matching the studio mockup.\n\nA single QSS string applied once, app-wide, from `main.py`. Colors are\nnamed constants so any widget-specific tweaks (e.g. TimelineWidget's\nselection border) can reference the same palette instead of hardcoding\ntheir own hex values.\n\"\"\"\n\n# --- Palette -----------------------------------------------------------\nBG_WINDOW = \"#0d1821\"       # app chrome: menu bar, side panels, bottom bar\nBG_CANVAS = \"#05090c\"       # the live-view / capture surface, darkest area\nBG_PANEL = \"#141f2a\"        # cards, inputs, thumbnails, list rows\nBG_PANEL_RAISED = \"#182531\"  # slightly lighter cards (footer bars, headers)\nBG_PANEL_HOVER = \"#1e2c39\"\nBORDER = \"#22323f\"\nBORDER_SOFT = \"#182530\"\nACCENT = \"#00bc90\"          # selection border, active states, highlights\nACCENT_DIM = \"#0a3d31\"       # accent at low opacity feel, for subtle fills\nTEXT_PRIMARY = \"#eef2f5\"\nTEXT_SECONDARY = \"#7c8b98\"  # menu items, section labels, field labels\nTEXT_DISABLED = \"#455563\"\n\nFONT_FAMILY = '\"JetBrains Mono\", \"Cascadia Code\", \"Consolas\", \"SF Mono\", \"Menlo\", monospace'\n\nSTYLESHEET = f\"\"\"\n* {{\n    font-family: {FONT_FAMILY};\n    font-size: 12px;\n    color: {TEXT_PRIMARY};\n}}\n\nQMainWindow, QDialog, QWidget {{\n    background-color: {BG_WINDOW};\n}}\n\nQMenuBar {{\n    background-color: {BG_WINDOW};\n    border-bottom: 1px solid {BORDER};\n    padding: 6px 10px;\n    color: {TEXT_SECONDARY};\n}}\nQMenuBar::item {{\n    background: transparent;\n    padding: 5px 12px;\n    border-radius: 5px;\n    margin: 0 1px;\n}}\nQMenuBar::item:selected {{\n    background: {BG_PANEL_HOVER};\n    color: {TEXT_PRIMARY};\n}}\nQMenu {{\n    background-color: {BG_PANEL};\n    border: 1px solid {BORDER};\n    color: {TEXT_PRIMARY};\n    padding: 6px;\n    border-radius: 8px;\n}}\nQMenu::item {{\n    padding: 7px 26px 7px 14px;\n    border-radius: 5px;\n}}\nQMenu::item:selected {{\n    background-color: {ACCENT};\n    color: {BG_WINDOW};\n}}\nQMenu::separator {{\n    height: 1px;\n    background: {BORDER};\n    margin: 5px 8px;\n}}\n\nQSplitter::handle {{\n    background-color: {BG_WINDOW};\n    width: 13px;\n}}\nQSplitter::handle:hover {{\n    background-color: {BORDER_SOFT};\n}}\n\n/* Central capture / live-view surface */\nQGraphicsView#liveViewWidget {{\n    background-color: {BG_CANVAS};\n    border: 1px solid {BORDER_SOFT};\n    border-radius: 10px;\n}}\n\n/* Side panels: project browser + inspector */\n#projectBrowserWidget, #inspectorPanel, QScrollArea {{\n    background-color: {BG_WINDOW};\n    border: none;\n}}\n\nQPushButton {{\n    background-color: {BG_PANEL};\n    border: 1px solid {BORDER};\n    border-radius: 6px;\n    padding: 6px 14px;\n    color: {TEXT_PRIMARY};\n}}\nQPushButton:hover {{\n    background-color: {BG_PANEL_HOVER};\n    border-color: {ACCENT};\n}}\nQPushButton:pressed {{\n    background-color: {BORDER};\n}}\nQPushButton:disabled {{\n    color: {TEXT_DISABLED};\n    border-color: {BORDER_SOFT};\n}}\nQPushButton:checkable:checked {{\n    background-color: {ACCENT_DIM};\n    border-color: {ACCENT};\n    color: {ACCENT};\n}}\nQPushButton:flat {{\n    background: transparent;\n    border: none;\n    color: {TEXT_SECONDARY};\n    text-align: left;\n    font-weight: 600;\n    font-size: 12px;\n    padding: 10px 4px;\n}}\nQPushButton:flat:hover {{\n    color: {TEXT_PRIMARY};\n}}\n\nQLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{\n    background-color: {BG_PANEL};\n    border: 1px solid {BORDER};\n    border-radius: 6px;\n    padding: 6px 10px;\n    color: {TEXT_PRIMARY};\n    selection-background-color: {ACCENT};\n}}\nQLineEdit:disabled, QComboBox:disabled {{\n    color: {TEXT_DISABLED};\n    background-color: transparent;\n    border-color: transparent;\n}}\nQLineEdit:read-only {{\n    background-color: transparent;\n    border-color: transparent;\n}}\nQLineEdit:focus, QComboBox:focus {{\n    border-color: {ACCENT};\n}}\nQComboBox::drop-down {{\n    border: none;\n    width: 20px;\n}}\nQComboBox QAbstractItemView {{\n    background-color: {BG_PANEL};\n    border: 1px solid {BORDER};\n    border-radius: 6px;\n    selection-background-color: {ACCENT};\n    selection-color: {BG_WINDOW};\n    padding: 4px;\n}}\n\n/* Inspector fields: right-aligned, bold values, no boxy chrome --\n   matches the mockup's plain \"label ... value\" rows. */\n#inspectorPanel QLineEdit, #inspectorPanel QComboBox {{\n    background-color: transparent;\n    border: none;\n    padding: 4px 2px;\n    font-weight: 600;\n    qproperty-alignment: AlignRight;\n}}\n#inspectorPanel QLineEdit:focus, #inspectorPanel QComboBox:focus {{\n    background-color: {BG_PANEL};\n    border: 1px solid {ACCENT};\n    border-radius: 6px;\n}}\n#inspectorPanel QFormLayout QLabel {{\n    color: {TEXT_SECONDARY};\n    font-weight: 500;\n    padding: 4px 2px;\n}}\n\nQFormLayout QLabel, QLabel {{\n    color: {TEXT_SECONDARY};\n}}\n\nQListWidget {{\n    background-color: {BG_WINDOW};\n    border: none;\n    outline: none;\n}}\nQListWidget::item {{\n    border-radius: 6px;\n    padding: 4px;\n    margin: 1px 0;\n    color: {TEXT_PRIMARY};\n}}\nQListWidget::item:selected {{\n    background-color: {BG_PANEL_HOVER};\n    border: 1px solid {ACCENT};\n}}\nQListWidget::item:hover {{\n    background-color: {BG_PANEL};\n}}\n\nQScrollBar:vertical, QScrollBar:horizontal {{\n    background: {BG_WINDOW};\n    border: none;\n    margin: 0;\n}}\nQScrollBar:vertical {{ width: 10px; }}\nQScrollBar:horizontal {{ height: 10px; }}\nQScrollBar::handle {{\n    background: {BG_PANEL};\n    border-radius: 5px;\n    min-height: 24px;\n    min-width: 24px;\n}}\nQScrollBar::handle:hover {{\n    background: {BORDER};\n}}\nQScrollBar::add-line, QScrollBar::sub-line {{\n    height: 0;\n    width: 0;\n}}\n\nQStatusBar {{\n    background-color: {BG_WINDOW};\n    color: {TEXT_SECONDARY};\n    border-top: 1px solid {BORDER};\n}}\n\nQToolTip {{\n    background-color: {BG_PANEL};\n    color: {TEXT_PRIMARY};\n    border: 1px solid {BORDER};\n    border-radius: 6px;\n    padding: 5px 8px;\n}}\n\n/* Playback controls / frame action bar footer strips */\nPlaybackControls, FrameActionBar {{\n    background-color: {BG_PANEL_RAISED};\n    border-top: 1px solid {BORDER};\n}}\n\"\"\"\n\n"

EDITS = [('src/framelabs/app/main.py', [('from framelabs.ui.main_window import MainWindow\n', 'from framelabs.ui.main_window import MainWindow\nfrom framelabs.ui.theme import STYLESHEET\n'), ('app = QApplication(sys.argv)\n    window = MainWindow()', 'app = QApplication(sys.argv)\n    app.setStyleSheet(STYLESHEET)\n    window = MainWindow()')]), ('src/framelabs/ui/inspector_panel.py', [('        super().__init__()\n\n        layout = QFormLayout(self)\n', '        super().__init__()\n        self.setObjectName("inspectorPanel")\n\n        layout = QFormLayout(self)\n        layout.setContentsMargins(18, 18, 18, 18)\n        layout.setVerticalSpacing(14)\n        layout.setHorizontalSpacing(12)\n')]), ('src/framelabs/ui/live_view_widget.py', [('        super().__init__()\n        self._scene = QGraphicsScene(self)\n', '        super().__init__()\n        self.setObjectName("liveViewWidget")\n        self._scene = QGraphicsScene(self)\n'), ('self.setBackgroundBrush(QColor(30, 30, 30))', 'self.setBackgroundBrush(QColor("#05090c"))')]), ('src/framelabs/ui/project_browser_widget.py', [('        self.setStyleSheet(\n            "QPushButton { text-align: left; font-weight: bold; "\n            "border: none; padding: 4px 2px; }"\n        )', '        self.setStyleSheet(\n            "QPushButton { text-align: left; font-weight: 600; "\n            "font-size: 12px; border: none; padding: 10px 4px; }"\n        )'), ('        """Build the panel\'s sections (initially empty/hidden)."""\n        super().__init__()\n\n        layout = QVBoxLayout(self)\n        layout.setContentsMargins(4, 4, 4, 4)\n', '        """Build the panel\'s sections (initially empty/hidden)."""\n        super().__init__()\n        self.setObjectName("projectBrowserWidget")\n\n        layout = QVBoxLayout(self)\n        layout.setContentsMargins(10, 10, 10, 10)\n        layout.setSpacing(2)\n')]), ('src/framelabs/ui/timeline_widget.py', [('SELECTION_BORDER_COLOR = "#3b82f6"  # accent blue', 'SELECTION_BORDER_COLOR = "#00bc90"  # accent teal-green, matches theme.ACCENT'), ('        """Build the playback controls bar."""\n        super().__init__()\n        self.setFixedHeight(50)\n        self.setStyleSheet("border: 1px solid gray;")\n\n        layout = QHBoxLayout(self)\n', '        """Build the playback controls bar."""\n        super().__init__()\n        self.setFixedHeight(56)\n\n        layout = QHBoxLayout(self)\n        layout.setContentsMargins(14, 8, 14, 8)\n        layout.setSpacing(8)\n'), ('        """Build the bar, disabled until a frame is selected."""\n        super().__init__()\n        self.setFixedHeight(50)\n        self.setStyleSheet("border: 1px solid gray;")\n\n        layout = QHBoxLayout(self)\n', '        """Build the bar, disabled until a frame is selected."""\n        super().__init__()\n        self.setFixedHeight(56)\n\n        layout = QHBoxLayout(self)\n        layout.setContentsMargins(14, 8, 14, 8)\n        layout.setSpacing(8)\n'), ('self.setStyleSheet("border: 1px solid gray;" if visible else "")', 'self.setStyleSheet("border: 1px solid #1f2d38;" if visible else "")')]), ('src/framelabs/ui/main_window.py', [('        splitter = QSplitter(Qt.Orientation.Horizontal)\n        splitter.addWidget(self.project_browser_widget)', '        splitter = QSplitter(Qt.Orientation.Horizontal)\n        splitter.setHandleWidth(13)\n        splitter.addWidget(self.project_browser_widget)'), ('        central_layout = QVBoxLayout(central_widget)\n        central_layout.setContentsMargins(0, 0, 0, 0)\n        central_layout.addWidget(splitter, 1)', '        central_layout = QVBoxLayout(central_widget)\n        central_layout.setContentsMargins(12, 12, 12, 0)\n        central_layout.setSpacing(10)\n        central_layout.addWidget(splitter, 1)')]), ('tests/test_timeline_widget.py', [('assert "0px solid #3b82f6" in _all_style(thumbnail)', 'assert "0px solid #00bc90" in _all_style(thumbnail)')])]


def write_theme_file():
    path = ROOT / "src" / "framelabs" / "ui" / "theme.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == THEME_PY:
        print(f"  = {path.relative_to(ROOT)} (already up to date)")
        return
    path.write_text(THEME_PY, encoding="utf-8", newline="\n")
    print(f"  + wrote {path.relative_to(ROOT)}")


def apply_edits():
    any_missing = False
    for rel_path, replacements in EDITS:
        path = ROOT / rel_path
        if not path.exists():
            print(f"  ! MISSING FILE: {rel_path} -- is this the framelabs repo root?")
            any_missing = True
            continue
        text = path.read_text(encoding="utf-8")
        changed = False
        for old, new in replacements:
            if new in text:
                continue  # already applied
            if old not in text:
                print(f"  ! could not find expected text in {rel_path} -- "
                      f"may already differ from what this script expects. "
                      f"Skipping that one hunk (file may be partially patched).")
                continue
            text = text.replace(old, new, 1)
            changed = True
        if changed:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"  + updated {rel_path}")
        else:
            print(f"  = {rel_path} (already up to date)")
    return not any_missing


def main():
    print("Applying FrameLabs dark theme + polish pass...")
    if not (ROOT / "pyproject.toml").exists():
        print("ERROR: pyproject.toml not found next to this script. "
              "Run it from your framelabs repo root.")
        sys.exit(1)
    write_theme_file()
    ok = apply_edits()
    print()
    if ok:
        print("Done. Next: pytest tests/ -q   then   python -m framelabs.app.main")
    else:
        print("Done, with warnings above -- check you're in the right folder.")


if __name__ == "__main__":
    main()

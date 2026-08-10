"""Dark theme for FrameLabs, matching the studio mockup.

A single QSS string applied once, app-wide, from `main.py`. Colors are
named constants so any widget-specific tweaks (e.g. TimelineWidget's
selection border) can reference the same palette instead of hardcoding
their own hex values.
"""

# --- Palette -----------------------------------------------------------
BG_WINDOW = "#0d1821"       # app chrome: menu bar, side panels, bottom bar
BG_CANVAS = "#05090c"       # the live-view / capture surface, darkest area
BG_PANEL = "#141f2a"        # cards, inputs, thumbnails, list rows
BG_PANEL_RAISED = "#182531"  # slightly lighter cards (footer bars, headers)
BG_PANEL_HOVER = "#1e2c39"
BORDER = "#22323f"
BORDER_SOFT = "#182530"
ACCENT = "#00bc90"          # selection border, active states, highlights
ACCENT_DIM = "#0a3d31"       # accent at low opacity feel, for subtle fills
TEXT_PRIMARY = "#eef2f5"
TEXT_SECONDARY = "#7c8b98"  # menu items, section labels, field labels
TEXT_DISABLED = "#455563"

FONT_FAMILY = (
    '"JetBrains Mono", "Cascadia Code", "Consolas", "SF Mono", "Menlo", monospace'
)

STYLESHEET = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 12px;
    color: {TEXT_PRIMARY};
}}

QMainWindow, QDialog, QWidget {{
    background-color: {BG_WINDOW};
}}

QMenuBar {{
    background-color: {BG_WINDOW};
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    color: {TEXT_SECONDARY};
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 12px;
    border-radius: 5px;
    margin: 0 1px;
}}
QMenuBar::item:selected {{
    background: {BG_PANEL_HOVER};
    color: {TEXT_PRIMARY};
}}
QMenu {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    color: {TEXT_PRIMARY};
    padding: 6px;
    border-radius: 8px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: {ACCENT};
    color: {BG_WINDOW};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 5px 8px;
}}

QSplitter::handle {{
    background-color: {BG_WINDOW};
    width: 13px;
}}
QSplitter::handle:hover {{
    background-color: {BORDER_SOFT};
}}

/* Central capture / live-view surface */
QGraphicsView#liveViewWidget {{
    background-color: {BG_CANVAS};
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
}}

/* Side panels: project browser + inspector */
#projectBrowserWidget, #inspectorPanel, QScrollArea {{
    background-color: {BG_WINDOW};
    border: none;
}}

QPushButton {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {BG_PANEL_HOVER};
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {BORDER};
}}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
    border-color: {BORDER_SOFT};
}}
QPushButton:checkable:checked {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:flat {{
    background: transparent;
    border: none;
    color: {TEXT_SECONDARY};
    text-align: left;
    font-weight: 600;
    font-size: 12px;
    padding: 10px 4px;
}}
QPushButton:flat:hover {{
    color: {TEXT_PRIMARY};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {TEXT_DISABLED};
    background-color: transparent;
    border-color: transparent;
}}
QLineEdit:read-only {{
    background-color: transparent;
    border-color: transparent;
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {ACCENT};
    selection-color: {BG_WINDOW};
    padding: 4px;
}}

/* Inspector fields: right-aligned, bold values, no boxy chrome --
   matches the mockup's plain "label ... value" rows. */
#inspectorPanel QLineEdit, #inspectorPanel QComboBox {{
    background-color: transparent;
    border: none;
    padding: 4px 2px;
    font-weight: 600;
    qproperty-alignment: AlignRight;
}}
#inspectorPanel QLineEdit:focus, #inspectorPanel QComboBox:focus {{
    background-color: {BG_PANEL};
    border: 1px solid {ACCENT};
    border-radius: 6px;
}}
#inspectorPanel QFormLayout QLabel {{
    color: {TEXT_SECONDARY};
    font-weight: 500;
    padding: 4px 2px;
}}

QFormLayout QLabel, QLabel {{
    color: {TEXT_SECONDARY};
}}

QListWidget {{
    background-color: {BG_WINDOW};
    border: none;
    outline: none;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 4px;
    margin: 1px 0;
    color: {TEXT_PRIMARY};
}}
QListWidget::item:selected {{
    background-color: {BG_PANEL_HOVER};
    border: 1px solid {ACCENT};
}}
QListWidget::item:hover {{
    background-color: {BG_PANEL};
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: {BG_WINDOW};
    border: none;
    margin: 0;
}}
QScrollBar:vertical {{ width: 10px; }}
QScrollBar:horizontal {{ height: 10px; }}
QScrollBar::handle {{
    background: {BG_PANEL};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:hover {{
    background: {BORDER};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QStatusBar {{
    background-color: {BG_WINDOW};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
}}

QToolTip {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* Playback controls / frame action bar footer strips */
PlaybackControls, FrameActionBar {{
    background-color: {BG_PANEL_RAISED};
    border-top: 1px solid {BORDER};
}}
"""


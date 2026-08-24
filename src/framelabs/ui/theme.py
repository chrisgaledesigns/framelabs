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
ACCENT_YELLOW = "#ffe800"    # logo's "LABS" wordmark yellow -- used sparingly
                              # on pre-launch screens (e.g. version badge)
                              # over the hero photo, never in-app chrome.
TEXT_PRIMARY = "#eef2f5"
TEXT_SECONDARY = "#7c8b98"  # menu items, section labels, field labels
TEXT_DISABLED = "#455563"

# Corner radii. Pro tools (Blender, Resolve, After Effects) round just
# enough to soften a hard edge -- nowhere near a pill shape. Buttons and
# fields get the tightest radius; menus/popovers/panels get one step up
# since a bigger shape reads better with slightly more curve.
RADIUS_TIGHT = "3px"   # buttons, inputs, list rows, checkboxes
RADIUS_PANEL = "4px"   # menus, popups, tooltips, the live-view frame

# Sans-serif, tuned for small UI sizes rather than a document face --
# Inter/SF/Segoe/Roboto are all designed with tall x-heights and open
# counters that stay legible at 12px, unlike the monospace stack this
# theme used to use.
FONT_FAMILY = (
    '"Inter", "SF Pro Text", "Segoe UI", "Roboto", "Helvetica Neue", '
    '"DejaVu Sans", Arial, sans-serif'
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
    border-radius: {RADIUS_TIGHT};
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
    border-radius: {RADIUS_PANEL};
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: {RADIUS_TIGHT};
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
    border-radius: {RADIUS_PANEL};
}}

/* Side panels: project browser + inspector */
#projectBrowserWidget, #inspectorPanel, QScrollArea {{
    background-color: {BG_WINDOW};
    border: none;
}}

/* Panel title labels ("Project Browser", "Live View", "Inspector",
   "Timeline") sitting above each main-window pane -- one step quieter
   than a section header, just enough to label which pane is which. */
/* Qt's QSS subset has neither text-transform nor letter-spacing, so the
   widget code uppercases the label text itself before setting it. */
QLabel#panelTitle {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
    font-weight: 600;
    padding: 0 2px 6px 2px;
    border-bottom: 1px solid {BORDER_SOFT};
    margin-bottom: 6px;
}}

QPushButton {{
    background-color: {BG_PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_TIGHT};
    padding: 7px 16px;
    color: {TEXT_PRIMARY};
    font-weight: 400;
}}
QPushButton:hover {{
    background-color: {BG_PANEL_HOVER};
    border-color: #3c5468;
}}
QPushButton:pressed {{
    background-color: {BORDER};
    padding-top: 8px;
    padding-bottom: 6px;
}}
QPushButton:disabled {{
    background-color: {BG_PANEL};
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
    font-weight: 500;
    font-size: 12px;
    padding: 10px 4px;
}}
QPushButton:flat:hover {{
    color: {TEXT_PRIMARY};
}}

/* Project Browser's overflow ("burger") button -- References/Overlays'
   tab stand-in. An #objectName selector so it wins over the generic
   QPushButton:flat rule above regardless of stylesheet order, since a
   checked overflow button needs to read as "active" the same way a
   real tab does. */
#projectBrowserOverflowButton {{
    padding: 7px 10px;
}}
#projectBrowserOverflowButton:checked {{
    color: {ACCENT};
}}

/* Primary/default action -- the button a dialog's Enter key triggers
   (Create, Save, Ok, ...). Solid accent fill so the one action most
   people want stands out from every neutral button around it, instead
   of every button in a dialog competing at the same visual weight. */
QPushButton:default {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: {BG_WINDOW};
    font-weight: 500;
}}
QPushButton:default:hover {{
    background-color: #0fc294;
    border-color: #0fc294;
}}
QPushButton:default:pressed {{
    background-color: #009973;
    border-color: #009973;
}}
QPushButton:default:disabled {{
    background-color: {BG_PANEL};
    border-color: {BORDER_SOFT};
    color: {TEXT_DISABLED};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_TIGHT};
    padding: 7px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: {BG_WINDOW};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: #3c5468;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {TEXT_DISABLED};
    background: transparent;
    border-color: transparent;
}}
QLineEdit:read-only {{
    background: transparent;
    border-color: transparent;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {ACCENT};
    padding: 6.5px 9.5px;
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SECONDARY};
    margin-right: 10px;
}}
QComboBox::down-arrow:on {{
    border-top-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL};
    selection-background-color: {ACCENT};
    selection-color: {BG_WINDOW};
    padding: 4px;
    outline: none;
}}

/* Spin buttons: native OS up/down chrome doesn't match a flat dark
   theme, so these are redrawn as plain triangles that pick up the
   same hover feedback as everything else instead of standing out as
   the one un-styled control. */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 18px;
    subcontrol-origin: border;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: {RADIUS_TIGHT};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: {RADIUS_TIGHT};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {BG_PANEL_HOVER};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {TEXT_SECONDARY};
}}
QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {{
    border-bottom-color: {ACCENT};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SECONDARY};
}}
QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {{
    border-top-color: {ACCENT};
}}

/* Checkboxes -- e.g. the Export dialog's format list. Flat filled-square
   checked state (no native checkmark glyph) to match the rest of the
   flat, borderless-icon language used everywhere else in this theme. */
QCheckBox {{
    spacing: 9px;
    color: {TEXT_PRIMARY};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_TIGHT};
    background-color: {BG_PANEL};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox::indicator:disabled {{
    border-color: {BORDER_SOFT};
    background-color: transparent;
}}

/* Inspector fields: right-aligned, bold values, no boxy chrome --
   matches the mockup's plain "label ... value" rows. */
#inspectorPanel QLineEdit, #inspectorPanel QComboBox {{
    background: transparent;
    border: none;
    padding: 4px 2px;
    font-weight: 500;
    qproperty-alignment: AlignRight;
}}
#inspectorPanel QLineEdit:focus, #inspectorPanel QComboBox:focus {{
    background: {BG_PANEL};
    border: 1.5px solid {ACCENT};
    border-radius: {RADIUS_TIGHT};
    padding: 3.5px 1.5px;
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
    border-radius: {RADIUS_TIGHT};
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
    border-radius: {RADIUS_TIGHT};
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
    border-radius: {RADIUS_PANEL};
    padding: 5px 8px;
}}

/* Playback controls / frame action bar footer strips */
PlaybackControls, FrameActionBar {{
    background-color: {BG_PANEL_RAISED};
    border-top: 1px solid {BORDER};
}}

/* Timecode readout -- centered between Live View and the Timeline
   strip. A small pill so it reads as its own control, not just loose
   text floating in the gap between panes. */
#timecodeWidget {{
    background-color: {BG_PANEL_RAISED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL};
}}
#timecodeReadout {{
    color: {TEXT_PRIMARY};
    font-family: "SF Mono", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 1px;
}}
#timecodeFrameCount {{
    color: {TEXT_SECONDARY};
    font-size: 11px;
    border-left: 1px solid {BORDER};
    padding-left: 10px;
}}
"""



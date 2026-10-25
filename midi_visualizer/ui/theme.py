"""界面配色与全局样式（GitHub Dark 风格，配合深色 IDE）。"""

from __future__ import annotations

BG = "#0D1117"
PANEL = "#161B22"
PANEL_ALT = "#1C2128"
BORDER = "#30363D"
TEXT = "#E6EDF3"
TEXT_DIM = "#8B949E"
TEXT_MUTED = "#6E7681"
ACCENT = "#58A6FF"
GREEN = "#3FB950"
RED = "#F85149"
ORANGE = "#FFA657"
PURPLE = "#BC8CFF"

WHITE_KEY = "#E6EDF3"
WHITE_KEY_SHADOW = "#C9D1D9"
BLACK_KEY = "#10151C"
BLACK_KEY_EDGE = "#30363D"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QFrame#Panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#SectionTitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QLabel#BigNote {{
    color: {ACCENT};
    font-size: 40px;
    font-weight: 700;
    font-family: "Consolas", "Cascadia Mono", monospace;
}}
QLabel#Chip {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 8px;
    color: {TEXT_DIM};
    font-family: "Consolas", "Cascadia Mono", monospace;
}}
QComboBox, QLineEdit {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 18px;
    selection-background-color: {ACCENT};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: #1F6FEB;
    outline: none;
}}
QPushButton, QToolButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 12px;
    color: {TEXT};
}}
QPushButton:hover, QToolButton:hover {{
    border-color: {ACCENT};
    background: #1F2937;
}}
QPushButton:pressed, QToolButton:pressed {{ background: #111827; }}
QPushButton:checked, QToolButton:checked {{
    background: #1F6FEB;
    border-color: #1F6FEB;
    color: #FFFFFF;
}}
QPlainTextEdit {{
    background: #0A0E14;
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    color: {TEXT};
    selection-background-color: #1F6FEB;
}}
QCheckBox {{ spacing: 6px; color: {TEXT_DIM}; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border-radius: 3px;
    border: 1px solid {BORDER};
    background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: {BORDER};
}}
QSlider::sub-page:horizontal {{
    height: 4px; border-radius: 2px; background: {ACCENT};
}}
QSlider::handle:horizontal {{
    width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    background: {TEXT}; border: 1px solid {BORDER};
}}
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {PANEL_ALT};
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}
QStatusBar {{ color: {TEXT_DIM}; background: {PANEL}; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{
    background: {PANEL_ALT}; color: {TEXT};
    border: 1px solid {BORDER}; padding: 4px;
}}
"""

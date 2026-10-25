"""五线谱控件：把当前按下的音画到大谱表（高音谱 + 低音谱）上。

坐标体系说明（重要）：
    每个音先换算成「音级步进 step」——以自然音阶为单位，C4 = 28，
    每 +1 表示在谱表上升高半格（一条线到一个相邻间）。
    同一个八度内 C=0, D=1, E=2, F=3, G=4, A=5, B=6，
    所以 step = (八度 × 7) + 自然音级；升号不改变 step，只额外画一个 ♯。

    大谱表的线位置：
        高音谱（G 谱号）五条线自下而上 E4 G4 B4 D5 F5 -> step 30 32 34 36 38
        低音谱（F 谱号）五条线自下而上 G2 B2 D3 F3 A3 -> step 18 20 22 24 26
    中央 C（step 28）正好落在两个谱表中间，用它自己的加线表示。

视窗策略：
    默认显示 C2–C6 这一块（日常弹奏几乎都在这），一旦有音超出就自动把视窗撑大，
    所以低音的 A0 或高音的 C8 都不会被裁掉，只是谱表会相应缩小一点。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPen,
    QRawFont,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..core.notes import note_name
from . import theme
from .piano_widget import velocity_color

# 音级 -> (自然音级 0-6, 是否升号)
_STEP_TABLE: dict[int, tuple[int, int]] = {
    0: (0, 0), 1: (0, 1), 2: (1, 0), 3: (1, 1), 4: (2, 0), 5: (3, 0),
    6: (3, 1), 7: (4, 0), 8: (4, 1), 9: (5, 0), 10: (5, 1), 11: (6, 0),
}

TREBLE_LINES = (30, 32, 34, 36, 38)   # E4 G4 B4 D5 F5
BASS_LINES = (18, 20, 22, 24, 26)     # G2 B2 D3 F3 A3
MIDDLE_C_STEP = 28

DEFAULT_LOW_STEP = 14                 # C2
DEFAULT_HIGH_STEP = 42                # C6
MIN_SPACING, MAX_SPACING = 7.0, 24.0

_MUSIC_CHARS = "\U0001D11E\U0001D122\u266F"   # 高音谱号 / 低音谱号 / 升号
_music_family: str | None | bool = False       # False = 还没探测过


def staff_step(note: int) -> tuple[int, int]:
    """MIDI 音符号 -> (音级步进, 是否升号)。"""
    pitch_class = note % 12
    octave = note // 12 - 1
    step, accidental = _STEP_TABLE[pitch_class]
    return octave * 7 + step, accidental


def music_font_family() -> str | None:
    """找一个能渲染音乐符号的字体；没有就返回 None（走手绘降级方案）。"""
    global _music_family
    if _music_family is not False:
        return _music_family  # type: ignore[return-value]
    candidates = ["Bravura", "Bravura Text", "Noto Music", "Segoe UI Symbol",
                  "Opus", "DejaVu Sans"]
    families = set(QFontDatabase.families())
    found: str | None = None
    for family in candidates:
        if family not in families:
            continue
        raw = QRawFont.fromFont(QFont(family, 40))
        if all(idx != 0 for idx in raw.glyphIndexesForString(_MUSIC_CHARS)):
            found = family
            break
    _music_family = found
    return found


def _fit_font(family: str, glyph: str, target_height: float) -> QFont:
    """按目标墨迹高度反推字号，这样换任何音乐字体都能对上谱表比例。"""
    font = QFont(family)
    font.setPixelSize(100)
    ink = QFontMetricsF(font).boundingRect(glyph).height()
    font.setPixelSize(max(8, int(round(100.0 * target_height / max(1.0, ink)))))
    return font


class StaffView(QWidget):
    """大谱表：实时显示当前按下的音在五线谱上的位置。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._notes: dict[int, tuple[int, bool]] = {}
        self._family = music_font_family()
        self.setMinimumWidth(190)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(252)
        self.setToolTip("大谱表（高音谱 + 低音谱）：实心音头＝正在按下，空心＝踏板延音中；"
                        "升号以临时记号表示（不设调号）")

    # ------------------------------------------------------------------
    def set_notes(self, notes: dict[int, tuple[int, bool]]) -> None:
        """notes: note -> (velocity, sustained)。"""
        if notes != self._notes:
            self._notes = dict(notes)
            self.update()

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------
    def _window(self) -> tuple[int, int]:
        """当前要显示的 step 范围（含上下留白），超出默认音域时自动扩展。"""
        low, high = DEFAULT_LOW_STEP, DEFAULT_HIGH_STEP
        for note in self._notes:
            step, _ = staff_step(note)
            low = min(low, step)
            high = max(high, step)
        return low - 2, high + 2

    def _geometry(self) -> tuple[float, float, int]:
        """返回 (行距 s, 顶部 y, 视窗最高 step)。"""
        low, high = self._window()
        span = max(8, high - low)                       # 半格数
        avail = max(60.0, self.height() - 20.0)
        s = max(MIN_SPACING, min(MAX_SPACING, avail * 2.0 / span))
        total = span * s / 2.0
        top = (self.height() - total) / 2.0
        return s, top, high

    def _y_of(self, step: int, s: float, top: float, high: int) -> float:
        return top + (high - step) * s / 2.0

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0A0E14"))
        painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        s, top, high = self._geometry()
        left = 26.0
        right = w - 8.0

        self._draw_staves(painter, left, right, s, top, high)
        self._draw_clefs(painter, left, s, top, high)
        self._draw_notes(painter, left, right, s, top, high)

        if not self._notes:
            painter.setPen(QColor(theme.TEXT_MUTED))
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(11)
            painter.setFont(font)
            painter.drawText(QRectF(0, h - 26, w, 18),
                             Qt.AlignmentFlag.AlignHCenter, "按下一个琴键…")

    # -- 谱表 -----------------------------------------------------------
    def _draw_staves(self, painter: QPainter, left: float, right: float,
                     s: float, top: float, high: int) -> None:
        # 每条谱表先铺一层极淡的底色带，让"五线"区域在长条控件里更立得住
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 9))
        for lines in (BASS_LINES, TREBLE_LINES):
            y0 = self._y_of(lines[-1], s, top, high)
            y1 = self._y_of(lines[0], s, top, high)
            painter.drawRoundedRect(QRectF(left, y0, right - left, y1 - y0), 3, 3)

        painter.setPen(QPen(QColor(theme.BORDER).lighter(145), 1.0))
        for step in (*BASS_LINES, *TREBLE_LINES):
            y = self._y_of(step, s, top, high)
            painter.drawLine(QPointF(left, y), QPointF(right, y))

        # 左侧小节线 + 简易大括号，把两个谱表连成一个系统
        painter.setPen(QPen(QColor(theme.BORDER).lighter(155), 1.3))
        y_top = self._y_of(TREBLE_LINES[-1], s, top, high)
        y_bot = self._y_of(BASS_LINES[0], s, top, high)
        painter.drawLine(QPointF(left, y_top), QPointF(left, y_bot))
        brace_x = left - 5
        painter.drawLine(QPointF(brace_x, y_top + 2), QPointF(brace_x, y_bot - 2))
        painter.drawLine(QPointF(brace_x, y_top + 2), QPointF(left - 1, y_top + 2))
        painter.drawLine(QPointF(brace_x, y_bot - 2), QPointF(left - 1, y_bot - 2))

    # -- 谱号 -----------------------------------------------------------
    def _draw_clefs(self, painter: QPainter, left: float, s: float,
                    top: float, high: int) -> None:
        painter.setPen(QColor(theme.TEXT_DIM))
        treble_y = self._y_of(34, s, top, high)
        bass_y = self._y_of(22, s, top, high)

        if self._family:
            font = _fit_font(self._family, "\U0001D11E", s * 6.6)
            painter.setFont(font)
            self._draw_glyph_centered(painter, "\U0001D11E", left + 3, treble_y, font)
            self._draw_glyph_centered(painter, "\U0001D122", left + 4, bass_y, font)
        else:
            # 没有音乐字体时的降级：用字母 G / F 示意（正是这两种谱号的名字来源）
            font = QFont("Georgia")
            font.setPixelSize(max(12, int(round(s * 3.2))))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(left, treble_y - s * 2, 20, s * 4),
                             Qt.AlignmentFlag.AlignCenter, "G")
            painter.drawText(QRectF(left, bass_y - s * 2, 20, s * 4),
                             Qt.AlignmentFlag.AlignCenter, "F")

    def _draw_glyph_centered(self, painter: QPainter, glyph: str,
                             x: float, center_y: float, font: QFont) -> None:
        """按字形的墨迹框把符号垂直居中画到 center_y。"""
        box = QFontMetricsF(font).boundingRect(glyph)
        painter.drawText(QPointF(x - box.left(),
                                 center_y - box.height() / 2.0 - box.top()),
                         glyph)

    # -- 音符 -----------------------------------------------------------
    def _draw_notes(self, painter: QPainter, left: float, right: float,
                    s: float, top: float, high: int) -> None:
        if not self._notes:
            return
        base_x = left + (right - left) * 0.42
        placed: list[tuple[float, int]] = []      # (y, 横向错位列号)

        for note in sorted(self._notes):
            velocity, sustained = self._notes[note]
            step, accidental = staff_step(note)
            lines = TREBLE_LINES if step >= MIDDLE_C_STEP else BASS_LINES
            y = self._y_of(step, s, top, high)

            # 音高相近的音头会挤在同一列，按真实排版往右错开
            offset = 0
            while any(abs(py - y) < s * 1.35 and po == offset for py, po in placed):
                offset += 1
            placed.append((y, offset))
            x = base_x + offset * s * 1.35

            color = velocity_color(velocity)
            if sustained:
                color = color.lighter(115)
            ink = QColor(color).darker(105)

            self._draw_ledger(painter, x, y, step, lines, s, top, high, ink)
            if accidental:
                self._draw_sharp(painter, x - s * 1.55, y, s, ink)
            self._draw_notehead(painter, x, y, s, color, filled=not sustained,
                                label=note_name(note))

    def _draw_ledger(self, painter: QPainter, x: float, y: float, step: int,
                     lines: tuple[int, ...], s: float, top: float, high: int,
                     color: QColor) -> None:
        low, top_line = lines[0], lines[-1]
        steps: list[int] = []
        if step < low:
            steps = list(range(low - 2, step - 1, -2))
        elif step > top_line:
            steps = list(range(top_line + 2, step + 1, 2))
        if not steps:
            return
        painter.setPen(QPen(color, 1.0))
        half = s * 1.6
        for ls in steps:
            ly = self._y_of(ls, s, top, high)
            painter.drawLine(QPointF(x - half, ly), QPointF(x + half, ly))

    def _draw_sharp(self, painter: QPainter, x: float, y: float,
                    s: float, color: QColor) -> None:
        if self._family:
            font = _fit_font(self._family, "\u266F", s * 2.5)
            painter.setFont(font)
            painter.setPen(color)
            self._draw_glyph_centered(painter, "\u266F", x, y, font)
            return
        painter.setPen(QPen(color, 1.0))
        h = s * 1.5
        painter.drawLine(QPointF(x - s * 0.25, y - h / 2), QPointF(x - s * 0.25, y + h / 2))
        painter.drawLine(QPointF(x + s * 0.25, y - h / 2), QPointF(x + s * 0.25, y + h / 2))
        painter.drawLine(QPointF(x - s * 0.55, y - h * 0.18), QPointF(x + s * 0.55, y - h * 0.30))
        painter.drawLine(QPointF(x - s * 0.55, y + h * 0.22), QPointF(x + s * 0.55, y + h * 0.10))

    def _draw_notehead(self, painter: QPainter, x: float, y: float,
                       s: float, color: QColor, filled: bool,
                       label: str = "") -> None:
        ew, eh = s * 1.24, s * 0.88
        painter.save()
        painter.translate(x, y)
        painter.rotate(-20.0)
        painter.setPen(QPen(color, max(1.2, s * 0.20)))
        painter.setBrush(color if filled else QColor("#0A0E14"))
        painter.drawEllipse(QRectF(-ew / 2, -eh / 2, ew, eh))
        painter.restore()

        # 音名直接写在音头中间：谱表窄、和弦密的时候比外挂标签更靠谱
        if not label or ew < 19:
            return
        font = QFont("Consolas")
        font.setPixelSize(max(7, int(round(eh * 0.62))))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#0A0E14") if filled else QColor(color).lighter(130))
        painter.drawText(QRectF(x - ew / 2, y - eh / 2, ew, eh),
                         Qt.AlignmentFlag.AlignCenter, label)

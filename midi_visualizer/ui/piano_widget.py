"""钢琴键盘可视化控件。

只负责「画键盘 + 显示按下的键」，不碰 MIDI 和音频；外部调用
``set_note()`` / ``clear_note()`` 来更新状态，鼠标点击则通过信号抛出，
方便单独复用或换一套输入源。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..core.notes import is_black_key, note_name, PIANO_HIGH_NOTE, PIANO_LOW_NOTE
from . import theme


def velocity_color(velocity: int) -> QColor:
    """力度 -> 颜色：轻按偏蓝青，重按偏橙红。"""
    v = max(1, min(127, velocity)) / 127.0
    hue = (205.0 - 205.0 * v) / 360.0
    return QColor.fromHsvF(hue, 0.55 + 0.38 * v, 0.72 + 0.26 * v)


class PianoKeyboard(QWidget):
    """88 键（可配置音域）键盘图。"""

    keyPressed = pyqtSignal(int, int)   # note, velocity（鼠标点击时发出）
    keyReleased = pyqtSignal(int)       # note

    def __init__(self, low: int = PIANO_LOW_NOTE, high: int = PIANO_HIGH_NOTE,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._low = low
        self._high = high
        self._notes: dict[int, tuple[int, bool]] = {}   # note -> (velocity, sustained)
        self._white_rects: dict[int, QRectF] = {}
        self._black_rects: dict[int, QRectF] = {}
        self._mouse_note: int | None = None

        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rebuild_layout()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def set_range(self, low: int, high: int) -> None:
        self._low = max(0, min(low, 126))
        self._high = max(self._low + 5, min(high, 127))
        self._rebuild_layout()
        self.update()

    def set_note(self, note: int, velocity: int, sustained: bool = False) -> None:
        """标记某个键处于按下状态。"""
        self._notes[note] = (velocity, sustained)
        self.update()

    def clear_note(self, note: int) -> None:
        if self._notes.pop(note, None) is not None:
            self.update()

    def clear_all(self) -> None:
        if self._notes:
            self._notes.clear()
            self.update()

    def set_notes(self, notes: dict[int, tuple[int, bool]]) -> None:
        """一次性刷新所有按键状态，避免逐键重绘。"""
        if notes != self._notes:
            self._notes = dict(notes)
            self.update()

    @property
    def active_notes(self) -> dict[int, tuple[int, bool]]:
        return dict(self._notes)

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------
    def _rebuild_layout(self) -> None:
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        notes = list(range(self._low, self._high + 1))
        whites = [n for n in notes if not is_black_key(n)]
        n_white = max(1, len(whites))
        ww = w / n_white

        self._white_rects = {}
        white_index: dict[int, int] = {}
        for i, n in enumerate(whites):
            white_index[n] = i
            self._white_rects[n] = QRectF(i * ww, 0.0, ww, h)

        self._black_rects = {}
        bw = ww * 0.62
        for n in notes:
            if not is_black_key(n):
                continue
            # 黑键骑在「它左边那个白键」的右边界上
            left_whites = sum(1 for m in whites if m < n)
            cx = left_whites * ww
            self._black_rects[n] = QRectF(cx - bw / 2.0, 0.0, bw, h * 0.62)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._rebuild_layout()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 背板
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.PANEL_ALT))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)

        # 白键
        for note, rect in self._white_rects.items():
            self._draw_white_key(painter, note, rect)

        # 黑键（后画，压在白键上）
        for note, rect in self._black_rects.items():
            self._draw_black_key(painter, note, rect)

        self._draw_octave_labels(painter)

    def _draw_white_key(self, painter: QPainter, note: int, rect: QRectF) -> None:
        state = self._notes.get(note)
        r = rect.adjusted(0.6, 0.0, -0.6, -0.5)
        radius = 3.0

        if state is None:
            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0.0, QColor(theme.WHITE_KEY))
            grad.setColorAt(1.0, QColor(theme.WHITE_KEY_SHADOW))
            painter.setBrush(grad)
            painter.setPen(QPen(QColor(theme.BORDER), 1.0))
        else:
            velocity, sustained = state
            color = velocity_color(velocity)
            if sustained:
                color = color.lighter(115)
            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0.0, color.lighter(112))
            grad.setColorAt(1.0, color.darker(115))
            painter.setBrush(grad)
            # 按下的键加一圈光晕
            glow = QColor(color)
            glow.setAlpha(90)
            painter.setPen(QPen(glow, 2.5))

        painter.drawRoundedRect(r, radius, radius)

        if state is not None:
            velocity, _ = state
            self._draw_velocity_bar(painter, r, velocity)
            self._draw_pressed_label(painter, r, velocity, dark_text=True)

    def _draw_black_key(self, painter: QPainter, note: int, rect: QRectF) -> None:
        state = self._notes.get(note)
        r = rect.adjusted(0.5, 0.0, -0.5, 0.0)
        radius = 2.5

        if state is None:
            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0.0, QColor("#1B222C"))
            grad.setColorAt(1.0, QColor(theme.BLACK_KEY))
            painter.setBrush(grad)
            painter.setPen(QPen(QColor(theme.BLACK_KEY_EDGE), 1.0))
        else:
            velocity, sustained = state
            color = velocity_color(velocity)
            if sustained:
                color = color.lighter(120)
            grad = QLinearGradient(r.topLeft(), r.bottomLeft())
            grad.setColorAt(0.0, color.lighter(105))
            grad.setColorAt(1.0, color.darker(125))
            painter.setBrush(grad)
            glow = QColor(color)
            glow.setAlpha(110)
            painter.setPen(QPen(glow, 2.0))

        painter.drawRoundedRect(r, radius, radius)

        if state is not None:
            velocity, _ = state
            if r.width() > 18:
                self._draw_pressed_label(painter, r, velocity, dark_text=False,
                                         y_ratio=0.86)

    def _draw_velocity_bar(self, painter: QPainter, rect: QRectF, velocity: int) -> None:
        """在按键底部画一条力度条，长度正比于力度。"""
        bar_h = 4.0
        ratio = max(0.04, min(1.0, velocity / 127.0))
        bar = QRectF(rect.left() + 2, rect.bottom() - bar_h - 2,
                     max(3.0, (rect.width() - 4) * ratio), bar_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(bar, bar_h / 2, bar_h / 2)

    def _draw_pressed_label(self, painter: QPainter, rect: QRectF,
                            velocity: int, dark_text: bool, y_ratio: float = 0.72) -> None:
        if rect.width() < 16:
            return
        font = QFont("Consolas", max(7, int(min(11, rect.width() / 4.2))))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#0D1117") if dark_text else QColor("#FFFFFF"))
        text_rect = QRectF(rect.left(), rect.top() + rect.height() * y_ratio - 9,
                           rect.width(), 16)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter, str(velocity))

    def _draw_octave_labels(self, painter: QPainter) -> None:
        font = QFont("Consolas", 8)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_MUTED))
        for note, rect in self._white_rects.items():
            if note % 12 != 0:
                continue
            label = note_name(note)
            label_rect = QRectF(rect.left(), rect.bottom() - 16, rect.width(), 14)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter, label)

    # ------------------------------------------------------------------
    # 鼠标：点键盘可以本地发声（相当于虚拟键盘）
    # ------------------------------------------------------------------
    def _hit_test(self, pos: QPointF) -> int | None:
        for note, rect in self._black_rects.items():
            if rect.contains(pos):
                return note
        for note, rect in self._white_rects.items():
            if rect.contains(pos):
                return note
        return None

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        note = self._hit_test(pos)
        if note is None:
            return
        rect = self._black_rects.get(note) or self._white_rects.get(note)
        # 越靠下弹得越重
        ratio = 0.0 if rect is None else max(0.0, min(1.0, (pos.y() - rect.top()) / rect.height()))
        velocity = int(round(45 + ratio * 82))
        self._mouse_note = note
        self.keyPressed.emit(note, max(1, min(127, velocity)))

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._mouse_note is not None:
            self.keyReleased.emit(self._mouse_note)
            self._mouse_note = None

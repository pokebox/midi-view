"""音符瀑布图：按下的音从键盘位置向上「升起」，直观看出音高走向与力度。

水平方向直接复用 :class:`PianoKeyboard` 的键位坐标，所以音符条和下面的琴键严格对齐；
竖直方向表示时间，越靠下越新。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from . import theme
from .piano_widget import PianoKeyboard, velocity_color


@dataclass
class _TrailItem:
    note: int
    velocity: int
    start: float
    end: float | None = None      # None = 还按着
    color: QColor | None = None


class NoteTrail(QWidget):
    def __init__(self, keyboard: PianoKeyboard, window_seconds: float = 4.5,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._keyboard = keyboard
        self._window = max(1.0, window_seconds)
        self._items: list[_TrailItem] = []
        self._max_items = 500

        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(33)          # 约 30fps，够顺滑也不烧 CPU
        self._timer.timeout.connect(self._advance)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def note_on(self, note: int, velocity: int) -> None:
        now = time.perf_counter()
        self._items.append(_TrailItem(note, velocity, now, None,
                                      velocity_color(velocity)))
        if len(self._items) > self._max_items:
            del self._items[: len(self._items) - self._max_items]
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def note_off(self, note: int) -> None:
        now = time.perf_counter()
        for item in reversed(self._items):
            if item.note == note and item.end is None:
                item.end = now
                break
        self.update()

    def clear(self) -> None:
        self._items.clear()
        self.update()

    # ------------------------------------------------------------------
    # 动画
    # ------------------------------------------------------------------
    def _px_per_second(self) -> float:
        return max(1.0, self.height()) / self._window

    def _advance(self) -> None:
        now = time.perf_counter()
        pps = self._px_per_second()
        alive = [it for it in self._items if (now - it.start) * pps < self.height() + 40]
        self._items = alive
        if not self._items:
            self._timer.stop()
        self.update()

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

        self._draw_grid(painter, h)

        now = time.perf_counter()
        pps = self._px_per_second()
        for item in self._items:
            span = self._keyboard.key_span(item.note)
            if span is None:
                continue
            x, key_w, is_black = span
            # 时间轴：越新的越靠下。start 决定上边，end（没松键就是"此刻"）决定下边
            y_top = h - (now - item.start) * pps
            end = item.end if item.end is not None else now
            y_bottom = h - (now - end) * pps
            if y_top > h:          # 还没出现（不该发生，防御一下）
                continue
            if y_top < -2:         # 已经滚出画面
                continue
            height = max(3.0, y_bottom - y_top)

            color = QColor(item.color) if item.color else velocity_color(item.velocity)
            alpha = 90 + int(140 * min(1.0, item.velocity / 127.0))
            color.setAlpha(alpha if item.end is None else max(50, alpha - 45))
            inset = 0.6 if is_black else 0.8
            rect = QRectF(x + inset, y_top, max(2.0, key_w - inset * 2), height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 2.0, 2.0)

        # 底部「此刻」基准线
        painter.setPen(QPen(QColor(theme.BORDER), 1.0))
        painter.drawLine(0, int(h) - 1, int(w), int(h) - 1)

    def _draw_grid(self, painter: QPainter, height: float) -> None:
        """按 C 键位置画一层很淡的竖线，方便对齐音区。"""
        pen = QPen(QColor(255, 255, 255, 10), 1.0)
        painter.setPen(pen)
        for note in range(0, 128):
            if note % 12 != 0:
                continue
            span = self._keyboard.key_span(note)
            if span is None:
                continue
            painter.drawLine(int(span[0]), 0, int(span[0]), int(height))

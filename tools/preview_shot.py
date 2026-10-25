"""生成界面预览图（不需要真的接键盘/声卡）。

    .venv/Scripts/python.exe tools/preview_shot.py

脚本会按时间顺序「重放」一段演奏，让音符瀑布有层次感，然后把窗口截成 preview.png。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# 默认用真实平台渲染（字体正常）；无显示环境下可设 MIDI_PREVIEW_OFFSCREEN=1
if os.environ.get("MIDI_PREVIEW_OFFSCREEN"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from midi_visualizer.core.midi_input import parse_message  # noqa: E402
from midi_visualizer.ui.main_window import MainWindow  # noqa: E402

# (距离上一条的秒数, 原始字节)
SCRIPT: list[tuple[float, bytes]] = [
    (0.00, bytes([0x90, 48, 0x28])),    # C3  vel 40
    (0.12, bytes([0x90, 55, 0x52])),    # G3  vel 82
    (0.12, bytes([0x90, 60, 0x64])),    # C4  vel 100
    (0.12, bytes([0x90, 64, 0x6F])),    # E4  vel 111
    (0.12, bytes([0x90, 67, 0x7F])),    # G4  vel 127
    (0.14, bytes([0x90, 72, 0x5A])),    # C5  vel 90
    (0.30, bytes([0xB0, 0x40, 0x7F])),  # 踩延音踏板
    (0.20, bytes([0xB0, 0x01, 0x2A])),  # 调制轮 42
    (0.15, bytes([0xE0, 0x00, 0x50])),  # 弯音 +2048
    (0.60, bytes([0x80, 48, 0x40])),    # 松 C3
    (0.25, bytes([0x80, 55, 0x40])),    # 松 G3
    (0.55, bytes([0x90, 76, 0x33])),    # E5  vel 51
    (0.30, bytes([0xB0, 0x07, 0x64])),  # CC7 音量
    (0.35, bytes([0x90, 79, 0x45])),    # G5  vel 69
    (0.28, bytes([0xC0, 0x00])),        # 音色切换
    (0.30, bytes([0x80, 60, 0x00])),    # 松 C4
    (0.26, bytes([0x90, 88, 0x5E])),    # E6  vel 94（高音区，验证瀑布不被裁掉）
    (0.18, bytes([0x90, 96, 0x74])),    # C7  vel 116
    (0.22, bytes([0x90, 91, 0x46])),    # G6  vel 70
]


def main() -> int:
    app = QApplication(sys.argv[:1])
    window = MainWindow(enable_audio=False)
    window.resize(1440, 780)
    window.show()
    app.processEvents()

    for delay, raw in SCRIPT:
        if delay:
            time.sleep(delay)
            app.processEvents()
        ev = parse_message(raw)
        window._handle_event(ev)
        window.log_view.appendPlainText(window._format_line(ev))
        window._refresh_ui()

    time.sleep(0.15)
    app.processEvents()
    window._refresh_ui()
    app.processEvents()

    kbd = window.keyboard
    widths = [r.width() for r in kbd._white_rects.values()]
    if widths:
        print(f"键盘区域 {kbd.width()}x{kbd.height()}  白键 {len(widths)} 个，"
              f"键宽 {min(widths):.1f}~{max(widths):.1f}px")

    out = ROOT / "preview.png"
    pixmap = window.grab()
    pixmap.save(str(out))
    print(f"saved {out} ({pixmap.width()}x{pixmap.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

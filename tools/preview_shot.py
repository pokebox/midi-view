"""生成界面预览图（离屏渲染，不需要真的接键盘/声卡）。

    .venv/Scripts/python.exe tools/preview_shot.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from midi_visualizer.core.midi_input import parse_message  # noqa: E402
from midi_visualizer.ui.main_window import MainWindow  # noqa: E402

# 模拟一段演奏：C 大三和弦 + 力度差异 + 延音踏板 + 弯音
SCRIPT: list[bytes] = [
    bytes([0x90, 48, 0x28]),   # C3 vel 40
    bytes([0x90, 55, 0x52]),   # G3 vel 82
    bytes([0x90, 60, 0x64]),   # C4 vel 100
    bytes([0x90, 64, 0x6F]),   # E4 vel 111
    bytes([0x90, 67, 0x7F]),   # G4 vel 127
    bytes([0x90, 72, 0x5A]),   # C5 vel 90
    bytes([0xB0, 64, 0x7F]),   # 踩延音
    bytes([0xB0, 01, 0x2A]),   # 调制轮 42
    bytes([0xE0, 0x00, 0x50]), # 弯音 +2048
    bytes([0x80, 48, 0x40]),
    bytes([0x80, 55, 0x40]),
    bytes([0x90, 76, 0x33]),   # E5 vel 51
    bytes([0xB0, 07, 0x64]),   # CC7 音量
    bytes([0x90, 79, 0x45]),   # G5
    bytes([0xC0, 0x00]),       # 音色切换
    bytes([0x80, 60, 0x00]),
]


def main() -> int:
    app = QApplication(sys.argv[:1])
    window = MainWindow(enable_audio=False)
    window.resize(1240, 700)

    for raw in SCRIPT:
        ev = parse_message(raw)
        window._handle_event(ev)
        window.log_view.appendPlainText(window._format_line(ev))

    window._refresh_ui()
    window.show()
    app.processEvents()

    out = ROOT / "preview.png"
    pixmap = window.grab()
    pixmap.save(str(out))
    print(f"saved {out} ({pixmap.width()}x{pixmap.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

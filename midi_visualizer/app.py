"""程序入口：图形界面 + 命令行参数。"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="midi-visualizer",
        description="MIDI 键盘可视化：显示原始 MIDI 数据、按键位置与力度，并播放声音。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port", "-p", help="MIDI 输入端口名或索引（默认第一个）")
    parser.add_argument("--list-ports", action="store_true", help="列出所有 MIDI 输入端口后退出")
    parser.add_argument("--cli", action="store_true", help="不开界面，在终端打印 MIDI 消息")
    parser.add_argument("--notes-only", action="store_true", help="配合 --cli：只显示音符事件")
    parser.add_argument("--no-audio", action="store_true", help="不初始化音频（只看数据）")
    parser.add_argument("--soundfont", help="SoundFont 音源文件路径（.sf2）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_ports:
        from .core.midi_input import list_input_ports

        ports = list_input_ports()
        if not ports:
            print("未检测到 MIDI 输入端口。")
            return 1
        for i, name in enumerate(ports):
            print(f"[{i}] {name}")
        return 0

    port: str | int | None = args.port
    if isinstance(port, str) and port.isdigit():
        port = int(port)

    if args.cli:
        from .cli import monitor

        return monitor(port, args.notes_only)

    from PyQt6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MIDI Visualizer")
    app.setStyle("Fusion")

    window = MainWindow(
        port=port,
        soundfont=args.soundfont,
        enable_audio=not args.no_audio,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

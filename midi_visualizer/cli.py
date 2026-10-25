"""命令行监听模式：不开界面，只把 MIDI 消息打到终端。

既能当调试工具，也是「MIDI 输入模块可独立复用」的示范。
"""

from __future__ import annotations

import argparse
import sys
import time

from .core.midi_input import MidiInput, MidiPortError, list_input_ports


def monitor(port: str | int | None = None, only_notes: bool = False) -> int:
    ports = list_input_ports()
    if not ports:
        print("没有检测到 MIDI 输入端口。请检查键盘连接，或安装 python-rtmidi。")
        return 1

    if port is None:
        print("可用端口：")
        for i, name in enumerate(ports):
            print(f"  [{i}] {name}")
        port = 0

    try:
        midi = MidiInput()
        name = midi.open(port)
    except MidiPortError as exc:
        print(f"打开失败：{exc}")
        return 1

    print(f"正在监听：{name}（Ctrl+C 退出）\n")
    print(f"{'时间':<13s} {'原始数据':<12s} {'间隔':>9s}  解析")
    print("-" * 78)
    last = 0.0
    try:
        for ev in midi:
            if only_notes and not ev.is_note:
                continue
            gap = f"{(ev.timestamp - last) * 1000:8.1f}ms" if last else " " * 10
            last = ev.timestamp
            stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
            print(f"{stamp:<13s} {ev.hex:<12s} {gap:>9s}  {ev.describe()}")
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        midi.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="midi-monitor", description="MIDI 消息终端监视")
    parser.add_argument("port", nargs="?", help="端口名或索引，省略则列出并选第一个")
    parser.add_argument("--notes", action="store_true", help="只显示音符事件")
    args = parser.parse_args(argv)
    return monitor(args.port, args.notes)


if __name__ == "__main__":
    sys.exit(main())

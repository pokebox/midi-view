"""MIDI 可视化 —— 读本机 MIDI 键盘、显示原始数据、键盘图与声音。

包结构：

* :mod:`midi_visualizer.core.midi_input` —— **可复用的 MIDI 输入模块**（无界面依赖）
* :mod:`midi_visualizer.audio`            —— 音频后端（内置合成器 / SoundFont）
* :mod:`midi_visualizer.ui`               —— PyQt6 界面
"""

from __future__ import annotations

from .core.midi_input import (
    MidiEvent,
    MidiInput,
    MidiPortError,
    list_input_ports,
    list_output_ports,
    parse_message,
)

__version__ = "0.1.0"

__all__ = [
    "MidiEvent",
    "MidiInput",
    "MidiPortError",
    "list_input_ports",
    "list_output_ports",
    "parse_message",
    "__version__",
]

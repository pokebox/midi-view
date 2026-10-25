"""MIDI 音符与频率相关的小工具（无第三方依赖）。"""

from __future__ import annotations

NOTE_NAMES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)

# 十二平均律中属于黑键的音级（C=0 起）
BLACK_KEY_PITCH_CLASSES: frozenset[int] = frozenset({1, 3, 6, 8, 10})

# 标准 88 键钢琴的 MIDI 音域：A0(21) ~ C8(108)
PIANO_LOW_NOTE = 21
PIANO_HIGH_NOTE = 108


def is_black_key(note: int) -> bool:
    """该 MIDI 音符在钢琴上是否是黑键。"""
    return (note % 12) in BLACK_KEY_PITCH_CLASSES


def note_name(note: int) -> str:
    """MIDI 音符号 -> 音名，例如 60 -> 'C4'（以 C4=60 的常用约定）。"""
    octave = note // 12 - 1
    return f"{NOTE_NAMES[note % 12]}{octave}"


def note_to_freq(note: int, a4: float = 440.0) -> float:
    """MIDI 音符号 -> 频率（Hz），A4=69。"""
    return a4 * 2.0 ** ((note - 69) / 12.0)


def clamp_note(note: int, low: int = 0, high: int = 127) -> int:
    return max(low, min(high, note))

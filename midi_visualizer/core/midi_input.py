"""可复用的 MIDI 输入模块。

设计目标：
  * **不依赖任何界面库**，只依赖 ``mido`` + ``python-rtmidi``，可以单独拿到别的项目里用；
  * 把原始字节（wire bytes）完整保留下来，方便做「原始数据」展示与协议调试；
  * 线程安全：MIDI 回调跑在 rtmidi 自己的线程里，本模块统一转成 ``MidiEvent``
    塞进队列，界面层用定时器 ``drain()`` 取，避免跨线程碰 UI；
  * 同时提供回调风格（适合脚本）与迭代/队列风格（适合 GUI 或后台线程）。

典型用法 1（脚本轮询）::

    from midi_visualizer.core.midi_input import MidiInput, list_input_ports

    print(list_input_ports())
    with MidiInput() as midi:            # 不传端口名 = 自动打开第一个输入端口
        midi.open("Arturia KeyStep")
        for event in midi:               # 阻塞迭代，close() 时正常退出
            print(event.timestamp, event.hex, event.describe())

典型用法 2（回调）::

    def on_note_on(ev):
        print("按下", ev.note_name, ev.velocity)

    midi = MidiInput(port="Arturia KeyStep", callbacks={"note_on": on_note_on})
    midi.open()
    ...
    midi.close()

典型用法 3（GUI，非阻塞）::

    midi = MidiInput(port="Arturia KeyStep")
    midi.open()
    # 界面定时器里：
    for ev in midi.drain():
        ...
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterator

import mido

from .notes import note_name

__all__ = [
    "MidiEvent",
    "MidiInput",
    "MidiPortError",
    "parse_message",
    "list_input_ports",
    "list_output_ports",
]

# ---------------------------------------------------------------------------
# 常量表
# ---------------------------------------------------------------------------

# 通道消息状态字节高 4 位 -> 消息类型
_CHANNEL_TYPES: dict[int, str] = {
    0x80: "note_off",
    0x90: "note_on",
    0xA0: "poly_aftertouch",
    0xB0: "control_change",
    0xC0: "program_change",
    0xD0: "aftertouch",
    0xE0: "pitch_bend",
}

# 实时/系统消息
_SYSTEM_TYPES: dict[int, str] = {
    0xF0: "sysex",
    0xF1: "mtc_quarter_frame",
    0xF2: "song_position",
    0xF3: "song_select",
    0xF6: "tune_request",
    0xF8: "clock",
    0xFA: "start",
    0xFB: "continue",
    0xFC: "stop",
    0xFE: "active_sensing",
    0xFF: "reset",
}

# 常见 CC 编号 -> 名称，仅用于展示
CC_NAMES: dict[int, str] = {
    0: "Bank Select MSB",
    1: "Mod Wheel",
    2: "Breath",
    7: "Volume",
    10: "Pan",
    11: "Expression",
    64: "Sustain Pedal",
    65: "Portamento",
    66: "Sostenuto",
    67: "Soft Pedal",
    91: "Reverb",
    93: "Chorus",
    120: "All Sound Off",
    121: "Reset All Controllers",
    123: "All Notes Off",
    124: "Omni Off",
    125: "Omni On",
    126: "Mono Mode",
    127: "Poly Mode",
}

# 消息类型 -> 是否有第二个数据字节
_TWO_DATA_TYPES = {
    "note_off", "note_on", "poly_aftertouch",
    "control_change", "pitch_bend",
}


class MidiPortError(RuntimeError):
    """端口打不开 / MIDI 后端不可用。"""


# ---------------------------------------------------------------------------
# 事件对象
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MidiEvent:
    """一条已经解析好的 MIDI 消息（原始字节完整保留）。"""

    timestamp: float      # time.perf_counter() 时间戳，用于计算间隔/延迟
    raw: bytes            # 线上原始字节，例如 b"\x90\x3c\x60"
    status: int           # 状态字节，例如 0x90
    type: str             # note_on / note_off / control_change / ...
    channel: int          # 1~16；系统消息为 0
    data1: int            # 第一个数据字节（音符 / CC 号 / LSB）
    data2: int            # 第二个数据字节（力度 / CC 值 / MSB）

    # -- 语义判定 ---------------------------------------------------------
    @property
    def is_note_on(self) -> bool:
        """真·按下：note_on 且力度 > 0。"""
        return self.type == "note_on" and self.data2 > 0

    @property
    def is_note_off(self) -> bool:
        """松开：note_off，或者 note_on + 力度 0（很多键盘这样发）。"""
        return self.type == "note_off" or (self.type == "note_on" and self.data2 == 0)

    @property
    def is_note(self) -> bool:
        return self.type in ("note_on", "note_off")

    @property
    def is_sustain(self) -> bool:
        """延音踏板（CC64）。"""
        return self.type == "control_change" and self.data1 == 64

    # -- 便捷字段 ---------------------------------------------------------
    @property
    def note(self) -> int:
        return self.data1

    @property
    def velocity(self) -> int:
        """力度；note_off 时为 0。"""
        if self.type == "note_off":
            return 0
        return self.data2 if self.type in ("note_on", "poly_aftertouch") else 0

    @property
    def note_name(self) -> str:
        return note_name(self.data1)

    @property
    def control(self) -> int:
        return self.data1

    @property
    def value(self) -> int:
        return self.data2

    @property
    def bend(self) -> int:
        """弯音值，-8192 ~ +8191（14bit 有符号，中心 0）。"""
        if self.type != "pitch_bend":
            return 0
        return (self.data2 << 7 | self.data1) - 8192

    @property
    def hex(self) -> str:
        """原始字节的大写十六进制，例如 ``90 3C 60``。"""
        return self.raw.hex(" ").upper()

    def describe(self) -> str:
        """人类可读的一行描述，字段宽度固定以便对齐。"""
        t = self.type
        ch = f"ch{self.channel:<2d}"
        if t == "note_on":
            if self.data2 == 0:
                return f"Note Off  {ch} {self.note_name:<4s} ({self.data1:3d})  vel 0"
            return f"Note On   {ch} {self.note_name:<4s} ({self.data1:3d})  vel {self.data2}"
        if t == "note_off":
            return f"Note Off  {ch} {self.note_name:<4s} ({self.data1:3d})  vel {self.data2}"
        if t == "control_change":
            name = CC_NAMES.get(self.data1, "")
            return f"CC        {ch} #{self.data1:<3d} {name:<18s} {self.data2}"
        if t == "pitch_bend":
            pct = self.bend / 8192.0 * 100.0
            return f"PitchBend {ch} {self.bend:+6d}  ({pct:+.1f}%)"
        if t == "program_change":
            return f"Program   {ch} {self.data1}"
        if t == "poly_aftertouch":
            return f"PolyAT    {ch} {self.note_name:<4s} ({self.data1:3d})  {self.data2}"
        if t == "aftertouch":
            return f"ChanAT    {ch} {self.data1}"
        if t == "sysex":
            return f"SysEx     {len(self.raw)} bytes"
        return f"{t:<9s} {ch} {self.data1} {self.data2}"

    def __str__(self) -> str:  # pragma: no cover - 打印用
        return f"{self.hex:<20s} {self.describe()}"


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def parse_message(raw: bytes, timestamp: float | None = None) -> MidiEvent:
    """把线上原始字节解析成 :class:`MidiEvent`。

    自己解析而不是依赖 ``mido.Message``，好处是拿到的一定是「收到的字节」，
    不会被库做任何规范化（比如 note_on/vel=0 的转换）。
    """
    if not raw:
        raise ValueError("空消息")
    raw = bytes(raw)
    status = raw[0]
    ts = time.perf_counter() if timestamp is None else timestamp

    if status >= 0xF0:
        mtype = _SYSTEM_TYPES.get(status, "sysex" if status == 0xF0 else "system")
        return MidiEvent(ts, raw, status, mtype, 0, raw[1] if len(raw) > 1 else 0, 0)

    mtype = _CHANNEL_TYPES.get(status & 0xF0, "unknown")
    channel = (status & 0x0F) + 1
    d1 = raw[1] if len(raw) > 1 else 0
    d2 = raw[2] if len(raw) > 2 and mtype in _TWO_DATA_TYPES else 0
    return MidiEvent(ts, raw, status, mtype, channel, d1, d2)


# ---------------------------------------------------------------------------
# 端口枚举
# ---------------------------------------------------------------------------

def list_input_ports() -> list[str]:
    """当前系统上可用的 MIDI 输入端口名列表（通常是键盘/控制器）。"""
    try:
        return list(mido.get_input_names())
    except Exception:  # 后端缺失或驱动异常，视为没有端口
        return []


def list_output_ports() -> list[str]:
    """当前系统上可用的 MIDI 输出端口名列表。"""
    try:
        return list(mido.get_output_names())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 输入端口封装
# ---------------------------------------------------------------------------

_Callback = Callable[[MidiEvent], None]


class MidiInput:
    """一个 MIDI 输入端口。

    :param port: 端口名（str）、索引（int）或 None（打开第一个可用端口）
    :param callbacks: 回调字典，键可以是 ``"message"``（所有消息）、
        ``"note_on"``、``"note_off"``、``"control_change"``、``"pitch_bend"``、
        ``"program_change"``、``"aftertouch"``、``"poly_aftertouch"``、``"sysex"``。
        回调运行在 MIDI 后台线程里，**不要直接操作界面**。
    :param queue_maxsize: 内部事件队列上限，满了丢最旧的（防止界面卡住时内存暴涨）
    """

    def __init__(
        self,
        port: str | int | None = None,
        *,
        callbacks: dict[str, _Callback] | None = None,
        queue_maxsize: int = 4096,
    ) -> None:
        self._callbacks: dict[str, list[_Callback]] = {}
        for key, fn in (callbacks or {}).items():
            self.add_callback(key, fn)

        self._queue: queue.Queue[MidiEvent | None] = queue.Queue(maxsize=queue_maxsize)
        self._port: mido.ports.BaseInput | None = None
        self._port_name: str = ""
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._closed.set()
        self._dropped = 0
        self.last_error: str | None = None

    # -- 端口状态 ---------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._port is not None

    @property
    def port_name(self) -> str:
        return self._port_name

    @property
    def dropped_count(self) -> int:
        """因队列满被丢弃的事件数（正常应该一直是 0）。"""
        return self._dropped

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    # -- 打开 / 关闭 ------------------------------------------------------
    def open(self, port: str | int | None = None) -> str:
        """打开端口并返回实际打开的端口名。重复调用会先关闭旧的。"""
        self.close()
        target = port if port is not None else self._port
        available = list_input_ports()

        if not available:
            raise MidiPortError(
                "没有可用的 MIDI 输入端口。请确认键盘已连接，并已安装 python-rtmidi。"
            )

        if target is None:
            resolved = available[0]
        elif isinstance(target, int):
            if not 0 <= target < len(available):
                raise MidiPortError(f"端口索引 {target} 超出范围（共 {len(available)} 个）")
            resolved = available[target]
        else:
            if target not in available:
                raise MidiPortError(
                    f"找不到端口 {target!r}。可用端口：{', '.join(available)}"
                )
            resolved = target

        try:
            self._port = mido.open_input(resolved, callback=self._on_message)
        except Exception as exc:  # 端口被别的程序独占等
            self._port = None
            raise MidiPortError(f"打开端口 {resolved!r} 失败：{exc}") from exc

        self._port_name = resolved
        self._closed.clear()
        self._dropped = 0
        self.last_error = None
        return resolved

    def close(self) -> None:
        """关闭端口并唤醒所有迭代者。"""
        with self._lock:
            port, self._port = self._port, None
            was_open = port is not None
            self._closed.set()
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
        if was_open:
            self._push(None)  # 唤醒阻塞中的 __iter__

    def __enter__(self) -> "MidiInput":
        if not self.is_open:
            self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- 回调注册 ---------------------------------------------------------
    def add_callback(self, key: str, fn: _Callback) -> None:
        self._callbacks.setdefault(key, []).append(fn)

    def remove_callback(self, key: str, fn: _Callback) -> None:
        try:
            self._callbacks.get(key, []).remove(fn)
        except ValueError:
            pass

    # -- 事件读取 ---------------------------------------------------------
    def drain(self) -> list[MidiEvent]:
        """非阻塞取出当前所有待处理事件（GUI 定时器里用）。"""
        items: list[MidiEvent] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            items.append(item)
        return items

    def get(self, timeout: float | None = None) -> MidiEvent | None:
        """取一条事件；``timeout`` 秒内没有就返回 None。"""
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return item

    def __iter__(self) -> Iterator[MidiEvent]:
        """阻塞迭代，直到 :meth:`close` 被调用。"""
        while True:
            try:
                item = self._queue.get()
            except Exception:  # pragma: no cover
                return
            if item is None:
                return
            yield item

    # -- 内部：rtmidi 线程回调 -------------------------------------------
    def _on_message(self, msg: mido.Message) -> None:
        try:
            event = parse_message(bytes(msg.bytes()))
        except Exception as exc:  # 解析失败不影响后续消息
            self.last_error = f"解析失败：{exc}"
            return

        self._dispatch(event)
        self._push(event)

    def _dispatch(self, event: MidiEvent) -> None:
        key = event.type
        # note_on + vel 0 在语义上是松开，回调也按松开派发
        if event.type == "note_on" and event.data2 == 0:
            key = "note_off"
        for fn in self._callbacks.get(key, ()):  # 类型回调
            self._safe_call(fn, event)
        for fn in self._callbacks.get("message", ()):  # 全量回调
            self._safe_call(fn, event)

    @staticmethod
    def _safe_call(fn: _Callback, event: MidiEvent) -> None:
        try:
            fn(event)
        except Exception:  # 单个回调出错不拖垮 MIDI 线程
            import traceback

            traceback.print_exc()

    def _push(self, item: MidiEvent | None) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # 丢最旧的一条，保证界面延迟不会越积越大
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._dropped += 1
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass

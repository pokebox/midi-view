"""音频输出后端。

两个可选后端：

* :class:`SynthBackend`  —— 内置软音源（numpy 合成），装完 numpy + sounddevice 就有声；
* :class:`SoundFontBackend` —— 通过 pyfluidsynth 加载 .sf2 音源文件，
  音色真实得多，但需要 ``fluidsynth`` 动态库（Windows 上要单独放 DLL）。

用 :func:`create_backend` 自动挑选：能加载 SoundFont 就用 SoundFont，
否则退回内置合成器，实在没声卡就返回一个静默后端（界面照常能显示数据）。

所有后端方法都允许从任意线程调用。
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .synth import PolySynth

SAMPLE_RATE = 44100
BLOCK_SIZE = 512


class AudioError(RuntimeError):
    """音频设备/音源不可用。"""


class NullBackend:
    """静默后端：没有可用声卡时的兜底，界面不会因此崩掉。"""

    name = "无音频"
    detail = ""

    def __init__(self, reason: str = "") -> None:
        self.detail = reason

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def note_on(self, note: int, velocity: int) -> None: ...
    def note_off(self, note: int) -> None: ...
    def control_change(self, control: int, value: int) -> None: ...
    def pitch_bend(self, value: int) -> None: ...
    def program_change(self, program: int) -> None: ...
    def all_notes_off(self) -> None: ...
    def set_volume(self, volume: float) -> None: ...
    def set_muted(self, muted: bool) -> None: ...

    @property
    def running(self) -> bool:
        return False


class SynthBackend:
    """内置合成器 + sounddevice 输出。"""

    name = "内置合成器"

    def __init__(self, sample_rate: int = SAMPLE_RATE, volume: float = 0.75) -> None:
        self.sample_rate = sample_rate
        self._synth = PolySynth(sample_rate=sample_rate)
        self._volume = volume
        self._muted = False
        self._stream = None
        self._lock = threading.RLock()
        self.detail = f"{sample_rate} Hz / 软件合成"

    # -- 生命周期 ---------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            try:
                import sounddevice as sd
            except Exception as exc:  # pragma: no cover
                raise AudioError(f"sounddevice 不可用：{exc}") from exc
            try:
                self._stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    blocksize=BLOCK_SIZE,
                    channels=2,
                    dtype="float32",
                    latency="low",
                    callback=self._callback,
                )
                self._stream.start()
            except Exception as exc:
                self._stream = None
                raise AudioError(f"打开音频输出失败：{exc}") from exc

    def stop(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._stream is not None

    # -- 音频回调（sounddevice 线程） ------------------------------------
    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        mono = self._synth.render(frames)
        gain = 0.0 if self._muted else self._volume
        if gain != 1.0:
            mono = mono * gain
        outdata[:] = mono.reshape(-1, 1)

    # -- 演奏接口 ---------------------------------------------------------
    def note_on(self, note: int, velocity: int) -> None:
        self._synth.note_on(note, velocity)

    def note_off(self, note: int) -> None:
        self._synth.note_off(note)

    def control_change(self, control: int, value: int) -> None:
        if control == 64:
            self._synth.set_sustain(value >= 64)
        elif control in (120, 123):
            self._synth.all_notes_off(immediate=(control == 120))

    def pitch_bend(self, value: int) -> None:
        self._synth.set_pitch_bend(value)

    def program_change(self, program: int) -> None:
        pass  # 内置合成器音色固定

    def all_notes_off(self) -> None:
        self._synth.all_notes_off()

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)

    @property
    def active_voices(self) -> int:
        return self._synth.active_voices


class SoundFontBackend:
    """用 pyfluidsynth 加载 .sf2 音源文件。"""

    name = "SoundFont"

    def __init__(self, sf2_path: str | Path, sample_rate: int = SAMPLE_RATE,
                 volume: float = 0.75, program: int = 0) -> None:
        self.sf2_path = Path(sf2_path)
        self.sample_rate = sample_rate
        self._volume = volume
        self._muted = False
        self._program = program
        self._fs = None
        self._synth = None
        self._sfid = 0
        self.detail = self.sf2_path.name

    def start(self) -> None:
        if self._synth is not None:
            return
        try:
            import fluidsynth  # type: ignore
        except Exception as exc:
            raise AudioError(
                "未安装 pyfluidsynth（或缺少 fluidsynth 动态库），无法加载 SoundFont。"
            ) from exc
        if not self.sf2_path.exists():
            raise AudioError(f"音源文件不存在：{self.sf2_path}")

        self._fs = fluidsynth
        synth = fluidsynth.Synth(samplerate=float(self.sample_rate))
        try:
            synth.start()  # 让 fluidsynth 自己挑默认音频驱动
        except Exception as exc:
            raise AudioError(f"fluidsynth 启动失败：{exc}") from exc

        sfid = synth.sfload(str(self.sf2_path))
        if sfid == -1:
            synth.delete()
            raise AudioError(f"加载音源失败：{self.sf2_path}")
        synth.program_select(0, sfid, 0, self._program)
        self._sfid = sfid
        self._synth = synth
        self._apply_gain()

    def stop(self) -> None:
        synth, self._synth = self._synth, None
        if synth is not None:
            try:
                synth.delete()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return self._synth is not None

    def _apply_gain(self) -> None:
        if self._synth is None:
            return
        gain = 0.0 if self._muted else self._volume * 1.2
        try:
            self._synth.setting("synth.gain", gain)
        except Exception:
            pass

    def note_on(self, note: int, velocity: int) -> None:
        if self._synth is not None:
            self._synth.noteon(0, int(note), int(velocity))

    def note_off(self, note: int) -> None:
        if self._synth is not None:
            self._synth.noteoff(0, int(note))

    def control_change(self, control: int, value: int) -> None:
        if self._synth is None:
            return
        try:
            if control in (120, 123):
                self._synth.system_reset() if control == 123 else self._synth.cc(0, control, value)
            else:
                self._synth.cc(0, int(control), int(value))
        except Exception:
            pass

    def pitch_bend(self, value: int) -> None:
        if self._synth is not None:
            try:
                self._synth.pitch_bend(0, int(value))
            except Exception:
                pass

    def program_change(self, program: int) -> None:
        self._program = int(program)
        if self._synth is not None:
            try:
                self._synth.program_change(0, self._program)
            except Exception:
                pass

    def set_channel_program(self, bank: int, program: int) -> None:
        """切换音色（bank/program 均为 0 起的序号）。"""
        if self._synth is not None:
            try:
                self._synth.program_select(0, self._sfid, int(bank), int(program))
            except Exception:
                pass

    def all_notes_off(self) -> None:
        if self._synth is not None:
            try:
                self._synth.system_reset()
            except Exception:
                pass

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        self._apply_gain()

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._apply_gain()


def create_backend(soundfont: str | Path | None = None,
                   sample_rate: int = SAMPLE_RATE,
                   volume: float = 0.75):
    """按优先级创建后端，返回 ``(backend, 说明文字)``。

    会尝试启动，失败则降级；不会抛异常。
    """
    if soundfont:
        try:
            backend = SoundFontBackend(soundfont, sample_rate=sample_rate, volume=volume)
            backend.start()
            return backend, f"已加载音源：{Path(soundfont).name}"
        except AudioError as exc:
            fallback_msg = f"SoundFont 加载失败（{exc}），改用内置合成器"

    try:
        backend = SynthBackend(sample_rate=sample_rate, volume=volume)
        backend.start()
        return backend, (fallback_msg if soundfont else "内置软音源已就绪")
    except AudioError as exc:
        silent = NullBackend(str(exc))
        return silent, f"音频不可用：{exc}"

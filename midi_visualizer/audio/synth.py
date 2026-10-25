"""内置软音源（纯 numpy 加法合成）。

不依赖任何采样库：每个音符用若干谐波叠加 + 包络模拟「电钢琴」音色。
好处是装完 numpy 就能出声，不需要下载 SoundFont；
如果需要更真实的乐器音色，可以用 engine 里的 SoundFont 后端。

所有公开方法都是线程安全的（音频回调线程与界面线程会同时访问）。
"""

from __future__ import annotations

import threading

import numpy as np

from ..core.notes import note_to_freq

# --- 包络参数（秒） -------------------------------------------------------
ATTACK = 0.005           # 起音
DECAY_TAU = 0.60         # 衰减时间常数
SUSTAIN_LEVEL = 0.45     # 衰减后的保持电平
RELEASE_TAU = 0.085      # 松键后的余音
VOICE_END_LEVEL = 8e-4   # 低于这个电平就回收该发声单元
MAX_VOICE_LIFE = 45.0    # 兜底：单个音符最长存活时间


class SynthVoice:
    """单个发声单元（一个按下的音符）。"""

    __slots__ = (
        "note", "velocity", "sample_rate", "freq", "peak",
        "harmonics", "t", "release_time", "start_time",
    )

    def __init__(self, note: int, velocity: int, sample_rate: int) -> None:
        self.note = int(note)
        self.velocity = int(max(1, min(127, velocity)))
        self.sample_rate = sample_rate
        self.freq = note_to_freq(self.note)
        self.t = 0.0
        self.release_time: float | None = None
        self.start_time = 0.0

        vel = self.velocity / 127.0
        # 力度越大 -> 泛音越多（更亮）、音量越大
        bright = 0.30 + 0.70 * vel
        weights = np.array([1.0, 0.62 * bright, 0.34 * bright, 0.18 * bright, 0.10 * bright])
        nyquist = sample_rate * 0.45
        pairs = [(k + 1, float(w)) for k, w in enumerate(weights)
                 if (k + 1) * self.freq < nyquist and w > 1e-3]
        total = sum(w for _, w in pairs) or 1.0
        self.harmonics = [(k, w / total) for k, w in pairs]

        # 单音峰值：控制多音同时按下时不至于爆音
        self.peak = 0.26 * vel ** 1.35

    # -- 状态 -------------------------------------------------------------
    def release(self, at_time: float | None = None) -> None:
        if self.release_time is None:
            self.release_time = self.t if at_time is None else at_time

    @property
    def released(self) -> bool:
        return self.release_time is not None

    def is_finished(self) -> bool:
        if self.t > MAX_VOICE_LIFE:
            return True
        if self.release_time is None:
            return False
        return (self.t - self.release_time) > RELEASE_TAU * 8.0

    # -- 渲染 -------------------------------------------------------------
    def render(self, frames: int, bend_ratio: float = 1.0) -> np.ndarray:
        """生成 ``frames`` 个采样点（float32，单声道）。"""
        sr = self.sample_rate
        t = self.t + np.arange(frames, dtype=np.float64) / sr
        self.t += frames / sr

        freq = self.freq * bend_ratio
        sig = np.zeros(frames, dtype=np.float64)
        for k, w in self.harmonics:
            sig += w * np.sin(2.0 * np.pi * freq * k * t)

        return (sig * self._envelope(t) * self.peak).astype(np.float32)

    def _envelope(self, t: np.ndarray) -> np.ndarray:
        attack = np.minimum(t / ATTACK, 1.0)
        decay = SUSTAIN_LEVEL + (1.0 - SUSTAIN_LEVEL) * np.exp(
            -np.maximum(t - ATTACK, 0.0) / DECAY_TAU
        )
        env = attack * decay
        if self.release_time is not None:
            rel_t = np.maximum(t - self.release_time, 0.0)
            env = env * np.exp(-rel_t / RELEASE_TAU)
        return env


class PolySynth:
    """多复音合成器：管理音符的按下/松开/延音踏板/弯音。"""

    def __init__(self, sample_rate: int = 44100, max_voices: int = 48) -> None:
        self.sample_rate = sample_rate
        self.max_voices = max_voices
        self._voices: list[SynthVoice] = []
        self._lock = threading.RLock()
        self._sustain = False
        self._pedal_held: set[int] = set()   # 踏板踩下时松开的音符
        self._bend = 0.0                     # 弯音半音数

    # -- 音符 -------------------------------------------------------------
    def note_on(self, note: int, velocity: int = 100) -> None:
        with self._lock:
            # 同一个键重复按下：先把旧的收掉，避免叠音
            for v in self._voices:
                if v.note == note and not v.released:
                    v.release()
            if len(self._voices) >= self.max_voices:
                self._steal_voice()

            voice = SynthVoice(note, velocity, self.sample_rate)
            voice.start_time = max((v.t for v in self._voices), default=0.0)
            self._voices.append(voice)
            self._pedal_held.discard(note)

    def note_off(self, note: int) -> None:
        with self._lock:
            if self._sustain:
                self._pedal_held.add(note)   # 等踏板抬起再收
                return
            for v in self._voices:
                if v.note == note and not v.released:
                    v.release()

    def all_notes_off(self, immediate: bool = False) -> None:
        with self._lock:
            if immediate:
                self._voices.clear()
                self._pedal_held.clear()
                return
            for v in self._voices:
                v.release()
            self._pedal_held.clear()

    # -- 控制器 -----------------------------------------------------------
    def set_sustain(self, on: bool) -> None:
        with self._lock:
            if self._sustain and not on:
                for v in self._voices:
                    if v.note in self._pedal_held and not v.released:
                        v.release()
                self._pedal_held.clear()
            self._sustain = on

    @property
    def sustain(self) -> bool:
        return self._sustain

    def set_pitch_bend(self, value: int, semitone_range: float = 2.0) -> None:
        """``value`` 为 -8192~8191 的 14bit 弯音值。"""
        with self._lock:
            self._bend = (value / 8192.0) * semitone_range

    @property
    def bend_ratio(self) -> float:
        return 2.0 ** (self._bend / 12.0)

    # -- 渲染 -------------------------------------------------------------
    def render(self, frames: int) -> np.ndarray:
        """混合出 ``frames`` 个采样（float32，-1~1 单声道）。"""
        with self._lock:
            if not self._voices:
                return np.zeros(frames, dtype=np.float32)

            buf = np.zeros(frames, dtype=np.float32)
            ratio = self.bend_ratio
            for v in self._voices:
                buf += v.render(frames, ratio)

            self._voices = [v for v in self._voices if not v.is_finished()]

        np.clip(buf, -1.0, 1.0, out=buf)
        return buf

    @property
    def active_voices(self) -> int:
        with self._lock:
            return len(self._voices)

    # -- 内部 -------------------------------------------------------------
    def _steal_voice(self) -> None:
        """复音数满了：优先偷已经松开的、最老的音符。"""
        released = [v for v in self._voices if v.released]
        target = released[0] if released else self._voices[0]
        self._voices.remove(target)

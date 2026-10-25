"""主窗口：设备选择 + 键盘可视化 + 原始 MIDI 数据流。"""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..audio.engine import NullBackend, create_backend
from ..core.midi_input import MidiEvent, MidiInput, MidiPortError, list_input_ports
from ..core.notes import note_name
from . import theme
from .note_trail import NoteTrail
from .piano_widget import PianoKeyboard

MAX_LOG_BLOCKS = 2000
REFRESH_MS = 16      # 约 60fps


def _chip(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Chip")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


class MainWindow(QMainWindow):
    def __init__(self, port: str | int | None = None,
                 soundfont: str | Path | None = None,
                 enable_audio: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("MIDI 可视化 · MIDI Visualizer")
        self.resize(1320, 740)

        # -- 状态 ---------------------------------------------------------
        self._held: dict[int, int] = {}        # 物理按住的键 -> 力度
        self._sustained: dict[int, int] = {}   # 踏板延音中的键 -> 力度
        self._sustain_on = False
        self._bend = 0
        self._mod = 0
        self._last_note: tuple[int, int] | None = None
        self._last_ts = 0.0
        self._event_count = 0
        self._log_paused = False
        self._audio_enabled = enable_audio

        self.midi = MidiInput()
        self.audio = NullBackend("音频未初始化")
        self._audio_message = "音频未初始化"

        # -- 界面 ---------------------------------------------------------
        self._build_ui()
        self.setStyleSheet(theme.STYLESHEET)

        # -- 音频 ---------------------------------------------------------
        if enable_audio:
            self._switch_audio_backend(soundfont)
        else:
            self._audio_message = "音频已关闭"

        # -- 设备 ---------------------------------------------------------
        self._refresh_ports(select=port)

        # -- 数据泵 -------------------------------------------------------
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ==================================================================
    # 界面搭建
    # ==================================================================
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(10)

        outer.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([740, 540])
        outer.addWidget(splitter, 1)

        self.statusBar().showMessage("就绪")

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Panel")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        lay.addWidget(_section_title("MIDI 输入"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(240)
        self.port_combo.currentIndexChanged.connect(self._on_port_changed)
        lay.addWidget(self.port_combo)

        refresh_btn = QToolButton()
        refresh_btn.setText("刷新")
        refresh_btn.setToolTip("重新扫描 MIDI 输入设备 (Ctrl+R)")
        refresh_btn.setShortcut("Ctrl+R")
        refresh_btn.clicked.connect(lambda: self._refresh_ports())
        lay.addWidget(refresh_btn)

        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 15px;")
        lay.addWidget(self.status_dot)
        self.device_label = QLabel("未连接")
        self.device_label.setStyleSheet(f"color: {theme.TEXT_DIM};")
        lay.addWidget(self.device_label)

        lay.addStretch(1)

        self.audio_check = QCheckBox("声音")
        self.audio_check.setChecked(self._audio_enabled)
        self.audio_check.setToolTip("开关音频输出")
        self.audio_check.toggled.connect(self._on_audio_toggled)
        lay.addWidget(self.audio_check)

        lay.addWidget(QLabel("音量"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(75)
        self.volume_slider.setFixedWidth(110)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        lay.addWidget(self.volume_slider)

        self.sf2_btn = QToolButton()
        self.sf2_btn.setText("音源…")
        self.sf2_btn.setToolTip("加载 SoundFont (.sf2) 音源文件")
        self.sf2_btn.clicked.connect(self._choose_soundfont)
        lay.addWidget(self.sf2_btn)

        self.sound_label = QLabel("")
        self.sound_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(self.sound_label)
        return bar

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # --- 信息条 ---
        info = QFrame()
        info.setObjectName("Panel")
        info_lay = QHBoxLayout(info)
        info_lay.setContentsMargins(14, 10, 14, 10)
        info_lay.setSpacing(18)

        note_box = QVBoxLayout()
        note_box.setSpacing(0)
        note_box.addWidget(_section_title("最新音符"))
        self.note_label = QLabel("—")
        self.note_label.setObjectName("BigNote")
        note_box.addWidget(self.note_label)
        info_lay.addLayout(note_box)

        vel_box = QVBoxLayout()
        vel_box.setSpacing(4)
        vel_box.addWidget(_section_title("力度 VELOCITY"))
        self.vel_bar = QProgressBar()
        self.vel_bar.setRange(0, 127)
        self.vel_bar.setValue(0)
        self.vel_bar.setTextVisible(False)
        self.vel_bar.setFixedWidth(150)
        self.vel_bar.setFixedHeight(10)
        vel_box.addWidget(self.vel_bar)
        self.vel_label = QLabel("0")
        self.vel_label.setStyleSheet(
            f"color: {theme.ORANGE}; font-family: Consolas; font-size: 13px;")
        vel_box.addWidget(self.vel_label)
        info_lay.addLayout(vel_box)

        info_lay.addStretch(1)

        chips_box = QVBoxLayout()
        chips_box.setSpacing(6)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.chip_channel = _chip("CH —")
        self.chip_notes = _chip("按住 0")
        self.chip_sustain = _chip("延音 OFF")
        for c in (self.chip_channel, self.chip_notes, self.chip_sustain):
            row1.addWidget(c)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.chip_bend = _chip("弯音 0")
        self.chip_mod = _chip("调制轮 0")
        self.chip_events = _chip("事件 0")
        for c in (self.chip_bend, self.chip_mod, self.chip_events):
            row2.addWidget(c)
        chips_box.addLayout(row1)
        chips_box.addLayout(row2)
        info_lay.addLayout(chips_box)

        lay.addWidget(info)

        # --- 键盘 + 瀑布 ---
        kbd_frame = QFrame()
        kbd_frame.setObjectName("Panel")
        kbd_lay = QVBoxLayout(kbd_frame)
        kbd_lay.setContentsMargins(10, 8, 10, 10)
        kbd_lay.setSpacing(6)
        kbd_lay.addWidget(_section_title(
            "音符瀑布 · 颜色越暖力度越大（点击键盘可本地发声，Esc 急停）"))
        self.keyboard = PianoKeyboard()
        self.keyboard.setFixedHeight(142)
        self.keyboard.keyPressed.connect(self._on_mouse_press)
        self.keyboard.keyReleased.connect(self._on_mouse_release)
        self.trail = NoteTrail(self.keyboard)
        kbd_lay.addWidget(self.trail, 1)
        kbd_lay.addWidget(self.keyboard, 0)
        lay.addWidget(kbd_frame, 1)
        return panel

    def _build_log_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(_section_title("原始 MIDI 数据"))
        head.addStretch(1)

        self.only_notes = QCheckBox("仅音符")
        self.only_notes.setToolTip("只显示 Note On / Note Off")
        self.only_notes.toggled.connect(lambda _: None)
        head.addWidget(self.only_notes)

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setToolTip("暂停滚动 (空格)")
        self.pause_btn.setShortcut("Space")
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        head.addWidget(self.pause_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setToolTip("清空日志 (Ctrl+L)")
        clear_btn.setShortcut("Ctrl+L")
        clear_btn.clicked.connect(self._clear_log)
        head.addWidget(clear_btn)
        lay.addLayout(head)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_BLOCKS)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        font = QFont("Consolas", 9)
        self.log_view.setFont(font)
        lay.addWidget(self.log_view, 1)
        return frame

    # ==================================================================
    # MIDI 设备
    # ==================================================================
    def _refresh_ports(self, select: str | int | None = None) -> None:
        ports = list_input_ports()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        if ports:
            self.port_combo.addItems(ports)
        else:
            self.port_combo.addItem("（未检测到 MIDI 设备）")
            self.port_combo.setEnabled(False)
        self.port_combo.setEnabled(bool(ports))
        self.port_combo.blockSignals(False)

        if not ports:
            self._set_connected(False, "未检测到设备，请连接键盘后点刷新")
            return

        target = 0
        if select is not None:
            if isinstance(select, int):
                target = max(0, min(select, len(ports) - 1))
            elif select in ports:
                target = ports.index(select)
        self.port_combo.setCurrentIndex(target)
        self._open_port(ports[target])

    def _on_port_changed(self, index: int) -> None:
        if index < 0:
            return
        self._open_port(self.port_combo.itemText(index))

    def _open_port(self, name: str) -> None:
        try:
            opened = self.midi.open(name)
        except MidiPortError as exc:
            self._set_connected(False, str(exc))
            self.statusBar().showMessage(f"打开失败：{exc}")
            return
        self._set_connected(True, f"已连接 {opened}")
        self.statusBar().showMessage(
            f"正在监听 {opened} · 音频：{self._audio_message}")

    def _set_connected(self, ok: bool, text: str) -> None:
        color = theme.GREEN if ok else theme.TEXT_MUTED
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 15px;")
        self.device_label.setText(text)

    # ==================================================================
    # 音频
    # ==================================================================
    def _switch_audio_backend(self, soundfont: str | Path | None) -> None:
        try:
            self.audio.stop()
        except Exception:
            pass
        self.audio, self._audio_message = create_backend(
            soundfont, volume=self.volume_slider.value() / 100.0
        )
        self.audio.set_muted(not self.audio_check.isChecked())
        self.sound_label.setText(self.audio.name)
        self.sound_label.setToolTip(self._audio_message)

    def _on_audio_toggled(self, on: bool) -> None:
        self._audio_enabled = on
        self.audio.set_muted(not on)
        if not on:
            self.audio.all_notes_off()

    def _on_volume_changed(self, value: int) -> None:
        self.audio.set_volume(value / 100.0)

    def _choose_soundfont(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 SoundFont 音源", "", "SoundFont (*.sf2);;所有文件 (*)"
        )
        if not path:
            return
        self._switch_audio_backend(path)
        self.statusBar().showMessage(self._audio_message)
        if not self.audio.running:
            self.statusBar().showMessage(f"音源加载失败：{self._audio_message}")

    # ==================================================================
    # 数据泵
    # ==================================================================
    def _tick(self) -> None:
        events = self.midi.drain()
        if not events:
            return

        lines: list[str] = []
        only_notes = self.only_notes.isChecked()
        for ev in events:
            self._handle_event(ev)
            if only_notes and not ev.is_note:
                continue
            lines.append(self._format_line(ev))

        self._event_count += len(events)
        self._refresh_ui()

        if lines and not self._log_paused:
            self.log_view.appendPlainText("\n".join(lines))

    def _handle_event(self, ev: MidiEvent) -> None:
        if ev.is_note_on:
            self._held[ev.note] = ev.velocity
            self._sustained.pop(ev.note, None)
            self._last_note = (ev.note, ev.velocity)
            self.chip_channel.setText(f"CH {ev.channel}")
            self.audio.note_on(ev.note, ev.velocity)
            self.trail.note_on(ev.note, ev.velocity)
        elif ev.is_note_off:
            velocity = self._held.pop(ev.note, None) or 0
            if self._sustain_on:
                self._sustained[ev.note] = velocity or 100
            else:
                self._sustained.pop(ev.note, None)
            self.audio.note_off(ev.note)
            self.trail.note_off(ev.note)
        elif ev.type == "control_change":
            if ev.control == 64:
                self._sustain_on = ev.value >= 64
                if not self._sustain_on:
                    self._sustained.clear()
            elif ev.control == 1:
                self._mod = ev.value
            elif ev.control in (120, 123):
                self._held.clear()
                self._sustained.clear()
                self.trail.clear()
            self.audio.control_change(ev.control, ev.value)
        elif ev.type == "pitch_bend":
            self._bend = ev.bend
            self.audio.pitch_bend(ev.bend)
        elif ev.type == "program_change":
            self.audio.program_change(ev.data1)

    def _refresh_ui(self) -> None:
        state = {n: (v, False) for n, v in self._held.items()}
        for n, v in self._sustained.items():
            state.setdefault(n, (v, True))
        self.keyboard.set_notes(state)

        if self._last_note is not None:
            note, velocity = self._last_note
            self.note_label.setText(note_name(note))
            self.vel_bar.setValue(velocity)
            self.vel_label.setText(str(velocity))
        self.chip_notes.setText(f"按住 {len(self._held)}")
        self.chip_sustain.setText(f"延音 {'ON' if self._sustain_on else 'OFF'}")
        self.chip_sustain.setStyleSheet(
            f"color: {theme.GREEN};" if self._sustain_on else "")
        self.chip_bend.setText(f"弯音 {self._bend:+d}")
        self.chip_mod.setText(f"调制轮 {self._mod}")
        self.chip_events.setText(f"事件 {self._event_count}")

    def _format_line(self, ev: MidiEvent) -> str:
        now = time.localtime()
        stamp = time.strftime("%H:%M:%S", now) + f".{int(time.time() * 1000) % 1000:03d}"
        if self._last_ts:
            delta_ms = (ev.timestamp - self._last_ts) * 1000.0
            gap = f"{delta_ms:+8.1f}ms" if delta_ms < 10000 else "     —— "
        else:
            gap = " " * 10
        self._last_ts = ev.timestamp
        return f"[{stamp}] {ev.hex:<11s} {gap}  {ev.describe()}"

    # ==================================================================
    # 鼠标弹奏（本地发声）
    # ==================================================================
    def _on_mouse_press(self, note: int, velocity: int) -> None:
        self._held[note] = velocity
        self._sustained.pop(note, None)
        self._last_note = (note, velocity)
        self.audio.note_on(note, velocity)
        self.trail.note_on(note, velocity)
        self._refresh_ui()
        if not self._log_paused:
            self.log_view.appendPlainText(
                f"[鼠标]  {note_name(note):<4s} ({note:3d})  vel {velocity}")

    def _on_mouse_release(self, note: int) -> None:
        velocity = self._held.pop(note, None) or 0
        if self._sustain_on and velocity:
            self._sustained[note] = velocity
        self.audio.note_off(note)
        self.trail.note_off(note)
        self._refresh_ui()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._log_paused = paused
        self.pause_btn.setText("继续" if paused else "暂停")

    def _clear_log(self) -> None:
        self.log_view.clear()

    # ==================================================================
    # 收尾
    # ==================================================================
    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if event.key() == Qt.Key.Key_Escape:   # 急停：全部音符关掉
            self._held.clear()
            self._sustained.clear()
            self.audio.all_notes_off()
            self.trail.clear()
            self._refresh_ui()
            self.statusBar().showMessage("已复位：全部音符关闭", 2000)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._timer.stop()
        try:
            self.midi.close()
        except Exception:
            pass
        try:
            self.audio.stop()
        except Exception:
            pass
        super().closeEvent(event)

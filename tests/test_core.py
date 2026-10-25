"""核心逻辑单元测试（不需要 MIDI 设备、不需要声卡）。

    .venv/Scripts/python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

import numpy as np

from midi_visualizer.audio.synth import PolySynth, SynthVoice
from midi_visualizer.core.midi_input import parse_message
from midi_visualizer.core.notes import is_black_key, note_name, note_to_freq
from midi_visualizer.ui.staff_widget import (
    BASS_LINES,
    MIDDLE_C_STEP,
    TREBLE_LINES,
    staff_step,
)


class TestNotes(unittest.TestCase):
    def test_note_name(self):
        self.assertEqual(note_name(60), "C4")
        self.assertEqual(note_name(21), "A0")
        self.assertEqual(note_name(108), "C8")
        self.assertEqual(note_name(61), "C#4")

    def test_freq(self):
        self.assertAlmostEqual(note_to_freq(69), 440.0)
        self.assertAlmostEqual(note_to_freq(81), 880.0)
        self.assertAlmostEqual(note_to_freq(60), 261.6256, places=3)

    def test_black_keys(self):
        self.assertTrue(is_black_key(61))    # C#4
        self.assertFalse(is_black_key(60))   # C4
        self.assertFalse(is_black_key(64))   # E4


class TestParser(unittest.TestCase):
    def test_note_on(self):
        ev = parse_message(bytes([0x90, 60, 96]))
        self.assertEqual(ev.type, "note_on")
        self.assertEqual(ev.channel, 1)
        self.assertEqual(ev.note, 60)
        self.assertEqual(ev.velocity, 96)
        self.assertTrue(ev.is_note_on)
        self.assertFalse(ev.is_note_off)
        self.assertEqual(ev.hex, "90 3C 60")
        self.assertIn("C4", ev.describe())

    def test_note_on_velocity_zero_is_note_off(self):
        ev = parse_message(bytes([0x90, 60, 0]))
        self.assertEqual(ev.type, "note_on")   # 线上类型还是 note_on
        self.assertTrue(ev.is_note_off)        # 语义上是松开
        self.assertEqual(ev.velocity, 0)

    def test_note_off(self):
        ev = parse_message(bytes([0x80, 61, 64]))
        self.assertTrue(ev.is_note_off)
        self.assertEqual(ev.channel, 1)

    def test_channel_is_one_based(self):
        self.assertEqual(parse_message(bytes([0x90, 60, 1])).channel, 1)
        self.assertEqual(parse_message(bytes([0x9F, 60, 1])).channel, 16)

    def test_control_change(self):
        ev = parse_message(bytes([0xB0, 64, 127]))
        self.assertEqual(ev.type, "control_change")
        self.assertTrue(ev.is_sustain)
        self.assertEqual(ev.value, 127)
        self.assertIn("Sustain", ev.describe())

    def test_pitch_bend_center(self):
        low, high = 0x00, 0x40   # 0x40<<7 | 0x00 = 8192
        ev = parse_message(bytes([0xE0, low, high]))
        self.assertEqual(ev.type, "pitch_bend")
        self.assertEqual(ev.bend, 0)

    def test_pitch_bend_extremes(self):
        self.assertEqual(parse_message(bytes([0xE0, 0x00, 0x00])).bend, -8192)
        self.assertEqual(parse_message(bytes([0xE0, 0x7F, 0x7F])).bend, 8191)

    def test_program_change_has_single_data_byte(self):
        ev = parse_message(bytes([0xC3, 42]))
        self.assertEqual(ev.type, "program_change")
        self.assertEqual(ev.channel, 4)
        self.assertEqual(ev.data1, 42)
        self.assertEqual(ev.data2, 0)

    def test_system_realtime(self):
        ev = parse_message(bytes([0xF8]))
        self.assertEqual(ev.channel, 0)
        self.assertEqual(ev.type, "clock")


class TestStaffPosition(unittest.TestCase):
    """五线谱定位：音级步进必须和各谱表的线位置严格对应。"""

    def test_middle_c(self):
        self.assertEqual(staff_step(60), (MIDDLE_C_STEP, 0))

    def test_sharp_keeps_diatonic_step(self):
        self.assertEqual(staff_step(61), (28, 1))    # C#4 与 C4 同一位置
        self.assertEqual(staff_step(66), (31, 1))    # F#4
        self.assertEqual(staff_step(58), (26, 1))    # A#3 与 A3 同线

    def test_treble_lines(self):
        # E4 G4 B4 D5 F5 必须正好落在高音谱的五条线上
        for note in (64, 67, 71, 74, 77):
            self.assertIn(staff_step(note)[0], TREBLE_LINES, note_name(note))

    def test_bass_lines(self):
        # G2 B2 D3 F3 A3 必须正好落在低音谱的五条线上
        for note in (43, 47, 50, 53, 57):
            self.assertIn(staff_step(note)[0], BASS_LINES, note_name(note))

    def test_space_between_lines(self):
        # 线之间的音（间）应该是奇数步进
        self.assertEqual(staff_step(65)[0], 31)      # F4 在 E4/G4 之间
        self.assertEqual(staff_step(62)[0], 29)      # D4 在中央 C 之上

    def test_range_corners(self):
        self.assertEqual(staff_step(21), (5, 0))     # A0
        self.assertEqual(staff_step(108), (56, 0))   # C8


class TestSynth(unittest.TestCase):
    SR = 44100

    def _render_blocks(self, synth: PolySynth, seconds: float) -> np.ndarray:
        block = 512
        chunks = []
        for _ in range(int(seconds * self.SR / block) + 1):
            chunks.append(synth.render(block))
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    def test_voice_produces_sound(self):
        voice = SynthVoice(60, 100, self.SR)
        buf = voice.render(1024)
        self.assertEqual(len(buf), 1024)
        self.assertTrue(np.all(np.isfinite(buf)))
        self.assertGreater(float(np.max(np.abs(buf))), 1e-3)

    def test_voice_release_finishes(self):
        voice = SynthVoice(72, 80, self.SR)
        voice.render(512)
        voice.release()
        self.assertTrue(voice.released)
        for _ in range(200):
            voice.render(512)
        self.assertTrue(voice.is_finished())

    def test_polyphony_and_release(self):
        synth = PolySynth(sample_rate=self.SR)
        synth.note_on(60, 100)
        synth.note_on(64, 90)
        self.assertEqual(synth.active_voices, 2)
        buf = synth.render(512)
        self.assertGreater(float(np.max(np.abs(buf))), 1e-3)
        synth.note_off(60)
        synth.note_off(64)
        self._render_blocks(synth, 1.5)
        self.assertEqual(synth.active_voices, 0)

    def test_sustain_pedal_holds_notes(self):
        synth = PolySynth(sample_rate=self.SR)
        synth.set_sustain(True)
        synth.note_on(60, 100)
        synth.note_off(60)            # 踏板踩着，不该真的松开
        self._render_blocks(synth, 0.3)
        self.assertEqual(synth.active_voices, 1)
        synth.set_sustain(False)      # 抬踏板后开始余音
        self._render_blocks(synth, 1.5)
        self.assertEqual(synth.active_voices, 0)

    def test_voice_stealing_limits_polyphony(self):
        synth = PolySynth(sample_rate=self.SR, max_voices=4)
        for note in range(60, 70):
            synth.note_on(note, 100)
        self.assertLessEqual(synth.active_voices, 4)

    def test_pitch_bend_changes_ratio(self):
        synth = PolySynth(sample_rate=self.SR)
        synth.set_pitch_bend(0)
        self.assertAlmostEqual(synth.bend_ratio, 1.0)
        synth.set_pitch_bend(8192)   # 默认 +/-2 半音
        self.assertAlmostEqual(synth.bend_ratio, 2 ** (2 / 12), places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

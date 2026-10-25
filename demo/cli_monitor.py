"""示例：不依赖界面，直接复用 MIDI 输入模块。

    .venv/Scripts/python.exe demo/cli_monitor.py
    .venv/Scripts/python.exe demo/cli_monitor.py "你的键盘名称" --notes
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_visualizer.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

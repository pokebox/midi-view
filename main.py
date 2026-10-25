#!/usr/bin/env python
"""启动 MIDI 可视化。

    python main.py                 # 自动连接第一个 MIDI 输入设备
    python main.py --list-ports    # 看看有哪些设备
    python main.py --cli           # 只在终端打印 MIDI 数据
"""

import sys

from midi_visualizer.app import main

if __name__ == "__main__":
    sys.exit(main())

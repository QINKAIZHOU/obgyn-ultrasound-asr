"""妇产科/乳腺科超声口述语音识别 CLI。"""
from __future__ import annotations

import argparse

from modes import run_file, run_realtime, run_text


def main():
    p = argparse.ArgumentParser(description="妇产科/乳腺科超声语音识别（Paraformer + Qwen 优化）")
    sub = p.add_subparsers(dest="cmd", required=True)

    rt = sub.add_parser("realtime", help="麦克风实时识别")
    rt.add_argument("--mic", type=int, default=None, help="麦克风设备编号（默认系统默认设备）")
    rt.add_argument("--simulate", default=None, help="用 16kHz wav 文件模拟麦克风输入（调试用）")
    rt.add_argument("--speed", type=float, default=1.0, help="模拟模式的送块速度倍率")

    fl = sub.add_parser("file", help="音频文件转写")
    fl.add_argument("audio", help="音频文件路径（wav/mp3 等）")
    fl.add_argument("--srt", default=None, help="保存字幕文件路径（优化后文本）")
    fl.add_argument("--report", default=None, help="保存报告文本文件路径（仅增强后的报告内容，每段一行）")

    tx = sub.add_parser("text", help="命令行文本模式（Qwen 流式优化）")
    tx.add_argument("text", nargs="*", help="要优化的文本（不传则进入交互模式）")

    for sp in (rt, fl, tx):
        sp.add_argument("--no-enhance", action="store_true", help="跳过增强优化（报告内容提取）第二遍")
    for sp in (rt, fl):
        sp.add_argument("--device", default="cuda:0", help="推理设备，如 cuda:0 或 cpu")
        sp.add_argument("--no-llm", action="store_true", help="关闭 Qwen 文本优化")

    args = p.parse_args()
    {"realtime": run_realtime, "file": run_file, "text": run_text}[args.cmd](args)


if __name__ == "__main__":
    main()

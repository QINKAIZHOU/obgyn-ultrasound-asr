"""Qwen 优化效果快速验证脚本。"""
import time

from llm import UltrasoundOptimizer

CASES = [
    "肝脏形态大小正常，包膜光滑，实质回升均匀，胆囊大小约六点五乘三点二厘米，闭光滑，腔内未见明显异常。",
    "双肾大小形态正常，甚于未见分离。",
    "甲状腺右侧叶可见一滴回升，结节大小约八乘五毫米，边界清晰，内部未见明显血流信号。",
]

opt = UltrasoundOptimizer()
for text in CASES:
    t0 = time.perf_counter()
    out = opt.optimize(text)
    dt = time.perf_counter() - t0
    print(f"原文: {text}")
    print(f"优化: {out}")
    print(f"耗时: {dt:.2f}s\n")

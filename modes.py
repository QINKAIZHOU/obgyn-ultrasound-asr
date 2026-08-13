"""三个子命令（realtime / file / text）的运行实现与共用的格式工具。"""
from __future__ import annotations

import queue
import re
import sys
import threading
import time

import numpy as np

from llm import UltrasoundOptimizer, is_non_report
from pipeline import (
    CHUNK_MS,
    CHUNK_SAMPLES,
    load_asr_pipeline,
    load_streaming_vad,
    recognize,
)

# 标点恢复时插入的符号（用于把带标点文本对齐回逐 token 时间戳）
_INSERTED_PUNCT = set("，。！？；：、,.;:!?…—·“”\"'‘’（）()《》 ")
_SENT_RE = re.compile(r"[^。！？；\n]+[。！？；]?")


def fmt_ts(ms: float) -> str:
    s = ms / 1000.0
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def load_optimizer(no_llm: bool) -> UltrasoundOptimizer | None:
    return None if no_llm else UltrasoundOptimizer()


def emit_all(
    beg_ms: float,
    text: str,
    optimizer: UltrasoundOptimizer | None,
    do_enhance: bool = True,
) -> tuple[str, str | None]:
    """打印 原文/优化/增强 三行对照；返回 (优化文本, 增强文本或None)。"""
    ts = fmt_ts(beg_ms)
    print(f"[{ts}] 原文: {text}")
    optimized = text
    enhanced: str | None = None
    if optimizer is not None:
        optimized = optimizer.optimize(text) or text
        print(f"[{ts}] 优化: {optimized}")
        if do_enhance:
            enhanced = optimizer.enhance(optimized)
            print(f"[{ts}] 增强: {enhanced}")
    sys.stdout.flush()
    return optimized, enhanced


# ---------- realtime ----------

def _start_mic(q: queue.Queue, device: int | None):
    import sounddevice as sd

    def cb(indata, frames, time_info, status):
        q.put(bytes(indata))

    stream = sd.RawInputStream(
        samplerate=16000,
        blocksize=CHUNK_SAMPLES,
        dtype="int16",
        channels=1,
        callback=cb,
        device=device,
    )
    stream.start()
    return stream


def _start_simulated_mic(q: queue.Queue, path: str, speed: float):
    import soundfile as sf

    data, sr = sf.read(path, dtype="int16")
    if data.ndim > 1:
        data = data.mean(axis=1).astype(np.int16)
    if sr != 16000:
        raise SystemExit(f"模拟音频需为 16000Hz，当前文件为 {sr}Hz")

    def feeder():
        for i in range(0, len(data), CHUNK_SAMPLES):
            q.put(data[i : i + CHUNK_SAMPLES].tobytes())
            time.sleep(CHUNK_MS / 1000 / speed)
        q.put(None)

    threading.Thread(target=feeder, daemon=True).start()
    print(f"模拟麦克风输入: {path}（{speed}x 速度）")


def run_realtime(args):
    model = load_asr_pipeline(args.device)
    optimizer = load_optimizer(args.no_llm)
    vad = load_streaming_vad(args.device)

    q: queue.Queue = queue.Queue()
    stream = None
    if args.simulate:
        _start_simulated_mic(q, args.simulate, args.speed)
    else:
        stream = _start_mic(q, args.mic)
        print("开始录音，Ctrl+C 停止。")

    audio = bytearray()
    cache: dict = {}
    seen: set[tuple[int, int]] = set()
    cur_start: list[int | None] = [None]  # VAD 流式协议：已完成段起点报 -1

    def handle_segments(segs):
        for beg, end in segs:
            if beg >= 0:
                cur_start[0] = beg
            if end < 0:
                continue
            start = beg if beg >= 0 else cur_start[0]
            if start is None or (start, end) in seen:
                continue
            seen.add((start, end))
            cur_start[0] = None
            seg = (
                np.frombuffer(bytes(audio[start * 32 : end * 32]), dtype=np.int16).astype(
                    np.float32
                )
                / 32768.0
            )
            text = recognize(model, seg)
            if text:
                emit_all(start, text, optimizer, do_enhance=not args.no_enhance)

    try:
        while True:
            try:
                chunk = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None:
                break
            audio.extend(chunk)
            f32 = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            res = vad.generate(
                input=f32, cache=cache, is_final=False,
                chunk_size=CHUNK_MS, disable_pbar=True,
            )
            if res and res[0].get("value"):
                handle_segments(res[0]["value"])
    except KeyboardInterrupt:
        pass
    finally:
        res = vad.generate(
            input=np.zeros(CHUNK_SAMPLES, dtype=np.float32),
            cache=cache, is_final=True, chunk_size=CHUNK_MS, disable_pbar=True,
        )
        if res and res[0].get("value"):
            handle_segments(res[0]["value"])
        if stream is not None:
            stream.stop()
            stream.close()
        print("已停止。")


# ---------- file ----------

def split_sentences(text: str) -> list[str]:
    return [m.group(0) for m in _SENT_RE.finditer(text) if m.group(0).strip()]


def sentence_spans(
    sentences: list[str], timestamps: list[list[float]]
) -> list[tuple[float, float] | None]:
    """按非标点字符数把句子对齐到逐 token 时间戳（英文多字符 token 时为近似）。"""
    spans = []
    tok = 0
    for sent in sentences:
        n = sum(1 for ch in sent if ch not in _INSERTED_PUNCT)
        if n == 0 or tok >= len(timestamps):
            spans.append(None)
            continue
        end_tok = min(tok + n, len(timestamps)) - 1
        spans.append((timestamps[tok][0], timestamps[end_tok][1]))
        tok += n
    return spans


def write_srt(path: str, rows: list[tuple[tuple[float, float] | None, str]]) -> None:
    def srt_ts(ms: float) -> str:
        s, msec = divmod(int(ms), 1000)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d},{msec:03d}"

    idx = 0
    with open(path, "w", encoding="utf-8") as f:
        for span, text in rows:
            if span is None:
                continue
            idx += 1
            f.write(f"{idx}\n{srt_ts(span[0])} --> {srt_ts(span[1])}\n{text}\n\n")
    print(f"字幕已保存: {path}")


def write_report(path: str, lines: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    print(f"报告已保存: {path}（{len(lines)} 行）")


def run_file(args):
    model = load_asr_pipeline(args.device)
    optimizer = load_optimizer(args.no_llm)

    print(f"转写: {args.audio}")
    res = model.generate(input=args.audio, batch_size_s=300, disable_pbar=True)
    if not res or not (res[0].get("text") or "").strip():
        print("未识别到语音。")
        return
    text = res[0]["text"].strip()
    timestamps = res[0].get("timestamp") or []

    sentences = split_sentences(text)
    spans = sentence_spans(sentences, timestamps)
    srt_rows = []
    report_lines: list[str] = []
    do_enhance = optimizer is not None and not args.no_enhance
    for sent, span in zip(sentences, spans):
        beg = span[0] if span else 0.0
        optimized, enhanced = emit_all(beg, sent, optimizer, do_enhance=do_enhance)
        srt_rows.append((span, optimized))
        if enhanced is not None and not is_non_report(enhanced):
            report_lines.append(enhanced)
    sys.stdout.flush()

    if args.srt:
        write_srt(args.srt, srt_rows)
    if args.report and optimizer is not None:
        write_report(args.report, report_lines)


# ---------- text ----------

def run_text(args):
    optimizer = load_optimizer(False)

    def optimize_one(line: str) -> None:
        line = line.strip()
        if not line:
            return
        print(f"原文: {line}")
        optimized = optimizer.optimize(line) or line
        print(f"优化: {optimized}")
        if not args.no_enhance:
            print("增强: ", end="", flush=True)
            optimizer.enhance(optimized, stream=True)
            print()

    if args.text:
        for t in args.text:
            optimize_one(t)
    else:
        print("输入要优化的文本后回车；Ctrl+C 或 Ctrl+D 退出。", flush=True)
        try:
            while True:
                try:
                    line = input("> ")
                except EOFError:
                    break
                optimize_one(line)
        except KeyboardInterrupt:
            pass
        print()

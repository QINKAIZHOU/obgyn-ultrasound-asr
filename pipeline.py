"""ASR 模型加载与单段识别。"""
from __future__ import annotations

from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHUNK_MS = 200
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000

# SeACo-Paraformer：Paraformer-large 的热词增强版（同量级，输出含时间戳），默认引擎
SEACO_ASR_MODEL_ID = "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
# 旧版 Paraformer-large（--legacy-asr 回退 / A-B 对比用）
LEGACY_ASR_MODEL_ID = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
ASR_MODEL_ID = SEACO_ASR_MODEL_ID
DEFAULT_HOTWORDS_FILE = "hotwords/精选热词.txt"
_PROJECT_ROOT = Path(__file__).resolve().parent

VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL_ID = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

_MIN_SEG_SAMPLES = SAMPLE_RATE // 10  # 短于 100ms 的段直接丢弃


def load_hotwords(path: str | None) -> str | None:
    """读热词表（UTF-8，每行一词，# 注释/空行剥离）→ 空格分隔字符串。

    不直接把文件路径交给 funasr：其本地 txt 分支用 codecs.open 未指定编码，
    Windows GBK locale 下 UTF-8 热词会静默乱码失效。路径不存在返回 None。
    """
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = _PROJECT_ROOT / path
    if not p.exists():
        return None
    words = [
        w for ln in p.read_text(encoding="utf-8").splitlines()
        if (w := ln.strip()) and not w.startswith("#")
    ]
    return " ".join(words) or None


def load_asr_pipeline(device: str, model_id: str = ASR_MODEL_ID):
    from funasr import AutoModel

    print(f"加载 ASR 模型（{device} · {model_id}）…")
    return AutoModel(
        model=model_id,
        vad_model=VAD_MODEL_ID,
        punc_model=PUNC_MODEL_ID,
        device=device,
        disable_update=True,
    )


def load_streaming_vad(device: str):
    from funasr import AutoModel

    return AutoModel(model=VAD_MODEL_ID, device=device, disable_update=True)


def recognize(model, audio: np.ndarray | str, hotword: str | None = None, **gen_kwargs) -> str:
    """对单段 ndarray 或音频文件路径做识别（自动带 VAD 切分与标点恢复）。

    hotword: 空格分隔的热词字符串（SeACo-Paraformer 生效，其他模型忽略）。
    """
    if isinstance(audio, np.ndarray) and len(audio) < _MIN_SEG_SAMPLES:
        return ""
    if hotword:
        gen_kwargs["hotword"] = hotword
    res = model.generate(input=audio, batch_size_s=300, disable_pbar=True, **gen_kwargs)
    if not res:
        return ""
    return (res[0].get("text") or "").strip()

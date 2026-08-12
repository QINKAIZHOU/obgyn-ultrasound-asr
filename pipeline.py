"""ASR 模型加载与单段识别。"""
from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000
CHUNK_MS = 200
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000

ASR_MODEL_ID = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL_ID = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

_MIN_SEG_SAMPLES = SAMPLE_RATE // 10  # 短于 100ms 的段直接丢弃


def load_asr_pipeline(device: str):
    from funasr import AutoModel

    print(f"加载 ASR 模型（{device}）…")
    return AutoModel(
        model=ASR_MODEL_ID,
        vad_model=VAD_MODEL_ID,
        punc_model=PUNC_MODEL_ID,
        device=device,
        disable_update=True,
    )


def load_streaming_vad(device: str):
    from funasr import AutoModel

    return AutoModel(model=VAD_MODEL_ID, device=device, disable_update=True)


def recognize(model, audio: np.ndarray | str) -> str:
    """对单段 ndarray 或音频文件路径做识别（自动带 VAD 切分与标点恢复）。"""
    if isinstance(audio, np.ndarray) and len(audio) < _MIN_SEG_SAMPLES:
        return ""
    res = model.generate(input=audio, batch_size_s=300, disable_pbar=True)
    if not res:
        return ""
    return (res[0].get("text") or "").strip()

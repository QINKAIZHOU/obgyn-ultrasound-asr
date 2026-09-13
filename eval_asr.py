"""ASR 级 A/B 评测：量化对比 旧Paraformer / SeACo / SeACo+热词（/ +文本级纠错映射）。

不加载 LLM，纯 ASR 指标（无逐字真值也可跑）：
  1. 错误变体计数↓  —— SYSTEM_PROMPT 收录的已知同音错字，命中附上下文供人工复核
  2. 规范术语命中↑  —— 高频规范术语子串计数（配置间相对比较）
  3. 总字数         —— 异常膨胀/缩水 = 退化信号
  4. 耗时/RTF       —— 量化热词偏置开销
  5. 可选 CER       —— --ref-dir 下提供 <wav同名>.txt 参考文本时计算

用法:
  .venv/Scripts/python eval_asr.py [--configs A,B,C] [--device cuda:0]
      [--data-dir data/0911-案例] [--hotwords hotwords/精选热词.txt]
      [--pp-map hotwords/纠错映射.txt] [--ref-dir eval_refs]
      [--limit-seconds N] [--out-dir eval_out]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from pipeline import (
    LEGACY_ASR_MODEL_ID,
    SEACO_ASR_MODEL_ID,
    load_asr_pipeline,
    load_hotwords,
    recognize,
)

# 已知同音错字变体，越少越好。两类来源：
#   1) llm.py SYSTEM_PROMPT 括号内收录的示例错字
#   2) data/0911-案例 真实门诊录音中实际观察到的错误变体（首轮评测人工复核）
# 注意：部分变体（前臂/基层/后鼻/面膜）是通用汉语合法词，在本域内几乎必为错字，
# 命中均附上下文抽样供人工复核误报。
ERROR_VARIANTS = [
    # SYSTEM_PROMPT 示例错字
    "子工", "内幕", "内模", "宫井", "乱巢", "机留", "肌留", "囊种", "几胎留",
    "叶性暗区", "韵囊", "太心", "太芽", "太盘", "杨水", "双顶颈", "骨股长",
    "其血流", "节节", "盖化", "流血信号", "夜窝淋巴结",
    # 真实录音观察变体
    "乱抽", "乱潮", "卵朝", "芒肿", "激瘤", "回伸", "回升", "回身", "落回身",
    "前臂", "后臂", "后鼻", "基层", "波炉", "波漏", "面膜", "晕超", "南块",
]

# 高频规范术语（与 build_hotwords.py CORE_TERMS 对齐 + 真实录音高频词），越多越好
CANON_TERMS = [
    "子宫", "子宫内膜", "宫颈", "卵巢", "肌瘤", "囊肿", "畸胎瘤", "孕囊",
    "胎心", "胎芽", "胎盘", "羊水", "双顶径", "股骨长", "肱骨长", "头围",
    "腹围", "脐血流", "羊水指数", "前置胎盘", "孕周", "结节", "肿块", "钙化",
    "导管扩张", "纵横比", "血流信号", "弹性成像", "腋窝淋巴结", "低回声",
    "强回声", "无回声", "混合性回声", "盆腔积液", "液性暗区", "卵泡", "黄体",
    "输卵管", "肌层", "宫腔", "内膜", "前壁", "后壁", "回声", "阴超", "腺肌症",
]

_PUNCT_RE = re.compile(r"[\s，。！？；：、,.;:!?…—·“”\"'‘’（）()《》【】\[\]{}×~～-]")


@dataclass(frozen=True)
class Config:
    key: str
    label: str
    model_id: str
    use_hotwords: bool
    use_pp: bool


CONFIGS: dict[str, Config] = {
    "A": Config("A", "旧Paraformer", LEGACY_ASR_MODEL_ID, False, False),
    "B": Config("B", "SeACo无热词", SEACO_ASR_MODEL_ID, False, False),
    "C": Config("C", "SeACo+热词", SEACO_ASR_MODEL_ID, True, False),
    "D": Config("D", "SeACo+热词+映射", SEACO_ASR_MODEL_ID, True, True),
}


def find_audios(data_dir: Path) -> list[Path]:
    return sorted(data_dir.glob("*.wav"))


def load_audio(path: Path, limit_seconds: int | None) -> tuple[np.ndarray, float]:
    """读音频 → 混单声道 float32 → 可选截断；返回 (数据, 时长秒)。"""
    data, sr = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if limit_seconds:
        data = data[: int(sr * limit_seconds)]
    return data.astype(np.float32), len(data) / sr


def count_hits(text: str, terms: list[str]) -> dict[str, int]:
    return {t: text.count(t) for t in terms if text.count(t) > 0}


def find_contexts(text: str, term: str, width: int = 10) -> list[str]:
    out = []
    start = 0
    while (i := text.find(term, start)) >= 0:
        out.append(text[max(0, i - width) : i + len(term) + width])
        start = i + 1
    return out


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    r = _PUNCT_RE.sub("", ref)
    h = _PUNCT_RE.sub("", hyp)
    return levenshtein(r, h) / max(len(r), 1)


def run_all(args) -> dict:
    cfgs = [CONFIGS[k.strip().upper()] for k in args.configs.split(",")]
    hotword_str = load_hotwords(args.hotwords) if any(c.use_hotwords for c in cfgs) else None
    if hotword_str is None and any(c.use_hotwords for c in cfgs):
        raise SystemExit(f"热词文件不可用: {args.hotwords}")
    pp_map = args.pp_map if any(c.use_pp for c in cfgs) else None
    if pp_map and not Path(pp_map).exists():
        raise SystemExit(f"纠错映射文件不存在: {pp_map}")

    audios = find_audios(Path(args.data_dir))
    if not audios:
        raise SystemExit(f"未找到 wav: {args.data_dir}")
    audio_data = {p.name: load_audio(p, args.limit_seconds) for p in audios}
    total_dur = sum(d for _, d in audio_data.values())
    print(f"音频 {len(audios)} 段，共 {total_dur:.0f}s"
          + (f"（各截前 {args.limit_seconds}s）" if args.limit_seconds else ""))

    models: dict[str, object] = {}
    results: dict = {"meta": {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "audios": [p.name for p in audios],
        "total_seconds": total_dur,
        "limit_seconds": args.limit_seconds,
        "hotwords_file": args.hotwords,
        "hotwords_count": hotword_str.count(" ") + 1 if hotword_str else 0,
        "configs": [c.key for c in cfgs],
    }, "results": {}}

    for c in cfgs:
        if c.model_id not in models:
            models[c.model_id] = load_asr_pipeline(args.device, c.model_id)
        model = models[c.model_id]
        results["results"][c.key] = {}
        for name, (data, dur) in audio_data.items():
            extra: dict = {}
            if c.use_hotwords:
                extra["hotword"] = hotword_str
            if c.use_pp:
                extra.update(postprocess_hotword_file=pp_map, postprocess_hotword_fuzzy=False)
            t0 = time.perf_counter()
            text = recognize(model, data, **extra)
            elapsed = time.perf_counter() - t0

            entry = {
                "text": text,
                "elapsed": round(elapsed, 2),
                "duration": round(dur, 1),
                "chars": len(text),
                "bad_variants": count_hits(text, ERROR_VARIANTS),
                "canon_hits": count_hits(text, CANON_TERMS),
            }
            ref_dir = Path(args.ref_dir) if args.ref_dir else None
            ref_path = ref_dir / (Path(name).stem + ".txt") if ref_dir else None
            if ref_path and ref_path.exists():
                entry["cer"] = round(cer(ref_path.read_text(encoding="utf-8"), text), 4)
            results["results"][c.key][name] = entry
            bad_n = sum(entry["bad_variants"].values())
            print(f"  [{c.key}] {name}: {elapsed:.1f}s（RTF {elapsed / dur:.3f}）"
                  f" 字数 {entry['chars']} 错误变体 {bad_n}"
                  + (f" CER {entry['cer']:.4f}" if "cer" in entry else ""))
    return results


def render_markdown(results: dict) -> str:
    meta = results["meta"]
    res = results["results"]
    lines = [
        f"# ASR A/B 评测（{meta['time']}）",
        "",
        f"- 音频：{len(meta['audios'])} 段，共 {meta['total_seconds']:.0f}s"
        + (f"（各截前 {meta['limit_seconds']}s）" if meta["limit_seconds"] else ""),
        f"- 热词：{meta['hotwords_file']}（{meta['hotwords_count']} 条）",
        f"- 配置：{', '.join(f'{k} {CONFIGS[k].label}' for k in meta['configs'])}",
        "",
        "## 总览",
        "",
        "| 配置 | 错误变体↓ | 规范术语命中↑ | 总字数 | ASR耗时 | RTF | CER均值 |",
        "|---|---|---|---|---|---|---|",
    ]
    summary = {}
    for k in meta["configs"]:
        cfg_res = res[k]
        bad = sum(sum(e["bad_variants"].values()) for e in cfg_res.values())
        canon = sum(sum(e["canon_hits"].values()) for e in cfg_res.values())
        chars = sum(e["chars"] for e in cfg_res.values())
        elapsed = sum(e["elapsed"] for e in cfg_res.values())
        rtf = elapsed / max(meta["total_seconds"], 1e-9)
        cers = [e["cer"] for e in cfg_res.values() if "cer" in e]
        cer_s = f"{sum(cers) / len(cers):.4f}" if cers else "-"
        summary[k] = (bad, canon)
        lines.append(f"| {k} {CONFIGS[k].label} | {bad} | {canon} | {chars} "
                     f"| {elapsed:.0f}s | {rtf:.3f} | {cer_s} |")

    lines += ["", "## 错误变体明细（词 × 配置）", "",
              "| 变体 | " + " | ".join(meta["configs"]) + " |",
              "|---" * (len(meta["configs"]) + 1) + "|"]
    for term in ERROR_VARIANTS:
        row = [str(sum(res[k][n]["bad_variants"].get(term, 0) for n in res[k]))
               for k in meta["configs"]]
        if any(int(v) for v in row):
            lines.append(f"| {term} | " + " | ".join(row) + " |")

    lines += ["", "## 规范术语命中明细（词 × 配置）", "",
              "| 术语 | " + " | ".join(meta["configs"]) + " |",
              "|---" * (len(meta["configs"]) + 1) + "|"]
    for term in CANON_TERMS:
        row = [str(sum(res[k][n]["canon_hits"].get(term, 0) for n in res[k]))
               for k in meta["configs"]]
        lines.append(f"| {term} | " + " | ".join(row) + " |")

    lines += ["", "## 错误变体命中上下文抽样（人工复核误报）", ""]
    for k in meta["configs"]:
        for n, e in res[k].items():
            for term in e["bad_variants"]:
                for ctx in find_contexts(e["text"], term)[:2]:
                    lines.append(f"- [{k}] {term}: …{ctx}…")

    if "A" in summary and "C" in summary:
        a_bad, a_canon = summary["A"]
        c_bad, c_canon = summary["C"]
        lines += ["", "## 结论", ""]
        if a_bad:
            lines.append(f"- C 相对 A 错误变体：{a_bad} → {c_bad}"
                         f"（{(a_bad - c_bad) / a_bad * 100:+.0f}% 减少）")
        lines.append(f"- C 相对 A 规范术语命中：{a_canon} → {c_canon}（{c_canon - a_canon:+d}）")
        lines.append("- 判定标准：C 错误变体较 A 下降 >50% 且规范命中上升 → 采纳 C 为默认；"
                     "C 劣于 B → 裁剪热词表重跑。")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="ASR 级 A/B 评测")
    p.add_argument("--configs", default="A,B,C", help="评测配置（A/B/C/D，逗号分隔）")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--data-dir", default="data/0911-案例")
    p.add_argument("--hotwords", default="hotwords/精选热词.txt")
    p.add_argument("--pp-map", default="hotwords/纠错映射.txt")
    p.add_argument("--ref-dir", default=None, help="参考文本目录（<wav同名>.txt，可选 CER）")
    p.add_argument("--limit-seconds", type=int, default=None, help="每段音频只取前 N 秒（快速预览）")
    p.add_argument("--out-dir", default="eval_out")
    args = p.parse_args()

    results = run_all(args)
    md = render_markdown(results)
    print("\n" + md)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (out_dir / f"asr_ab_{stamp}.md").write_text(md, encoding="utf-8")
    (out_dir / f"asr_ab_{stamp}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"报告已保存: {out_dir}/asr_ab_{stamp}.md / .json")


if __name__ == "__main__":
    main()

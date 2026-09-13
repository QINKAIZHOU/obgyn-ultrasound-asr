"""从 hotwords/解析结果/*.txt（TSV：词条\t拼音）构建 SeACo-Paraformer 精选热词表。

三层筛选（总量默认 ≤1000 条）：
  Tier 0  核心术语：与 llm.py SYSTEM_PROMPT 术语库严格对齐（内置常量，排序最前）
  Tier 1  专科全量：超声/妇产科病理词库，按源序去重全收
  Tier 2  大库筛选：解剖学/医学词汇大全等按词根打分排序，受每源上限约束填满预算

过滤规则：只收纯中文 2-8 字（seg_dict 对含字母/连字符词打 <unk>，白占槽位；
单字词偏置噪声大；超长短语命中率低）。BI-RADS/TI-RADS 等交给 LLM 层纠错。

用法:
  .venv/Scripts/python build_hotwords.py [--max-total 1000] [--out hotwords/精选热词.txt]
      [--check-chars] [--emit-postprocess-map]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "hotwords" / "解析结果"
DEFAULT_OUT = PROJECT_ROOT / "hotwords" / "精选热词.txt"
DEFAULT_MAP_OUT = PROJECT_ROOT / "hotwords" / "纠错映射.txt"

# 只收纯中文 2-8 字
WORD_RE = re.compile(r"^[一-龥]{2,8}$")

# ---- Tier 0：核心术语（抄录自 llm.py SYSTEM_PROMPT 的规范词，与 LLM 纠错表/评测指标对齐）----
CORE_TERMS = [
    # 妇科
    "子宫", "子宫内膜", "宫颈", "卵巢", "肌瘤", "囊肿", "畸胎瘤", "子宫腺肌症",
    "多囊卵巢", "卵泡", "黄体", "输卵管", "盆腔积液", "液性暗区", "子宫肌瘤",
    "附件", "附件区", "子宫前位", "子宫后位", "肌层回声均匀",
    # 产科
    "孕囊", "胎心", "胎芽", "胎盘", "羊水", "双顶径", "股骨长", "肱骨长",
    "头围", "腹围", "脐血流", "羊水指数", "胎盘成熟度", "前置胎盘", "孕周",
    "胎心搏动", "脐动脉", "胎儿",
    # 乳腺
    "结节", "肿块", "钙化", "导管扩张", "边界清晰", "边界不清", "形态规则",
    "形态不规则", "纵横比", "血流信号", "弹性成像", "腋窝淋巴结", "乳腺结节",
    "低回声结节", "乳房", "腺体",
    # 通用超声术语
    "低回声", "强回声", "无回声", "混合性回声", "肾盂分离", "胆囊息肉",
    "结石", "脂肪肝", "甲状腺结节", "回声均匀", "回声不均", "光点",
    "盆腔", "腹腔", "游离液体", "占位", "占位性病变",
]

# ---- Tier 1：专科核心词库（全量收录，按此源序）----
TIER1_SOURCES = [
    "最全超声医学.txt",
    "超声医学.txt",
    "超声素语.txt",
    "妇产科病理学.txt",
]

# ---- Tier 2：大库按词根打分筛选（文件名, 每源入选上限）----
TIER2_SOURCES = [
    ("人体解剖学名词【官方推荐】.txt", 150),
    ("医学词汇大全【官方推荐】.txt", 150),
    ("医生常用词汇.txt", 100),
    ("肿瘤形态学编码词库1.txt", 80),
    ("ICD-10疾病编码1.txt", 80),
]

# 词根打分：强相关 +3，弱相关 +1（命中多个累加）
STRONG_ROOTS = [
    "宫", "乳", "卵", "胎", "孕", "脐", "宫颈", "内膜", "盆腔", "结节",
    "囊肿", "畸胎", "回声", "钙化", "羊水", "胎盘", "双顶径", "股骨",
    "乳腺", "输卵管",
]
WEAK_ROOTS = ["腺", "瘤", "腹", "淋巴", "超声", "血流", "导管", "肾", "肝", "胆", "胸", "窝", "管"]

# ---- 文本级纠错映射（保守原则；配合 funasr postprocess_hotword_file，默认不启用）----
# 有意排除「其血流=>脐血流」：盲替换会破坏合法报告语「及其血流」，上下文相关纠错留给 Qwen。
POSTPROCESS_PAIRS = [
    ("子工", "子宫"), ("内幕", "内膜"), ("内模", "内膜"), ("宫井", "宫颈"),
    ("乱巢", "卵巢"), ("机留", "肌瘤"), ("肌留", "肌瘤"), ("囊种", "囊肿"),
    ("几胎留", "畸胎瘤"), ("叶性暗区", "液性暗区"), ("韵囊", "孕囊"),
    ("太心", "胎心"), ("太芽", "胎芽"), ("太盘", "胎盘"), ("杨水", "羊水"),
    ("双顶颈", "双顶径"), ("骨股长", "股骨长"), ("节节", "结节"),
    ("盖化", "钙化"), ("流血信号", "血流信号"), ("夜窝淋巴结", "腋窝淋巴结"),
]


def read_tsv_words(path: Path) -> list[str]:
    """读取 TSV 词库第一列（跳过表头行）。"""
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("词条"):
            continue
        w = line.split("\t")[0].strip()
        if w:
            words.append(w)
    return words


def valid(w: str) -> bool:
    return bool(WORD_RE.match(w))


def domain_score(w: str) -> int:
    return sum(3 for r in STRONG_ROOTS if r in w) + sum(1 for r in WEAK_ROOTS if r in w)


def dedupe(seq: list[str], seen: set[str]) -> list[str]:
    """保序去重（首次出现的 tier 生效），就地更新 seen。"""
    out = []
    for w in seq:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def load_seg_dict_keys() -> set[str] | None:
    """从 ModelScope 缓存加载 seg_dict 键集合（用于 --check-chars 校验字符可 tokenize）。"""
    cache = Path.home() / ".cache" / "modelscope" / "hub"
    candidates = list(cache.glob("**/seg_dict"))
    if not candidates:
        return None
    keys = set()
    for p in candidates:
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts:
                keys.add(parts[0])
    return keys or None


def check_chars(words: list[str], seg_keys: set[str]) -> tuple[list[str], list[str]]:
    """剔除含 <unk> 字符（不在 seg_dict 中）的热词。"""
    kept, dropped = [], []
    for w in words:
        (kept if all(ch in seg_keys for ch in w) else dropped).append(w)
    return kept, dropped


def build(max_total: int, do_check_chars: bool) -> tuple[list[tuple[str, str]], dict]:
    """返回 [(word, tier_label)] 与统计信息。"""
    stats: dict = {"tier0": 0, "tier1": {}, "tier2": {}, "filtered_invalid": 0, "dropped_unk": 0}
    selected: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Tier 0
    t0 = dedupe([w for w in CORE_TERMS if valid(w)], seen)
    selected += [(w, "T0核心") for w in t0]
    stats["tier0"] = len(t0)

    # Tier 1：专科词库全量
    for name in TIER1_SOURCES:
        path = SRC_DIR / name
        if not path.exists():
            print(f"警告: 缺少源文件 {path}")
            continue
        raw = read_tsv_words(path)
        good = dedupe([w for w in raw if valid(w)], seen)
        stats["filtered_invalid"] += sum(1 for w in raw if not valid(w))
        stats["tier1"][name] = (len(raw), len(good))
        selected += [(w, "T1专科") for w in good]

    # Tier 2：大库打分筛选，填满剩余预算
    budget = max_total - len(selected)
    for name, cap in TIER2_SOURCES:
        if budget <= 0:
            break
        path = SRC_DIR / name
        if not path.exists():
            print(f"警告: 缺少源文件 {path}")
            continue
        raw = read_tsv_words(path)
        pool = dedupe([w for w in raw if valid(w) and w not in seen], seen)
        stats["filtered_invalid"] += sum(1 for w in raw if not valid(w))
        scored = [w for w in pool if domain_score(w) >= 1]
        scored.sort(key=lambda w: (-domain_score(w), w))
        picked = scored[: min(cap, budget)]
        stats["tier2"][name] = (len(raw), len(pool), len(picked))
        budget -= len(picked)
        selected += [(w, "T2大库") for w in picked]

    # 可选：seg_dict 字符校验（剔除含 <unk> 字符的词）
    if do_check_chars:
        seg_keys = load_seg_dict_keys()
        if seg_keys is None:
            print("警告: 未找到 seg_dict（模型未下载？），跳过字符校验")
        else:
            kept, dropped = [], []
            for w, tier in selected:
                (kept if all(ch in seg_keys for ch in w) else dropped).append((w, tier))
            selected = kept
            stats["dropped_unk"] = len(dropped)
            if dropped:
                print(f"字符校验剔除 {len(dropped)} 条（含词表外字符）: {'、'.join(w for w, _ in dropped[:20])}"
                      + ("…" if len(dropped) > 20 else ""))

    return selected, stats


def write_out(selected: list[tuple[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SeACo-Paraformer 精选热词表（build_hotwords.py 自动生成，勿手改）",
        "# 每行一词；# 开头为注释；由 pipeline.load_hotwords 以 UTF-8 读入",
    ]
    cur_tier = None
    tier_names = {"T0核心": "Tier 0 核心术语", "T1专科": "Tier 1 超声/妇产科专科", "T2大库": "Tier 2 大库筛选"}
    for w, tier in selected:
        if tier != cur_tier:
            lines.append(f"# ---- {tier_names[tier]} ----")
            cur_tier = tier
        lines.append(w)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def emit_postprocess_map(out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 文本级纠错映射（funasr postprocess_hotword_file 格式：错误词=>目标词）",
        "# 保守原则：仅收录无歧义的同音错字；上下文相关纠错（如「及其血流」）留给 Qwen。",
    ]
    lines += [f"{bad}=>{good}" for bad, good in POSTPROCESS_PAIRS]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"纠错映射已写入: {out_path}（{len(POSTPROCESS_PAIRS)} 对）")


def main() -> None:
    p = argparse.ArgumentParser(description="构建 SeACo 精选热词表")
    p.add_argument("--max-total", type=int, default=1000, help="热词总量上限（默认 1000）")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="输出热词表路径")
    p.add_argument("--check-chars", action="store_true", help="用本地 seg_dict 校验字符可 tokenize")
    p.add_argument("--emit-postprocess-map", action="store_true", help="同时生成 纠错映射.txt")
    args = p.parse_args()

    selected, stats = build(args.max_total, args.check_chars)
    out_path = Path(args.out)
    write_out(selected, out_path)

    print(f"\n===== 统计 =====")
    print(f"Tier 0 核心术语: {stats['tier0']} 条")
    for name, (raw, good) in stats["tier1"].items():
        print(f"Tier 1 {name}: 读取 {raw}，有效新增 {good}")
    for name, (raw, pool, picked) in stats["tier2"].items():
        print(f"Tier 2 {name}: 读取 {raw}，去重候选 {pool}，入选 {picked}")
    print(f"过滤（非纯中文2-8字/重复）: {stats['filtered_invalid']} 条")
    if stats["dropped_unk"]:
        print(f"字符校验剔除: {stats['dropped_unk']} 条")
    print(f"总计: {len(selected)} 条 → {out_path}")

    if args.emit_postprocess_map:
        emit_postprocess_map(DEFAULT_MAP_OUT)


if __name__ == "__main__":
    main()

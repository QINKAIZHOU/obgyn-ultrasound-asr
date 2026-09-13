"""金标准报告对比评测：本项目全链路（SeACo热词+三级LLM）vs 其他模型（xls 内基线）。

数据源: data/0911-案例/*.xls —— 医院系统导出，列含：
  检查所见 + 检查结论（医生签发终稿，金标准）
  语音识别（其他模型 ASR 转写）/ 语音生成报告（其他模型生成报告）
检查时间列（如 2026-07-20 14:59:27）与 wav 文件名一一对应。

指标（金标准为参照，本项目 vs 基线相对比较）：
  报告CER↓ / 测量值还原率↑ / 幻觉数值↓ / 关键项覆盖↑ / 结论覆盖↑ / ASR错误变体↓

依赖: xlrd（pip install xlrd）
用法: .venv/Scripts/python eval_report.py [--xls 路径] [--data-dir data/0911-案例]
          [--device cuda:0] [--hotwords hotwords/精选热词.txt] [--no-hotwords]
          [--self-check] [--out-dir eval_out]
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from eval_asr import CANON_TERMS, ERROR_VARIANTS, levenshtein
from pipeline import DEFAULT_HOTWORDS_FILE, load_asr_pipeline

DEFAULT_XLS = "data/0911-案例/0720 LIMENG 查询结果-按检查时间排序 - 案例.xls"

# 结论区关键诊断词（CANON_TERMS + 结论高频词，去重）
CONCLUSION_TERMS = list(dict.fromkeys(
    CANON_TERMS + ["腺肌症", "囊块", "液稠", "多发", "宫腔", "来源"]
))

# 报告模板关键项（金标准结构化模板 → 生成报告应有对应内容）
KEY_ITEMS = [
    ("子宫位置", r"子宫位置|前位|后位|中位"),
    ("子宫大小", r"长径|子宫大小"),
    ("子宫形态", r"子宫形态|形态[：:]?"),
    ("子宫回声", r"子宫回声|回声不均匀|回声欠均匀|回声均匀"),
    ("内膜厚度", r"内膜厚"),
    ("宫内IUD", r"IUD|节育环"),
    ("宫颈长度", r"宫颈长度|宫颈长"),
    ("肌层病灶", r"中低回声|低回声|中等回声|弱回声"),
    ("卵巢/附件", r"卵巢|附件"),
    ("盆腔积液", r"盆腔积液|后陷凹|积液"),
    ("提示结论", r"提示|考虑|可能|符合"),
]

_PUNCT_STRIP = re.compile(
    r"[\s，。！？；：、,.;:!?…—·“”\"'‘’（）()《》【】\[\]{}×*~～\-—_#/\\]"
)
_DIM_SEP = re.compile(r"(?<=\d)\s*[×xX*＊]\s*(?=\d)")
_DIM_RE = re.compile(r"\d+(?:\.\d+)?(?:×\d+(?:\.\d+)?){1,2}\s*(?:mm|cm|MM|CM)?")
_SINGLE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|cm|MM|CM)")


@dataclass
class Case:
    exam_time: str
    item: str
    gt_findings: str
    gt_conclusion: str
    baseline_asr: str
    baseline_report: str
    wav: Path | None = None
    ours_asr: str = ""
    ours_report: str = ""
    metrics: dict = field(default_factory=dict)

    @property
    def gt(self) -> str:
        return (self.gt_findings + "\n" + self.gt_conclusion).strip()


# ---------- 文本归一化 ----------

def norm(text: str) -> str:
    """NFKC（全角→半角）+ 维度分隔符统一为 ×。"""
    t = unicodedata.normalize("NFKC", text or "")
    return _DIM_SEP.sub("×", t)


_SECTION_MARK = re.compile(r"【?(?:超声所见|超声提示|超声印象|检查所见|检查结论)】?")


def report_cer(ref: str, hyp: str) -> float:
    """归一化、去节标记与标点后的字符错误率（节标题是格式脚手架，不计入内容差异）。"""
    r = _PUNCT_STRIP.sub("", _SECTION_MARK.sub("", norm(ref)))
    h = _PUNCT_STRIP.sub("", _SECTION_MARK.sub("", norm(hyp)))
    return levenshtein(r, h) / max(len(r), 1)


# ---------- 测量值提取 ----------

def measurements(text: str) -> list[str]:
    """提取归一化测量值：多维 61×61×60（去单位）与单值 67mm；多维区间不再重复计单值。"""
    t = norm(text)
    out: list[str] = []
    masked = t
    for m in _DIM_RE.finditer(t):
        s = re.sub(r"\s*(mm|cm|MM|CM)$", "", m.group(0))
        out.append(s)
        masked = masked[: m.start()] + " " * (m.end() - m.start()) + masked[m.end() :]
    for m in _SINGLE_RE.finditer(masked):
        out.append(m.group(0).replace(" ", ""))
    return out


def measurement_recovery(gt: str, report: str) -> tuple[float, list[str], list[str]]:
    """返回 (还原率, 缺失测量值, 幻觉测量值)。"""
    gt_ms = measurements(gt)
    rp_ms = measurements(report)
    gt_set = set(gt_ms)
    rp_set = set(rp_ms)
    missing = [m for m in dict.fromkeys(gt_ms) if m not in rp_set]
    halluc = [m for m in dict.fromkeys(rp_ms) if m not in gt_set]
    hit = len(gt_set) - len(set(missing))
    return (hit / len(gt_set) if gt_set else 1.0), missing, halluc


# ---------- 结构覆盖 ----------

def split_sections(report: str) -> tuple[str, str]:
    """按 超声提示/检查结论 标记切出 (所见部分, 提示部分)。"""
    parts = re.split(r"【?超声提示】?|【?检查结论】?|【?超声印象】?", report or "")
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


def key_item_coverage(report: str) -> tuple[float, list[str]]:
    r = norm(report)
    missed = [name for name, pat in KEY_ITEMS if not re.search(pat, r)]
    return (len(KEY_ITEMS) - len(missed)) / len(KEY_ITEMS), missed


def conclusion_coverage(gt_conclusion: str, report: str) -> tuple[float, list[str]]:
    """金标准结论中的诊断词在生成报告"提示"节的出现比例。"""
    _, concl = split_sections(report)
    concl_n = norm(concl)
    terms = [t for t in CONCLUSION_TERMS if t in norm(gt_conclusion)]
    if not terms:
        return 1.0, []
    missed = [t for t in terms if t not in concl_n]
    return (len(terms) - len(missed)) / len(terms), missed


# ---------- xls 解析与 wav 匹配 ----------

def parse_xls(path: str) -> list[Case]:
    import xlrd

    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    header = {str(sh.cell_value(0, c)).strip(): c for c in range(sh.ncols)}
    required = ["检查时间", "检查所见", "检查结论", "语音识别", "语音生成报告"]
    missing = [k for k in required if k not in header]
    if missing:
        raise SystemExit(f"xls 缺少列: {missing}（实际表头: {list(header)}）")
    cases = []
    for r in range(1, sh.nrows):
        cases.append(Case(
            exam_time=str(sh.cell_value(r, header["检查时间"])).strip(),
            item=str(sh.cell_value(r, header.get("检查项目", 1))).strip(),
            gt_findings=str(sh.cell_value(r, header["检查所见"])).strip(),
            gt_conclusion=str(sh.cell_value(r, header["检查结论"])).strip(),
            baseline_asr=str(sh.cell_value(r, header["语音识别"])).strip(),
            baseline_report=str(sh.cell_value(r, header["语音生成报告"])).strip(),
        ))
    return cases


def match_wav(exam_time: str, data_dir: Path) -> Path | None:
    """检查时间 '2026-07-20 14:59:27' → '2026-07-20-14-59-27.wav'；失败则就近匹配。"""
    direct = data_dir / (exam_time.replace(" ", "-").replace(":", "-") + ".wav")
    if direct.exists():
        return direct
    try:
        t = datetime.strptime(exam_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    best, best_dt = None, None
    for p in sorted(data_dir.glob("*.wav")):
        try:
            pt = datetime.strptime(p.stem, "%Y-%m-%d-%H-%M-%S")
        except ValueError:
            continue
        dt = abs((pt - t).total_seconds())
        if best_dt is None or dt < best_dt:
            best, best_dt = p, dt
    return best if best_dt is not None and best_dt <= 600 else None


# ---------- 指标汇总 ----------

def compute_metrics(case: Case) -> dict:
    m: dict = {}
    m["cer_ours"] = round(report_cer(case.gt, case.ours_report), 4)
    m["cer_baseline"] = round(report_cer(case.gt, case.baseline_report), 4)

    rec_o, miss_o, hall_o = measurement_recovery(case.gt, case.ours_report)
    rec_b, miss_b, hall_b = measurement_recovery(case.gt, case.baseline_report)
    m["meas_recovery_ours"] = round(rec_o, 3)
    m["meas_recovery_baseline"] = round(rec_b, 3)
    m["meas_missing_ours"] = miss_o
    m["meas_missing_baseline"] = miss_b
    m["halluc_ours"] = hall_o
    m["halluc_baseline"] = hall_b

    cov_o, missed_o = key_item_coverage(case.ours_report)
    cov_b, missed_b = key_item_coverage(case.baseline_report)
    m["key_items_ours"] = round(cov_o, 3)
    m["key_items_baseline"] = round(cov_b, 3)
    m["key_items_missed_ours"] = missed_o
    m["key_items_missed_baseline"] = missed_b

    cc_o, cmiss_o = conclusion_coverage(case.gt_conclusion, case.ours_report)
    cc_b, cmiss_b = conclusion_coverage(case.gt_conclusion, case.baseline_report)
    m["concl_ours"] = round(cc_o, 3)
    m["concl_baseline"] = round(cc_b, 3)
    m["concl_missed_ours"] = cmiss_o
    m["concl_missed_baseline"] = cmiss_b

    from eval_asr import count_hits
    m["asr_bad_ours"] = sum(count_hits(case.ours_asr, ERROR_VARIANTS).values())
    m["asr_bad_baseline"] = sum(count_hits(case.baseline_asr, ERROR_VARIANTS).values())
    m["asr_bad_detail_ours"] = count_hits(case.ours_asr, ERROR_VARIANTS)
    m["asr_bad_detail_baseline"] = count_hits(case.baseline_asr, ERROR_VARIANTS)
    m["asr_cross_cer"] = round(report_cer(case.baseline_asr, case.ours_asr), 4)
    return m


def render_markdown(cases: list[Case], meta: dict) -> str:
    lines = [
        f"# 金标准报告对比评测（{meta['time']}）",
        "",
        f"- 金标准：xls「检查所见+检查结论」（医生签发终稿）；基线：xls「语音生成报告」（其他模型）",
        f"- 本项目：SeACo-Paraformer{'+' + str(meta['hotwords_count']) + '条热词' if meta['hotwords_count'] else '无热词'} + Qwen 三级优化（生产默认配置）",
        f"- 案例数：{len(cases)}；CER 为相对比较（金标准是终稿措辞，与口述存在合理差异）",
        "",
        "## 汇总",
        "",
        "| 案例 | 报告CER 本项目/基线↓ | 测量值还原 本项目/基线↑ | 幻觉数值 本项目/基线↓ | 关键项覆盖 本项目/基线↑ | 结论覆盖 本项目/基线↑ | ASR错误变体 本项目/基线↓ |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in cases:
        m = c.metrics
        lines.append(
            f"| {c.exam_time} | {m['cer_ours']:.3f} / {m['cer_baseline']:.3f} "
            f"| {m['meas_recovery_ours']:.0%} / {m['meas_recovery_baseline']:.0%} "
            f"| {len(m['halluc_ours'])} / {len(m['halluc_baseline'])} "
            f"| {m['key_items_ours']:.0%} / {m['key_items_baseline']:.0%} "
            f"| {m['concl_ours']:.0%} / {m['concl_baseline']:.0%} "
            f"| {m['asr_bad_ours']} / {m['asr_bad_baseline']} |"
        )
    n = max(len(cases), 1)
    avg = lambda k: sum(c.metrics[k] for c in cases) / n
    lines += [
        f"| **均值** | **{avg('cer_ours'):.3f} / {avg('cer_baseline'):.3f}** "
        f"| **{avg('meas_recovery_ours'):.0%} / {avg('meas_recovery_baseline'):.0%}** "
        f"| — | — | — | — |",
        "",
    ]
    for i, c in enumerate(cases, 1):
        m = c.metrics
        lines += [
            f"## 案例 {i}：{c.exam_time}（{c.item}）",
            "",
            f"音频：`{c.wav.name if c.wav else '未匹配'}`",
            "",
            "### 金标准（检查所见+结论）",
            "",
            c.gt.replace("\n", "\n") or "（空）",
            "",
            "### 基线报告（其他模型语音生成报告）",
            "",
            c.baseline_report or "（空）",
            "",
            "### 本项目报告（整体梳理输出）",
            "",
            c.ours_report or "（空——增强级未提取到报告内容）",
            "",
            "### 指标",
            "",
            f"- 报告 CER：本项目 {m['cer_ours']:.3f} vs 基线 {m['cer_baseline']:.3f}",
            f"- 测量值还原：本项目 {m['meas_recovery_ours']:.0%}（缺 {m['meas_missing_ours'] or '无'}）"
            f" vs 基线 {m['meas_recovery_baseline']:.0%}（缺 {m['meas_missing_baseline'] or '无'}）",
            f"- 幻觉数值：本项目 {m['halluc_ours'] or '无'} vs 基线 {m['halluc_baseline'] or '无'}",
            f"- 关键项缺失：本项目 {m['key_items_missed_ours'] or '无'} vs 基线 {m['key_items_missed_baseline'] or '无'}",
            f"- 结论词缺失（提示节）：本项目 {m['concl_missed_ours'] or '无'} vs 基线 {m['concl_missed_baseline'] or '无'}",
            f"- ASR 错误变体：本项目 {m['asr_bad_ours']} {m['asr_bad_detail_ours']} vs 基线 {m['asr_bad_baseline']} {m['asr_bad_detail_baseline']}",
            f"- 两侧 ASR 互异 CER：{m['asr_cross_cer']:.3f}",
            "",
        ]
    return "\n".join(lines) + "\n"


def self_check() -> None:
    """指标 sanity：金标准 vs 自身应 CER=0、还原率=100%、覆盖=100%。

    自检时把金标准包装成真实输出的两段式结构（CER 计算不受标记影响）。
    """
    cases = parse_xls(DEFAULT_XLS)
    c = cases[0]
    wrapped = f"【超声所见】\n{c.gt_findings}\n【超声提示】\n{c.gt_conclusion}"
    c.ours_report, c.ours_asr = wrapped, ""
    c.baseline_report, c.baseline_asr = wrapped, ""
    m = compute_metrics(c)
    assert m["cer_ours"] == 0 and m["cer_baseline"] == 0, m
    assert m["meas_recovery_ours"] == 1.0 and not m["halluc_ours"], m
    assert m["key_items_ours"] == 1.0 and m["concl_ours"] == 1.0, m
    print("self-check 通过：CER=0，测量值还原=100%，关键项/结论覆盖=100%")
    print(f"案例1金标准测量值: {measurements(c.gt)}")


def main() -> None:
    p = argparse.ArgumentParser(description="金标准报告对比评测")
    p.add_argument("--xls", default=DEFAULT_XLS)
    p.add_argument("--data-dir", default="data/0911-案例")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--hotwords", default=DEFAULT_HOTWORDS_FILE)
    p.add_argument("--no-hotwords", action="store_true")
    p.add_argument("--self-check", action="store_true", help="只跑指标 sanity 检查")
    p.add_argument("--out-dir", default="eval_out")
    args = p.parse_args()

    if args.self_check:
        self_check()
        return

    cases = parse_xls(args.xls)
    data_dir = Path(args.data_dir)
    print(f"解析 xls：{len(cases)} 条记录")
    todo = []
    for c in cases:
        c.wav = match_wav(c.exam_time, data_dir)
        print(f"  {c.exam_time}（{c.item}）→ {c.wav.name if c.wav else '!! 未匹配 wav'}")
        if c.wav:
            todo.append(c)
    if not todo:
        raise SystemExit("没有匹配到任何 wav")

    # 本项目全链路（生产默认配置：SeACo+热词+三级 LLM）
    from llm import UltrasoundOptimizer
    from modes import process_file, resolve_engine

    ns_engine = SimpleNamespace(
        device=args.device, hotwords=args.hotwords,
        no_hotwords=args.no_hotwords, legacy_asr=False,
    )
    model_id, hotword = resolve_engine(ns_engine)
    model = load_asr_pipeline(args.device, model_id)
    optimizer = UltrasoundOptimizer()

    for c in todo:
        print(f"\n===== 本项目全链路: {c.wav.name} =====")
        ns = SimpleNamespace(
            audio=str(c.wav), srt=None, report=None,
            no_llm=False, no_enhance=False, postprocess_hotwords=None,
        )
        result = process_file(ns, model, optimizer, hotword)
        if result is None:
            print("未识别到语音，跳过")
            continue
        c.ours_asr = result["asr_text"]
        c.ours_report = result["final_report"]

    for c in cases:
        if c.wav:
            c.metrics = compute_metrics(c)

    done = [c for c in cases if c.metrics]
    meta = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "xls": args.xls,
        "hotwords_count": (hotword.count(" ") + 1) if hotword else 0,
        "device": args.device,
    }
    md = render_markdown(done, meta)
    print("\n" + md)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (out_dir / f"report_eval_{stamp}.md").write_text(md, encoding="utf-8")
    payload = {
        "meta": meta,
        "cases": [{**{k: (str(v) if k == "wav" else v) for k, v in c.__dict__.items()}}
                  for c in done],
    }
    (out_dir / f"report_eval_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"报告已保存: {out_dir}/report_eval_{stamp}.md / .json")


if __name__ == "__main__":
    main()

"""分步演示数据采集：离线跑一遍真实 pipeline，把各步中间产物落盘为演示数据。

复用 modes.process_file（monkeypatch modes.emit_all 捕获逐句三级：原文/优化/增强），
金标准与基线取自 eval_out 已有报告评测 JSON（按 wav 文件名匹配案例），
指标用 eval_report.compute_metrics 以本次采集结果重算（口径与评测完全一致）。

产出:
  demo_data/case_<音频名>.json   演示数据（自校验的对象，可 git 提交）
  demo/demo_data.js             同数据的 window.DEMO_DATA 形式（demo.html 引用）

演示页 demo/demo.html 纯离线读该数据分步播放，不再调用 ASR/LLM。

用法:
  .venv/Scripts/python collect_demo.py data/0911-案例/2026-07-20-15-12-39.wav
      [--eval-json eval_out/report_eval_20260913_203643.json] [--device cuda:0]
      [--hotwords hotwords/精选热词.txt] [--no-hotwords] [--no-llm]
      [--out-dir demo_data] [--demo-dir demo] [--self-check]
"""
from __future__ import annotations

import argparse
import json
import re
import wave
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from eval_report import Case, compute_metrics
from llm import LLM_MODEL_ID, is_non_report
from pipeline import ASR_MODEL_ID, DEFAULT_HOTWORDS_FILE, load_asr_pipeline

SCHEMA_VERSION = 2
DEFAULT_EVAL_JSON = "eval_out/report_eval_20260913_203643.json"
DEFAULT_MAP_FILE = "hotwords/纠错映射.txt"

# 报告模板骨架（步骤 8 展示用，按医院妇科超声报告模板格式逐行列出）
TEMPLATE_NAME = "妇科常规彩色超声（经阴道）"
TEMPLATE_SKELETON = [
    "【子宫】【经阴道】",
    "子宫位置：",
    "子宫形态：",
    "【附件】",
    "右卵巢：",
    "左卵巢：",
    "【盆腔积液】：",
]

# 语音指令模糊命中（步骤 2 播放用；实际系统为专用指令词，此处仅示意）
# 「晕超」是本段录音中「阴超」的 ASR 误识，正好演示热词/LLM 纠错的价值
_COMMAND_RE = re.compile(r"阴超|晕超|经阴道|模板|常规")

# 展示层细分：按逗号把长句切成短句（同步识别观感更细腻；不影响识别结果本身）
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[，,])")


def load_golden(eval_json_path: str, wav_name: str) -> dict:
    """从评测 JSON 按 wav 文件名匹配案例，返回金标准与基线字段。"""
    path = Path(eval_json_path)
    if not path.exists():
        raise SystemExit(f"评测 JSON 不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for c in data.get("cases", []):
        if Path(c.get("wav", "")).name == wav_name:
            return {
                "exam_time": c["exam_time"],
                "item": c["item"],
                "gt_findings": c["gt_findings"],
                "gt_conclusion": c["gt_conclusion"],
                "baseline_asr": c["baseline_asr"],
                "baseline_report": c["baseline_report"],
                "ours_asr_ref": c["ours_asr"],
                "metrics_ref": c.get("metrics", {}),
            }
    raise SystemExit(f"评测 JSON 中未找到 wav 为 {wav_name} 的案例")


def refresh_timestamps(audio: Path, args, cache: dict) -> list:
    """重跑一次 ASR 取 token 级时间戳（不跑 LLM），写入缓存。

    同配置下 ASR 文本必须与缓存逐字一致，否则拒绝混用时间戳。
    """
    from modes import resolve_engine

    ns_engine = SimpleNamespace(
        device=args.device, hotwords=args.hotwords,
        no_hotwords=args.no_hotwords, legacy_asr=False,
    )
    model_id, hotword = resolve_engine(ns_engine)
    model = load_asr_pipeline(args.device, model_id)
    gen_kwargs = {"hotword": hotword} if hotword else {}
    res = model.generate(input=str(audio), batch_size_s=300, disable_pbar=True, **gen_kwargs)
    text = (res[0].get("text") or "").strip() if res else ""
    if text != cache["result"]["asr_text"]:
        raise SystemExit("重跑 ASR 文本与缓存不一致（检查热词/device 参数是否同构），拒绝混用时间戳")
    ts = res[0].get("timestamp") or []
    print(f"token 时间戳已获取：{len(ts)} 个")
    return ts


def capture_sentences(args: SimpleNamespace, model, optimizer, hotword: str | None, cache_path: Path):
    """monkeypatch modes.emit_all 后复用 process_file，捕获逐句三级结果与 token 时间戳。

    返回 (process_file 结果 dict, 逐句列表, token 时间戳)。
    首次跑完把原始产物写入 cache_path，之后直接读缓存，不再加载模型。
    """
    import json as _json

    if cache_path.exists():
        c = _json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"已使用缓存: {cache_path}（删除该文件或 --refresh-timestamps 可重跑）")
        return c["result"], c["captured"], c["timestamps"]

    import modes

    captured: list[dict] = []
    orig = modes.emit_all

    def _spy(beg_ms: float, text: str, opt, do_enhance: bool = True):
        optimized, enhanced = orig(beg_ms, text, opt, do_enhance)
        captured.append({
            "beg_ms": beg_ms,
            "raw": text,
            "optimized": optimized or text,
            "enhanced": enhanced,
        })
        return optimized, enhanced

    # process_file 丢弃 timestamp，包一层 generate 原样带出
    orig_gen = model.generate
    holder: dict = {}

    def _gen(input, **kw):
        res = orig_gen(input, **kw)
        holder["res"] = res
        return res

    model.generate = _gen
    modes.emit_all = _spy
    try:
        result = modes.process_file(args, model, optimizer, hotword)
    finally:
        modes.emit_all = orig
        model.generate = orig_gen
    if result is None:
        raise SystemExit("未识别到语音，采集失败")
    timestamps = (holder["res"][0].get("timestamp") or []) if holder.get("res") else []
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(_json.dumps(
        {"result": result, "captured": captured, "timestamps": timestamps},
        ensure_ascii=False), encoding="utf-8")
    print(f"原始产物已缓存: {cache_path}")
    return result, captured, timestamps


def read_word_list(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [
        w for ln in p.read_text(encoding="utf-8").splitlines()
        if (w := ln.strip()) and not w.startswith("#")
    ]


def read_map(path: str) -> list[tuple[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    pairs = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=>" not in ln:
            continue
        wrong, right = ln.split("=>", 1)
        pairs.append((wrong.strip(), right.strip()))
    return pairs


def collect_stats(asr_text: str, hotwords_file: str, map_file: str) -> tuple[list[dict], list[dict]]:
    """热词命中与纠错映射命中统计（在 ASR 原文上计数，供步骤 5/6 展示）。"""
    hits = sorted(
        ({"word": w, "count": asr_text.count(w)} for w in read_word_list(hotwords_file)),
        key=lambda x: -x["count"],
    )
    hits = [h for h in hits if h["count"] > 0]
    map_hits = sorted(
        ({"wrong": w, "right": r, "count": asr_text.count(w)} for w, r in read_map(map_file)),
        key=lambda x: -x["count"],
    )
    map_hits = [h for h in map_hits if h["count"] > 0]
    return hits, map_hits


def _split_clauses(text: str) -> list[str]:
    """按逗号把句子切成带标点的短句片段。"""
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


def clause_diff(raw: str, optimized: str) -> list[dict]:
    """被纠正片段的字级 diff：[{a: 原片段, b: 新片段}]（删除/插入缺省一侧）。"""
    import difflib

    sm = difflib.SequenceMatcher(a=raw, b=optimized, autojunk=False)
    out = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            continue
        d = {}
        if a1 < a2:
            d["a"] = raw[a1:a2]
        if b1 < b2:
            d["b"] = optimized[b1:b2]
        out.append(d)
    return out


def build_sentences(result: dict, captured: list[dict], timestamps: list) -> tuple[list[dict], list[dict]]:
    """合并 process_file 结果与捕获的逐句三级。

    返回 (逐短句列表 sentences, 逐句级 report_items)：
      sentences  — 步骤 4/6 用的细分短句 {i, si, t0, t1, raw, optimized}，
                   时间轴用 token 级时间戳按非标点字符计数精确对齐（复用 modes.sentence_spans）
      report_items — 步骤 7 用的句级 {i, t0, optimized, enhanced, is_report}
    """
    from modes import sentence_spans

    if len(captured) != len(result["sentences"]):
        raise SystemExit(f"逐句捕获数 {len(captured)} 与分句数 {len(result['sentences'])} 不一致")

    # 展平全部短句（片段拼接==原句，字符计数指针跨句连续），一次对齐到 token 时间戳
    flat: list[tuple[int, str, str]] = []  # (句级索引, 原文片段, 优化片段)
    for si, cap in enumerate(captured):
        raw_cl = _split_clauses(cap["raw"])
        opt_cl = _split_clauses(cap["optimized"])
        # 优化级可能微调标点导致片段数不一致时，保持整句不细分
        if len(raw_cl) != len(opt_cl) or len(raw_cl) <= 1:
            raw_cl, opt_cl = [cap["raw"]], [cap["optimized"]]
        flat.extend((si, rc, oc) for rc, oc in zip(raw_cl, opt_cl))

    if timestamps:
        spans = sentence_spans([f[1] for f in flat], timestamps)
    else:
        spans = [None] * len(flat)

    sentences: list[dict] = []
    for i, ((si, rc, oc), sp) in enumerate(zip(flat, spans)):
        if sp:
            t0, t1 = round(sp[0], 1), round(sp[1], 1)
        else:  # 无时间戳兜底：落到句级起始时刻
            t0, t1 = round(captured[si]["beg_ms"], 1), None
        sentences.append({"i": i, "si": si, "t0": t0, "t1": t1, "raw": rc, "optimized": oc,
                          **({"diff": clause_diff(rc, oc)} if rc != oc else {})})

    report_items = [{
        "i": si, "t0": round(cap["beg_ms"], 1),
        "optimized": cap["optimized"], "enhanced": cap["enhanced"],
        "is_report": bool(cap["enhanced"]) and not is_non_report(cap["enhanced"]),
    } for si, cap in enumerate(captured)]
    return sentences, report_items


def find_command_sentence(captured: list[dict], spans) -> dict | None:
    """在逐句原文里模糊搜语音指令相关词，返回首个命中句（步骤 2 播放引用）。"""
    for si, cap in enumerate(captured):
        if _COMMAND_RE.search(cap["raw"]):
            span = spans[si] if si < len(spans) else None
            return {
                "raw_snippet": cap["raw"],
                "t0": round(cap["beg_ms"], 1),
                "t1": round(span[1], 1) if span else None,
            }
    return None


def validate_payload(p: dict, with_llm: bool) -> None:
    """自校验：结构完整性 + 时间轴单调 + 交叉核对。失败 raise SystemExit。"""
    problems: list[str] = []
    warns: list[str] = []

    for key in ("schema_version", "meta", "sentences", "report_items", "hotwords",
                "corrections", "report", "golden", "metrics"):
        if key not in p:
            problems.append(f"缺少顶层键: {key}")
    sents = p.get("sentences", [])
    if not sents:
        problems.append("sentences 为空")
    last_t1 = -1.0
    for s in sents:
        for k in ("i", "si", "t0", "raw", "optimized"):
            if k not in s:
                problems.append(f"短句 {s.get('i')} 缺字段: {k}")
        if s.get("t1") is not None and s["t1"] < s["t0"]:
            problems.append(f"短句 {s['i']} 时间轴倒挂: t1 < t0")
        for d in s.get("diff", []):
            if not (d.get("a") or d.get("b")):
                problems.append(f"短句 {s['i']} diff 片段为空")
        if s.get("t1") is not None:
            if s["t1"] < last_t1:
                problems.append(f"短句 {s['i']} 时间轴非单调")
            last_t1 = s["t1"]
    if len({s["si"] for s in sents}) != len(p.get("report_items", [])):
        problems.append("report_items 数与短句所属句数不一致")
    if with_llm:
        final = p["report"]["final"]
        if not final:
            problems.append("report.final 为空")
        elif "超声所见" not in final:
            warns.append("report.final 不含「超声所见」节标记")
        for it in p.get("report_items", []):
            if it["is_report"] and (not it["enhanced"] or is_non_report(it["enhanced"])):
                problems.append(f"句 {it['i']} is_report 与增强文本矛盾")
        if sum(1 for it in p["report_items"] if it["is_report"]) != len(p["report"]["lines"]):
            problems.append("is_report 句数与 report.lines 数不一致")
    if p["hotwords"].get("total", 0) <= 0:
        warns.append("热词库为空")
    if not p["hotwords"].get("hits"):
        warns.append("ASR 原文未命中任何热词")
    for d in p.get("diff", []):
        if d.get("op") not in ("=", "-", "+"):
            problems.append(f"diff 非法操作符: {d.get('op')}")
    for k in ("cer_ours", "meas_recovery_ours", "key_items_ours"):
        if k not in p.get("metrics", {}):
            problems.append(f"metrics 缺键: {k}")

    if warns:
        print("[WARN] " + "\n[WARN] ".join(warns))
    if problems:
        raise SystemExit("自校验失败:\n  " + "\n  ".join(problems))
    print(f"自校验通过：{len(sents)} 句，热词命中 {len(p['hotwords']['hits'])}，"
          f"纠错映射命中 {len(p['corrections'])}，diff 段 {len(p.get('diff', []))}")


def build_diff(gt_text: str, ours: str) -> list[dict]:
    """difflib.SequenceMatcher 字符级 opcodes → [{op: =/-/+, text}]（金标准→本项目）。"""
    import difflib

    sm = difflib.SequenceMatcher(a=gt_text, b=ours, autojunk=False)
    out = []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            out.append({"op": "=", "text": gt_text[a1:a2]})
        elif op == "delete":
            out.append({"op": "-", "text": gt_text[a1:a2]})
        elif op == "insert":
            out.append({"op": "+", "text": ours[b1:b2]})
        else:  # replace
            if a1 < a2:
                out.append({"op": "-", "text": gt_text[a1:a2]})
            if b1 < b2:
                out.append({"op": "+", "text": ours[b1:b2]})
    return out


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return round(w.getnframes() / w.getframerate(), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="分步演示数据采集（离线跑真实 pipeline）")
    ap.add_argument("audio", nargs="?", default="data/0911-案例/2026-07-20-15-12-39.wav")
    ap.add_argument("--eval-json", default=DEFAULT_EVAL_JSON)
    ap.add_argument("--map", default=DEFAULT_MAP_FILE, help="纠错映射文件（命中统计用）")
    ap.add_argument("--hotwords", default=DEFAULT_HOTWORDS_FILE)
    ap.add_argument("--no-hotwords", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="只采集 ASR 级（不跑三级优化）")
    ap.add_argument("--refresh-timestamps", action="store_true",
                    help="缓存存在时也重跑一次 ASR（秒级）刷新 token 时间戳")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--out-dir", default="demo_data")
    ap.add_argument("--demo-dir", default="demo")
    ap.add_argument("--self-check", action="store_true", help="只校验已存在的 JSON，不加载模型")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        raise SystemExit(f"音频不存在: {audio}")
    out_dir = Path(args.out_dir)
    demo_dir = Path(args.demo_dir)
    out_json = out_dir / f"case_{audio.stem}.json"
    out_js = demo_dir / "demo_data.js"

    if args.self_check:
        if not out_json.exists():
            raise SystemExit(f"待校验 JSON 不存在: {out_json}（先运行采集）")
        p = json.loads(out_json.read_text(encoding="utf-8"))
        validate_payload(p, with_llm=bool(p["report"]["final"]))
        return

    golden = load_golden(args.eval_json, audio.name)
    duration = wav_duration(audio)
    print(f"案例: {golden['exam_time']}（{golden['item']}），音频 {duration}s")

    # ASR + 逐句三级（与 eval_report 同参复用 process_file）；命中缓存则不加载模型
    cache_path = out_dir / f"_cache_{audio.stem}.json"
    ns = SimpleNamespace(
        audio=str(audio), srt=None, report=None,
        no_llm=args.no_llm, no_enhance=False, postprocess_hotwords=None,
    )
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if args.refresh_timestamps or not cache.get("timestamps"):
            cache["timestamps"] = refresh_timestamps(audio, args, cache)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"时间戳已写回缓存: {cache_path}")
        result, captured, timestamps = cache["result"], cache["captured"], cache["timestamps"]
        hotword = None
    else:
        from llm import UltrasoundOptimizer
        from modes import resolve_engine

        ns_engine = SimpleNamespace(
            device=args.device, hotwords=args.hotwords,
            no_hotwords=args.no_hotwords, legacy_asr=False,
        )
        model_id, hotword = resolve_engine(ns_engine)
        model = load_asr_pipeline(args.device, model_id)
        optimizer = None if args.no_llm else UltrasoundOptimizer()
        result, captured, timestamps = capture_sentences(ns, model, optimizer, hotword, cache_path)
    sentences, report_items = build_sentences(result, captured, timestamps)

    # ASR 级与评测 JSON 交叉核对（同配置下应逐字一致）
    if result["asr_text"] != golden["ours_asr_ref"]:
        print("[WARN] 本次 ASR 文本与评测 JSON 的 ours_asr 不一致（检查热词/device 参数是否同构）")
    else:
        print("本次 ASR 文本与评测 JSON 一致")

    hotword_hits, map_hits = collect_stats(result["asr_text"], args.hotwords, args.map)
    gt_full = (golden["gt_findings"] + "\n" + golden["gt_conclusion"]).strip()
    final_report = result["final_report"]

    # 用本次采集结果重算指标（口径与 eval_report 完全一致）
    case = Case(
        exam_time=golden["exam_time"], item=golden["item"],
        gt_findings=golden["gt_findings"], gt_conclusion=golden["gt_conclusion"],
        baseline_asr=golden["baseline_asr"], baseline_report=golden["baseline_report"],
        wav=audio, ours_asr=result["asr_text"], ours_report=final_report,
    )
    metrics = compute_metrics(case)
    print(f"本次报告 CER={metrics['cer_ours']:.3f}（评测 JSON 参考 {golden['metrics_ref'].get('cer_ours', '—')}）")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "case_id": audio.stem,
            "audio_rel": f"../{audio.as_posix()}",
            "audio_file": audio.name,
            "duration_sec": duration,
            "exam_time": golden["exam_time"],
            "item": golden["item"],
            "template_name": TEMPLATE_NAME,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "asr_model": ASR_MODEL_ID,
            "llm_model": LLM_MODEL_ID if not args.no_llm else None,
            "hotwords_count": len(read_word_list(args.hotwords)),
            "device": args.device,
            "with_llm": not args.no_llm,
        },
        "template_skeleton": TEMPLATE_SKELETON,
        "sentences": sentences,
        "report_items": report_items,
        "voice_command": {
            "template_name": TEMPLATE_NAME,
            "asr_text": "插入妇科常规模板",
            "demo": True,
            **({"raw_snippet": h["raw_snippet"], "t0": h["t0"], "t1": h["t1"]}
               if (h := find_command_sentence(captured, result["spans"])) else {}),
        },
        "voiceprint": {
            "doctor": "李医生（妇产科）", "similarity": 0.96,
            "passed": True, "demo": True,
        },
        "emr": {
            "patient": "王**", "exam_no": "US-20260720-****",
            "history": "示意：既往子宫肌瘤病史（外院超声提示）",
            "images": "示意：已调阅本次经阴道超声影像",
            "demo": True,
        },
        "hotwords": {"total": len(read_word_list(args.hotwords)), "hits": hotword_hits},
        "corrections": map_hits,
        "report": {"lines": result["report_lines"], "final": final_report},
        "golden": {
            "findings": golden["gt_findings"],
            "conclusion": golden["gt_conclusion"],
            "baseline_asr": golden["baseline_asr"],
            "baseline_report": golden["baseline_report"],
        },
        "diff": build_diff(gt_full, final_report),
        "metrics": metrics,
    }
    validate_payload(payload, with_llm=not args.no_llm)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"演示数据已保存: {out_json}")

    demo_dir.mkdir(parents=True, exist_ok=True)
    out_js.write_text(
        "window.DEMO_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"演示页数据已保存: {out_js}（demo/demo.html 引用）")


if __name__ == "__main__":
    main()

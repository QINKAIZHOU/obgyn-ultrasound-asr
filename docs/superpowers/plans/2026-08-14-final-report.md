# 整体报告梳理（第三级 LLM 处理）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管线末端增加第三级 LLM 处理：会话结束时把全部增强后内容梳理为【超声所见】+【超声提示】两段式整体报告。

**Architecture:** llm.py 加 `FINAL_SYSTEM_PROMPT` + `finalize()`（复用现有 `_run`）；modes.py 的 run_file / run_realtime 收集报告行并在结束时调用 finalize；--report 文件内容改为整体报告。eval_terms.py 加 3 条整体梳理用例。

**Tech Stack:** 现有 .venv（Python 3.12）、Qwen3.5-9B（已缓存）。

**Spec:** `docs/superpowers/specs/2026-08-14-final-report-design.md`

**通用注意事项：**
- 所有 python 命令用 `.venv/Scripts/python`，cwd 为仓库根目录；打印中文前置 `PYTHONIOENCODING=utf-8`
- 模型加载约 1–2 分钟，eval 全量约 5–8 分钟，Bash 超时 600000ms
- 验证产物（*.srt、verify_*、日志）不入库，用后删除；不要覆盖用户现有的 out.srt / out2.srt / test/

---

### Task 1: llm.py 增加 FINAL_SYSTEM_PROMPT + finalize()

**Files:**
- Modify: `llm.py`（在 ENHANCE_SYSTEM_PROMPT / is_non_report 之后追加）

- [ ] **Step 1: 在 llm.py 的 `is_non_report` 函数之后、class 之前追加模块常量**

```python
FINAL_SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告医师。输入是一次超声检查过程中提取的全部报告内容句子（已经过术语纠错与内容筛选，按口述先后顺序排列，可能含有重复描述）。你的任务：将全部内容梳理为一份规范的书面超声报告，分【超声所见】与【超声提示】两节输出。要求：
1. 【超声所见】收录客观检查描述（脏器位置、大小、回声、血流、测量数值等）；【超声提示】收录结论性用语（含"考虑""可能""建议""符合""提示"等字样的句子）。若输入中没有结论性内容，只输出【超声所见】一节。
2. 只使用输入中明确存在的医学内容，绝不补充、推测、编造输入中没有的医学事实、数值或诊断；若输入中混入与报告无关的内容（如对患者的指示、闲聊），直接忽略。
3. 内容基本一致的重复描述只保留一次；同一项目重复测量且数值不一致时，全部数值都要保留（如"内膜厚约 8mm，后测约 9mm"），不得自行取舍。
4. 绝对不得改动数值、单位、左右侧等关键信息，不得在中英文与数字之间增删空格。
5. 两节标题各占一行，格式为【超声所见】和【超声提示】；节内为通顺的书面语句。
6. 只输出报告文本本身，不要任何解释、前缀或评论。"""
```

- [ ] **Step 2: 在 UltrasoundOptimizer 类中 `enhance` 方法之后追加**

```python
    def finalize(self, text: str) -> str:
        """整体梳理：把全部增强后内容整理为两段式完整报告。"""
        return self._run(FINAL_SYSTEM_PROMPT, text) or ""
```

- [ ] **Step 3: 语法检查**

Run: `.venv/Scripts/python -m py_compile llm.py && .venv/Scripts/python -c "from llm import FINAL_SYSTEM_PROMPT; print(len(FINAL_SYSTEM_PROMPT))"`
Expected: 编译通过，打印长度数字

- [ ] **Step 4: Commit**

```bash
git add llm.py
git commit -m "feat: 第三级整体报告梳理 prompt + finalize()"
```

---

### Task 2: eval_terms.py 增加整体梳理用例并运行

**Files:**
- Modify: `eval_terms.py`

- [ ] **Step 1: 在 `ENHANCE_CATEGORIES` 之后追加**

```python
# (输入=增强后句子组, 输出必须包含, 输出不得包含, 只能出现一次的子串)
FINAL_CASES: list[tuple[str, list[str], list[str], list[str]]] = [
    (
        "子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。子宫内膜厚约8mm。子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。双侧卵巢未见明显异常。考虑子宫腺肌症可能，建议结合临床。",
        ["【超声所见】", "【超声提示】", "子宫腺肌症"],
        [],
        ["8.2×6.5×7.1cm"],
    ),
    (
        "子宫内膜厚约8mm。子宫内膜厚约9mm。双侧附件区未见明显异常。",
        ["【超声所见】", "8mm", "9mm"],
        [],
        [],
    ),
    (
        "好的检查完了去外面等报告吧。子宫前位，内膜厚约8mm。",
        ["【超声所见】", "子宫前位", "8mm"],
        ["等报告", "检查完了"],
        [],
    ),
]


def judge_final(out: str, present: list[str], absent: list[str], once: list[str]) -> bool:
    out_n = _norm(out)
    return (
        all(_norm(s) in out_n for s in present)
        and all(_norm(s) not in out_n for s in absent)
        and all(out_n.count(_norm(s)) == 1 for s in once)
    )
```

- [ ] **Step 2: 在 main() 末尾（增强 suite 汇总之后）追加**

```python
    print("\n===== 整体报告梳理 =====")
    f_ok = 0
    for i, (src, present, absent, once) in enumerate(FINAL_CASES, 1):
        out = (optimizer.finalize(src) or "").strip()
        ok = judge_final(out, present, absent, once)
        f_ok += ok
        print(f"[F{i:02d}/{len(FINAL_CASES)}][{'PASS' if ok else 'FAIL'}]")
        print(f"  输入: {src}")
        print(f"  输出: {out}")
    print(f"整体: {f_ok}/{len(FINAL_CASES)}")
```

- [ ] **Step 3: 语法检查 + commit**

Run: `.venv/Scripts/python -m py_compile eval_terms.py && echo OK`

```bash
git add eval_terms.py
git commit -m "feat: 验证集增加整体报告梳理用例（去重/冲突数值/闲聊过滤）"
```

- [ ] **Step 4: 运行全量 eval**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -u eval_terms.py > eval_results_final.txt 2>&1; tail -15 eval_results_final.txt`
Expected: 术语 20/20、增强 5/5（回归），整体 3/3

- [ ] **Step 5:（仅在不满足时）迭代 FINAL_SYSTEM_PROMPT**

整体用例 FAIL 时诊断失败模式做最小修改（去重失败 → 强化规则 3 示例；分节错误 → 强化规则 1；编造内容 → 强化规则 2），每轮 commit（`fix: 迭代 FINAL prompt（第N轮）`）并重跑，最多 3 轮。术语/增强 suite 回归失败则 STOP 上报（不得改 SYSTEM_PROMPT / ENHANCE_SYSTEM_PROMPT）。

---

### Task 3: modes.py 接入整体报告（run_file + run_realtime）

**Files:**
- Modify: `modes.py`（run_file 结尾段、run_realtime 的 handle_segments 与 finally、删除 write_report）

- [ ] **Step 1: run_file — 循环后、写 SRT 前插入整体梳理；替换 --report 分支**

循环与 srt 部分不变。将现有：

```python
    if args.srt:
        write_srt(args.srt, srt_rows)
    if args.report:
        if optimizer is None:
            print("--report 需要开启 LLM，已跳过。")
        elif not report_lines and args.no_enhance:
            print("--report 与 --no-enhance 同用，无增强内容，已跳过。")
        else:
            write_report(args.report, report_lines)
```

替换为：

```python
    if args.srt:
        write_srt(args.srt, srt_rows)

    final_report = ""
    if report_lines:
        print("整体梳理中…")
        final_report = optimizer.finalize("\n".join(report_lines))
        print("\n===== 整体报告 =====")
        print(final_report)

    if args.report:
        if optimizer is None:
            print("--report 需要开启 LLM，已跳过。")
        elif args.no_enhance:
            print("--report 依赖增强优化，--no-enhance 时无法生成，已跳过。")
        elif not final_report:
            print("未识别到报告内容，未生成报告文件。")
        else:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(final_report + "\n")
            print(f"报告已保存: {args.report}")
```

（report_lines 非空 ⇒ do_enhance 为真 ⇒ optimizer 非 None，finalize 调用安全。）

- [ ] **Step 2: 删除 write_report 函数**（已无用例）

- [ ] **Step 3: run_realtime — 收集报告行 + finally 中整体梳理**

`handle_segments` 定义前加 `report_lines: list[str] = []`；把：

```python
            text = recognize(model, seg)
            if text:
                emit_all(start, text, optimizer, do_enhance=not args.no_enhance)
```

改为：

```python
            text = recognize(model, seg)
            if text:
                _, enhanced = emit_all(start, text, optimizer, do_enhance=not args.no_enhance)
                if enhanced and not is_non_report(enhanced):
                    report_lines.append(enhanced)
```

finally 块中，在 VAD flush 的 handle_segments 调用之后、`print("已停止。")` 之前插入：

```python
        if report_lines:
            print("整体梳理中…")
            print("\n===== 整体报告 =====")
            print(optimizer.finalize("\n".join(report_lines)))
```

- [ ] **Step 4: 验证**

Run: `.venv/Scripts/python -m py_compile modes.py && echo OK && grep -n write_report modes.py`
Expected: OK；grep 无输出

- [ ] **Step 5: Commit**

```bash
git add modes.py
git commit -m "feat: file/realtime 结束输出整体报告，--report 写入两段式报告"
```

---

### Task 4: 端到端验证

**Files:** 无改动（产物 verify_* 用后删除）

- [ ] **Step 1: B.WAV（含真实报告口述）**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -u asr.py file test/B.WAV --srt verify_b.srt --report verify_b_report.txt > verify_b_log.txt 2>&1; tail -25 verify_b_log.txt`
Expected: 终端打印 `===== 整体报告 =====` 与两段式报告；verify_b_report.txt 含【超声所见】【超声提示】、含原 4 行报告内容的关键数值（15周6天/4mm/32mm/肌瘤等）、无闲聊、无【非报告内容】

- [ ] **Step 2: A.WAV（纯闲聊）**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -u asr.py file test/A.WAV --report verify_a_report.txt 2>&1 | tail -3; ls verify_a_report.txt 2>/dev/null || echo "报告文件未生成（符合预期）"`
Expected: 打印"未识别到报告内容，未生成报告文件。"；文件不存在

- [ ] **Step 3: realtime 模拟（B.WAV，验证 finally 路径）**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -u asr.py realtime --simulate test/B.WAV --speed 8 2>&1 | tail -15`
Expected: 逐段三行输出正常；结尾打印整体报告（两段式）；无 crash

- [ ] **Step 4: 清理产物**

Run: `rm -f verify_b.srt verify_b_report.txt verify_b_log.txt verify_a_report.txt eval_results_final.txt && git status --short`
Expected: 只剩用户文件（out.srt、out2.srt、test/）

---

### Task 5: 终审与合并

- [ ] **Step 1: 全分支净 diff 终审**（spec 覆盖、无遗留、README 是否需同步——三级变四级输出、--report 语义变化需更新 README）
- [ ] **Step 2: README 同步（若终审确认需要）并 commit**
- [ ] **Step 3: 合并 main 并删除特性分支**

---

## Self-Review 记录

- Spec 覆盖：FINAL prompt（Task 1）✓、eval 用例（Task 2）✓、run_file/realtime（Task 3）✓、成功标准 3 条（Task 2 Step 4 / Task 4 Step 1-3）✓、A.WAV 不写空文件（Task 3 Step 1 的 elif not final_report + Task 4 Step 2）✓
- 类型一致：finalize() -> str；emit_all 返回 (optimized, enhanced)，realtime 用 `_, enhanced` ✓；judge_final 四元组与 FINAL_CASES 一致 ✓
- 无占位符；所有代码块完整

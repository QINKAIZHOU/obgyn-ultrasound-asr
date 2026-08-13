# 超声术语纠错增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 系统性增强 `llm.py` SYSTEM_PROMPT 的妇产科/乳腺科术语覆盖，并用验证集量化优化效果。

**Architecture:** 先建验证集 `eval_terms.py`（20 条用例，直接调 `UltrasoundOptimizer`），用旧 prompt 跑出基线；再重写 SYSTEM_PROMPT（结构化四组术语库 + 同音错误对照）；最后复跑验证集对比。只改 prompt 字符串，不动任何识别逻辑。

**Tech Stack:** Python 3.12 venv（`.venv/`）、transformers 5.x、Qwen3.5-9B（已缓存本地）。

**Spec:** `docs/superpowers/specs/2026-08-13-ultrasound-terms-prompt-design.md`

**通用注意事项（所有任务）：**
- 所有 python 命令用 `.venv/Scripts/python`，工作目录为仓库根目录 `D:\Projects\obgyn-ultrasound-asr`
- 涉及打印中文的命令前置 `PYTHONIOENCODING=utf-8`（Windows 管道编码）
- 验证集运行需加载 Qwen3.5-9B（约 1–2 分钟）+ 20 次生成，单次运行约 5–10 分钟，Bash 超时需设 600000ms
- 验证结果文件（`eval_results_*.txt`）**不提交 git**，对比完成后删除（用户偏好：测试产物不入库）

---

### Task 1: 创建验证集 eval_terms.py

**Files:**
- Create: `eval_terms.py`

- [ ] **Step 1: 写验证集脚本（完整内容如下）**

```python
"""术语纠错验证集：评估当前 SYSTEM_PROMPT 的纠错 / 防误伤 / 关键信息保持表现。

用法: .venv/Scripts/python eval_terms.py
逐条打印 输入/输出/判定，末尾按类别汇总通过率。
"""
from __future__ import annotations

from llm import UltrasoundOptimizer

# (类别, 输入, 输出中必须出现的子串, 输出中不得出现的子串)
# 类别 "无误" 的判定规则是输出与输入完全一致（此时后两项为空）。
CASES: list[tuple[str, str, list[str], list[str]]] = [
    # ---- 含错句：同音错字应被纠正 ----
    ("含错", "子工前位，大小形态正常。", ["子宫"], ["子工"]),
    ("含错", "子工内幕厚约8mm。", ["子宫", "内膜"], ["子工", "内幕"]),
    ("含错", "子工机留，大小约25mm×20mm。", ["肌瘤"], ["机留"]),
    ("含错", "右侧卵巢可见一囊种，大小约30mm。", ["囊肿"], ["囊种"]),
    ("含错", "左侧卵巢几胎留可能大。", ["畸胎瘤"], ["几胎留"]),
    ("含错", "盆腔可见叶性暗区，深约15mm。", ["液性暗区"], ["叶性暗区"]),
    ("含错", "宫内可见韵囊，可见太心搏动。", ["孕囊", "胎心"], ["韵囊", "太心"]),
    ("含错", "太盘位于子宫前壁，成熟度1级。", ["胎盘"], ["太盘"]),
    ("含错", "杨水指数约80mm。", ["羊水"], ["杨水"]),
    ("含错", "胎儿双顶颈约85mm，骨股长约66mm。", ["双顶径", "股骨长"], ["双顶颈", "骨股长"]),
    ("含错", "右侧乳腺节节，边界清晰，可见流血信号。", ["结节", "血流信号"], ["节节", "流血信号"]),
    ("含错", "左侧乳腺可见细小盖化，BI-RADS 4A类。", ["钙化"], ["盖化"]),
    # ---- 无误句：应原样输出 ----
    ("无误", "子宫前位，大小形态正常，肌层回声均匀。", [], []),
    ("无误", "双侧卵巢未见明显异常回声。", [], []),
    ("无误", "胎儿胎心搏动可见，胎心率145次/分。", [], []),
    ("无误", "右侧乳腺未见明显占位性病变，BI-RADS 1类。", [], []),
    ("无误", "盆腔未见明显游离液性暗区。", [], []),
    # ---- 关键信息句：数值 / 单位 / 左右侧零改动 ----
    ("关键", "子宫内膜厚约8mm，左侧卵巢大小约28mm×15mm。", ["8mm", "28mm×15mm", "左侧"], []),
    ("关键", "胎儿双顶径约85mm，股骨长约66mm，羊水指数约120mm。", ["85mm", "66mm", "120mm"], []),
    ("关键", "右侧乳腺外上象限可见低回声结节，大小约12mm×8mm，BI-RADS 3类。", ["右侧", "12mm×8mm", "3类"], []),
]

CATEGORIES = ["含错", "无误", "关键"]


def judge(cat: str, src: str, out: str, present: list[str], absent: list[str]) -> bool:
    if cat == "无误":
        return out == src
    return all(s in out for s in present) and all(s not in out for s in absent)


def main() -> None:
    optimizer = UltrasoundOptimizer()
    stats = {c: [0, 0] for c in CATEGORIES}  # 类别 -> [通过, 总数]
    for i, (cat, src, present, absent) in enumerate(CASES, 1):
        out = (optimizer.optimize(src) or "").strip()
        ok = judge(cat, src, out, present, absent)
        stats[cat][1] += 1
        stats[cat][0] += ok
        print(f"[{i:02d}/{len(CASES)}][{cat}][{'PASS' if ok else 'FAIL'}]")
        print(f"  输入: {src}")
        print(f"  输出: {out}")
    print("\n===== 汇总 =====")
    total_ok = total = 0
    for cat in CATEGORIES:
        ok, n = stats[cat]
        total_ok += ok
        total += n
        print(f"{cat}: {ok}/{n}")
    print(f"总计: {total_ok}/{total}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 语法检查**

Run: `.venv/Scripts/python -m py_compile eval_terms.py && echo OK`
Expected: 输出 `OK`

- [ ] **Step 3: Commit**

```bash
git add eval_terms.py
git commit -m "feat: 术语纠错验证集（20 条用例：含错/无误/关键信息）"
```

---

### Task 2: 用旧 prompt 跑基线

**Files:**
- 无改动（只产出 `eval_results_baseline.txt`，不入库）

- [ ] **Step 1: 运行基线评估并保存输出**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -u eval_terms.py > eval_results_baseline.txt 2>&1; tail -8 eval_results_baseline.txt`
（Bash 超时设 600000ms；运行约 5–10 分钟）
Expected: 正常跑完 20 条，末尾打印汇总（含错/无误/关键 各类通过数 + 总计）。**记录基线数字，供 Task 4 对比。**

注意：旧 prompt 下部分"含错"句 FAIL 是正常的（这正是要改进的）；若"无误"句出现 FAIL（如数值被加空格），也记录下来。

---

### Task 3: 重写 SYSTEM_PROMPT

**Files:**
- Modify: `llm.py:8-14`（只替换 SYSTEM_PROMPT 字符串，其余不动）

- [ ] **Step 1: 替换 SYSTEM_PROMPT 为以下内容**

```python
SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告助手。输入是医生口述超声报告的语音识别结果，可能含有同音或近音识别错误。请优化为规范、通顺的超声医学书面用语。要求：
1. 纠正明显的同音/近音错别字，尤其是本专科医学术语。常见术语及易错对照（括号内为可能的错误识别，仅为示例，请举一反三）：
妇科：子宫（子工）、子宫内膜（内幕、内模）、宫颈（宫井）、卵巢（乱巢）、肌瘤（机留、肌留）、囊肿（囊种）、畸胎瘤（几胎留）、子宫腺肌症、多囊卵巢、卵泡、黄体、输卵管、盆腔积液、液性暗区（叶性暗区）。
产科：孕囊（韵囊）、胎心（太心）、胎芽（太芽）、胎盘（太盘）、羊水（杨水）、双顶径（双顶颈）、股骨长（骨股长）、肱骨长、头围、腹围、脐血流（其血流）、羊水指数、胎盘成熟度、前置胎盘、孕周。
乳腺：结节（节节）、肿块、钙化（盖化）、导管扩张、边界清晰或不清晰、形态规则或不规则、纵横比、血流信号（流血信号）、弹性成像、BI-RADS 分级、腋窝淋巴结（夜窝淋巴结）。
其他常见超声术语：低回声、强回声、无回声、混合性回声、肾盂分离、胆囊息肉、结石、脂肪肝、甲状腺结节、TI-RADS 分级。
2. 绝对不得改动数值、单位、左右侧等关键信息，不得增加或删除任何医学事实。
3. 保持句子数量与顺序，不合并、不拆分。
4. 只输出优化后的文本本身，不要任何解释、前缀或引号。
5. 若原文没有错误，或原文不是医学内容，直接将原文原样输出。
6. 任何情况下都只输出处理后的文本，绝不输出解释、提示、拒绝或评论。"""
```

- [ ] **Step 2: 语法 + 长度检查**

Run: `.venv/Scripts/python -m py_compile llm.py && .venv/Scripts/python -c "from llm import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT))"`
Expected: 打印的数字 ≤ 800

- [ ] **Step 3: Commit**

```bash
git add llm.py
git commit -m "feat: SYSTEM_PROMPT 结构化术语库（妇科/产科/乳腺/通用 + 同音错对照）"
```

---

### Task 4: 新 prompt 复跑验证集并对比

**Files:**
- 无改动（只产出 `eval_results_new.txt`，不入库）

- [ ] **Step 1: 运行新评估并保存输出**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -u eval_terms.py > eval_results_new.txt 2>&1; tail -8 eval_results_new.txt`
（Bash 超时设 600000ms）

- [ ] **Step 2: 对比基线，按成功标准判定**

对照 `eval_results_baseline.txt` 与 `eval_results_new.txt` 的汇总：

1. 含错句通过率 ≥ 基线且有提升 → 通过；若持平或下降，进入 Step 3 迭代
2. 无误句 5/5 原样输出 → 必须满足；否则说明 prompt 误伤，进入 Step 3 迭代（可在规则 5 后追加"，包括用词、数值写法与标点均保持不变"）
3. 关键句 3/3 数值/单位/左右侧保留 → 必须满足

- [ ] **Step 3: （仅在不满足时执行）迭代 prompt 并重跑**

根据 FAIL 用例的失败模式微调 SYSTEM_PROMPT（如：误伤则强化规则 5；漏纠则在对应科室补充该同音对照），重复 Step 1–2 直到满足成功标准。每轮微调后 commit。

---

### Task 5: 清理与收尾

- [ ] **Step 1: 删除验证结果文件**

```bash
rm -f eval_results_baseline.txt eval_results_new.txt
git status --short
```

Expected: git status 干净（或只剩已提交的改动）

- [ ] **Step 2: 汇报对比结果**

向用户展示基线 vs 新 prompt 的逐类通过率对照表和典型用例输出差异。

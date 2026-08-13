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
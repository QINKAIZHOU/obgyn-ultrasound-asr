"""LLM 三级验证集：评估 SYSTEM_PROMPT 的纠错/防误伤/关键信息/报数还原、
ENHANCE_SYSTEM_PROMPT 的混合段报告成分提取、FINAL_SYSTEM_PROMPT 的模板对齐与防编造。

用法: .venv/Scripts/python eval_terms.py
逐条打印 输入/输出/判定，末尾按类别汇总通过率（35 条）。
"""
from __future__ import annotations

import re
import sys

from llm import UltrasoundOptimizer, conflict_check, is_non_report

# (类别, 输入, 输出中必须出现的子串, 输出中不得出现的子串)
# 类别 "无误" 的判定规则是输出与输入完全一致（此时后两项为空）。
# 判定忽略空白差异（模型在中英文/数字间加空格属可接受行为）。
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
    # ---- 上下文冲突句：同音错字构成通顺常用词，须结合上下文纠正（LLM + 冲突检查兜底） ----
    ("含错", "子宫前臂肌层可见中低回声区，大小约25mm×18mm。", ["前壁", "25mm×18mm"], ["前臂"]),
    ("含错", "肌层回升均匀，宫壁回升稍强。", ["回声"], ["回升"]),
    ("含错", "子宫基层回声不均，可见基层瘤样低回声。", ["肌层"], ["基层"]),
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
    # ---- 报数句：逐字报读的测量值应还原为阿拉伯数字 mm，禁止单位换算 ----
    # （同时覆盖上下文冲突纠错：左前臂→左前壁，历史上该案例漏检过此回归）
    ("报数", "子宫左前臂肌层中低回声区六一六一六零毫米，压迫宫腔。",
     ["前壁", "61", "60", "mm", "压迫宫腔"], ["前臂", "cm", "厘米", "六一六一六零"]),
    ("报数", "内膜厚度八毫米，宫颈长度三十二毫米。",
     ["8mm", "32mm"], ["八毫米", "三十二", "cm", "厘米"]),
    ("报数", "子宫大小长径五十二毫米，左右径五十三毫米，前后径四十二毫米。",
     ["52mm", "53mm", "42mm"], ["五十二", "cm", "厘米"]),
    # 残缺报读分组不确定：可原样保留或合理分组，但绝不引入小数点（30.2×28 类错误）
    ("报数", "右卵巢大小三零二二十八毫米。", ["右卵巢"], [".", "cm", "厘米"]),
]

CATEGORIES = ["含错", "无误", "关键", "报数"]

# (类别, 输入=优化后文本, 输出中必须出现的子串, 输出中不得出现的子串)
# 类别 "非报告" 的判定规则是输出被识别为非报告标记（此时后两项为空）。
ENHANCE_CASES: list[tuple[str, str, list[str], list[str]]] = [
    ("混合", "来，躺好，把衣服撩起来。子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。好了，可以起来了。",
     ["子宫前位", "8.2×6.5×7.1cm", "肌层回声均匀"], ["躺", "衣服", "起来"]),
    ("混合", "别动啊，马上就好。右侧乳腺外上象限可见低回声结节，大小约12mm×8mm，BI-RADS 3类。放松，结束了。",
     ["右侧", "低回声结节", "12mm×8mm", "3类"], ["别动", "放松", "结束"]),
    ("混合", "宫内可见孕囊，可见胎心搏动。你几周了？末次月经什么时候？",
     ["孕囊", "胎心搏动"], ["几周", "末次月经"]),
    # 真实门诊模式：数值报读与对患者的指示混杂在同一句，报告成分必须保留
    ("混合", "屁股稍微垫高一点，垫起来。子宫前壁突起中低回声区九零八五八四毫米。好了放松，可以起来了。",
     ["子宫前壁", "中低回声"], ["垫高", "放松", "起来", "屁股"]),
    ("混合", "你怎么记得怎么了？右侧卵巢大小三十二十八毫米。其他医院查一个大的。",
     ["卵巢"], ["医院", "怎么回事"]),
    ("非报告", "东西放下，脱鞋，脱裤子，往这边躺。", [], []),
    ("非报告", "好的，检查做完了，去外面等报告吧，下一个。", [], []),
]

ENHANCE_CATEGORIES = ["混合", "非报告"]


def judge_enhance(cat: str, out: str, present: list[str], absent: list[str]) -> bool:
    if cat == "非报告":
        return is_non_report(out)
    out_n = _norm(out)
    if "非报告" in out_n:
        return False  # 混合句被误判为纯非报告
    return all(_norm(s) in out_n for s in present) and all(
        _norm(s) not in out_n for s in absent
    )


# (输入=增强后句子组, 输出必须包含, 输出不得包含, 只能出现一次的子串)
FINAL_CASES: list[tuple[str, list[str], list[str], list[str]]] = [
    (
        "子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。子宫内膜厚约8mm。子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。双侧卵巢未见明显异常。考虑子宫腺肌症可能，建议结合临床。",
        ["【超声所见】", "【超声提示】", "子宫腺肌症"],
        [],
        # 模板化输出允许把 8.2×6.5×7.1cm 分解为 长径/左右径/前后径（医院模板格式），
        # 去重判定改为检查 "8.2" 只出现一次（若被换算成 82mm 则该判定失败）
        ["8.2"],
    ),
    (
        "子宫内膜厚约8mm。子宫内膜厚约9mm。双侧附件区未见明显异常。",
        ["【超声所见】", "8mm", "9mm"],
        [],
        [],
    ),
    (
        "好的检查完了去外面等报告吧。子宫前位，内膜厚约8mm。",
        # 模板化输出会把"子宫前位"改写为"子宫位置：前位"，判定放宽为"前位"
        ["【超声所见】", "前位", "8mm"],
        ["等报告", "检查完了"],
        [],
    ),
    # 模板对齐：输入含哪些项输出哪些节，未口述的项目绝不编造
    (
        "子宫前位，长径52mm，左右径53mm，前后径42mm，形态不规则，回声不均匀。"
        "子宫前壁突起中低回声区90×85×84mm。右卵巢大小30×22×18mm，左卵巢大小24×20×15mm。子宫肌瘤可能。",
        ["【超声所见】", "【子宫】", "【附件】", "【超声提示】",
         "52mm", "90×85×84", "30×22×18", "子宫肌瘤"],
        ["内膜", "IUD", "宫颈长度", "盆腔积液"],
        [],
    ),
    # 报读还原兜底：整理级收到未归一的逐字报数时按 mm 还原
    (
        "子宫左前壁肌层中低回声区六一六一六零毫米，压迫宫腔。"
        "后壁稍突起中低回声区三四二五二二毫米。右卵巢大小二四二零一六毫米。",
        ["【超声所见】", "61", "60", "34", "22", "24", "16", "压迫宫腔", "mm"],
        ["cm", "厘米", "六一六一六零", "三四二五二二"],
        [],
    ),
    # 解剖归属：未明确定位于肌层的"右/左侧弱回声"必须归入【附件】节（医院模板惯例）；
    # 无内容的节省略而非填充说明
    (
        "子宫前位，长径45mm。右侧弱回声，大小48×43×35mm。左侧弱回声，大小83×71×58mm。",
        ["【超声所见】", "【子宫】", "【附件】", "48×43×35", "83×71×58"],
        ["未行检查", "未述及", "cm"],
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


def _norm(s: str) -> str:
    """比较前去除所有空白：模型在中英文/数字间加空格属可接受行为。"""
    return re.sub(r"\s+", "", s)


def judge(cat: str, src: str, out: str, present: list[str], absent: list[str]) -> bool:
    out_n = _norm(out)
    if cat == "无误":
        return out_n == _norm(src)
    return all(_norm(s) in out_n for s in present) and all(
        _norm(s) not in out_n for s in absent
    )


def main() -> None:
    if "--check-conflicts" in sys.argv:
        # 离线自测 conflict_check：锚点命中必须纠正、真本义必须放行（不加载模型）
        pos = [
            ("子宫前臂肌层中低回声区", "子宫前壁肌层中低回声区"),
            ("左前臂突起中低回声区", "左前壁突起中低回声区"),
            ("肌层回升均匀", "肌层回声均匀"),
            ("宫壁回升稍强", "宫壁回声稍强"),
            ("内膜回升欠均匀", "内膜回声欠均匀"),
            ("子宫基层回声不均", "子宫肌层回声不均"),
            ("宫体面膜增厚", "宫体内膜增厚"),
        ]
        neg = ["今天敷了面膜，胳膊前臂晒伤了", "基层医院复查即可", "回升的体温", "前臂骨折石膏固定"]
        for src, want in pos:
            got, hits = conflict_check(src)
            assert got == want, f"应纠正: {src} → {got}（期望 {want}）"
            assert hits, src
        for src in neg:
            got, hits = conflict_check(src)
            assert got == src and not hits, f"误伤本义: {src} → {got}"
        print(f"CONFLICT_OK（{len(pos)} 条锚点命中全纠正，{len(neg)} 条本义全放行）")
        return

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

    print("\n===== 增强优化（报告内容提取） =====")
    estats = {c: [0, 0] for c in ENHANCE_CATEGORIES}
    for i, (cat, src, present, absent) in enumerate(ENHANCE_CASES, 1):
        out = (optimizer.enhance(src) or "").strip()
        ok = judge_enhance(cat, out, present, absent)
        estats[cat][1] += 1
        estats[cat][0] += ok
        print(f"[E{i:02d}/{len(ENHANCE_CASES)}][{cat}][{'PASS' if ok else 'FAIL'}]")
        print(f"  输入: {src}")
        print(f"  输出: {out}")
    for cat in ENHANCE_CATEGORIES:
        ok, n = estats[cat]
        print(f"增强-{cat}: {ok}/{n}")

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


if __name__ == "__main__":
    main()

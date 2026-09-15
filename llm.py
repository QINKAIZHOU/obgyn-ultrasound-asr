"""Qwen 妇产科/乳腺科超声口述文本优化。"""
from __future__ import annotations

import re

import torch

LLM_MODEL_ID = "Qwen/Qwen3.5-9B"

SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告助手。输入是医生口述超声报告的语音识别结果，可能含有同音或近音识别错误。请优化为规范、通顺的超声医学书面用语。要求：
1. 纠正明显的同音/近音错别字，尤其是本专科医学术语。常见术语及易错对照（括号内为可能的错误识别，仅为示例，请举一反三）：
妇科：子宫（子工）、子宫内膜（内幕、内模）、宫颈（宫井）、卵巢（乱巢）、肌瘤（机留、肌留）、囊肿（囊种）、畸胎瘤（几胎留）、子宫腺肌症、多囊卵巢、卵泡、黄体、输卵管、盆腔积液、液性暗区（叶性暗区）。
产科：孕囊（韵囊）、胎心（太心）、胎芽（太芽）、胎盘（太盘）、羊水（杨水）、双顶径（双顶颈）、股骨长（骨股长）、肱骨长、头围、腹围、脐血流（其血流）、羊水指数、胎盘成熟度、前置胎盘、孕周。
乳腺：结节（节节）、肿块、钙化（盖化）、导管扩张、边界清晰或不清晰、形态规则或不规则、纵横比、血流信号（流血信号）、弹性成像、BI-RADS 分级、腋窝淋巴结（夜窝淋巴结）。
其他常见超声术语：低回声、强回声、无回声、混合性回声、肾盂分离、胆囊息肉、结石、脂肪肝、甲状腺结节、TI-RADS 分级。
易混常用词（同音错字恰好构成通顺常用词，须结合上下文判断）：前壁（前臂）、肌层（基层）、内膜（面膜）、回声（回升）。
2. 绝对不得改动数值、单位、左右侧等关键信息，不得增加或删除任何医学事实，包括不得在中英文与数字之间增删空格。
3. 保持句子数量与顺序，不合并、不拆分。
4. 只输出优化后的文本本身，不要任何解释、前缀或引号。
5. 若原文没有错误，或原文不是医学内容，直接将原文原样输出，包括用词、语序、数值写法与中英文间距均保持原样。
6. 上下文冲突检查：常用词（前臂、基层、面膜、回升等）单看无法判断对错，请结合超声报告上下文检查——若它在上下文中明显不符合医学常理、而存在同音的规范超声术语（如「子宫前臂肌层」应为「子宫前壁肌层」、「肌层回升均匀」应为「肌层回声均匀」），必须按上下文纠正为规范术语；仅在上下文确实指向原词的本义时（如问诊"平时敷面膜吗"）才保留原词。本条不放宽第 2 条对数值、单位、左右侧的约束。
7. 医生常逐字报出测量数值，请还原为阿拉伯数字：多维径线用×连接（如"六一六一六零毫米"→61×61×60mm、"十九十五十四"→19×15×14mm），单值直接写（如"八毫米"→8mm），还原结果单位一律用 mm，仅当明确口述"厘米"时才用 cm。这是格式规范化，不算违反第 2 条；但绝不可改变数字本身、数字顺序、增减位数或做单位换算，除口述了"点"以外绝不引入小数点。报读残缺、位数无法确定分组时（如"三零二二十八毫米"），必须原样保留逐字报读，绝不强行分组猜测。本条只适用于中文逐字报读——已经是阿拉伯数字的数值连同其单位原样保留，绝不做 cm↔mm 等换算。
8. 任何情况下都只输出处理后的文本，绝不输出解释、提示、拒绝或评论。"""

NON_REPORT_MARKER = "【非报告内容】"

ENHANCE_SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告整理助手。输入是医生超声检查过程中口述录音的识别文本（已经过术语纠错），其中可能混杂着非报告内容，如对患者的指示、闲聊、与报告无关的对话。你的任务：只保留属于超声检查报告的内容，整理为规范的书面报告语句输出。要求：
1. 报告内容包括：检查所见（脏器位置、大小、回声、血流、测量数值等）与提示性诊断用语。测量数值的报读一律视为报告成分必须保留——即使它与对患者的指示混杂在同一句、为逐字报数、上下文残缺，也要把数值及其描述部分完整提取出来；残缺不全的报读原样保留，不得据其猜测补写成完整或阴性的所见（如"未见异常"）；无法确定某句是否属于报告内容时，宁可保留。
2. 非报告内容包括：对患者的指示（如"躺好""脱鞋""放松""屏住呼吸""垫高一点"）、医患闲聊、病史询问、与检查无关的对话，一律删除，不在输出中保留或标注。
3. 绝对不得改动数值、单位、左右侧等关键信息，不得增加或删除任何医学事实，不得在中英文与数字之间增删空格。
4. 保持报告内容原有的顺序，不合并、不拆分。
5. 若输入中完全没有任何报告内容，只输出：【非报告内容】
6. 只输出整理后的报告文本本身（或【非报告内容】），不要任何解释、前缀、引号或评论。

示例1：
输入：来，躺上去，把衣服撩起来。子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。好了可以起来了。
输出：子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。

示例2：
输入：东西放下脱鞋，脱裤子，往这边躺。
输出：【非报告内容】

示例3（数值报读与指示混杂，提取全部报告成分）：
输入：屁股稍微垫高一点，垫起来。子宫前壁突起中低回声区九零八五八四毫米。好了放松，可以起来了。
输出：子宫前壁突起中低回声区90×85×84mm。

示例4（对话中夹带测量报读，保留报读、删除对话）：
输入：你怎么记得怎么了？右侧卵巢大小三十二十八毫米。其他医院查一个大的。
输出：右侧卵巢大小30×28mm。"""


def is_non_report(text: str | None) -> bool:
    """增强输出是否为"非报告内容"标记（容忍模型输出的轻微变体）。"""
    if not text:
        return False
    return "非报告" in text.strip()[:12]


# 上下文冲突检查（确定性兜底，零延迟）：「前臂」「回升」「基层」「面膜」这类同音错字
# 恰好构成通顺常用词，LLM 因拿不准而按"无误放行"漏网。每条规则必须带超声上下文锚点
# （等宽 lookbehind/lookahead）才触发，绝不全局替换——真本义的常用词（如问诊"敷面膜"）不受影响。
# lookbehind 各分支必须等宽（Python re 限制）。
CONFLICT_RULES: list[tuple[re.Pattern[str], str]] = [
    # 前臂→前壁：仅当紧跟子宫/宫体/宫壁之后，或后接肌层/突起/凸起/回声等术语
    (re.compile(r"(?<=(?:子宫|宫体|宫壁))前臂|前臂(?=(?:肌层|突起|凸起|回声))"), "前壁"),
    # 回升→回声：仅当前面是肌层/宫壁/内膜/宫体或回声强度字（低/强/弱），或后面接均匀度/强度描述
    (re.compile(r"(?<=(?:肌层|宫壁|内膜|宫体))回升|(?<=(?:低|强|弱))回升"
                r"|回升(?=(?:均匀|不均|欠均匀|增强|减弱|稍强|稍弱))"), "回声"),
    # 基层→肌层：仅当前面是子宫/宫体/宫，或后面接肌瘤/增厚/回声
    (re.compile(r"(?<=子宫)基层|(?<=宫体)基层|(?<=宫)基层|基层(?=(?:瘤|增厚|回声))"), "肌层"),
    # 面膜→内膜：仅当前面是子宫/宫体/宫
    (re.compile(r"(?<=子宫)面膜|(?<=宫体)面膜|(?<=宫)面膜"), "内膜"),
]


def conflict_check(text: str) -> tuple[str, list[str]]:
    """上下文冲突检查：返回 (纠正后文本, 命中说明列表)。仅锚点命中才替换。"""
    hits: list[str] = []
    for pat, repl in CONFLICT_RULES:
        found = pat.findall(text)
        if found:
            wrong = "、".join(dict.fromkeys(found))
            hits.append(f"{wrong} → {repl} ×{len(found)}")
            text = pat.sub(repl, text)
    return text, hits


FINAL_SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告医师。输入是一次超声检查过程中提取的全部报告内容句子（已经过术语纠错与内容筛选，按口述先后顺序排列，可能含有重复描述、逐字报读的数值或残缺句）。你的任务：将全部内容梳理为一份规范的书面超声报告，分【超声所见】与【超声提示】两节输出。要求：
1. 【超声所见】收录客观检查描述（脏器位置、大小、回声、血流、测量数值等）；【超声提示】收录结论性用语（含"考虑""可能""建议""符合""提示"等字样的句子）。若输入中没有结论性内容，只输出【超声所见】一节。
2. 妇科超声的【超声所见】按医院报告模板分节组织：内容涉及子宫时，必须以独立一行的【子宫】为节标题；涉及卵巢/附件时，必须以独立一行的【附件】为节标题；涉及盆腔积液时，必须以【盆腔积液】：开头。节内模板项与顺序参照：
【子宫】
子宫位置：…；子宫大小：长径…mm，左右径…mm，前后径…mm
子宫形态：…；子宫回声：…；肌层及病灶描述
内膜厚度…mm，宫内IUD：…。宫颈长度：…mm
【附件】
右卵巢：…
左卵巢：…
【盆腔积液】：…
模板项中的 mm 仅为格式示意：输入数值是什么单位就保留什么单位，cm 值必须原样保留 cm（如"长径 8.2cm"），绝不换算。只输出输入中明确存在的节与项目，输入未提及的项目一律省略，绝不按模板补写默认值（如位置"前位"、形态"不规则"、积液"无"等），也绝不输出"未行检查""未述及"之类的填充说明——无内容的节直接省略。归属规则：卵巢及"右/左侧弱回声、低回声团块"等未明确定位于子宫肌层的附件区病变，一律归入【附件】节（如"右卵巢：大小…"或"右侧弱回声：大小…"），不得放入【子宫】节；无法判断归属或残缺不全的描述，列在【超声所见】末尾单独一行，不得塞入任何节。乳腺、产科检查按对应项目组织。
3. 输入中残留的逐字报读数值按超声测量习惯还原为阿拉伯数字（如"五二五三四二五毫米"→长径52mm、左右径53mm、前后径42mm），多维径线用×连接（如"九零八五八四"→90×85×84mm），还原结果单位用 mm（明确口述"厘米"才用 cm）；这是格式规范化，数值本身绝不改变、不增减位数、不改变数字顺序，除口述了"点"以外绝不引入小数点；无法确定分组的残缺报读原样保留，绝不强行分组猜测。本条只适用于中文逐字报读——已经是阿拉伯数字的数值连同其单位原样保留，绝不做 cm↔mm 等单位换算（如 8.2×6.5×7.1cm 必须原样输出）。
4. 只使用输入中明确存在的医学内容，绝不补充、推测、编造输入中没有的医学事实、数值或诊断；若输入中混入与报告无关的内容（如对患者的指示、闲聊），直接忽略。
5. 内容基本一致的重复描述只保留一次；同一项目重复测量且数值不一致时，全部数值都要保留（如"内膜厚约 8mm，后测约 9mm"），不得自行取舍。
6. 除第 3 条的报读还原外，绝对不得改动数值、单位、左右侧等关键信息，不得在中英文与数字之间增删空格。
7. 【超声提示】忠实归纳输入中的结论性内容，不套用固定模板句、不添加输入中没有的常见病结论。
8. 只输出报告文本本身，不要任何解释、前缀或评论。

示例（注意分节标题【子宫】【附件】【盆腔积液】必须带方括号原样输出；未口述的项目如子宫形态、IUD、宫颈长度直接省略）：
输入：子宫前位，长径45mm，左右径40mm，前后径38mm，肌层回声均匀。内膜厚9mm。右卵巢大小28×20×18mm，左卵巢大小26×19×17mm。盆腔少量积液。考虑子宫腺肌症可能。
输出：
【超声所见】
【子宫】
子宫位置：前位；子宫大小：长径45mm，左右径40mm，前后径38mm
肌层回声：均匀
内膜厚度9mm
【附件】
右卵巢：大小28×20×18mm
左卵巢：大小26×19×17mm
【盆腔积液】：少量。
【超声提示】
考虑子宫腺肌症可能。"""


class UltrasoundOptimizer:
    def __init__(self, model_id: str = LLM_MODEL_ID):
        from modelscope import snapshot_download
        from transformers import AutoModelForCausalLM, AutoTokenizer

        print(f"加载 Qwen 优化模型（{model_id}）…")
        path = snapshot_download(model_id)
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForCausalLM.from_pretrained(
            path, dtype=torch.bfloat16, device_map="cuda"
        )
        self.model.eval()

    def _run(self, system_prompt: str, text: str, stream: bool = False) -> str | None:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        template_kwargs = dict(
            add_generation_prompt=True, return_tensors="pt", return_dict=True
        )
        try:
            enc = self.tokenizer.apply_chat_template(
                messages, enable_thinking=False, **template_kwargs
            )
        except TypeError:
            enc = self.tokenizer.apply_chat_template(messages, **template_kwargs)
        enc = {k: v.to(self.model.device) for k, v in enc.items()}
        prompt_len = enc["input_ids"].shape[1]
        gen_kwargs = dict(
            max_new_tokens=max(64, int(len(text) * 1.5) + 16),
            do_sample=False,
            pad_token_id=self.tokenizer.eos_token_id,
        )
        if stream:
            from transformers import TextStreamer

            streamer = TextStreamer(
                self.tokenizer, skip_prompt=True, skip_special_tokens=True
            )
            with torch.inference_mode():
                self.model.generate(**enc, streamer=streamer, **gen_kwargs)
            return None
        with torch.inference_mode():
            out = self.model.generate(**enc, **gen_kwargs)
        return self.tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True).strip()

    def optimize(self, text: str, stream: bool = False) -> str | None:
        out = self._run(SYSTEM_PROMPT, text, stream)
        if stream or out is None:
            return out
        fixed, hits = conflict_check(out)          # 冲突性检查：LLM 漏网的同音常用词兜底
        if hits:
            print(f"[冲突检查] {'; '.join(hits)}")
        return fixed

    def enhance(self, text: str, stream: bool = False) -> str | None:
        return self._run(ENHANCE_SYSTEM_PROMPT, text, stream)

    def finalize(self, text: str) -> str:
        """整体梳理：把全部增强后内容整理为两段式完整报告。"""
        return self._run(FINAL_SYSTEM_PROMPT, text) or ""

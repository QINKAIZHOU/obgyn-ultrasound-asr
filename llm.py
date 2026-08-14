"""Qwen 妇产科/乳腺科超声口述文本优化。"""
from __future__ import annotations

import torch

LLM_MODEL_ID = "Qwen/Qwen3.5-9B"

SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告助手。输入是医生口述超声报告的语音识别结果，可能含有同音或近音识别错误。请优化为规范、通顺的超声医学书面用语。要求：
1. 纠正明显的同音/近音错别字，尤其是本专科医学术语。常见术语及易错对照（括号内为可能的错误识别，仅为示例，请举一反三）：
妇科：子宫（子工）、子宫内膜（内幕、内模）、宫颈（宫井）、卵巢（乱巢）、肌瘤（机留、肌留）、囊肿（囊种）、畸胎瘤（几胎留）、子宫腺肌症、多囊卵巢、卵泡、黄体、输卵管、盆腔积液、液性暗区（叶性暗区）。
产科：孕囊（韵囊）、胎心（太心）、胎芽（太芽）、胎盘（太盘）、羊水（杨水）、双顶径（双顶颈）、股骨长（骨股长）、肱骨长、头围、腹围、脐血流（其血流）、羊水指数、胎盘成熟度、前置胎盘、孕周。
乳腺：结节（节节）、肿块、钙化（盖化）、导管扩张、边界清晰或不清晰、形态规则或不规则、纵横比、血流信号（流血信号）、弹性成像、BI-RADS 分级、腋窝淋巴结（夜窝淋巴结）。
其他常见超声术语：低回声、强回声、无回声、混合性回声、肾盂分离、胆囊息肉、结石、脂肪肝、甲状腺结节、TI-RADS 分级。
2. 绝对不得改动数值、单位、左右侧等关键信息，不得增加或删除任何医学事实，包括不得在中英文与数字之间增删空格。
3. 保持句子数量与顺序，不合并、不拆分。
4. 只输出优化后的文本本身，不要任何解释、前缀或引号。
5. 若原文没有错误，或原文不是医学内容，直接将原文原样输出，包括用词、语序、数值写法与中英文间距均保持原样。
6. 任何情况下都只输出处理后的文本，绝不输出解释、提示、拒绝或评论。"""

NON_REPORT_MARKER = "【非报告内容】"

ENHANCE_SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告整理助手。输入是医生超声检查过程中口述录音的识别文本（已经过术语纠错），其中可能混杂着非报告内容，如对患者的指示、闲聊、与报告无关的对话。你的任务：只保留属于超声检查报告的内容，整理为规范的书面报告语句输出。要求：
1. 报告内容包括：检查所见（脏器位置、大小、回声、血流、测量数值等）与提示性诊断用语。非报告内容包括：对患者的指示（如"躺好""脱鞋""放松""屏住呼吸"）、医患闲聊、与检查无关的对话，一律删除，不在输出中保留或标注。
2. 绝对不得改动数值、单位、左右侧等关键信息，不得增加或删除任何医学事实，不得在中英文与数字之间增删空格。
3. 保持报告内容原有的句子顺序，不合并、不拆分。
4. 若输入中完全没有任何报告内容，只输出：【非报告内容】
5. 只输出整理后的报告文本本身（或【非报告内容】），不要任何解释、前缀、引号或评论。

示例1：
输入：来，躺上去，把衣服撩起来。子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。好了可以起来了。
输出：子宫前位，大小约8.2×6.5×7.1cm，肌层回声均匀。

示例2：
输入：东西放下脱鞋，脱裤子，往这边躺。
输出：【非报告内容】"""


def is_non_report(text: str | None) -> bool:
    """增强输出是否为"非报告内容"标记（容忍模型输出的轻微变体）。"""
    if not text:
        return False
    return "非报告" in text.strip()[:12]


FINAL_SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告医师。输入是一次超声检查过程中提取的全部报告内容句子（已经过术语纠错与内容筛选，按口述先后顺序排列，可能含有重复描述）。你的任务：将全部内容梳理为一份规范的书面超声报告，分【超声所见】与【超声提示】两节输出。要求：
1. 【超声所见】收录客观检查描述（脏器位置、大小、回声、血流、测量数值等）；【超声提示】收录结论性用语（含"考虑""可能""建议""符合""提示"等字样的句子）。若输入中没有结论性内容，只输出【超声所见】一节。
2. 只使用输入中明确存在的医学内容，绝不补充、推测、编造输入中没有的医学事实、数值或诊断；若输入中混入与报告无关的内容（如对患者的指示、闲聊），直接忽略。
3. 内容基本一致的重复描述只保留一次；同一项目重复测量且数值不一致时，全部数值都要保留（如"内膜厚约 8mm，后测约 9mm"），不得自行取舍。
4. 绝对不得改动数值、单位、左右侧等关键信息，不得在中英文与数字之间增删空格。
5. 两节标题各占一行，格式为【超声所见】和【超声提示】；节内为通顺的书面语句。
6. 只输出报告文本本身，不要任何解释、前缀或评论。"""


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
        return self._run(SYSTEM_PROMPT, text, stream)

    def enhance(self, text: str, stream: bool = False) -> str | None:
        return self._run(ENHANCE_SYSTEM_PROMPT, text, stream)

    def finalize(self, text: str) -> str:
        """整体梳理：把全部增强后内容整理为两段式完整报告。"""
        return self._run(FINAL_SYSTEM_PROMPT, text) or ""

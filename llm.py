"""Qwen 妇产科/乳腺科超声口述文本优化。"""
from __future__ import annotations

import torch

LLM_MODEL_ID = "Qwen/Qwen3.5-9B"

SYSTEM_PROMPT = """你是一名妇产科与乳腺科超声报告助手。输入是医生口述超声报告的语音识别结果，可能含有同音或近音识别错误。请优化为规范、通顺的超声医学书面用语。要求：
1. 纠正明显的同音/近音错别字，尤其是本专科医学术语，例如：妇产科（子宫、宫颈、内膜、卵巢、肌瘤、囊肿、盆腔积液、卵泡、胎儿、胎心、胎芽、羊水、胎盘、双顶径、股骨长、脐血流）、乳腺（结节、导管、钙化、边界、血流信号、BI-RADS 分级），以及其他常见超声术语（如肾盂、胆囊、肝、甲状腺等）。
2. 绝对不得改动数值、单位、左右侧等关键信息，不得增加或删除任何医学事实。
3. 保持句子数量与顺序，不合并、不拆分。
4. 只输出优化后的文本本身，不要任何解释、前缀或引号。
5. 若原文没有错误，或原文不是医学内容，直接将原文原样输出。
6. 任何情况下都只输出处理后的文本，绝不输出解释、提示、拒绝或评论。"""


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

    def optimize(self, text: str, stream: bool = False) -> str | None:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
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

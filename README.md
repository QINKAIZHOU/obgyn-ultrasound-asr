# 妇产科与乳腺科超声口述实时语音识别

本地部署 SeACo-Paraformer ASR（专科热词激励）+ Qwen3.5-9B 文本优化，面向妇产科 / 乳腺科超声口述报告。

## 功能

- `realtime` — 麦克风伪流式实时识别（FSMN-VAD 切段 + SeACo-Paraformer 热词识别 + 标点 + Qwen 三级优化，停止时输出整体报告）
- `file` — 音频文件转写（自动 VAD 分段，可输出 SRT 字幕与整体报告文本）
- `text` — 命令行文本模式（Qwen 优化，可批量或交互）

每个语音段输出三级结果：**原文**（ASR）→ **优化**（术语纠错）→ **增强**（提取纯报告内容，闲聊/指令显示为【非报告内容】）。会话结束后对全部报告内容做整体梳理，输出第四级**整体报告**（【超声所见】+【超声提示】两段式）。

ASR 层与 LLM 层形成"热词激励 + 术语纠错"双保险：SeACo-Paraformer 解码时用精选专科热词（超声/妇产科/乳腺，约 1000 条）做语义偏置，从源头减少同音错字；漏网错误再由 Qwen 第一级术语纠错兜底。

## 环境

- Windows 11 / Python 3.13 / NVIDIA RTX 5090 D
- 依赖：torch 2.11+cu128、funasr 1.4+、modelscope、transformers 5.x、sounddevice
- 首次运行自动从 ModelScope 下载模型至 `~/.cache/modelscope/`

## 安装

```bash
python -m venv .venv
.venv/Scripts/python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python -m pip install -r requirements.txt
```

## 使用

```bash
.venv/Scripts/python asr.py realtime                          # 麦克风实时识别（默认 SeACo+热词）
.venv/Scripts/python asr.py realtime --no-enhance             # 只要术语纠错（低延迟）
.venv/Scripts/python asr.py realtime --no-hotwords            # 关闭热词偏置
.venv/Scripts/python asr.py file test.wav --srt out.srt       # 文件转写 + 字幕（含全部内容）
.venv/Scripts/python asr.py file test.wav --report out.txt    # 输出整体报告（超声所见/提示两段式）
.venv/Scripts/python asr.py file test.wav --legacy-asr        # 回退旧版 Paraformer-large（A/B 对比）
.venv/Scripts/python asr.py text "子宫前位内幕厚约八毫米"      # 文本优化
.venv/Scripts/python asr.py text                              # 文本交互模式
```

热词相关开关（realtime / file 通用）：

- `--hotwords FILE` — 模型级热词文件（每行一词，默认 `hotwords/精选热词.txt`）
- `--no-hotwords` — 禁用语义热词偏置
- `--legacy-asr` — 回退旧版 Paraformer-large（自动禁用热词）
- `--postprocess-hotwords FILE` — （仅 file）文本级纠错映射（`错误词=>目标词`，默认关闭；开启时 SRT 时间轴可能轻微漂移）

热词表重建（从 `hotwords/解析结果/` 的 15 个医学词库 TSV 三层筛选生成）：

```bash
.venv/Scripts/python build_hotwords.py --check-chars --emit-postprocess-map
```

## 评测

```bash
.venv/Scripts/python eval_terms.py                            # LLM 术语/增强/整体验证集（28 条）
.venv/Scripts/python eval_asr.py --configs A,B,C,D            # ASR 级 A/B 评测（真实门诊录音）
.venv/Scripts/python eval_asr.py --limit-seconds 120          # 快速预览（每段截前 120s）
```

`eval_asr.py` 在无逐字真值下量化四配置（A 旧 Paraformer / B SeACo / C SeACo+热词 / D +纠错映射）：已知同音错字变体计数（↓，附上下文供人工复核）、规范术语命中（↑）、总字数、耗时 RTF、可选 CER（`--ref-dir` 提供参考文本时）。报告输出至 `eval_out/`。

首轮 A/B 结论（3 段真实门诊录音共 933s，2026-09-13）：

| 配置 | 错误变体↓ | 规范术语命中↑ | RTF |
|---|---|---|---|
| A 旧 Paraformer-large | 23 | 17 | 0.006 |
| B SeACo 无热词 | 23 | 17 | 0.005 |
| C SeACo+热词（默认） | 20 | 20 | 0.005 |
| D C+文本级纠错映射 | **15** | **26** | 0.005 |

- 引擎切换本身中性（B≈A，SeACo 即 Paraformer-large 加热词模块微调），价值在热词能力
- 热词在解码端纠正无歧义专科词（乱潮/卵朝→卵巢、芒肿→囊肿），无延迟代价
- 文本级映射再修复 乱抽/激瘤/回伸/晕超 等（D 较 A 错误 -35%），但可能使 SRT 时间轴轻微漂移，默认关闭，`--postprocess-hotwords hotwords/纠错映射.txt` 开启
- 剩余错误多为通用汉语合法词（前臂/基层/面膜/回升），须上下文判断，由 Qwen 第一级术语纠错兜底

## 项目结构

```
asr.py            # CLI 入口
pipeline.py       # 模型加载（SeACo-Paraformer 默认 / legacy 可回退）+ 热词加载 + 单段识别
modes.py          # realtime / file / text 三个模式实现
llm.py            # Qwen 优化器（术语纠错 + 报告内容增强 + 整体梳理 三级 prompt）
build_hotwords.py # 热词表构建（TSV 词库三层筛选 → hotwords/精选热词.txt + 纠错映射.txt）
eval_terms.py     # LLM 术语/增强/整体验证集（28 条用例）
eval_asr.py       # ASR 级 A/B 评测（错误变体/术语命中/RTF/可选 CER）
hotwords/         # 医学词库源 TSV（解析结果/）+ 生成的精选热词表
```

## 系统架构

```
输入源 → pipeline.py（SeACo-Paraformer + 精选热词激励 + FSMN-VAD + CT-Punc）→ ASR 原文
                                                       ↓
                              llm.py 第一级（术语纠错 SYSTEM_PROMPT）→ 优化文本
                                                       ↓
                       llm.py 第二级（报告内容增强 ENHANCE_SYSTEM_PROMPT）→ 纯报告文本
                                                       ↓
                              llm.py 第三级（整体梳理 FINAL_SYSTEM_PROMPT）→ 整体报告
                                                       ↓
                                          终端四段输出 / SRT / --report 文件
```

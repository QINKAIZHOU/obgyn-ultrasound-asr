# 妇产科与乳腺科超声口述实时语音识别

本地部署 Paraformer-large ASR + Qwen3.5-9B 文本优化，面向妇产科 / 乳腺科超声口述报告。

## 功能

- `realtime` — 麦克风伪流式实时识别（FSMN-VAD 切段 + Paraformer + 标点 + Qwen 两级优化）
- `file` — 音频文件转写（自动 VAD 分段，可输出 SRT 字幕与纯报告文本）
- `text` — 命令行文本模式（Qwen 优化，可批量或交互）

每个语音段输出三级结果：**原文**（ASR）→ **优化**（术语纠错）→ **增强**（提取纯报告内容，闲聊/指令显示为【非报告内容】）。

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
.venv/Scripts/python asr.py realtime                          # 麦克风实时识别
.venv/Scripts/python asr.py realtime --no-enhance             # 只要术语纠错（低延迟）
.venv/Scripts/python asr.py file test.wav --srt out.srt       # 文件转写 + 字幕（含全部内容）
.venv/Scripts/python asr.py file test.wav --report out.txt    # 额外输出纯报告文本
.venv/Scripts/python asr.py text "子宫前位内幕厚约八毫米"      # 文本优化
.venv/Scripts/python asr.py text                              # 文本交互模式
.venv/Scripts/python eval_terms.py                            # 术语/增强验证集回归
```

## 项目结构

```
asr.py            # CLI 入口
pipeline.py       # 模型加载 + 单段识别
modes.py          # realtime / file / text 三个模式实现
llm.py            # Qwen 优化器（术语纠错 + 报告内容增强 两级 prompt）
eval_terms.py     # 术语/增强验证集（25 条用例）
```

## 系统架构

```
输入源 → pipeline.py（Paraformer + FSMN-VAD + CT-Punc）→ ASR 原文
                                                       ↓
                              llm.py 第一级（术语纠错 SYSTEM_PROMPT）→ 优化文本
                                                       ↓
                       llm.py 第二级（报告内容增强 ENHANCE_SYSTEM_PROMPT）→ 纯报告文本
                                                       ↓
                                          终端三段输出 / SRT / --report 文件
```

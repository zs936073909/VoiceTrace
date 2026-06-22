# VoiceTrace 声迹

> **语音档案智能追踪系统 v3.0**
> 面向播音主持专业学习者及语音训练需求的桌面应用

[![Release](https://img.shields.io/github/v/release/zs936073909/VoiceTrace)](https://github.com/zs936073909/VoiceTrace/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## 简介

VoiceTrace 声迹是一款专为播音主持专业学生及语音训练需求者设计的桌面应用，集成了录音、智能分析、韵律评估、字级对齐、台风训练、文案写作等全流程训练工具。

## 核心功能

- 📝 **稿件管理** — 4 种分类（新闻播报/即兴评述/模拟主持/自定义），3 种语言，自定义语速标准
- 🎤 **专业录音** — WAV 16kHz 高质量录音，**空格键**一键标记卡顿，回放可快速跳转，支持删除录音
- 📊 **智能分析** — 自动计算语速、停顿、能量，判断是否符合行业标准；支持调用文本大模型生成个性化 AI 建议
- 🤖 **实时 AI 陪练（v3.2 新增）** — 边说边反馈：实时音量/语速/卡顿提示，片段结束后 AI 教练给出点评；支持 NVIDIA/OpenAI/DeepSeek/Moonshot/Anthropic/自定义接口
- 🎵 **韵律分析（v3.0 新增）** — 基于 Praat/Parselmouth 提取基频 F0、共振峰、强度、谐噪比 HNR、音调稳定性，绘制音调曲线
- 🎯 **字级对齐（v3.0 新增）** — 基于 faster-whisper 实现每个字/词的精确时间戳，标红漏读、慢读、快读
- 🎧 **跟读模式** — 选示范录音 → 跟读 → AI 对比相似度，给出改进建议，支持删除跟读录音
- 📈 **趋势追踪** — 多次录音的语速趋势图，可视化进步轨迹
- 📅 **训练打卡** — 日历视图 + 连续打卡统计，养成练习习惯
- 📤 **数据导出** — 支持 CSV / JSON / PDF 三种格式
- 🎬 **台风训练（v2.0 新增，v3.3 AI 增强）** — 基于 MediaPipe 的镜头感 + 肢体语言分析，支持站姿/坐姿双模式，6 维雷达图评分；新增 AI 实时点拨与整体总结，可选文本/多模态两种模式
- ✍️ **文案写作（v2.0 新增）** — 9 套专业模板 + AI 智能生成，兼容 OpenAI/DeepSeek/Moonshot/通义千问

## 截图

> 软件包含 11 个功能标签页：稿件管理 / 文案写作 / 录音 / 分析 / 跟读模式 / 对比 / 实时陪练 / 台风训练 / 训练打卡 / 导出

### v3.3 新增功能（AI 统一配置与台风训练增强）

#### 统一 AI 大模型配置

新增「设置 → AI 大模型设置」，全应用共享一套 LLM 配置：

- **文本模式**：只配置文本大模型，文案写作、语音分析建议、实时陪练点评、台风训练总结全部基于结构化数据调用文本 LLM。
- **多模态模式**：在文本模型基础上启用多模态模型，台风训练结束时会额外截取一帧画面交给 GPT-4V / Claude 等模型做视觉分析。
- **本地兜底**：未配置 API 或网络异常时，自动切换到内置规则生成建议，保证软件始终可用。
- **多服务商支持**：NVIDIA NIM / OpenAI / DeepSeek / Moonshot / Anthropic / 自定义 OpenAI 兼容接口。

#### 台风训练 AI 教练

- **AI 实时点拨**：训练过程中每 5 秒基于最近的眼神、表情、姿态数据调用文本 LLM 生成一句具体调整建议（不阻塞 UI）。
- **AI 整体总结**：训练结束后基于完整数据生成整体评价 + 改进建议 + 针对性练习。
- **多模态画面分析**（仅多模态模式启用）：对训练画面进行视觉点评，指出体态、镜头感等具体问题。
- **模式状态提示**：界面上实时显示当前是「文本模式 / 多模态模式 / 本地规则模式」。

#### 语音分析 AI 建议

- 分析视图新增「获取 AI 建议」按钮，基于语速、卡顿、韵律、字级对齐等结构化数据调用文本 LLM 生成个性化训练反馈。

### v3.2 新增功能

#### 实时 AI 陪练

借鉴 RealtimeSTT / whisper_streaming 的滑动窗口 + VAD 断句思路，基于项目已有依赖实现边说边反馈：

- **实时仪表盘**：音量电平、当前语速、状态提示同步刷新
- **实时转写**：基于 faster-whisper + WebRTC VAD，说完一段话后立即显示识别文本
- **AI 教练点评**：每说完一段话，自动调用 LLM 生成整体评价 + 改进建议 + 针对性练习
- **多模型支持**：默认 NVIDIA NIM，同时兼容 OpenAI / DeepSeek / Moonshot / Anthropic / 自定义 OpenAI 兼容接口
- **本地 fallback**：未配置 LLM 时，自动使用本地规则给出反馈

#### 稳定性与交互优化

- 录音面板：新增实时音量电平、删除录音按钮、可滚动稿件预览
- 跟读模式：新增实时音量电平、删除跟读录音按钮、可滚动示范稿件预览
- 文案写作：模板描述、空状态提示、占位符提示更直观
- 分析视图：新增 AI 教练配置区，基于分析结果调用 LLM 生成智能建议

### v3.0 新增功能

#### 韵律分析

分析标签页新增「韵律分析」子标签，展示：

| 指标 | 含义 |
|---|---|
| 平均基频 (Hz) | 声音音高高低 |
| 基频标准差 | 语调起伏丰富度 |
| 基频范围 | 最高音与最低音差距 |
| 上升/下降段数 | 语调变化次数 |
| 平均强度 (dB) | 声音响度 |
| 强度动态范围 | 声音强弱变化 |
| F1/F2/F3 共振峰 | vowel 音色与口腔位置 |
| 谐噪比 HNR | 声音清晰度 |
| 声调稳定性/得分 | 中文普通话声调质量 |

#### 字级对齐

分析标签页新增「字级对齐」子标签：

- 用 **faster-whisper** 识别音频并生成字/词级时间戳
- 通过最小编辑距离将识别文本映射回原始稿件
- 每个字/词显示为时间块，长度代表读音时长
- **绿色**：正常识别；**红色**：漏读或识别缺失
- 可快速定位读得快、读得慢、读漏的字

## 快速开始

### 方式一：使用便携版（推荐普通用户）

1. 前往 [Releases](../../releases) 下载最新的 `VoiceTrace-v3.1.0-portable.zip`
2. 解压到任意目录
3. 双击 `VoiceTrace.exe` 运行

### 方式二：从源码运行（推荐开发者）

```bash
# 1. 克隆仓库
git clone https://github.com/zs936073909/VoiceTrace.git
cd VoiceTrace

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python main.py
```

**系统要求**：Python 3.10+，Windows 10/11 64 位

## v3.0 新增功能详解

### 韵律分析

基于 Praat 声学分析引擎，对录音进行专业级韵律评估：

- **基频 F0 曲线**：反映音高变化，可用于诊断语调平淡或过度起伏
- **共振峰 F1/F2/F3**：反映元音音色和口腔共鸣位置
- **强度曲线**：反映声音强弱变化，评估重音和情感表达
- **谐噪比 HNR**：衡量声音清晰度，数值越高越"干净"
- **声调稳定性/声调得分**：针对中文普通话的声调质量评估

### v2.0 功能回顾

#### 台风训练

通过摄像头实时分析你的**镜头感**和**肢体语言**：

| 维度 | 说明 |
|---|---|
| 眼神交流 | 虹膜追踪，判断是否直视镜头 |
| 表情管理 | 微笑度 + 紧张度识别 |
| 头部姿态 | yaw/pitch/roll 三维估计 |
| 站姿/坐姿 | 站姿检测倾斜，坐姿额外检测探颈 |
| 手势 | 手腕运动幅度分析 |
| 稳定性 | 身体晃动幅度 |

支持**站姿**和**坐姿**两种模式。

#### 文案写作

- **模板生成**：9 套专业模板（新闻播报、即兴评述、模拟主持、演讲），离线可用
- **AI 智能生成**：支持任何兼容 OpenAI 格式的 API（DeepSeek、Moonshot、通义千问等）
- **保存为稿件**：一键导入稿件管理，方便后续录音练习

## 功能特性

| 模块 | 核心功能 |
|---|---|
| 稿件管理 | 新建/编辑/删除、4 种分类、3 种语言、自定义语速标准 |
| 录音 | WAV 16kHz、空格标记卡顿、Ctrl+R 快捷键、降噪选项、回放跳转 |
| 分析 | 语速/卡顿/能量/**韵律**、标准检查、语速趋势图、波形图、逐句分析、音调曲线 |
| 跟读模式 | 示范播放 → 跟读录制 → MFCC 相似度对比 → 改进报告 |
| 对比 | 任意两条录音对比，相似度 + 语速差 + 卡顿差 |
| 训练打卡 | 统计卡片、打卡日历、手动打卡、训练记录表 |
| 导出 | CSV / JSON / PDF，可导出分析/稿件/对比记录 |
| 台风训练 | 6 维评分、雷达图可视化、坐姿/站姿双模式、训练历史 |
| 文案写作 | 模板库 + AI 生成、双语支持、一键保存为稿件 |

## 内置语速标准

| 分类 | 中文 (CPM) | 英文 (WPM) |
|---|---|---|
| 新闻播报 | 250–300 | 170–190 |
| 即兴评述 | 200–280 | 140–180 |
| 模拟主持 | 220–300 | 150–190 |

> 可在「稿件管理 → 自定义标准」中添加你自己的语速区间。

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+R` | 开始/停止录音 |
| `空格` | 标记卡顿（录音中） |
| `Ctrl+D` | 切换浅色/深色主题 |

## 技术栈

| 组件 | 技术 |
|---|---|
| 界面框架 | PySide6 (Qt 6) |
| 音频分析 | librosa、webrtcvad、pydub |
| 韵律分析 | Parselmouth（Praat） |
| 强制对齐 | faster-whisper + 最小编辑距离 |
| 台风分析 | MediaPipe Face Landmarker + Pose Landmarker |
| 机器学习 | scikit-learn（余弦相似度） |
| 实时 AI 陪练 | faster-whisper + WebRTC VAD |
| AI 服务 | NVIDIA NIM / OpenAI / DeepSeek / Moonshot / Anthropic / 自定义 |
| 多模态分析 | GPT-4V / Claude / 兼容 OpenAI Vision 的 API |
| 数据库 | SQLite 3 |
| 报告导出 | reportlab（PDF）、原生 CSV/JSON |
| 打包 | PyInstaller |

## 项目结构

```
voicetrace/
├── main.py                    # 程序入口（一键启动：python main.py）
├── requirements.txt           # 依赖列表
├── build_windows.py           # PyInstaller 打包脚本
├── config/
│   ├── llm_config.json        # AI 大模型配置（自动生成）
│   └── script_templates.json  # 文案模板库
├── core/                      # 核心算法
│   ├── analyzer.py            # 音频分析（语速、卡顿、MFCC、降噪、韵律、对齐）
│   ├── comparator.py          # 相似度对比
│   ├── standards.py           # 语速标准
│   ├── prosody_analyzer.py    # 韵律分析（F0、共振峰、HNR）
│   ├── aligner.py             # 强制对齐（字/词级时间戳）
│   ├── posture_analyzer.py    # 面部分析（眼神、表情、头部姿态）
│   ├── pose_analyzer.py       # 身体姿态分析（站/坐姿、手势、稳定性）
│   ├── posture_ai_coach.py    # 台风训练 AI 教练（文本+多模态）
│   ├── realtime_coach.py      # 实时 AI 陪练核心
│   ├── llm_service.py         # 统一 LLM/多模态服务层
│   ├── llm_config_manager.py  # 全局 LLM 配置管理
│   ├── feedback_generator.py  # 分析结果 → AI 建议
│   └── script_writer.py       # 文案生成
├── data/                      # 数据层
│   ├── database.py            # SQLite CRUD
│   └── models.py              # 数据模型
├── ui/                        # 界面层
│   ├── main_window.py         # 主窗口
│   ├── script_manager.py      # 稿件管理
│   ├── recording_panel.py     # 录音面板
│   ├── analysis_view.py       # 分析视图（波形图、趋势图、逐句、韵律）
│   ├── follow_read_view.py    # 跟读模式
│   ├── comparison_view.py     # 对比视图
│   ├── realtime_coach_view.py # 实时 AI 陪练界面
│   ├── progress_view.py       # 训练打卡
│   ├── export_dialog.py       # 导出对话框
│   ├── llm_settings_dialog.py # AI 大模型统一设置
│   ├── camera_view.py         # 摄像头预览
│   ├── posture_view.py        # 台风训练视图
│   ├── radar_chart.py         # 雷达图组件
│   ├── script_writer_view.py  # 文案写作界面
│   └── styles.py              # QSS 样式（浅色/深色）
├── utils/                     # 工具
│   ├── audio.py               # 中英文字数统计
│   └── export.py              # CSV/JSON/PDF 导出
├── scripts/                   # 工具脚本
│   └── download_models.py     # 下载 MediaPipe 模型
├── tests/                     # 测试
│   ├── test_smoke.py             # 冒烟测试
│   ├── test_features.py          # 功能测试
│   ├── test_prosody.py           # 韵律分析测试
│   ├── test_alignment.py         # 强制对齐测试
│   ├── test_robustness.py        # 稳定性测试
│   └── test_posture_ai_coach.py  # 台风训练 AI 教练测试
└── models/                    # MediaPipe 模型文件
    ├── face_landmarker.task
    └── pose_landmarker_lite.task
```

## 从源码打包

```bash
# 1. 安装打包依赖
pip install pyinstaller

# 2. PyInstaller 打包
python build_windows.py

# 输出：dist/VoiceTrace/VoiceTrace.exe
```

## 数据存储

- 数据目录：`C:\Users\你的用户名\.voicetrace\`
  - `broadcast.db` — SQLite 数据库
  - `recordings/` — WAV 录音文件
- 卸载软件**不会**删除数据

## 许可证

MIT License — 可自由使用、修改、分发

## 致谢

- 基于 mimocode 2.5pro 开发第一版，trae glm5.2 开发第二版以及架构优化
- 第三版（韵律分析、强制对齐、台风训练、AI 统一配置与教练、稳定性优化）由 trae Kimi Code 2.7 制作
- 所有开源依赖库的作者

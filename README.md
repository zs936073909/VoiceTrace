# VoiceTrace 声迹

> **语音档案智能追踪系统** — 面向播音主持专业学习者及语音训练需求的桌面应用

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-6.6+-green.svg)](https://www.qt.io)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blueviolet.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 简介

VoiceTrace（声迹）是一款专为播音主持专业学生（如浙江传媒大学双播专业）及有语音训练需求的用户设计的桌面应用。它能帮你：

- 📝 **管理稿件** — 分类管理新闻播报、即兴评述、模拟主持等训练稿件
- 🎙️ **录音标记** — 录音时一键标记卡顿点，回放可快速跳转
- 📊 **智能分析** — 自动计算语速、停顿、能量，判断是否符合行业标准
- 🎧 **跟读模式** — 选示范录音 → 跟读 → AI 对比相似度，给出改进建议
- 📈 **趋势追踪** — 多次录音的语速趋势图，可视化进步轨迹
- 📅 **训练打卡** — 日历视图 + 连续打卡统计，养成练习习惯
- 📤 **数据导出** — 支持 CSV / JSON / PDF 三种格式

## 截图

> 软件包含 7 个功能标签页：稿件管理 / 录音 / 分析 / 跟读模式 / 对比 / 训练打卡 / 导出

## 快速开始

### 方式一：使用安装包（推荐普通用户）

1. 前往 [Releases](../../releases) 下载最新的 `VoiceTrace_Setup_v1.0.0.exe`
2. 双击安装
3. 参考随包附带的「使用指南.md」

### 方式二：从源码运行（推荐开发者）

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/VoiceTrace.git
cd VoiceTrace

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python main.py
```

**系统要求**：Python 3.10+，Windows 10/11 64 位

## 功能特性

| 模块 | 核心功能 |
|---|---|
| 稿件管理 | 新建/编辑/删除、4 种分类、3 种语言、自定义语速标准 |
| 录音 | WAV 16kHz、空格标记卡顿、Ctrl+R 快捷键、降噪选项、回放跳转 |
| 分析 | 语速/卡顿/能量、标准检查、语速趋势图、波形图、逐句分析 |
| 跟读模式 | 示范播放 → 跟读录制 → MFCC 相似度对比 → 改进报告 |
| 对比 | 任意两条录音对比，相似度 + 语速差 + 卡顿差 |
| 训练打卡 | 统计卡片、打卡日历、手动打卡、训练记录表 |
| 导出 | CSV / JSON / PDF，可导出分析/稿件/对比记录 |

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
| 机器学习 | scikit-learn（余弦相似度） |
| 数据库 | SQLite 3 |
| 报告导出 | reportlab（PDF）、原生 CSV/JSON |
| 打包 | PyInstaller + Inno Setup |

## 项目结构

```
voicetrace/
├── main.py                  # 程序入口
├── requirements.txt         # 依赖列表
├── build_windows.py         # PyInstaller 打包脚本
├── voicetrace_installer.iss # Inno Setup 安装包脚本
├── config/
│   └── defaults.json        # 默认配置
├── core/                    # 核心算法
│   ├── analyzer.py          # 音频分析（语速、卡顿、MFCC、降噪）
│   ├── comparator.py        # 相似度对比
│   └── standards.py         # 语速标准
├── data/                    # 数据层
│   ├── database.py          # SQLite CRUD
│   └── models.py            # 数据模型
├── ui/                      # 界面层
│   ├── main_window.py       # 主窗口
│   ├── script_manager.py    # 稿件管理
│   ├── recording_panel.py   # 录音面板
│   ├── analysis_view.py     # 分析视图（波形图、趋势图、逐句）
│   ├── follow_read_view.py  # 跟读模式
│   ├── comparison_view.py   # 对比视图
│   ├── progress_view.py     # 训练打卡
│   ├── export_dialog.py     # 导出对话框
│   └── styles.py            # QSS 样式（浅色/深色）
├── utils/                   # 工具
│   ├── audio.py             # 中英文字数统计
│   └── export.py            # CSV/JSON/PDF 导出
└── tests/                   # 测试
    ├── test_smoke.py        # 冒烟测试
    └── test_features.py     # 功能测试
```

## 从源码打包

```bash
# 1. 安装打包依赖
pip install pyinstaller inno-setup

# 2. PyInstaller 打包
python build_windows.py

# 3. 生成安装包（需 Inno Setup 6）
ISCC.exe voicetrace_installer.iss
# 输出：installer_output/VoiceTrace_Setup_v1.0.0.exe
```

## 数据存储

- 数据目录：`C:\Users\你的用户名\.voicetrace\`
  - `broadcast.db` — SQLite 数据库
  - `recordings/` — WAV 录音文件
- 卸载软件**不会**删除数据

## 许可证

MIT License — 可自由使用、修改、分发

## 致谢

- 浙江传媒大学双播专业的需求启发
- 所有开源依赖库的作者

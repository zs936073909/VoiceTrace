"""实时 AI 陪练界面

基于 core/realtime_coach 的实时音频处理能力，
提供边说边反馈的可视化训练界面。
"""
from pathlib import Path
from typing import Optional

import numpy as np

from PySide6.QtCore import Qt, QUrl, QIODevice, QByteArray
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QMessageBox, QGroupBox, QTextEdit, QProgressBar, QLineEdit, QSplitter
)

from voicetrace.data.database import Database
from voicetrace.core.realtime_coach import RealtimeCoach
from voicetrace.core.llm_service import LLMConfig, get_default_api_url, get_default_model


class RealtimeCoachView(QWidget):
    """实时 AI 陪练视图"""

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.coach: Optional[RealtimeCoach] = None

        self._audio_source = None
        self._audio_io = None
        self._audio_format = None

        self._setup_ui()
        self._load_scripts()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("实时 AI 陪练")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel("边说边反馈：语速、音量、卡顿实时提示，片段结束后 AI 教练给出点评。")
        subtitle.setObjectName("writerSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        splitter = QSplitter(Qt.Vertical)
        layout.addWidget(splitter, 1)

        # ---- 上部：配置与控制 ----
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        # 稿件选择
        script_group = QGroupBox("练习稿件")
        script_layout = QVBoxLayout(script_group)
        script_select_layout = QHBoxLayout()
        script_select_layout.addWidget(QLabel("选择稿件:"))
        self.script_combo = QComboBox()
        self.script_combo.setMinimumWidth(240)
        self.script_combo.currentIndexChanged.connect(self._on_script_changed)
        script_select_layout.addWidget(self.script_combo, 1)
        script_select_layout.addStretch()
        script_layout.addLayout(script_select_layout)

        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setPlaceholderText("选择稿件后将在此显示全文...")
        self.script_preview.setMaximumHeight(140)
        script_layout.addWidget(self.script_preview)
        top_layout.addWidget(script_group)

        # LLM 配置
        llm_group = QGroupBox("AI 教练配置（默认 NVIDIA）")
        llm_layout = QHBoxLayout(llm_group)
        llm_layout.addWidget(QLabel("服务商:"))
        self.llm_provider_combo = QComboBox()
        self.llm_provider_combo.addItems(["NVIDIA", "OpenAI", "DeepSeek", "Moonshot", "Anthropic", "自定义"])
        for idx, provider in enumerate(["nvidia", "openai", "deepseek", "moonshot", "anthropic", "custom"]):
            self.llm_provider_combo.setItemData(idx, provider)
        self.llm_provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        llm_layout.addWidget(self.llm_provider_combo)

        llm_layout.addWidget(QLabel("API Key:"))
        self.llm_key_edit = QLineEdit()
        self.llm_key_edit.setEchoMode(QLineEdit.Password)
        self.llm_key_edit.setPlaceholderText("nvapi-xxx")
        self.llm_key_edit.setMinimumWidth(160)
        llm_layout.addWidget(self.llm_key_edit)

        llm_layout.addWidget(QLabel("模型:"))
        self.llm_model_edit = QLineEdit()
        self.llm_model_edit.setPlaceholderText("meta/llama3-70b-instruct")
        self.llm_model_edit.setMinimumWidth(160)
        llm_layout.addWidget(self.llm_model_edit)

        self.llm_url_edit = QLineEdit()
        self.llm_url_edit.setPlaceholderText("API 地址")
        self.llm_url_edit.setMinimumWidth(200)
        self.llm_url_edit.setVisible(False)
        llm_layout.addWidget(self.llm_url_edit)
        llm_layout.addStretch()
        top_layout.addWidget(llm_group)

        # 控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始陪练")
        self.start_btn.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px 24px;")
        self.start_btn.clicked.connect(self._start_coaching)
        self.stop_btn = QPushButton("停止陪练")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_coaching)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-size: 14px; color: #27ae60;")
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()
        top_layout.addLayout(control_layout)

        # 实时仪表盘
        meter_layout = QHBoxLayout()

        # 音量
        vol_box = QGroupBox("输入音量")
        vol_layout = QVBoxLayout(vol_box)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        self.level_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #d4cfc4; border-radius: 4px; background: #f0ebe2; height: 20px; } "
            "QProgressBar::chunk { background: #27ae60; border-radius: 4px; }"
        )
        vol_layout.addWidget(self.level_bar)
        self.level_value_label = QLabel("-inf dB")
        self.level_value_label.setAlignment(Qt.AlignCenter)
        vol_layout.addWidget(self.level_value_label)
        meter_layout.addWidget(vol_box, 1)

        # 语速
        rate_box = QGroupBox("当前语速")
        rate_layout = QVBoxLayout(rate_box)
        self.rate_label = QLabel("--")
        self.rate_label.setAlignment(Qt.AlignCenter)
        self.rate_label.setStyleSheet("font-size: 28px; font-weight: bold;")
        rate_layout.addWidget(self.rate_label)
        self.rate_unit_label = QLabel("CPM/WPM")
        self.rate_unit_label.setAlignment(Qt.AlignCenter)
        rate_layout.addWidget(self.rate_unit_label)
        meter_layout.addWidget(rate_box, 1)

        # 卡顿提示
        pause_box = QGroupBox("状态提示")
        pause_layout = QVBoxLayout(pause_box)
        self.hint_label = QLabel("等待开始...")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("font-size: 16px; color: #7f8c8d;")
        pause_layout.addWidget(self.hint_label)
        meter_layout.addWidget(pause_box, 2)

        top_layout.addLayout(meter_layout)
        splitter.addWidget(top_widget)

        # ---- 下部：识别文本与 AI 反馈 ----
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(12)

        # 实时转写
        transcript_group = QGroupBox("实时转写")
        transcript_layout = QVBoxLayout(transcript_group)
        self.transcript_text = QTextEdit()
        self.transcript_text.setReadOnly(True)
        self.transcript_text.setPlaceholderText("你说的话会实时显示在这里...")
        transcript_layout.addWidget(self.transcript_text)
        bottom_layout.addWidget(transcript_group, 1)

        # AI 反馈
        feedback_group = QGroupBox("AI 教练反馈")
        feedback_layout = QVBoxLayout(feedback_group)
        self.feedback_text = QTextEdit()
        self.feedback_text.setReadOnly(True)
        self.feedback_text.setPlaceholderText("每说完一段话，AI 教练会在这里给出点评...")
        feedback_layout.addWidget(self.feedback_text)
        bottom_layout.addWidget(feedback_group, 1)

        splitter.addWidget(bottom_widget)
        splitter.setSizes([450, 350])

        # 初始化 provider 默认配置
        self._on_provider_changed(0)

    def _load_scripts(self):
        """加载稿件列表"""
        self.script_combo.clear()
        self.script_combo.addItem("-- 不指定稿件（自由练习） --", None)
        try:
            scripts = self.db.get_all_scripts()
            for script in scripts:
                self.script_combo.addItem(f"{script.title} ({script.language})", script)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法加载稿件列表: {e}")

    def _on_script_changed(self, index: int):
        """切换稿件"""
        script = self.script_combo.itemData(index)
        if script:
            self.script_preview.setPlainText(script.content)
        else:
            self.script_preview.clear()

    def _on_provider_changed(self, index: int):
        """LLM 服务商切换"""
        provider = self.llm_provider_combo.itemData(index) or "nvidia"
        is_custom = provider == "custom"
        self.llm_url_edit.setVisible(is_custom)
        if is_custom:
            self.llm_url_edit.setText("")
            self.llm_model_edit.setPlaceholderText("模型名称")
        else:
            self.llm_url_edit.setText(get_default_api_url(provider))
            default_model = get_default_model(provider)
            self.llm_model_edit.setPlaceholderText(default_model)
            if not self.llm_model_edit.text():
                self.llm_model_edit.setText(default_model)

    def _build_llm_config(self) -> Optional[LLMConfig]:
        """从 UI 构建 LLM 配置"""
        api_key = self.llm_key_edit.text().strip()
        if not api_key:
            return None
        provider = self.llm_provider_combo.itemData(self.llm_provider_combo.currentIndex()) or "nvidia"
        return LLMConfig(
            provider=provider,
            api_key=api_key,
            model=self.llm_model_edit.text().strip() or get_default_model(provider),
            api_url=self.llm_url_edit.text().strip() or get_default_api_url(provider),
            temperature=0.6,
            max_tokens=1200
        )

    def _start_coaching(self):
        """开始实时陪练"""
        if self.coach is not None:
            self._stop_coaching()

        script = self.script_combo.currentData()
        script_text = script.content if script else ""
        language = script.language if script else "chinese"

        llm_config = self._build_llm_config()
        if llm_config is None:
            reply = QMessageBox.question(
                self,
                "未配置 LLM",
                "没有填写 API Key，将只使用本地规则反馈。\n是否继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        try:
            self.coach = RealtimeCoach(
                language=language,
                llm_config=llm_config,
                feedback_interval=1,
                script_text=script_text
            )
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"无法创建实时陪练: {e}")
            return

        # 连接信号
        self.coach.signals.frame_ready.connect(self._on_frame)
        self.coach.signals.utterance_ready.connect(self._on_utterance)
        self.coach.signals.feedback_ready.connect(self._on_feedback)
        self.coach.signals.status_changed.connect(self._on_status)
        self.coach.signals.error_occurred.connect(self._on_error)

        # 启动音频采集
        fmt = QAudioFormat()
        fmt.setSampleRate(self.coach.SAMPLE_RATE)
        fmt.setChannelCount(self.coach.CHANNELS)
        fmt.setSampleFormat(QAudioFormat.Int16)
        self._audio_format = fmt

        default_device = QMediaDevices.defaultAudioInput()
        if not default_device:
            QMessageBox.critical(self, "无麦克风", "未检测到麦克风设备")
            self.coach = None
            return

        self._audio_source = QAudioSource(default_device, fmt, self)
        self._audio_io = self._audio_source.start()
        self._audio_io.readyRead.connect(self._on_audio_data)

        self.coach.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.transcript_text.clear()
        self.feedback_text.clear()

    def _on_audio_data(self):
        """音频数据到达"""
        if self._audio_io and self.coach:
            data = self._audio_io.readAll()
            self.coach.feed_audio(data.data())

    def _stop_coaching(self):
        """停止实时陪练"""
        if self.coach:
            self.coach.stop()
            self.coach = None

        if self._audio_source:
            self._audio_source.stop()
            self._audio_source = None
            self._audio_io = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.level_bar.setValue(0)
        self.level_value_label.setText("-inf dB")
        self.rate_label.setText("--")
        self.hint_label.setText("已停止")
        self.hint_label.setStyleSheet("font-size: 16px; color: #7f8c8d;")

    def _on_frame(self, frame):
        """实时帧更新"""
        self.level_bar.setValue(int(frame.level))
        self.level_value_label.setText(f"{frame.db:.0f} dB")

        # 电平颜色
        if frame.level > 90:
            color = "#c0392b"
        elif frame.level > 60:
            color = "#f39c12"
        else:
            color = "#27ae60"
        self.level_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid #d4cfc4; border-radius: 4px; background: #f0ebe2; height: 20px; }} "
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )

        unit = "CPM" if self.coach and self.coach.language == "chinese" else "WPM"
        self.rate_unit_label.setText(unit)
        self.rate_label.setText(f"{frame.instant_rate:.0f}")

        # 提示
        hints = []
        if frame.level < 10:
            hints.append("音量太小，请靠近麦克风")
        elif frame.level > 92:
            hints.append("音量过大，注意保护嗓子")

        if frame.instant_rate > 300:
            hints.append("语速偏快，试着放慢")
        elif frame.instant_rate > 0 and frame.instant_rate < 150:
            hints.append("语速偏慢，保持流畅")

        if frame.is_speech:
            hints.append("正在监听...")

        if hints:
            self.hint_label.setText(" / ".join(hints[:2]))
            self.hint_label.setStyleSheet("font-size: 16px; color: #2c3e50;")
        else:
            self.hint_label.setText("状态良好，继续")
            self.hint_label.setStyleSheet("font-size: 16px; color: #27ae60;")

    def _on_utterance(self, utterance):
        """一段话说完，更新转写"""
        text = f"[{utterance.start_time:.1f}s - {utterance.end_time:.1f}s] {utterance.text}"
        self.transcript_text.append(text)

    def _on_feedback(self, feedback_text: str):
        """LLM 反馈到达"""
        self.feedback_text.setMarkdown(feedback_text)

    def _on_status(self, status: str):
        """状态文字"""
        self.status_label.setText(status)

    def _on_error(self, error: str):
        """错误处理"""
        QMessageBox.warning(self, "实时陪练错误", error)

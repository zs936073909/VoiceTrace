import json
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider, QGroupBox, QCheckBox, QTextEdit, QLineEdit
)
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QScatterSeries
from PySide6.QtCore import Qt, QUrl, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from voicetrace.data.database import Database
from voicetrace.core.analyzer import Analyzer
from voicetrace.core.standards import get_standard, check_rate
from voicetrace.core.feedback_generator import FeedbackGenerator
from voicetrace.core.llm_config_manager import get_llm_config_manager
from voicetrace.ui.llm_settings_dialog import show_llm_settings
from voicetrace.data.models import Analysis


class WaveformWidget(QWidget):
    """简易波形显示组件"""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)
        self._waveform = []
        self._stumbles = []

    def set_waveform(self, data: list, stumbles: list = None):
        self._waveform = data
        self._stumbles = stumbles or []
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QColor, QBrush
        from PySide6.QtCore import QRectF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        mid = h / 2

        # 背景
        painter.fillRect(self.rect(), QColor("#faf9f6"))

        # 中线
        painter.setPen(QPen(QColor("#d4cfc4"), 1))
        painter.drawLine(0, mid, w, mid)

        if not self._waveform:
            painter.setPen(QColor("#999999"))
            painter.drawText(self.rect(), Qt.AlignCenter, "分析后显示波形")
            return

        # 绘制波形
        n = len(self._waveform)
        step = w / n if n > 0 else 1
        painter.setPen(QPen(QColor("#c0392b"), 1))

        for i, val in enumerate(self._waveform):
            x = i * step
            bar_h = abs(val) * (h * 0.45)
            if val >= 0:
                painter.drawLine(int(x), int(mid), int(x), int(mid - bar_h))
            else:
                painter.drawLine(int(x), int(mid), int(x), int(mid + bar_h))

        # 绘制卡顿标记
        if self._stumbles:
            painter.setPen(QPen(QColor("#e74c3c"), 2))
            for s in self._stumbles:
                # 假设波形时长对应录音时长
                if self._waveform:
                    x_ratio = s.stumble_time / (len(self._waveform) * 0.01)  # 近似
                    x = min(x_ratio * w, w - 1)
                    painter.drawLine(int(x), 0, int(x), h)


class AlignmentWidget(QWidget):
    """字级/词级对齐可视化组件"""

    # 颜色
    COLOR_NORMAL = QColor("#27ae60")
    COLOR_MISSING = QColor("#e74c3c")
    COLOR_BG = QColor("#faf9f6")
    COLOR_BORDER = QColor("#d4cfc4")

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(200)
        self._alignment = None
        self._duration = 0.0
        self._row_height = 32
        self._token_width_min = 24
        self._margin = 20

    def set_alignment(self, alignment: dict, duration: float = 0.0):
        self._alignment = alignment
        self._duration = duration
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        painter.fillRect(self.rect(), self.COLOR_BG)

        if not self._alignment or not self._alignment.get("sentences"):
            painter.setPen(QColor("#999999"))
            painter.drawText(self.rect(), Qt.AlignCenter, "分析后显示字级对齐（需 faster-whisper 模型）")
            return

        # 计算总时长
        sentences = self._alignment["sentences"]
        end_times = []
        for s in sentences:
            for t in s.get("tokens", []):
                if t.get("end_time"):
                    end_times.append(t["end_time"])
        total_duration = self._duration or (max(end_times) if end_times else 1.0)
        if total_duration <= 0:
            total_duration = 1.0

        # 可用宽度
        usable_w = w - 2 * self._margin

        y = self._margin
        for s in sentences:
            # 句子标签
            painter.setPen(QColor("#333333"))
            painter.setFont(QFont("Microsoft YaHei", 9))
            painter.drawText(self._margin, y - 5, f"[{s.get('start_time', 0):.2f}s] {s.get('text', '')[:30]}")
            y += 18

            # 绘制每个 token
            x = self._margin
            row_start_y = y
            max_h_in_row = 0
            for t in s.get("tokens", []):
                start = t.get("start_time", 0.0)
                end = t.get("end_time", 0.0)
                text = t.get("text", "")
                is_missing = t.get("is_missing", False)

                if is_missing or end <= start:
                    # 缺失 token：固定宽度，红色
                    box_w = max(self._token_width_min, painter.fontMetrics().horizontalAdvance(text) + 12)
                    color = self.COLOR_MISSING
                else:
                    # 按时间比例计算宽度
                    ratio = (end - start) / total_duration
                    box_w = max(self._token_width_min, ratio * usable_w)
                    color = self.COLOR_NORMAL

                # 换行
                if x + box_w > w - self._margin:
                    x = self._margin
                    y += max_h_in_row + 8
                    row_start_y = y
                    max_h_in_row = 0

                # 绘制圆角矩形
                rect = QRectF(x, y, box_w, self._row_height)
                painter.setPen(QPen(self.COLOR_BORDER, 1))
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(rect, 4, 4)

                # 绘制文字
                painter.setPen(QColor("#ffffff"))
                fm = painter.fontMetrics()
                text_w = fm.horizontalAdvance(text)
                if text_w > box_w - 4:
                    # 文字太长则截断
                    text = text[:max(1, len(text) - 2)] + "…"
                    text_w = fm.horizontalAdvance(text)
                text_x = x + (box_w - text_w) / 2
                text_y = y + (self._row_height + fm.ascent() - fm.descent()) / 2
                painter.drawText(int(text_x), int(text_y), text)

                # 绘制时间提示（hover 效果简化：直接显示在下方）
                if not is_missing and end > start:
                    painter.setPen(QColor("#666666"))
                    painter.setFont(QFont("Microsoft YaHei", 7))
                    time_text = f"{end-start:.2f}s"
                    painter.drawText(int(x + 2), int(y + self._row_height + 12), time_text)
                    painter.setFont(QFont("Microsoft YaHei", 9))

                x += box_w + 6
                max_h_in_row = max(max_h_in_row, self._row_height + 14)

            y += max_h_in_row + 16

        # 调整最小高度
        min_h = y + self._margin
        if min_h > self.minimumHeight():
            self.setMinimumHeight(min_h)


class AnalysisView(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.analyzer = Analyzer()
        self.feedback_generator = FeedbackGenerator()
        self.llm_manager = get_llm_config_manager()
        self._last_analysis_result: Optional[dict] = None
        self._last_script = None
        self._current_recording_path = None
        self._current_recording_id = None

        # 回放
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_playback_position)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 录音选择
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("选择录音:"))
        self.recording_combo = QComboBox()
        self.recording_combo.setMinimumWidth(300)
        select_layout.addWidget(self.recording_combo)
        self.analyze_btn = QPushButton("分析")
        select_layout.addWidget(self.analyze_btn)
        self.denoise_check = QCheckBox("降噪")
        self.denoise_check.setToolTip("分析时启用谱减降噪（适用于有环境噪声的录音）")
        select_layout.addWidget(self.denoise_check)
        select_layout.addStretch()
        layout.addLayout(select_layout)

        # 指标显示
        metrics_layout = QHBoxLayout()

        self.rate_label = QLabel("语速: --")
        self.rate_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        metrics_layout.addWidget(self.rate_label)

        self.pause_label = QLabel("卡顿: --")
        self.pause_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        metrics_layout.addWidget(self.pause_label)

        self.energy_label = QLabel("能量: --")
        self.energy_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        metrics_layout.addWidget(self.energy_label)

        self.duration_label = QLabel("时长: --")
        self.duration_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        metrics_layout.addWidget(self.duration_label)

        metrics_layout.addStretch()
        layout.addLayout(metrics_layout)

        # 标准检查
        self.standard_label = QLabel("")
        self.standard_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.standard_label)

        # LLM 智能教练配置（使用全局设置）
        llm_group = QGroupBox("AI 教练（LLM 智能建议）")
        llm_layout = QHBoxLayout(llm_group)
        llm_layout.setSpacing(10)

        self.llm_status_label = QLabel("未配置 AI 服务，建议去「设置」>「AI 大模型设置」配置")
        self.llm_status_label.setStyleSheet("color: #7f8c8d;")
        llm_layout.addWidget(self.llm_status_label)
        llm_layout.addStretch()

        self.llm_settings_btn = QPushButton("打开 AI 设置")
        self.llm_settings_btn.setToolTip("配置全局 LLM 服务")
        self.llm_settings_btn.clicked.connect(self._open_llm_settings)
        llm_layout.addWidget(self.llm_settings_btn)

        self.llm_suggest_btn = QPushButton("获取 AI 建议")
        self.llm_suggest_btn.setToolTip("基于上方分析结果调用 LLM 生成个性化训练建议")
        self.llm_suggest_btn.setEnabled(False)
        self.llm_suggest_btn.clicked.connect(self._generate_llm_feedback)
        llm_layout.addWidget(self.llm_suggest_btn)

        layout.addWidget(llm_group)

        self._update_llm_status()

        # 智能分析结论
        insights_group = QGroupBox("分析意见与改进建议")
        insights_layout = QVBoxLayout(insights_group)
        self.insights_text = QTextEdit()
        self.insights_text.setReadOnly(True)
        self.insights_text.setPlaceholderText("分析后将在此给出针对性改进建议；点击'获取 AI 建议'可调用 LLM 生成更个性化的反馈。")
        self.insights_text.setMinimumHeight(120)
        self.insights_text.setMaximumHeight(240)
        insights_layout.addWidget(self.insights_text)
        layout.addWidget(insights_group)

        # 回放控制
        playback_layout = QHBoxLayout()
        self.play_btn = QPushButton("播放录音")
        self.play_btn.setEnabled(False)
        self.play_slider = QSlider(Qt.Horizontal)
        self.play_slider.setEnabled(False)
        self.play_time_label = QLabel("00:00")
        playback_layout.addWidget(self.play_btn)
        playback_layout.addWidget(self.play_slider)
        playback_layout.addWidget(self.play_time_label)
        layout.addLayout(playback_layout)

        # 子标签页：趋势图 / 波形 / 逐句分析 / 韵律
        self.sub_tabs = QTabWidget()

        # 趋势图
        self.chart = QChart()
        self.chart.setTitle("语速趋势")
        self.chart.legend().hide()
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setMinimumHeight(250)
        self.sub_tabs.addTab(self.chart_view, "语速趋势")

        # 波形
        self.waveform_widget = WaveformWidget()
        self.sub_tabs.addTab(self.waveform_widget, "波形图")

        # 逐句分析表格
        self.sentence_table = QTableWidget()
        self.sentence_table.setColumnCount(6)
        self.sentence_table.setHorizontalHeaderLabels([
            "句号", "内容", "字数", "语速", "停顿次数", "停顿时长"
        ])
        self.sentence_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sentence_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.sub_tabs.addTab(self.sentence_table, "逐句分析")

        # 韵律分析
        self.prosody_chart = QChart()
        self.prosody_chart.setTitle("基频 (F0) 曲线")
        self.prosody_chart.legend().hide()
        self.prosody_chart_view = QChartView(self.prosody_chart)
        self.prosody_chart_view.setRenderHint(QPainter.Antialiasing)
        self.prosody_chart_view.setMinimumHeight(250)

        self.prosody_table = QTableWidget()
        self.prosody_table.setColumnCount(2)
        self.prosody_table.setHorizontalHeaderLabels(["韵律指标", "数值"])
        self.prosody_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.prosody_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        prosody_widget = QWidget()
        prosody_layout = QVBoxLayout(prosody_widget)
        prosody_layout.addWidget(self.prosody_chart_view)
        prosody_layout.addWidget(self.prosody_table)
        self.sub_tabs.addTab(prosody_widget, "韵律分析")

        # 字级对齐
        self.alignment_widget = AlignmentWidget()
        self.sub_tabs.addTab(self.alignment_widget, "字级对齐")

        layout.addWidget(self.sub_tabs)

        # Connect
        self.analyze_btn.clicked.connect(self._run_analysis)
        self.recording_combo.currentIndexChanged.connect(self._on_recording_selected)
        self.play_btn.clicked.connect(self._toggle_playback)
        self.play_slider.sliderMoved.connect(self._seek_playback)

    def refresh_recordings(self):
        self.recording_combo.clear()
        recordings = self.db.list_recordings()
        for rec in recordings:
            script = self.db.get_script(rec.script_id)
            title = script.title if script else "未知"
            label = f"#{rec.id} {title} ({rec.duration:.1f}s)" if rec.duration else f"#{rec.id} {title}"
            self.recording_combo.addItem(label, rec.id)

    def _on_recording_selected(self):
        rec_id = self.recording_combo.currentData()
        if rec_id is not None:
            recording = self.db.get_recording(rec_id)
            if recording:
                self._current_recording_path = recording.file_path
                self._current_recording_id = rec_id
                self.play_btn.setEnabled(True)
                self.play_slider.setEnabled(True)

    def _run_analysis(self):
        rec_id = self.recording_combo.currentData()
        if rec_id is None:
            QMessageBox.warning(self, "提示", "请先选择一个录音")
            return

        recording = self.db.get_recording(rec_id)
        if not recording:
            QMessageBox.warning(self, "提示", "录音记录不存在")
            return

        script = self.db.get_script(recording.script_id)
        if not script:
            QMessageBox.warning(self, "提示", "关联稿件不存在")
            return

        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("分析中...")

        try:
            # 获取降噪设置
            denoise = self.denoise_check.isChecked()
            result = self.analyzer.analyze(
                recording.file_path,
                script.content or "",
                script.language,
                denoise=denoise
            )

            # 保存分析到数据库
            analysis = Analysis(
                recording_id=rec_id,
                speech_rate=result["speech_rate"],
                pause_count=result["pause_count"],
                total_pause_duration=result["total_pause_duration"],
                rms_energy=result["rms_energy"],
                mfcc_features=result["mfcc_features"],
                spectral_features=result["spectral_features"],
                sentence_analysis_json=result["sentence_analysis_json"],
                prosody_json=json.dumps(result.get("prosody"), ensure_ascii=False) if result.get("prosody") else None,
                alignment_json=json.dumps(result.get("alignment"), ensure_ascii=False) if result.get("alignment") else None
            )
            self.db.create_analysis(analysis)

            # 更新UI
            unit = "CPM" if script.language == "chinese" else "WPM"
            self.rate_label.setText(f"语速: {result['speech_rate']:.0f} {unit}")
            self.pause_label.setText(
                f"卡顿: {result['pause_count']} 次 ({result['total_pause_duration']:.1f}s)"
            )
            self.energy_label.setText(f"能量: {result['rms_energy']:.4f}")
            self.duration_label.setText(f"时长: {result['duration']:.1f}s")

            # 标准检查
            std_result = check_rate(result["speech_rate"], script.language, script.category)
            if std_result["status"] == "pass":
                self.standard_label.setStyleSheet("font-size: 14px; color: green;")
                self.standard_label.setText(f"✓ {std_result['message']}")
            else:
                self.standard_label.setStyleSheet("font-size: 14px; color: #cc4444;")
                self.standard_label.setText(f"✗ {std_result['message']}")

            # 智能分析结论
            insights = self._generate_insights(result, script, std_result)
            self.insights_text.setHtml(insights)

            # 更新趋势图
            self._update_chart(rec_id)

            # 更新波形
            stumbles = self.db.get_stumbles(rec_id)
            self.waveform_widget.set_waveform(result["waveform"], stumbles)

            # 更新逐句分析表
            self._update_sentence_table(result.get("sentence_analysis_json"))

            # 更新韵律分析
            self._update_prosody(result.get("prosody"))

            # 更新字级对齐
            self.alignment_widget.set_alignment(result.get("alignment"))

            # 保存本次分析结果，供 LLM 反馈使用
            self._last_analysis_result = result
            self._last_script = script
            self.llm_suggest_btn.setEnabled(True)

        except Exception as e:
            QMessageBox.critical(self, "分析失败", f"分析出错: {e}")
        finally:
            self.analyze_btn.setEnabled(True)
            self.analyze_btn.setText("分析")

    def _update_sentence_table(self, sentence_json: str):
        self.sentence_table.setRowCount(0)
        if not sentence_json:
            return

        try:
            sentences = json.loads(sentence_json)
        except json.JSONDecodeError:
            return

        self.sentence_table.setRowCount(len(sentences))
        for i, s in enumerate(sentences):
            self.sentence_table.setItem(i, 0, QTableWidgetItem(str(s["index"])))
            self.sentence_table.setItem(i, 1, QTableWidgetItem(s["sentence"]))
            self.sentence_table.setItem(i, 2, QTableWidgetItem(str(s["char_count"])))
            self.sentence_table.setItem(i, 3, QTableWidgetItem(f"{s['rate']:.0f}"))
            self.sentence_table.setItem(i, 4, QTableWidgetItem(str(s["pause_count"])))
            self.sentence_table.setItem(i, 5, QTableWidgetItem(f"{s['pause_duration']:.1f}s"))

    def _update_chart(self, recording_id: int):
        analyses = self.db.list_analyses(recording_id)
        rates = [a.speech_rate for a in analyses if a.speech_rate is not None]

        self.chart.removeAllSeries()
        # 清除旧轴
        for axis in self.chart.axes():
            self.chart.removeAxis(axis)

        if not rates:
            return

        series = QLineSeries()
        for i, rate in enumerate(rates):
            series.append(i + 1, rate)
        self.chart.addSeries(series)

        axis_x = QValueAxis()
        axis_x.setTitleText("次数")
        axis_x.setRange(1, max(len(rates), 1))
        axis_x.setTickInterval(1)
        self.chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setTitleText("语速")
        min_rate = min(rates) - 20
        max_rate = max(rates) + 20
        axis_y.setRange(max(0, min_rate), max_rate)
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)

    def _update_prosody(self, prosody: dict):
        """更新韵律分析视图"""
        # 清空
        self.prosody_chart.removeAllSeries()
        for axis in self.prosody_chart.axes():
            self.prosody_chart.removeAxis(axis)
        self.prosody_table.setRowCount(0)

        if not prosody:
            self.prosody_table.setRowCount(1)
            self.prosody_table.setItem(0, 0, QTableWidgetItem("状态"))
            self.prosody_table.setItem(0, 1, QTableWidgetItem("未检测到韵律数据"))
            return

        # 绘制 F0 曲线
        f0_times = json.loads(prosody.get("f0_times_json", "[]"))
        f0_values = json.loads(prosody.get("f0_values_json", "[]"))

        if len(f0_times) > 0 and len(f0_values) > 0:
            series = QLineSeries()
            series.setName("F0")
            pen = QPen(QColor("#2980b9"))
            pen.setWidth(1.5)
            series.setPen(pen)

            for t, v in zip(f0_times, f0_values):
                if v > 0:
                    series.append(float(t), float(v))

            self.prosody_chart.addSeries(series)

            axis_x = QValueAxis()
            axis_x.setTitleText("时间 (s)")
            axis_x.setRange(0, max(f0_times))
            self.prosody_chart.addAxis(axis_x, Qt.AlignBottom)
            series.attachAxis(axis_x)

            valid_values = [v for v in f0_values if v > 0]
            axis_y = QValueAxis()
            axis_y.setTitleText("基频 (Hz)")
            if valid_values:
                axis_y.setRange(max(0, min(valid_values) - 20), max(valid_values) + 20)
            self.prosody_chart.addAxis(axis_y, Qt.AlignLeft)
            series.attachAxis(axis_y)

        # 填充指标表
        rows = [
            ("平均基频 (Hz)", prosody.get("f0_mean")),
            ("基频标准差 (Hz)", prosody.get("f0_std")),
            ("基频范围 (Hz)", prosody.get("f0_range")),
            ("语调斜率均值", prosody.get("f0_slope_mean")),
            ("上升段数", prosody.get("f0_rise_count")),
            ("下降段数", prosody.get("f0_fall_count")),
            ("平均强度 (dB)", prosody.get("intensity_mean")),
            ("强度动态范围 (dB)", prosody.get("intensity_range")),
            ("第一共振峰 F1 (Hz)", prosody.get("formant_mean_1")),
            ("第二共振峰 F2 (Hz)", prosody.get("formant_mean_2")),
            ("第三共振峰 F3 (Hz)", prosody.get("formant_mean_3")),
            ("谐噪比 HNR (dB)", prosody.get("hnr_mean")),
            ("频率微扰 Jitter (%)", prosody.get("jitter")),
            ("振幅微扰 Shimmer (%)", prosody.get("shimmer")),
            ("声调稳定性", prosody.get("tone_stability")),
            ("声调得分", prosody.get("tone_score")),
        ]

        self.prosody_table.setRowCount(len(rows))
        for i, (label, value) in enumerate(rows):
            self.prosody_table.setItem(i, 0, QTableWidgetItem(label))
            if value is None:
                text = "--"
            elif isinstance(value, float):
                text = f"{value:.2f}"
            else:
                text = str(value)
            self.prosody_table.setItem(i, 1, QTableWidgetItem(text))

    def _generate_insights(self, result: dict, script, std_result: dict) -> str:
        """根据分析结果生成针对性改进建议"""
        lines = ["<html><body style='font-size: 13px; line-height: 1.6;'>"]
        lines.append("<h3>综合诊断</h3>")

        rate = result["speech_rate"]
        pause_count = result["pause_count"]
        total_pause = result["total_pause_duration"]
        duration = result["duration"]
        energy = result["rms_energy"]
        prosody = result.get("prosody") or {}
        alignment = result.get("alignment") or {}

        unit = "CPM" if script.language == "chinese" else "WPM"

        # 1. 语速结论
        if std_result["status"] == "pass":
            lines.append(f"<p>✅ <b>语速控制良好</b>，当前为 <b>{rate:.0f} {unit}</b>，符合所选类别的标准区间。保持这种节奏感。</p>")
        else:
            delta = std_result.get("delta", 0)
            if delta > 0:
                lines.append(
                    f"<p>⚠️ <b>语速偏快</b>：当前 <b>{rate:.0f} {unit}</b>，超出标准上限约 <b>{delta:.0f} {unit}</b>。"
                    f"建议适当放慢，尤其在关键句、数据、金句处增加停顿，让听众有消化时间。</p>"
                )
            else:
                lines.append(
                    f"<p>⚠️ <b>语速偏慢</b>：当前 <b>{rate:.0f} {unit}</b>，低于标准下限约 <b>{abs(delta):.0f} {unit}</b>。"
                    f"尝试减少不必要的停顿，保持语流连贯，避免听众注意力分散。</p>"
                )

        # 2. 卡顿/停顿结论
        if duration > 0:
            pause_ratio = total_pause / duration
            if pause_count == 0:
                lines.append("<p>✅ <b>语流连贯</b>：未检测到明显卡顿或过长停顿。</p>")
            elif pause_ratio < 0.1:
                lines.append(
                    f"<p>⚠️ <b>停顿偏少但存在 {pause_count} 处卡顿</b>。"
                    f"总停顿时长 {total_pause:.1f}s，占比 {pause_ratio:.1%}。"
                    f"注意区分'生理性卡顿'和'语义性停顿'，在句群之间适当增加换气停顿。</p>"
                )
            elif pause_ratio > 0.25:
                lines.append(
                    f"<p>⚠️ <b>停顿占比偏高</b>：检测到 {pause_count} 处停顿，总时长 {total_pause:.1f}s（{pause_ratio:.1%}）。"
                    f"建议先通读稿件熟悉内容，减少因忘词导致的空白；同时检查是否有过多气口。</p>"
                )
            else:
                lines.append(
                    f"<p>ℹ️ <b>停顿节奏正常</b>：{pause_count} 处停顿，总时长 {total_pause:.1f}s（{pause_ratio:.1%}）。"
                    f"如果部分停顿发生在句子中间，可重点练习该句的断句。</p>"
                )

        # 3. 音量/能量结论
        if energy > 0.3:
            lines.append("<p>✅ <b>音量充沛</b>：声音能量充足，适合播音主持场景。</p>")
        elif energy > 0.15:
            lines.append("<p>ℹ️ <b>音量适中</b>：能量正常，若环境较吵可适当提高音量或靠近麦克风。</p>")
        else:
            lines.append(
                "<p>⚠️ <b>音量偏小</b>：声音能量偏低，可能被环境噪声掩盖。"
                "建议提高发声力度、拉近麦克风距离，或检查录音设备增益。</p>"
            )

        # 4. 韵律结论
        if prosody:
            f0_mean = prosody.get("f0_mean")
            f0_std = prosody.get("f0_std")
            hnr = prosody.get("hnr_mean")
            tone_score = prosody.get("tone_score")

            lines.append("<h3>韵律与音色</h3>")

            if f0_std is not None:
                if f0_std < 15:
                    lines.append("<p>⚠️ <b>语调较平</b>：基频波动较小，听起来可能单调。尝试在强调处提高音高、句尾适当降调。</p>")
                elif f0_std > 45:
                    lines.append("<p>⚠️ <b>语调起伏过大</b>：基频波动明显，注意控制情绪表达，避免过度夸张。</p>")
                else:
                    lines.append("<p>✅ <b>语调自然</b>：基频波动适中，表达有层次感。</p>")

            if hnr is not None:
                if hnr < 10:
                    lines.append("<p>⚠️ <b>噪音占比偏高</b>：谐噪比较低，建议改善录音环境或使用降噪功能。</p>")
                else:
                    lines.append("<p>✅ <b>音质清晰</b>：谐噪比良好，声音干净。</p>")

            if tone_score is not None:
                if tone_score < 60:
                    lines.append(f"<p>⚠️ <b>声调稳定性不足</b>（得分 {tone_score:.0f}）。中文发音注意四声到位，避免滑音。</p>")
                else:
                    lines.append(f"<p>✅ <b>声调稳定</b>（得分 {tone_score:.0f}）。</p>")

        # 5. 字级对齐结论
        missing_count = 0
        if alignment and alignment.get("sentences"):
            for s in alignment["sentences"]:
                for t in s.get("tokens", []):
                    if t.get("is_missing"):
                        missing_count += 1

            if missing_count > 0:
                lines.append(
                    f"<p>⚠️ <b>漏读/错读检测</b>：字级对齐发现 <b>{missing_count}</b> 个字词与稿件不一致。"
                    f"建议对照原文逐句检查，重点练习这些易错处。</p>"
                )
            else:
                lines.append("<p>✅ <b>文本完整度好</b>：字级对齐未发现明显漏读或错读。</p>")

        # 6. 逐句突出问题
        sentence_json = result.get("sentence_analysis_json")
        if sentence_json:
            try:
                sentences = json.loads(sentence_json)
                problem_sentences = []
                for s in sentences:
                    s_rate = s.get("rate", 0)
                    s_pauses = s.get("pause_count", 0)
                    s_pause_dur = s.get("pause_duration", 0)
                    if s_rate > rate * 1.3 or s_rate < rate * 0.7 or s_pauses >= 2 or s_pause_dur > 1.0:
                        problem_sentences.append({
                            "index": s.get("index", 0),
                            "text": s.get("sentence", "")[:30],
                            "rate": s_rate,
                            "pauses": s_pauses,
                            "pause_dur": s_pause_dur
                        })

                if problem_sentences:
                    lines.append("<h3>需要重点练习的句子</h3><ul>")
                    for ps in problem_sentences[:5]:
                        reason = []
                        if ps["rate"] > rate * 1.3:
                            reason.append("语速偏快")
                        elif ps["rate"] < rate * 0.7:
                            reason.append("语速偏慢")
                        if ps["pauses"] >= 2:
                            reason.append("卡顿较多")
                        if ps["pause_dur"] > 1.0:
                            reason.append("停顿过长")
                        lines.append(
                            f"<li>第 {ps['index']} 句（{', '.join(reason)}）：{ps['text']}...</li>"
                        )
                    lines.append("</ul>")
            except json.JSONDecodeError:
                pass

        # 7. 总体练习建议
        lines.append("<h3>练习建议</h3><ul>")
        if std_result["status"] != "pass":
            lines.append("<li>使用'跟读模式'选择标准示范录音，对比语速和停顿节奏。</li>")
        if pause_count > 3:
            lines.append("<li>针对卡顿较多的句子，反复朗读直到流畅，再用录音功能检验。</li>")
        if prosody and prosody.get("f0_std", 30) < 15:
            lines.append("<li>做'语调练习'：用升调提问、降调陈述，录下来听差异。</li>")
        if missing_count > 0:
            lines.append("<li>打开'字级对齐'视图，对照红色标记逐字纠正发音。</li>")
        lines.append("<li>保持每次录音后查看趋势图，观察语速、停顿等指标的变化。</li>")
        lines.append("</ul>")

        lines.append("</body></html>")
        return "".join(lines)

    def _open_llm_settings(self):
        """打开全局 LLM 设置"""
        if show_llm_settings(self):
            self._update_llm_status()

    def _update_llm_status(self):
        """更新 LLM 状态标签"""
        cfg = self.llm_manager.get_config()
        if cfg.api_key:
            self.llm_status_label.setText(
                f"已配置文本模型：{cfg.provider} / {cfg.model or '默认模型'}"
            )
            self.llm_status_label.setStyleSheet("color: #27ae60;")
        else:
            self.llm_status_label.setText("未配置 AI 服务，建议去「设置」>「AI 大模型设置」配置")
            self.llm_status_label.setStyleSheet("color: #7f8c8d;")

    def _generate_llm_feedback(self):
        """调用 LLM 生成智能反馈"""
        if not self._last_analysis_result or not self._last_script:
            QMessageBox.warning(self, "提示", "请先完成一次分析")
            return

        config = self.llm_manager.get_text_config()
        if not config.api_key:
            QMessageBox.warning(self, "配置缺失", "请先在「设置」>「AI 大模型设置」中配置 API Key")
            return

        self.feedback_generator.set_llm_config(config)

        self.llm_suggest_btn.setEnabled(False)
        self.llm_suggest_btn.setText("AI 思考中...")

        try:
            feedback = self.feedback_generator.generate(
                result=self._last_analysis_result,
                script_content=self._last_script.content or "",
                script_language=self._last_script.language,
                script_category=self._last_script.category,
                use_llm=True
            )

            html = [
                "<html><body style='font-size: 13px; line-height: 1.6;'>"
                "<h3>AI 教练反馈</h3>"
            ]
            summary = feedback.get("summary", "")
            if summary:
                html.append(f"<p><b>整体评价：</b>{summary}</p>")

            suggestions = feedback.get("suggestions", "")
            if suggestions:
                html.append("<h4>改进建议</h4>")
                for line in suggestions.split("\n"):
                    line = line.strip()
                    if line:
                        html.append(f"<p>{line}</p>")

            drills = feedback.get("drills", "")
            if drills:
                html.append("<h4>针对性练习</h4>")
                for line in drills.split("\n"):
                    line = line.strip()
                    if line:
                        html.append(f"<p>{line}</p>")

            html.append("</body></html>")
            self.insights_text.setHtml("".join(html))

        except Exception as e:
            QMessageBox.warning(self, "AI 建议失败", f"生成失败: {e}")
        finally:
            self.llm_suggest_btn.setEnabled(True)
            self.llm_suggest_btn.setText("获取 AI 建议")

    # ---- 回放 ----

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText("播放")
        else:
            if self._current_recording_path:
                self.player.setSource(QUrl.fromLocalFile(self._current_recording_path))
                self.player.play()
                self.play_btn.setText("暂停")

    def _on_playback_position(self, position):
        duration = self.player.duration()
        if duration > 0:
            self.play_slider.setValue(int(position / duration * 100))
        pos_sec = position // 1000
        dur_sec = duration // 1000
        self.play_time_label.setText(f"{pos_sec//60:02d}:{pos_sec%60:02d} / {dur_sec//60:02d}:{dur_sec%60:02d}")

    def _seek_playback(self, value):
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(int(value / 100 * duration))

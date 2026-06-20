import json
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider, QGroupBox, QCheckBox
)
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis, QScatterSeries
from PySide6.QtCore import Qt, QUrl, QPointF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from voicetrace.data.database import Database
from voicetrace.core.analyzer import Analyzer
from voicetrace.core.standards import get_standard, check_rate
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


class AnalysisView(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.analyzer = Analyzer()
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
                prosody_json=json.dumps(result.get("prosody"), ensure_ascii=False) if result.get("prosody") else None
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

            # 更新趋势图
            self._update_chart(rec_id)

            # 更新波形
            stumbles = self.db.get_stumbles(rec_id)
            self.waveform_widget.set_waveform(result["waveform"], stumbles)

            # 更新逐句分析表
            self._update_sentence_table(result.get("sentence_analysis_json"))

            # 更新韵律分析
            self._update_prosody(result.get("prosody"))

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

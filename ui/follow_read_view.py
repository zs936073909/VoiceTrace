"""跟读模式：选示范录音 → 播放示范 → 录制跟读 → 对比相似度"""
import wave
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QMessageBox, QGroupBox, QSlider, QTextEdit
)
from PySide6.QtCore import Qt, QUrl, QTimer, QIODevice, QByteArray, Signal
from PySide6.QtMultimedia import (
    QAudioFormat, QAudioSource, QMediaPlayer, QAudioOutput
)
from PySide6.QtGui import QShortcut, QKeySequence

from voicetrace.data.database import Database
from voicetrace.data.models import Recording, Stumble
from voicetrace.core.comparator import Comparator
from voicetrace.core.analyzer import Analyzer


class FollowReadView(QWidget):
    recording_saved = Signal(int)

    def __init__(self, db: Database, recordings_dir: Path):
        super().__init__()
        self.db = db
        self.recordings_dir = recordings_dir
        self.comparator = Comparator()
        self.analyzer = Analyzer()

        # 示范播放器
        self.demo_player = QMediaPlayer()
        self.demo_output = QAudioOutput()
        self.demo_player.setAudioOutput(self.demo_output)
        self.demo_output.setVolume(0.9)
        self.demo_player.positionChanged.connect(self._on_demo_position)

        # 跟读播放器
        self.follow_player = QMediaPlayer()
        self.follow_output = QAudioOutput()
        self.follow_player.setAudioOutput(self.follow_output)
        self.follow_output.setVolume(0.9)

        # 录音
        self.is_recording = False
        self._audio_source = None
        self._audio_io = None
        self._audio_buffer = QByteArray()
        self._audio_format = None
        self.recording_start_time = 0.0
        self._last_follow_path = None

        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 说明
        info = QLabel("跟读模式：选择一条示范录音 → 听示范 → 跟读录制 → 自动对比相似度")
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 14px; padding: 8px; background: rgba(192,57,43,0.05); border-radius: 4px;")
        layout.addWidget(info)

        # 示范选择
        demo_group = QGroupBox("第一步：选择示范录音")
        demo_layout = QVBoxLayout()

        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("示范录音:"))
        self.demo_combo = QComboBox()
        self.demo_combo.setMinimumWidth(300)
        select_layout.addWidget(self.demo_combo)
        demo_layout.addLayout(select_layout)

        # 示范播放控制
        demo_play_layout = QHBoxLayout()
        self.play_demo_btn = QPushButton("播放示范")
        self.stop_demo_btn = QPushButton("停止")
        self.demo_slider = QSlider(Qt.Horizontal)
        self.demo_time_label = QLabel("00:00")
        demo_play_layout.addWidget(self.play_demo_btn)
        demo_play_layout.addWidget(self.stop_demo_btn)
        demo_play_layout.addWidget(self.demo_slider)
        demo_play_layout.addWidget(self.demo_time_label)
        demo_layout.addLayout(demo_play_layout)

        # 示范稿件预览（可滚动查看全文）
        self.demo_script_label = QTextEdit("稿件: --")
        self.demo_script_label.setReadOnly(True)
        self.demo_script_label.setMinimumHeight(100)
        self.demo_script_label.setMaximumHeight(180)
        demo_layout.addWidget(self.demo_script_label)

        demo_group.setLayout(demo_layout)
        layout.addWidget(demo_group)

        # 跟读录制
        follow_group = QGroupBox("第二步：录制跟读")
        follow_layout = QVBoxLayout()

        self.follow_status = QLabel("就绪")
        self.follow_status.setStyleSheet("font-size: 16px; font-weight: bold;")
        follow_layout.addWidget(self.follow_status)

        self.follow_duration = QLabel("00:00")
        self.follow_duration.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.follow_duration.setAlignment(Qt.AlignCenter)
        follow_layout.addWidget(self.follow_duration)

        follow_controls = QHBoxLayout()
        self.start_follow_btn = QPushButton("开始跟读录制")
        self.stop_follow_btn = QPushButton("停止录制")
        self.stop_follow_btn.setEnabled(False)
        follow_controls.addWidget(self.start_follow_btn)
        follow_controls.addWidget(self.stop_follow_btn)
        follow_controls.addStretch()
        follow_layout.addLayout(follow_controls)

        follow_group.setLayout(follow_layout)
        layout.addWidget(follow_group)

        # 对比结果
        result_group = QGroupBox("第三步：对比结果")
        result_layout = QVBoxLayout()

        self.similarity_label = QLabel("相似度: --")
        self.similarity_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #c0392b;")
        self.similarity_label.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(self.similarity_label)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(150)
        result_layout.addWidget(self.result_text)

        # 跟读回放
        replay_layout = QHBoxLayout()
        self.replay_btn = QPushButton("回放跟读")
        self.replay_btn.setEnabled(False)
        replay_layout.addWidget(self.replay_btn)
        replay_layout.addStretch()
        result_layout.addLayout(replay_layout)

        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

        # Connect
        self.play_demo_btn.clicked.connect(self._play_demo)
        self.stop_demo_btn.clicked.connect(self._stop_demo)
        self.demo_slider.sliderMoved.connect(self._seek_demo)
        self.demo_combo.currentIndexChanged.connect(self._on_demo_selected)
        self.start_follow_btn.clicked.connect(self._start_follow_recording)
        self.stop_follow_btn.clicked.connect(self._stop_follow_recording)
        self.replay_btn.clicked.connect(self._replay_follow)

    def _setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_follow_duration)

    def refresh_recordings(self):
        self.demo_combo.clear()
        recordings = self.db.list_recordings()
        for rec in recordings:
            script = self.db.get_script(rec.script_id)
            title = script.title if script else "未知"
            label = f"#{rec.id} {title} ({rec.duration:.1f}s)" if rec.duration else f"#{rec.id} {title}"
            self.demo_combo.addItem(label, rec.id)

    def _on_demo_selected(self):
        rec_id = self.demo_combo.currentData()
        if rec_id is None:
            return
        recording = self.db.get_recording(rec_id)
        if recording:
            script = self.db.get_script(recording.script_id)
            if script:
                self.demo_script_label.setPlainText(
                    f"稿件: {script.title}\n\n{script.content or ''}"
                )

    def _play_demo(self):
        rec_id = self.demo_combo.currentData()
        if rec_id is None:
            QMessageBox.warning(self, "提示", "请先选择示范录音")
            return
        recording = self.db.get_recording(rec_id)
        if recording:
            self.demo_player.setSource(QUrl.fromLocalFile(recording.file_path))
            self.demo_player.play()
            self.play_demo_btn.setText("播放中...")

    def _stop_demo(self):
        self.demo_player.stop()
        self.play_demo_btn.setText("播放示范")

    def _on_demo_position(self, position):
        duration = self.demo_player.duration()
        if duration > 0:
            self.demo_slider.setValue(int(position / duration * 100))
        pos_sec = position // 1000
        dur_sec = duration // 1000
        self.demo_time_label.setText(f"{pos_sec//60:02d}:{pos_sec%60:02d} / {dur_sec//60:02d}:{dur_sec%60:02d}")

    def _seek_demo(self, value):
        duration = self.demo_player.duration()
        if duration > 0:
            self.demo_player.setPosition(int(value / 100 * duration))

    # ---- 跟读录制 ----

    def _make_audio_format(self) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        return fmt

    def _start_follow_recording(self):
        rec_id = self.demo_combo.currentData()
        if rec_id is None:
            QMessageBox.warning(self, "提示", "请先选择示范录音")
            return

        self._audio_format = self._make_audio_format()
        self._audio_buffer = QByteArray()
        self._audio_source = QAudioSource(self._audio_format, self)

        self._audio_io = self._audio_source.start()
        if self._audio_io:
            self._audio_io.readyRead.connect(self._on_audio_data)

        self.is_recording = True
        self.recording_start_time = 0.0
        self.start_follow_btn.setEnabled(False)
        self.stop_follow_btn.setEnabled(True)
        self.follow_status.setText("跟读录制中...")
        self.timer.start(100)

    def _on_audio_data(self):
        if self._audio_io and self.is_recording:
            data = self._audio_io.readAll()
            self._audio_buffer.append(data)

    def _stop_follow_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.timer.stop()
        self.start_follow_btn.setEnabled(True)
        self.stop_follow_btn.setEnabled(False)
        self.follow_status.setText("分析中...")

        if self._audio_source:
            self._audio_source.stop()
            self._audio_source = None
            self._audio_io = None

        duration = self.recording_start_time
        if self._audio_buffer.size() > 0 and duration > 0:
            filepath = self._save_follow_wav(duration)
            if filepath:
                self._last_follow_path = filepath
                self.replay_btn.setEnabled(True)
                self._compare_with_demo(filepath)
            else:
                self.follow_status.setText("保存失败")
        else:
            self.follow_status.setText("录音为空")

    def _save_follow_wav(self, duration: float) -> str:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"follow_{timestamp}.wav"
        filepath = self.recordings_dir / filename

        try:
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(self._audio_buffer.data())
            return str(filepath)
        except Exception as e:
            print(f"Save follow WAV error: {e}")
            return ""

    def _update_follow_duration(self):
        self.recording_start_time += 0.1
        minutes = int(self.recording_start_time // 60)
        seconds = int(self.recording_start_time % 60)
        self.follow_duration.setText(f"{minutes:02d}:{seconds:02d}")

        if self.recording_start_time >= 300:
            self._stop_follow_recording()

    def _compare_with_demo(self, follow_path: str):
        """对比跟读与示范"""
        demo_rec_id = self.demo_combo.currentData()
        if demo_rec_id is None:
            return

        demo_recording = self.db.get_recording(demo_rec_id)
        demo_script = self.db.get_script(demo_recording.script_id) if demo_recording else None

        if not demo_script:
            QMessageBox.warning(self, "提示", "示范录音关联的稿件不存在")
            return

        try:
            # 分析跟读录音
            follow_result = self.analyzer.analyze(
                follow_path,
                demo_script.content or "",
                demo_script.language
            )

            # 获取示范的分析
            demo_analysis = self.db.get_latest_analysis(demo_rec_id)

            similarity = 0.0
            if demo_analysis and demo_analysis.mfcc_features:
                similarity = self.comparator.compute_similarity(
                    follow_result["mfcc_features"],
                    demo_analysis.mfcc_features
                )
            else:
                # 如果示范没有分析，先分析示范
                demo_result = self.analyzer.analyze(
                    demo_recording.file_path,
                    demo_script.content or "",
                    demo_script.language
                )
                similarity = self.comparator.compute_similarity(
                    follow_result["mfcc_features"],
                    demo_result["mfcc_features"]
                )

            # 生成报告
            report = self.comparator.generate_report(
                current_rate=follow_result["speech_rate"],
                baseline_rate=demo_analysis.speech_rate if demo_analysis else 0,
                current_pauses=follow_result["pause_count"],
                baseline_pauses=demo_analysis.pause_count if demo_analysis else 0,
                similarity_score=similarity
            )

            # 更新UI
            self.similarity_label.setText(f"相似度: {similarity:.1%}")
            self.follow_status.setText(f"完成 — 相似度 {similarity:.1%}")

            html = self._format_report(report, follow_result)
            self.result_text.setHtml(html)

            # 保存跟读录音到数据库
            follow_recording = Recording(
                script_id=demo_recording.script_id,
                file_path=str(follow_path),
                duration=self.recording_start_time
            )
            follow_rec_id = self.db.create_recording(follow_recording)
            self.recording_saved.emit(follow_rec_id)

        except Exception as e:
            QMessageBox.critical(self, "对比失败", f"对比出错: {e}")
            self.follow_status.setText("对比失败")

    def _format_report(self, report: dict, follow_result: dict) -> str:
        improvements = report.get("improvements", [])
        regressions = report.get("regressions", [])

        html = "<html><body style='font-size: 13px; line-height: 1.5;'>"
        html += f"<p><b>你的语速:</b> {follow_result['speech_rate']:.0f} | <b>示范语速:</b> {report.get('baseline_rate', 0):.0f}</p>"
        html += f"<p><b>语速差:</b> {report['rate_delta']:+.0f} | <b>卡顿差:</b> {report['pause_delta']:+d}</p>"

        if improvements:
            html += "<p style='color: #2e7d32;'><b>优点:</b></p><ul>"
            for item in improvements:
                html += f"<li>{item}</li>"
            html += "</ul>"

        if regressions:
            html += "<p style='color: #c62828;'><b>待改进:</b></p><ul>"
            for item in regressions:
                html += f"<li>{item}</li>"
            html += "</ul>"

        html += "</body></html>"
        return html

    def _replay_follow(self):
        if self._last_follow_path:
            self.follow_player.setSource(QUrl.fromLocalFile(self._last_follow_path))
            self.follow_player.play()

import wave
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QProgressBar,
    QMessageBox, QSlider, QGroupBox, QCheckBox
)
from PySide6.QtCore import Signal, QTimer, QIODevice, QByteArray, QUrl, Qt
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaPlayer, QAudioOutput
from PySide6.QtGui import QShortcut, QKeySequence

from voicetrace.data.database import Database
from voicetrace.data.models import Recording, Stumble, TrainingSession


class RecordingPanel(QWidget):
    recording_saved = Signal(int)  # recording_id

    def __init__(self, db: Database, recordings_dir: Path):
        super().__init__()
        self.db = db
        self.recordings_dir = recordings_dir
        self.current_script_id = None
        self.current_script_title = ""
        self.current_script_content = ""
        self.is_recording = False
        self.stumbles = []
        self.recording_start_time = 0.0
        self._audio_source = None
        self._audio_io = None
        self._audio_buffer = QByteArray()
        self._audio_format = None
        self._last_recording_path = None
        self._last_recording_id = None

        # 回放
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.player.positionChanged.connect(self._on_playback_position)

        self._setup_ui()
        self._setup_timer()
        self._setup_shortcuts()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 状态
        self.status_label = QLabel("就绪 — 请先在稿件管理标签页选择一个稿件")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # 稿件预览
        self.script_preview = QLabel("")
        self.script_preview.setWordWrap(True)
        self.script_preview.setStyleSheet("padding: 10px; background: rgba(0,0,0,0.03); border-radius: 4px; font-size: 13px;")
        layout.addWidget(self.script_preview)

        # 时长显示
        self.duration_label = QLabel("时长: 00:00")
        self.duration_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.duration_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.duration_label)

        # 卡顿计数
        self.stumble_label = QLabel("卡顿: 0 次 (按空格快速标记)")
        self.stumble_label.setStyleSheet("font-size: 16px;")
        self.stumble_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.stumble_label)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setMaximum(300)  # 5 分钟
        self.progress.setFormat("%v 秒")
        layout.addWidget(self.progress)

        # 录音控制
        controls = QHBoxLayout()
        self.record_btn = QPushButton("开始录音")
        self.stop_btn = QPushButton("停止")
        self.stumble_btn = QPushButton("标记卡顿")
        self.stop_btn.setEnabled(False)
        self.stumble_btn.setEnabled(False)
        controls.addWidget(self.record_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.stumble_btn)
        controls.addStretch()
        layout.addLayout(controls)

        # 降噪选项
        self.denoise_check = QCheckBox("分析时启用降噪")
        self.denoise_check.setChecked(False)
        layout.addWidget(self.denoise_check)

        # 回放区域
        playback_group = QGroupBox("录音回放")
        playback_layout = QVBoxLayout()

        playback_controls = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.stop_play_btn = QPushButton("停止")
        self.play_btn.setEnabled(False)
        self.stop_play_btn.setEnabled(False)
        playback_controls.addWidget(self.play_btn)
        playback_controls.addWidget(self.stop_play_btn)
        playback_controls.addStretch()
        playback_layout.addLayout(playback_controls)

        self.playback_slider = QSlider(Qt.Horizontal)
        self.playback_slider.setEnabled(False)
        playback_layout.addWidget(self.playback_slider)

        self.playback_time_label = QLabel("00:00 / 00:00")
        self.playback_time_label.setAlignment(Qt.AlignCenter)
        playback_layout.addWidget(self.playback_time_label)

        # 卡顿跳转按钮
        self.stumble_jump_layout = QHBoxLayout()
        self.stumble_jump_layout.addWidget(QLabel("卡顿点跳转:"))
        playback_layout.addLayout(self.stumble_jump_layout)

        playback_group.setLayout(playback_layout)
        layout.addWidget(playback_group)

        # Connect
        self.record_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.stumble_btn.clicked.connect(self.mark_stumble)
        self.play_btn.clicked.connect(self._play_recording)
        self.stop_play_btn.clicked.connect(self._stop_playback)
        self.playback_slider.sliderMoved.connect(self._seek_playback)

    def _setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_duration)

    def _setup_shortcuts(self):
        # 空格键标记卡顿
        self.stumble_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.stumble_shortcut.activated.connect(self.mark_stumble)
        # Ctrl+R 开始/停止录音
        self.record_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.record_shortcut.activated.connect(self._toggle_recording)

    def set_script(self, script_id: int, title: str = "", content: str = ""):
        self.current_script_id = script_id
        self.current_script_title = title
        self.current_script_content = content
        self.status_label.setText(f"就绪 — 当前稿件: {title}")
        preview = content[:200] + "..." if len(content) > 200 else content
        self.script_preview.setText(preview if preview else "（稿件内容为空）")

    def _make_audio_format(self) -> QAudioFormat:
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        return fmt

    def _toggle_recording(self):
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if self.current_script_id is None:
            QMessageBox.warning(self, "提示", "请先在稿件管理标签页选择一个稿件")
            return

        self._audio_format = self._make_audio_format()
        self._audio_buffer = QByteArray()
        self._audio_source = QAudioSource(self._audio_format, self)

        self._audio_io = self._audio_source.start()
        if self._audio_io:
            self._audio_io.readyRead.connect(self._on_audio_data)

        self.is_recording = True
        self.stumbles = []
        self.recording_start_time = 0.0
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.stumble_btn.setEnabled(True)
        self.status_label.setText("录音中... (空格=标记卡顿, Ctrl+R=停止)")
        self.progress.setValue(0)
        self.stumble_label.setText("卡顿: 0 次")
        self.timer.start(100)

    def _on_audio_data(self):
        if self._audio_io and self.is_recording:
            data = self._audio_io.readAll()
            self._audio_buffer.append(data)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.timer.stop()
        self.stumble_btn.setEnabled(False)
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("保存中...")

        if self._audio_source:
            self._audio_source.stop()
            self._audio_source = None
            self._audio_io = None

        duration = self.recording_start_time
        if self._audio_buffer.size() > 0 and duration > 0:
            filepath = self._save_wav(duration)
            if filepath:
                recording = Recording(
                    script_id=self.current_script_id,
                    file_path=str(filepath),
                    duration=duration
                )
                recording_id = self.db.create_recording(recording)

                for t in self.stumbles:
                    self.db.create_stumble(Stumble(
                        recording_id=recording_id,
                        stumble_time=t
                    ))

                # 自动创建训练打卡
                self.db.create_training_session(TrainingSession(
                    script_id=self.current_script_id,
                    recording_id=recording_id,
                    duration=duration,
                    notes=f"录音: {self.current_script_title}"
                ))

                self._last_recording_path = filepath
                self._last_recording_id = recording_id
                self.play_btn.setEnabled(True)
                self.stop_play_btn.setEnabled(True)
                self.playback_slider.setEnabled(True)

                self.recording_saved.emit(recording_id)
                self.status_label.setText(f"已保存: {Path(filepath).name} ({duration:.1f}s)")
            else:
                self.status_label.setText("保存失败")
        else:
            self.status_label.setText("录音为空，未保存")

    def _save_wav(self, duration: float) -> str:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in self.current_script_title if c.isalnum() or c in "_-") or "recording"
        filename = f"{safe_title}_{timestamp}.wav"
        filepath = self.recordings_dir / filename

        try:
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(self._audio_buffer.data())
            return str(filepath)
        except Exception as e:
            print(f"Save WAV error: {e}")
            return ""

    def _update_duration(self):
        self.recording_start_time += 0.1
        minutes = int(self.recording_start_time // 60)
        seconds = int(self.recording_start_time % 60)
        self.duration_label.setText(f"时长: {minutes:02d}:{seconds:02d}")
        self.progress.setValue(int(self.recording_start_time))

        if self.recording_start_time >= 300:
            self.stop_recording()

    def mark_stumble(self):
        if self.is_recording:
            self.stumbles.append(self.recording_start_time)
            self.stumble_label.setText(f"卡顿: {len(self.stumbles)} 次")
            # 短暂闪烁反馈
            self.stumble_label.setStyleSheet("font-size: 16px; color: #c0392b; font-weight: bold;")
            QTimer.singleShot(300, lambda: self.stumble_label.setStyleSheet("font-size: 16px;"))

    # ---- 回放功能 ----

    def _play_recording(self):
        if self._last_recording_path:
            self.player.setSource(QUrl.fromLocalFile(self._last_recording_path))
            self.player.play()
            self.play_btn.setText("播放中...")
            self._update_stumble_jump_buttons()

    def _stop_playback(self):
        self.player.stop()
        self.play_btn.setText("播放")

    def _on_playback_position(self, position):
        duration = self.player.duration()
        if duration > 0:
            self.playback_slider.setValue(int(position / duration * 100))
        pos_sec = position // 1000
        dur_sec = duration // 1000
        self.playback_time_label.setText(f"{pos_sec//60:02d}:{pos_sec%60:02d} / {dur_sec//60:02d}:{dur_sec%60:02d}")

    def _seek_playback(self, value):
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(int(value / 100 * duration))

    def _update_stumble_jump_buttons(self):
        # 清除旧按钮
        while self.stumble_jump_layout.count() > 1:
            item = self.stumble_jump_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        # 添加卡顿跳转按钮
        if self._last_recording_id:
            stumbles = self.db.get_stumbles(self._last_recording_id)
            for i, s in enumerate(stumbles):
                btn = QPushButton(f"{s.stumble_time:.1f}s")
                btn.setMaximumWidth(60)
                btn.clicked.connect(lambda checked, t=s.stumble_time: self._jump_to(t))
                self.stumble_jump_layout.addWidget(btn)
        self.stumble_jump_layout.addStretch()

    def _jump_to(self, time_sec: float):
        self.player.setPosition(int(time_sec * 1000))

    def get_denoise_enabled(self) -> bool:
        return self.denoise_check.isChecked()

"""台风训练视图：镜头感 + 肢体语言综合训练

整合摄像头实时预览、面部分析、身体姿态分析，
提供实时反馈和训练后综合评分。
"""
import json
import threading
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSplitter, QFrame, QScrollArea, QCheckBox, QTextEdit
)
from PySide6.QtGui import QFont, QColor

from voicetrace.data.models import PostureRecord
from voicetrace.ui.camera_view import CameraView
from voicetrace.ui.radar_chart import RadarChart

from voicetrace.core.llm_config_manager import get_llm_config_manager
from voicetrace.ui.llm_settings_dialog import show_llm_settings

try:
    from voicetrace.core.posture_analyzer import (
        PostureAnalyzer, FrameAnalysis, SessionSummary, is_mediapipe_available
    )
    from voicetrace.core.pose_analyzer import PoseAnalyzer, PoseSessionSummary
    from voicetrace.core.posture_ai_coach import (
        generate_summary, analyze_frame_image, generate_realtime_tip
    )
    MEDIAPIPE_AVAILABLE = is_mediapipe_available()
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    PostureAnalyzer = None
    PoseAnalyzer = None


class PostureView(QWidget):
    """台风训练视图"""

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._posture_analyzer: Optional[PostureAnalyzer] = None
        self._pose_analyzer: Optional[PoseAnalyzer] = None
        self._face_timeline = []
        self._pose_timeline = []
        self._is_training = False
        self._last_frame = None
        self.llm_manager = get_llm_config_manager()

        # 实时 AI 点拨状态
        self._ai_tip_lock = threading.Lock()
        self._last_ai_tip = ""
        self._last_tip_time = 0.0
        self._tip_worker_running = False
        self._ai_mode = self.llm_manager.get_ai_mode()

        # 分析器后台预加载
        self._analyzers_ready = False
        self._init_worker_running = False
        self._init_error = ""

        self._init_ui()

        if not MEDIAPIPE_AVAILABLE:
            self._show_mediapipe_warning()
        else:
            # 后台预加载 MediaPipe 模型，避免点击"开始训练"时卡住
            self._warmup_analyzers_async()

    def _show_mediapipe_warning(self):
        """显示 MediaPipe 未安装警告"""
        warning = QLabel(
            "⚠ MediaPipe 未安装，台风训练功能不可用。\n"
            "请在命令行运行: pip install mediapipe opencv-python\n"
            "安装后重启软件即可使用。"
        )
        warning.setStyleSheet("""
            QLabel {
                background-color: #fff3cd;
                color: #856404;
                padding: 15px;
                border: 1px solid #ffeaa7;
                border-radius: 6px;
                font-size: 14px;
            }
        """)
        warning.setAlignment(Qt.AlignCenter)
        self.layout().insertWidget(0, warning)

    def _warmup_analyzers_async(self):
        """后台预加载分析器，避免 UI 卡顿"""
        if self._init_worker_running or self._analyzers_ready:
            return
        self._init_worker_running = True
        self.feedback_label.setText("正在加载 MediaPipe 模型，请稍候...")
        thread = threading.Thread(target=self._init_analyzers_worker, daemon=True)
        thread.start()

    def _init_analyzers_worker(self):
        """在工作线程中初始化分析器"""
        try:
            face = PostureAnalyzer()
            face.initialize()
            pose = PoseAnalyzer(mode="sitting")
            pose.initialize()
            self._posture_analyzer = face
            self._pose_analyzer = pose
            self._analyzers_ready = True
            # 回到主线程更新 UI
            QTimer.singleShot(0, self._on_analyzers_ready)
        except Exception as exc:
            self._init_error = str(exc)
            QTimer.singleShot(0, lambda: self._on_analyzers_error(str(exc)))
        finally:
            self._init_worker_running = False

    def _on_analyzers_ready(self):
        """分析器准备就绪"""
        self.feedback_label.setText("模型加载完成，点击「开始训练」即可开始")

    def _on_analyzers_error(self, error: str):
        """分析器初始化失败"""
        self.feedback_label.setText(f"模型加载失败: {error}")
        QMessageBox.warning(self, "模型加载失败", f"MediaPipe 模型加载失败:\n{error}")

    def _ensure_analyzers(self) -> bool:
        """确保分析器已初始化，必要时阻塞等待"""
        if self._analyzers_ready and self._posture_analyzer and self._pose_analyzer:
            # 根据当前模式更新姿态分析器
            mode = "standing" if self.mode_combo.currentIndex() == 1 else "sitting"
            self._pose_analyzer.set_mode(mode)
            return True

        if self._init_worker_running:
            QMessageBox.information(
                self, "模型加载中",
                "MediaPipe 模型正在后台加载，请稍候几秒后再试。"
            )
            return False

        # 尝试同步初始化（兜底）
        try:
            self._posture_analyzer = PostureAnalyzer()
            self._posture_analyzer.initialize()
            mode = "standing" if self.mode_combo.currentIndex() == 1 else "sitting"
            self._pose_analyzer = PoseAnalyzer(mode=mode)
            self._pose_analyzer.initialize()
            self._analyzers_ready = True
            return True
        except Exception as exc:
            QMessageBox.warning(self, "初始化失败", f"无法加载台风训练模型:\n{exc}")
            return False

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # 顶部说明
        title = QLabel("台风训练")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #c0392b; padding: 8px;")
        subtitle = QLabel("通过摄像头实时分析眼神交流、表情管理、头部姿态和肢体语言，帮助你形成专业台风。")
        subtitle.setStyleSheet("color: #666; padding: 0 8px 8px;")
        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # 主分割器
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：摄像头 + 控制
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 摄像头视图
        self.camera_view = CameraView()
        self.camera_view.frame_ready.connect(self._on_frame_ready)
        left_layout.addWidget(self.camera_view)

        # 控制面板
        control_group = QGroupBox("训练设置")
        control_layout = QFormLayout(control_group)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["坐姿（电脑前训练）", "站姿（模拟演讲）"])
        control_layout.addRow("训练模式：", self.mode_combo)

        self.camera_combo = QComboBox()
        self.camera_combo.addItems(["默认摄像头 (0)", "外接摄像头 (1)"])
        control_layout.addRow("摄像头：", self.camera_combo)

        self.mirror_check = QCheckBox("镜像显示（自拍模式）")
        self.mirror_check.setChecked(True)
        self.mirror_check.toggled.connect(self.camera_view.set_mirror)
        control_layout.addRow("", self.mirror_check)

        # 训练时长设置
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(0, 600)
        self.duration_spin.setValue(0)
        self.duration_spin.setSuffix(" 秒 (0=手动停止)")
        control_layout.addRow("训练时长：", self.duration_spin)

        left_layout.addWidget(control_group)

        # 按钮区
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始训练")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #229954; }
            QPushButton:disabled { background-color: #95a5a6; }
        """)
        self.start_btn.clicked.connect(self._toggle_training)

        self.save_btn = QPushButton("保存结果")
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_result)

        self.ai_settings_btn = QPushButton("AI 设置")
        self.ai_settings_btn.setMinimumHeight(40)
        self.ai_settings_btn.clicked.connect(self._open_llm_settings)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.ai_settings_btn)
        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_widget)

        # 右侧：实时反馈 + 结果
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 实时反馈
        feedback_group = QGroupBox("实时反馈")
        feedback_layout = QVBoxLayout(feedback_group)

        self.feedback_label = QLabel("等待开始训练...")
        self.feedback_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                padding: 12px;
                border-radius: 6px;
                font-size: 13px;
                min-height: 80px;
            }
        """)
        self.feedback_label.setWordWrap(True)
        feedback_layout.addWidget(self.feedback_label)

        right_layout.addWidget(feedback_group)

        # AI 总结
        ai_group = QGroupBox("AI 教练总结")
        ai_layout = QVBoxLayout(ai_group)

        self.ai_mode_label = QLabel()
        self.ai_mode_label.setWordWrap(True)
        self._update_ai_mode_label()
        ai_layout.addWidget(self.ai_mode_label)

        self.ai_summary_text = QTextEdit()
        self.ai_summary_text.setReadOnly(True)
        self.ai_summary_text.setPlaceholderText("训练结束后，AI 教练会基于数据分析给出总结和建议。未配置 LLM 时将使用本地规则总结。")
        self.ai_summary_text.setMinimumHeight(120)
        ai_layout.addWidget(self.ai_summary_text)
        right_layout.addWidget(ai_group)

        # 雷达图
        radar_group = QGroupBox("综合评分")
        radar_layout = QVBoxLayout(radar_group)
        self.radar_chart = RadarChart()
        radar_layout.addWidget(self.radar_chart)
        right_layout.addWidget(radar_group, 1)

        # 详细数据
        detail_group = QGroupBox("详细数据")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_table = QTableWidget(8, 2)
        self.detail_table.setHorizontalHeaderLabels(["指标", "数值"])
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        detail_layout.addWidget(self.detail_table)
        right_layout.addWidget(detail_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([600, 500])
        main_layout.addWidget(splitter)

        # 历史记录
        history_group = QGroupBox("训练历史")
        history_layout = QVBoxLayout(history_group)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(
            ["日期", "时长", "眼神", "表情", "姿态", "综合"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        history_layout.addWidget(self.history_table)
        main_layout.addWidget(history_group)

        self._refresh_history()

        # 定时更新反馈
        self._feedback_timer = QTimer(self)
        self._feedback_timer.timeout.connect(self._update_feedback)
        self._feedback_timer.setInterval(500)

    def _open_llm_settings(self):
        """打开全局 LLM 设置"""
        if show_llm_settings(self):
            self._ai_mode = self.llm_manager.get_ai_mode()
            self._update_ai_mode_label()

    def _update_ai_mode_label(self):
        """更新当前 AI 模式提示"""
        text_available = self.llm_manager.is_text_available()
        mm_available = self.llm_manager.is_multimodal_available()
        if mm_available:
            self.ai_mode_label.setText(
                "当前模式：多模态模式（文本 LLM 生成总结 + 多模态 LLM 分析画面）"
            )
            self.ai_mode_label.setStyleSheet("color: #27ae60;")
        elif text_available:
            self.ai_mode_label.setText(
                "当前模式：文本模式（仅文本 LLM 基于结构化数据生成建议）"
            )
            self.ai_mode_label.setStyleSheet("color: #2980b9;")
        else:
            self.ai_mode_label.setText(
                "当前模式：本地规则模式（未配置 LLM，使用内置规则兜底）"
            )
            self.ai_mode_label.setStyleSheet("color: #7f8c8d;")

    def _toggle_training(self):
        """开始/停止训练"""
        if not MEDIAPIPE_AVAILABLE:
            QMessageBox.warning(self, "功能不可用", "MediaPipe 未安装，无法使用台风训练功能。")
            return

        if self._is_training:
            self._stop_training()
        else:
            self._start_training()

    def _start_training(self):
        """开始训练"""
        # 确保分析器已就绪（使用预加载或同步初始化兜底）
        if not self._ensure_analyzers():
            return

        # 重置分析器状态（保留已加载的模型）
        self._posture_analyzer.reset_state()
        self._pose_analyzer.reset_state()

        # 启动摄像头
        camera_idx = self.camera_combo.currentIndex()
        if not self.camera_view.start(camera_idx):
            QMessageBox.warning(self, "摄像头错误", "无法打开摄像头，请检查设备连接。")
            return

        self._face_timeline = []
        self._pose_timeline = []
        self._last_frame = None
        self._is_training = True
        self._last_tip_time = time.time()
        with self._ai_tip_lock:
            self._last_ai_tip = ""
        self.ai_summary_text.clear()
        self.start_btn.setText("停止训练")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #c0392b; }
        """)
        self.save_btn.setEnabled(False)
        self._feedback_timer.start()

        # 定时停止
        duration = self.duration_spin.value()
        if duration > 0:
            QTimer.singleShot(duration * 1000, self._stop_training)

    def _stop_training(self):
        """停止训练（保留分析器模型，便于快速再次开始）"""
        self._feedback_timer.stop()
        self.camera_view.stop()

        # 只重置状态，不关闭底层模型，避免重复加载导致卡顿
        if self._posture_analyzer:
            self._posture_analyzer.reset_state()
        if self._pose_analyzer:
            self._pose_analyzer.reset_state()

        self._is_training = False
        self.start_btn.setText("开始训练")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #229954; }
            QPushButton:disabled { background-color: #95a5a6; }
        """)

        # 计算汇总
        self._compute_summary()
        self.save_btn.setEnabled(True)

    def _on_frame_ready(self, frame, timestamp):
        """处理摄像头帧"""
        if not self._is_training:
            return

        self._last_frame = frame

        # 面部分析
        if self._posture_analyzer:
            face_result = self._posture_analyzer.analyze_frame(frame, timestamp)
            self._face_timeline.append(face_result)

            # 更新摄像头叠加层
            overlay = {
                'eye_contact': face_result.eye_contact,
                'smile': face_result.smile_score,
                'head_yaw': face_result.head_yaw,
                'warning': self._get_warning(face_result)
            }
            self.camera_view.set_overlay(overlay)
            self.camera_view.set_landmarks(face_result.landmarks)

        # 身体姿态分析
        if self._pose_analyzer:
            pose_result = self._pose_analyzer.analyze_frame(frame, timestamp)
            self._pose_timeline.append(pose_result)

    def _get_warning(self, face_result) -> str:
        """生成实时警告"""
        if not face_result.face_detected:
            return "请确保面部在画面中"
        if face_result.eye_contact < 0.3:
            return "请看向镜头"
        if face_result.tension_score > 0.6:
            return "表情紧张，请放松"
        if abs(face_result.head_yaw) > 20:
            return "头部偏转过大"
        return ""

    def _update_feedback(self):
        """更新实时反馈文字（规则提示 + 可选 LLM 点拨）"""
        if not self._face_timeline:
            return

        recent_face = self._face_timeline[-10:]  # 最近 10 帧
        avg_eye = sum(f.eye_contact for f in recent_face) / len(recent_face)
        avg_smile = sum(f.smile_score for f in recent_face) / len(recent_face)
        avg_tension = sum(f.tension_score for f in recent_face) / len(recent_face)

        feedback_parts = []

        # 检查是否有新的 AI 点拨
        ai_tip = ""
        with self._ai_tip_lock:
            ai_tip = self._last_ai_tip
            self._last_ai_tip = ""
        if ai_tip:
            feedback_parts.append(f"🤖 AI 点拨：{ai_tip}")

        if avg_eye > 0.7:
            feedback_parts.append("✓ 眼神交流良好")
        elif avg_eye > 0.4:
            feedback_parts.append("~ 眼神交流一般，请多看镜头")
        else:
            feedback_parts.append("✗ 眼神偏离镜头")

        if avg_smile > 0.5:
            feedback_parts.append("✓ 表情自然微笑")
        elif avg_tension > 0.5:
            feedback_parts.append("✗ 表情紧张，请放松面部")

        if recent_face:
            last = recent_face[-1]
            if abs(last.head_yaw) > 15:
                feedback_parts.append(f"✗ 头部偏转 {last.head_yaw:.0f}°")
            if abs(last.head_roll) > 10:
                feedback_parts.append(f"✗ 头部歪斜 {last.head_roll:.0f}°")

        self.feedback_label.setText("\n".join(feedback_parts))

        # 每隔 5 秒触发一次文本 LLM 实时点拨（不阻塞 UI）
        if self.llm_manager.is_text_available() and not self._tip_worker_running:
            now = time.time()
            if now - self._last_tip_time >= 5.0:
                self._last_tip_time = now
                self._tip_worker_running = True
                recent_pose = self._pose_timeline[-10:] if self._pose_timeline else []
                mode = "standing" if self.mode_combo.currentIndex() == 1 else "sit"
                thread = threading.Thread(
                    target=self._fetch_ai_tip,
                    args=(recent_face.copy(), recent_pose.copy(), mode),
                    daemon=True
                )
                thread.start()

    def _fetch_ai_tip(self, face_recent, pose_recent, mode):
        """在后台线程获取 AI 实时点拨"""
        try:
            tip = generate_realtime_tip(face_recent, pose_recent, mode)
            if tip:
                with self._ai_tip_lock:
                    self._last_ai_tip = tip
        except Exception as exc:
            logger = __import__("logging").getLogger(__name__)
            logger.warning(f"获取 AI 实时点拨失败: {exc}")
        finally:
            self._tip_worker_running = False

    def _compute_summary(self):
        """计算训练汇总"""
        if not self._face_timeline and not self._pose_timeline:
            return

        # 面部汇总
        face_summary = None
        if self._posture_analyzer and self._face_timeline:
            face_summary = self._posture_analyzer.summarize_session(self._face_timeline)

        # 身体姿态汇总
        pose_summary = None
        if self._pose_analyzer and self._pose_timeline:
            pose_summary = self._pose_analyzer.summarize_session(self._pose_timeline)

        # 更新雷达图
        labels = ["眼神交流", "表情管理", "头部姿态", "站姿/坐姿", "手势", "稳定性"]
        values = [0] * 6
        if face_summary:
            values[0] = face_summary.eye_contact_score
            values[1] = face_summary.expression_score
            values[2] = face_summary.head_pose_score
        if pose_summary:
            values[3] = pose_summary.posture_score
            values[4] = pose_summary.gesture_score
            values[5] = pose_summary.stability_score

        self.radar_chart.set_data(labels, values)

        # 更新详细数据表
        self._update_detail_table(face_summary, pose_summary)

        # 计算综合评分
        self._overall_score = sum(values) / 6

        # 存储汇总用于保存
        self._last_face_summary = face_summary
        self._last_pose_summary = pose_summary

        # AI 教练总结
        self._generate_ai_summary(face_summary, pose_summary)

    def _generate_ai_summary(self, face_summary, pose_summary):
        """生成 AI 教练总结"""
        mode = "standing" if self.mode_combo.currentIndex() == 1 else "sit"
        self.ai_summary_text.setPlainText("AI 教练正在生成总结，请稍候...")

        try:
            text_summary = generate_summary(face_summary, pose_summary, mode)
            # 仅多模态模式下才调用视觉分析
            if self._ai_mode == "multimodal" and self._last_frame is not None:
                mm_summary = analyze_frame_image(self._last_frame, face_summary, pose_summary, mode)
                if mm_summary:
                    text_summary += "\n\n---\n\n【多模态视觉分析】\n\n" + mm_summary
            self.ai_summary_text.setMarkdown(text_summary)
        except Exception as e:
            self.ai_summary_text.setPlainText(f"AI 总结生成失败: {e}")

    def _update_detail_table(self, face_summary, pose_summary):
        """更新详细数据表"""
        rows = [
            ("眼神交流时长占比", f"{face_summary.eye_contact_ratio:.1%}" if face_summary else "-"),
            ("眨眼次数", f"{face_summary.blink_count}" if face_summary else "-"),
            ("眨眼频率（次/分）", f"{face_summary.blink_rate:.1f}" if face_summary else "-"),
            ("平均微笑度", f"{face_summary.avg_smile:.1%}" if face_summary else "-"),
            ("平均紧张度", f"{face_summary.avg_tension:.1%}" if face_summary else "-"),
            ("头部运动量", f"{face_summary.head_movement:.1f}°" if face_summary else "-"),
            ("手势时长占比", f"{pose_summary.gesture_ratio:.1%}" if pose_summary else "-"),
            ("身体平均运动量", f"{pose_summary.avg_movement:.4f}" if pose_summary else "-"),
        ]
        self.detail_table.setRowCount(len(rows))
        for i, (label, value) in enumerate(rows):
            self.detail_table.setItem(i, 0, QTableWidgetItem(label))
            self.detail_table.setItem(i, 1, QTableWidgetItem(value))

    def _save_result(self):
        """保存训练结果到数据库"""
        face_summary = getattr(self, '_last_face_summary', None)
        pose_summary = getattr(self, '_last_pose_summary', None)

        if not face_summary and not pose_summary:
            QMessageBox.warning(self, "无数据", "没有可保存的训练数据")
            return

        duration = 0.0
        if face_summary:
            duration = face_summary.duration
        elif pose_summary:
            duration = pose_summary.duration

        # 构建详细数据 JSON
        details = {}
        if face_summary:
            details['face'] = {
                'eye_contact_ratio': face_summary.eye_contact_ratio,
                'blink_count': face_summary.blink_count,
                'blink_rate': face_summary.blink_rate,
                'avg_smile': face_summary.avg_smile,
                'avg_tension': face_summary.avg_tension,
                'head_movement': face_summary.head_movement,
                'gaze_away_moments': face_summary.gaze_away_moments[:50],  # 限制数量
            }
        if pose_summary:
            details['pose'] = {
                'mode': pose_summary.mode,
                'avg_shoulder_tilt': pose_summary.avg_shoulder_tilt,
                'avg_body_lean': pose_summary.avg_body_lean,
                'avg_head_forward': pose_summary.avg_head_forward,
                'gesture_ratio': pose_summary.gesture_ratio,
                'avg_movement': pose_summary.avg_movement,
                'max_movement': pose_summary.max_movement,
            }

        record = PostureRecord(
            duration=duration,
            eye_contact_score=face_summary.eye_contact_score if face_summary else None,
            expression_score=face_summary.expression_score if face_summary else None,
            head_pose_score=face_summary.head_pose_score if face_summary else None,
            posture_score=pose_summary.posture_score if pose_summary else None,
            gesture_score=pose_summary.gesture_score if pose_summary else None,
            stability_score=pose_summary.stability_score if pose_summary else None,
            overall_score=getattr(self, '_overall_score', None),
            details_json=json.dumps(details, ensure_ascii=False),
        )

        try:
            self.db.create_posture_record(record)
            QMessageBox.information(self, "保存成功", f"训练结果已保存\n综合评分: {self._overall_score:.1f}")
            self._refresh_history()
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _refresh_history(self):
        """刷新历史记录表"""
        records = self.db.list_posture_records(limit=50)
        self.history_table.setRowCount(len(records))
        for i, r in enumerate(records):
            self.history_table.setItem(i, 0, QTableWidgetItem(r.date or ""))
            self.history_table.setItem(i, 1, QTableWidgetItem(f"{r.duration:.0f}s"))
            self.history_table.setItem(i, 2, QTableWidgetItem(f"{r.eye_contact_score:.0f}" if r.eye_contact_score else "-"))
            self.history_table.setItem(i, 3, QTableWidgetItem(f"{r.expression_score:.0f}" if r.expression_score else "-"))
            self.history_table.setItem(i, 4, QTableWidgetItem(f"{r.posture_score:.0f}" if r.posture_score else "-"))
            self.history_table.setItem(i, 5, QTableWidgetItem(f"{r.overall_score:.0f}" if r.overall_score else "-"))

    def set_theme(self, theme: str):
        """设置主题"""
        self.radar_chart.set_theme(theme)

    def closeEvent(self, event):
        """关闭视图时彻底释放摄像头和分析器资源，避免应用卡死"""
        try:
            self._stop_training()
            self.camera_view.stop()
            if self._posture_analyzer:
                self._posture_analyzer.close()
                self._posture_analyzer = None
            if self._pose_analyzer:
                self._pose_analyzer.close()
                self._pose_analyzer = None
        except Exception as exc:
            # 释放资源失败不应阻止窗口关闭
            import logging
            logging.getLogger(__name__).warning(f"台风视图关闭时释放资源失败: {exc}")
        event.accept()
